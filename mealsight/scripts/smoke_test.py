#!/usr/bin/env python3
"""Verify external API access for MealSight before development starts.

Each check is independently skippable (missing key / missing test file) and
independently failable — one broken check must not block the others. Never
logs API key values, full or partial.

Run with: uv run --with httpx scripts/smoke_test.py
(falls back to stdlib urllib automatically if httpx is unavailable)
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
DOCS_DIR = REPO_ROOT / "docs"
IMAGES_DIR = REPO_ROOT / "test_data" / "images"
AUDIO_DIR = REPO_ROOT / "test_data" / "audio"

REQUEST_TIMEOUT = 20


class Outcome(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckOutcome:
    name: str
    outcome: Outcome
    detail: str = ""


def load_env(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE per line, '#' comments, no interpolation."""
    env: dict[str, str] = {}
    if not path.exists():
        logger.warning(".env not found at %s", path)
        return env
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, bytes]:
    """Stdlib-only HTTP request. Returns (status_code, body_bytes)."""
    data: bytes | None = None
    req_headers = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def build_multipart(
    fields: dict[str, str], file_field: str, file_path: Path
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())

    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    return b"".join(parts), boundary


def find_first_file(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.name != ".gitkeep":
            return entry
    return None


def check_mistral_models(api_key: str | None) -> CheckOutcome:
    name = "Mistral model discovery"
    if not api_key:
        return CheckOutcome(name, Outcome.SKIP, "MISTRAL_API_KEY not set in .env")

    try:
        status, body = http_request(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return CheckOutcome(name, Outcome.FAIL, f"invalid JSON response: {exc}")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = DOCS_DIR / "mistral_models_snapshot.json"
    snapshot_path.write_text(json.dumps(payload, indent=2))

    models = payload.get("data", [])
    print("\n--- Mistral available models ---")
    header = f"{'MODEL ID':<32}{'VISION':<10}{'FUNCTION CALLING'}"
    print(header)
    print("-" * len(header))
    vision_models: list[str] = []
    for model in models:
        model_id = model.get("id", "?")
        capabilities = model.get("capabilities", {}) or {}
        vision = bool(capabilities.get("vision", False))
        function_calling = bool(capabilities.get("function_calling", False))
        print(f"{model_id:<32}{str(vision):<10}{str(function_calling)}")
        if vision:
            vision_models.append(model_id)

    print("\n--- VISION-CAPABLE MODELS ---")
    if vision_models:
        for model_id in vision_models:
            print(f"  - {model_id}")
    else:
        print("  (none found)")

    return CheckOutcome(
        name, Outcome.PASS, f"{len(models)} models, {len(vision_models)} vision-capable; snapshot saved"
    )


def check_mistral_text(api_key: str | None) -> CheckOutcome:
    name = "Mistral text call"
    if not api_key:
        return CheckOutcome(name, Outcome.SKIP, "MISTRAL_API_KEY not set in .env")

    body = {
        "model": "ministral-8b-2512",
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
    }
    try:
        status, response_body = http_request(
            "https://api.mistral.ai/v1/chat/completions",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}"},
            json_body=body,
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}: {response_body[:300]!r}")

    try:
        payload = json.loads(response_body)
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"unexpected response shape: {exc}")

    print("\n--- Mistral text call response ---")
    print(f"Response text: {text!r}")
    print(f"Usage: {json.dumps(usage, indent=2)}")

    return CheckOutcome(name, Outcome.PASS, f"usage={usage}")


def check_mistral_vision(api_key: str | None) -> CheckOutcome:
    name = "Mistral vision call"
    if not api_key:
        return CheckOutcome(name, Outcome.SKIP, "MISTRAL_API_KEY not set in .env")

    image_path = find_first_file(IMAGES_DIR)
    if image_path is None:
        return CheckOutcome(
            name, Outcome.SKIP, f"no image found in {IMAGES_DIR} — add a fridge photo and re-run"
        )

    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"

    prompt = (
        "List every food item you can identify in this photo. Be specific — "
        "say 'chicken thighs' not 'meat', 'red bell pepper' not 'pepper'. "
        "Return one item per line."
    )
    body = {
        "model": "mistral-small-2603",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    try:
        status, response_body = http_request(
            "https://api.mistral.ai/v1/chat/completions",
            method="POST",
            headers={"Authorization": f"Bearer {api_key}"},
            json_body=body,
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}: {response_body[:300]!r}")

    try:
        payload = json.loads(response_body)
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"unexpected response shape: {exc}")

    print(f"\n--- Mistral vision call response (image: {image_path.name}) ---")
    print("Raw model output:")
    print(text)
    print(f"\nUsage: {json.dumps(usage, indent=2)}")

    return CheckOutcome(name, Outcome.PASS, f"usage={usage}")


def check_groq_whisper(api_key: str | None) -> CheckOutcome:
    name = "Groq Whisper transcription"
    if not api_key:
        return CheckOutcome(name, Outcome.SKIP, "GROQ_API_KEY not set in .env")

    audio_path = find_first_file(AUDIO_DIR)
    if audio_path is None:
        return CheckOutcome(
            name, Outcome.SKIP, f"no audio file found in {AUDIO_DIR} — add one and re-run"
        )

    body_bytes, boundary = build_multipart(
        fields={"model": "whisper-large-v3-turbo"},
        file_field="file",
        file_path=audio_path,
    )
    try:
        status, response_body = http_request(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            raw_body=body_bytes,
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}: {response_body[:300]!r}")

    try:
        payload = json.loads(response_body)
        transcript = payload.get("text", "")
    except json.JSONDecodeError as exc:
        return CheckOutcome(name, Outcome.FAIL, f"invalid JSON response: {exc}")

    print(f"\n--- Groq Whisper transcript (audio: {audio_path.name}) ---")
    print(transcript)

    return CheckOutcome(name, Outcome.PASS, "transcription received")


def check_themealdb() -> CheckOutcome:
    name = "TheMealDB"
    url = "https://www.themealdb.com/api/json/v1/1/search.php?s=chicken"
    try:
        status, body = http_request(url)
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return CheckOutcome(name, Outcome.FAIL, f"invalid JSON response: {exc}")

    meals = payload.get("meals") or []
    sample = meals[0].get("strMeal") if meals else "(none)"
    print("\n--- TheMealDB ---")
    print(f"Meals returned: {len(meals)}")
    print(f"Sample meal: {sample}")

    return CheckOutcome(name, Outcome.PASS, f"{len(meals)} meals, sample={sample!r}")


def check_openweathermap(api_key: str | None) -> CheckOutcome:
    name = "OpenWeatherMap"
    if not api_key:
        return CheckOutcome(name, Outcome.SKIP, "OPENWEATHER_API_KEY not set in .env")

    url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?q=Raleigh,NC,US&units=imperial&appid={api_key}"
    )
    try:
        status, body = http_request(url)
    except (urllib.error.URLError, TimeoutError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"network error: {exc}")

    if status == 401:
        print("\n--- OpenWeatherMap ---")
        print("HTTP 401 — new keys can take up to 2 hours to activate.")
        return CheckOutcome(name, Outcome.FAIL, "pending activation (401) — retry later, not a hard failure")

    if status != 200:
        return CheckOutcome(name, Outcome.FAIL, f"HTTP {status}")

    try:
        payload = json.loads(body)
        temp = payload["main"]["temp"]
        description = payload["weather"][0]["description"]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        return CheckOutcome(name, Outcome.FAIL, f"unexpected response shape: {exc}")

    print("\n--- OpenWeatherMap ---")
    print(f"Raleigh, NC: {temp}F, {description}")

    return CheckOutcome(name, Outcome.PASS, f"{temp}F, {description}")


def print_summary(outcomes: list[CheckOutcome]) -> None:
    name_width = max(len(o.name) for o in outcomes) + 2
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'CHECK':<{name_width}}{'RESULT':<8}DETAIL")
    print("-" * 70)
    for o in outcomes:
        print(f"{o.name:<{name_width}}{o.outcome.value:<8}{o.detail}")
    print()

    passed = sum(1 for o in outcomes if o.outcome is Outcome.PASS)
    failed = sum(1 for o in outcomes if o.outcome is Outcome.FAIL)
    skipped = sum(1 for o in outcomes if o.outcome is Outcome.SKIP)
    print(f"PASS: {passed}  FAIL: {failed}  SKIP: {skipped}")


def main() -> int:
    env = load_env(ENV_PATH)
    mistral_key = env.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY") or None
    groq_key = env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY") or None
    weather_key = env.get("OPENWEATHER_API_KEY") or os.environ.get("OPENWEATHER_API_KEY") or None

    outcomes = [
        check_mistral_models(mistral_key),
        check_mistral_text(mistral_key),
        check_mistral_vision(mistral_key),
        check_groq_whisper(groq_key),
        check_themealdb(),
        check_openweathermap(weather_key),
    ]

    print_summary(outcomes)

    return 1 if any(o.outcome is Outcome.FAIL for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
