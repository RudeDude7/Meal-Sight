"""Preflight: one trivial call per provider, before any dimension runs.

A bad secret (most often a trailing newline pasted with the key) makes every authenticated call fail, and
the retry policy then spends minutes per call on backoff before giving up. This costs seconds instead: it
reports, for each provider, the key's length and whether it has leading or trailing whitespace (the usual
invisible fault), then makes one request, and prints the status and any rate-limit headers.

It NEVER prints a key, a prefix of a key, or a URL carrying one.

Exit codes: 0 all providers fine, 1 a provider is unreachable, rejects the key, or is rate limited.

    python -m eval.preflight                 # Mistral, Groq, and OpenWeather if a key is set
    python -m eval.preflight --skip openweather
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

import httpx

from mealsight.config.settings import settings

TIMEOUT_SECONDS = 20.0
# A full run makes ~118 provider calls over 11-17 minutes (about 9 a minute). A key allowed fewer requests a
# minute than this cannot finish the suite inside any sane timeout, so it is reported as rate limited up
# front rather than discovered 45 minutes in.
MIN_REQUESTS_PER_MINUTE = 10
RATE_HEADER_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after")


@dataclass
class Result:
    provider: str
    ok: bool
    summary: str
    lines: list[str] = field(default_factory=list)


def describe_key(env_name: str) -> list[str]:
    """Length and whitespace of the key AS THE ENVIRONMENT HOLDS IT, before settings strips it."""
    raw = os.environ.get(env_name)
    if raw is None:
        return [f"{env_name}: not set in the environment (a .env file, if any, supplies it)"]
    problems = []
    if raw != raw.lstrip():
        problems.append("LEADING whitespace")
    if raw != raw.rstrip():
        problems.append("TRAILING whitespace/newline")
    if any(ch in raw for ch in "\r\n\t"):
        problems.append("contains a control character (newline/tab)")
    verdict = "; ".join(problems) if problems else "no leading or trailing whitespace"
    return [f"{env_name}: length {len(raw)}, {verdict}"]


def whitespace_padded(env_name: str) -> bool:
    raw = os.environ.get(env_name)
    return raw is not None and raw != raw.strip()


def _rate_headers(response: httpx.Response) -> list[str]:
    return [
        f"    {k}: {v}"
        for k, v in sorted(response.headers.items())
        if k.lower().startswith(RATE_HEADER_PREFIXES)
    ] or ["    (no rate-limit headers returned)"]


def _int_header(response: httpx.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


def judge(
    provider: str,
    response: httpx.Response,
    key_note: list[str],
    padded: bool,
    min_rpm: int = MIN_REQUESTS_PER_MINUTE,
) -> Result:
    code = response.status_code
    lines = [*key_note, f"  {provider}: HTTP {code}", *_rate_headers(response)]
    if padded:
        lines.append(
            "  WARNING: this secret has whitespace around it. Settings strips it at load time so calls "
            "work, but fix the stored secret."
        )
    if code == 429:
        return Result(provider, False, f"{provider} is RATE LIMITED (HTTP 429) on its first call", lines)
    if code in (401, 403):
        return Result(provider, False, f"{provider} REJECTED the key (HTTP {code})", lines)
    if code >= 500:
        return Result(provider, False, f"{provider} is failing server-side (HTTP {code})", lines)
    if code >= 400:
        return Result(provider, False, f"{provider} returned HTTP {code} to a trivial request", lines)
    allowed = _int_header(response, "x-ratelimit-limit-req-minute")
    if allowed is not None and allowed < min_rpm:
        return Result(
            provider,
            False,
            f"{provider} allows only {allowed} requests/minute on this key; the suite needs about {min_rpm} "
            "(118 calls over ~14 minutes). It would be rate limited all night.",
            lines,
        )
    return Result(provider, True, f"{provider} OK (HTTP {code})", lines)


async def check_mistral(client: httpx.AsyncClient, min_rpm: int) -> Result:
    key = settings.mistral_api_key.get_secret_value()
    note = describe_key("MISTRAL_API_KEY")
    padded = whitespace_padded("MISTRAL_API_KEY")
    try:
        response = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            json={
                "model": settings.REASONING_MODEL,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            headers={"Authorization": f"Bearer {key}"},
        )
    except httpx.HTTPError as exc:
        return Result("mistral", False, f"mistral is UNREACHABLE: {type(exc).__name__}", note)
    return judge("mistral", response, note, padded, min_rpm)


async def check_groq(client: httpx.AsyncClient, min_rpm: int) -> Result:
    key = settings.groq_api_key.get_secret_value()
    note = describe_key("GROQ_API_KEY")
    padded = whitespace_padded("GROQ_API_KEY")
    try:
        response = await client.get(
            "https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}
        )
    except httpx.HTTPError as exc:
        return Result("groq", False, f"groq is UNREACHABLE: {type(exc).__name__}", note)
    return judge("groq", response, note, padded, min_rpm)


async def check_openweather(client: httpx.AsyncClient, min_rpm: int) -> Result | None:
    secret = settings.openweather_api_key
    if secret is None or not secret.get_secret_value():
        return None
    note = describe_key("OPENWEATHER_API_KEY")
    padded = whitespace_padded("OPENWEATHER_API_KEY")
    try:
        response = await client.get(
            f"{settings.openweather_base_url}/weather",
            params={"q": "London", "appid": secret.get_secret_value()},
        )
    except httpx.HTTPError as exc:
        return Result("openweather", False, f"openweather is UNREACHABLE: {type(exc).__name__}", note)
    return judge("openweather", response, note, padded, min_rpm)


async def run(skip: set[str], min_rpm: int = MIN_REQUESTS_PER_MINUTE) -> list[Result]:
    results: list[Result] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for name, check in (
            ("mistral", check_mistral),
            ("groq", check_groq),
            ("openweather", check_openweather),
        ):
            if name in skip:
                continue
            result = await check(client, min_rpm)
            if result is not None:
                results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--skip", action="append", default=[], help="Provider to skip (repeatable).")
    parser.add_argument(
        "--min-rpm",
        type=int,
        default=MIN_REQUESTS_PER_MINUTE,
        help="Fail if a provider allows fewer requests per minute than this.",
    )
    args = parser.parse_args(argv)

    results = asyncio.run(run(set(args.skip), args.min_rpm))
    for result in results:
        print("\n".join(result.lines))
        print(f"  -> {result.summary}")
    failed = [r for r in results if not r.ok]
    if failed:
        for r in failed:
            print(f"::error::PREFLIGHT FAILED: {r.summary}", file=sys.stderr)
        return 1
    print("preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
