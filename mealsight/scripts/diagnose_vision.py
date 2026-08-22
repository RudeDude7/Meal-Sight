#!/usr/bin/env python3
"""Diagnose why MealSight's vision model output doesn't match ground truth.

On photo_01, mistral-small-2603 returned a plausible-looking but almost
entirely wrong list of fridge contents (only 3/16 items overlapped with the
human-verified ground truth). This script runs five checks to figure out
whether that's an image-transport bug (the model never actually sees the
photo) or a model/prompt accuracy problem, and writes everything up in
docs/vision_diagnostic_report.md.

Diagnostic tooling only — this does not touch or call any application code.

Run with: uv run --with Pillow scripts/diagnose_vision.py
"""

from __future__ import annotations

import base64
import csv
import json
import logging
import mimetypes
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
IMAGES_DIR = REPO_ROOT / "test_data" / "images"
GROUND_TRUTH_CSV = REPO_ROOT / "test_data" / "eval_cases" / "image_ground_truth.csv"
REPORT_PATH = REPO_ROOT / "docs" / "vision_diagnostic_report.md"

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0

# Requests-per-second caps this account is actually held to. Anything not
# listed here gets the more conservative of the two, since we don't know its
# real limit and getting rate-limited mid-diagnostic is worse than being slow.
KNOWN_RATE_LIMITS_RPS: dict[str, float] = {
    "mistral-small-2603": 0.83,
    "mistral-medium-2505": 0.42,
}
DEFAULT_RATE_LIMIT_RPS = 0.42

SMALL_IMAGE_DIMENSION_PX = 200
SMALL_FILE_SIZE_BYTES = 20_000

PROMPT_CURRENT = (
    "List every food item you can identify in this photo. Be specific — "
    "say 'chicken thighs' not 'meat', 'red bell pepper' not 'pepper'. "
    "Return one item per line."
)

PROMPT_CONSERVATIVE = (
    "Look at this photo carefully. List ONLY food items you can clearly and "
    "directly see in the image. Do not guess, and do not list items just "
    "because they're typical of a fridge or pantry — only list what is "
    "actually visible. If the image is unclear, blank, or you cannot "
    "confidently identify any items, respond with exactly this sentence and "
    "nothing else: \"I cannot identify any items with confidence\". "
    "Otherwise, list one item per line in exactly this format, with no "
    "other commentary: `<item name> | confidence: <high|medium|low>`"
)

PROMPT_GROUNDED = (
    "Look at this photo carefully. List ONLY food items you can clearly and "
    "directly see in the image. Do not guess, and do not list items just "
    "because they're typical of a fridge or pantry — only list what is "
    "actually visible. If the image is unclear, blank, or you cannot "
    "confidently identify any items, respond with exactly this sentence and "
    "nothing else: \"I cannot identify any items with confidence\". "
    "Otherwise, list one item per line in exactly this format, with no "
    "other commentary: `<item name> | confidence: <high|medium|low> | "
    "location: <brief spatial location, e.g. 'top shelf, left side'>`. "
    "The location must describe where in the frame you actually see the "
    "item — this is so we know you're pointing at pixels, not recalling a "
    "typical fridge from memory."
)

CANNOT_IDENTIFY_PHRASE = "cannot identify any items"

CHECK4_MODELS = [
    "mistral-small-2603",
    "ministral-8b-2512",
    "mistral-medium-2505",
    "magistral-small-latest",
    "pixtral-12b-latest",
]


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


class RateLimiter:
    """Keeps us under the per-model RPS cap by sleeping before a call if the
    previous one to that model happened too recently."""

    def __init__(self) -> None:
        self._last_call_at: dict[str, float] = {}

    def wait_for(self, model: str) -> None:
        rps = KNOWN_RATE_LIMITS_RPS.get(model, DEFAULT_RATE_LIMIT_RPS)
        min_interval = 1.0 / rps
        last = self._last_call_at.get(model)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = min_interval - elapsed
            if remaining > 0:
                logger.info("Rate limit: sleeping %.2fs before next %s call", remaining, model)
                time.sleep(remaining)
        self._last_call_at[model] = time.monotonic()


@dataclass
class VisionResult:
    model: str
    prompt_label: str
    text: str | None
    usage: dict[str, int] = field(default_factory=dict)
    latency_seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.text is not None


def http_post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, bytes, dict[str, str]]:
    data = json.dumps(body).encode("utf-8")
    req_headers = dict(headers)
    req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


def call_model(
    model: str,
    prompt: str,
    api_key: str,
    rate_limiter: RateLimiter,
    image_data_url: str | None,
    prompt_label: str,
) -> VisionResult:
    """Calls one Mistral chat model, optionally with an image attached,
    retrying on 429 with backoff instead of giving up."""
    content: Any
    if image_data_url is not None:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        content = prompt

    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(1, MAX_RETRIES + 1):
        rate_limiter.wait_for(model)
        started = time.monotonic()
        try:
            status, response_body, response_headers = http_post_json(MISTRAL_CHAT_URL, headers, body)
        except (urllib.error.URLError, TimeoutError) as exc:
            return VisionResult(model, prompt_label, None, error=f"network error: {exc}")
        latency = time.monotonic() - started

        if status == 429:
            retry_after = response_headers.get("Retry-After")
            delay = float(retry_after) if retry_after else BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "429 from %s (attempt %d/%d) — backing off %.1fs", model, attempt, MAX_RETRIES, delay
            )
            time.sleep(delay)
            continue

        if status == 404:
            return VisionResult(model, prompt_label, None, error=f"HTTP 404 — model does not resolve on this account")

        if status != 200:
            return VisionResult(model, prompt_label, None, error=f"HTTP {status}: {response_body[:300]!r}")

        try:
            payload = json.loads(response_body)
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            return VisionResult(model, prompt_label, None, error=f"unexpected response shape: {exc}")

        return VisionResult(model, prompt_label, text, usage=usage, latency_seconds=latency)

    return VisionResult(model, prompt_label, None, error=f"gave up after {MAX_RETRIES} retries (429)")


def build_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_item_lines(text: str) -> list[str]:
    """Extracts item names from a model response, handling plain one-per-line
    output as well as the '<item> | confidence: ... | location: ...' format
    used by the conservative/grounded prompts."""
    if CANNOT_IDENTIFY_PHRASE in text.lower():
        return []

    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # strip common bullet/numbering prefixes
        line = re.sub(r"^[\-\*•]\s*", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        name_part = line.split("|", 1)[0].strip()
        name_part = name_part.strip("`").strip()
        if name_part and CANNOT_IDENTIFY_PHRASE not in name_part.lower():
            items.append(name_part)
    return items


def normalize_item_set(items: list[str]) -> set[str]:
    return {item.strip().lower() for item in items if item.strip()}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def load_ground_truth(photo_id: str) -> list[str]:
    if not GROUND_TRUTH_CSV.exists():
        logger.warning("Ground truth CSV not found at %s", GROUND_TRUTH_CSV)
        return []
    with GROUND_TRUTH_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        return [row["item_name"] for row in reader if row["photo_id"] == photo_id]


def precision_recall(predicted: list[str], ground_truth: list[str]) -> tuple[float, float, float]:
    """Case-insensitive substring matching in both directions, e.g. 'onions'
    matches 'onion' and vice versa."""
    predicted_norm = [p.strip().lower() for p in predicted if p.strip()]
    truth_norm = [g.strip().lower() for g in ground_truth if g.strip()]

    matched_predicted: set[int] = set()
    matched_truth: set[int] = set()
    for pi, p in enumerate(predicted_norm):
        for ti, t in enumerate(truth_norm):
            if p in t or t in p:
                matched_predicted.add(pi)
                matched_truth.add(ti)

    precision = len(matched_predicted) / len(predicted_norm) if predicted_norm else 0.0
    recall = len(matched_truth) / len(truth_norm) if truth_norm else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


# --------------------------------------------------------------------------
# Check 1: image integrity
# --------------------------------------------------------------------------


@dataclass
class ImageIntegrityRow:
    photo_id: str
    file_size_bytes: int
    width: int
    height: int
    mode: str
    format: str
    base64_size_bytes: int
    data_uri_prefix: str
    flagged: bool
    flag_reason: str


def check_image_integrity(photo_ids: list[str]) -> list[ImageIntegrityRow]:
    rows: list[ImageIntegrityRow] = []
    for photo_id in photo_ids:
        path = IMAGES_DIR / f"{photo_id}.jpg"
        if not path.exists():
            logger.error("Missing image file for %s at %s", photo_id, path)
            continue

        file_bytes = path.read_bytes()
        file_size = len(file_bytes)
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        data_url = build_data_url(file_bytes, mime_type)
        base64_size = len(data_url)

        with Image.open(path) as img:
            width, height = img.size
            mode = img.mode
            image_format = img.format or "unknown"

        reasons = []
        if width < SMALL_IMAGE_DIMENSION_PX or height < SMALL_IMAGE_DIMENSION_PX:
            reasons.append(f"dimensions {width}x{height} under {SMALL_IMAGE_DIMENSION_PX}px threshold")
        if file_size < SMALL_FILE_SIZE_BYTES:
            reasons.append(f"file size {file_size}B under {SMALL_FILE_SIZE_BYTES}B threshold")

        rows.append(
            ImageIntegrityRow(
                photo_id=photo_id,
                file_size_bytes=file_size,
                width=width,
                height=height,
                mode=mode,
                format=image_format,
                base64_size_bytes=base64_size,
                data_uri_prefix=data_url[:80],
                flagged=bool(reasons),
                flag_reason="; ".join(reasons) if reasons else "none",
            )
        )
    return rows


# --------------------------------------------------------------------------
# Check 2: is the model seeing the image at all?
# --------------------------------------------------------------------------


@dataclass
class Check2Result:
    per_image: dict[str, VisionResult]
    no_image: VisionResult
    pairwise_jaccard: dict[str, float]
    image_vs_no_image_jaccard: dict[str, float]
    verdict: str


def check_model_seeing_image(api_key: str, rate_limiter: RateLimiter, photo_ids: list[str]) -> Check2Result:
    per_image: dict[str, VisionResult] = {}
    per_image_items: dict[str, set[str]] = {}

    for photo_id in photo_ids:
        path = IMAGES_DIR / f"{photo_id}.jpg"
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        data_url = build_data_url(path.read_bytes(), mime_type)
        result = call_model(
            "mistral-small-2603", PROMPT_CURRENT, api_key, rate_limiter, data_url, prompt_label="current"
        )
        per_image[photo_id] = result
        per_image_items[photo_id] = normalize_item_set(parse_item_lines(result.text)) if result.ok else set()

    no_image_result = call_model(
        "mistral-small-2603", PROMPT_CURRENT, api_key, rate_limiter, image_data_url=None, prompt_label="current-no-image"
    )
    no_image_items = normalize_item_set(parse_item_lines(no_image_result.text)) if no_image_result.ok else set()

    pairwise: dict[str, float] = {}
    ids = list(per_image_items.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            key = f"{ids[i]} vs {ids[j]}"
            pairwise[key] = jaccard_similarity(per_image_items[ids[i]], per_image_items[ids[j]])

    vs_no_image: dict[str, float] = {}
    for photo_id in ids:
        vs_no_image[photo_id] = jaccard_similarity(per_image_items[photo_id], no_image_items)

    avg_pairwise = sum(pairwise.values()) / len(pairwise) if pairwise else 0.0
    avg_vs_no_image = sum(vs_no_image.values()) / len(vs_no_image) if vs_no_image else 0.0

    # Threshold picked because Jaccard similarity between genuinely distinct
    # photos' item lists should be low (different fridges, different
    # contents); anything consistently over ~0.5 across independent images
    # is a stronger signal of "same output regardless of input" than of
    # "these fridges happen to be similar."
    similarity_threshold = 0.5
    if avg_pairwise > similarity_threshold and avg_vs_no_image > similarity_threshold:
        verdict = (
            "NOT RECEIVING USABLE VISUAL INPUT: the three per-image outputs are "
            f"highly similar to each other (avg Jaccard {avg_pairwise:.2f}) AND highly "
            f"similar to the no-image output (avg Jaccard {avg_vs_no_image:.2f}). This "
            "points to an image encoding/transport bug, not a model accuracy problem — "
            "the model appears to be answering from a generic prior regardless of what "
            "image (if any) it receives."
        )
    else:
        verdict = (
            "MODEL IS LOOKING, BUT INACCURATE: per-image outputs differ substantially "
            f"from each other (avg Jaccard {avg_pairwise:.2f}) and/or from the no-image "
            f"baseline (avg Jaccard {avg_vs_no_image:.2f}). The model is responding to "
            "distinct visual input per photo; low ground-truth overlap is a model/prompt "
            "accuracy issue rather than an encoding bug."
        )

    return Check2Result(
        per_image=per_image,
        no_image=no_image_result,
        pairwise_jaccard=pairwise,
        image_vs_no_image_jaccard=vs_no_image,
        verdict=verdict,
    )


# --------------------------------------------------------------------------
# Check 3: prompt sensitivity
# --------------------------------------------------------------------------


@dataclass
class PromptScore:
    label: str
    result: VisionResult
    precision: float
    recall: float
    f1: float


def check_prompt_sensitivity(api_key: str, rate_limiter: RateLimiter) -> list[PromptScore]:
    ground_truth = load_ground_truth("photo_01")
    path = IMAGES_DIR / "photo_01.jpg"
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data_url = build_data_url(path.read_bytes(), mime_type)

    prompts = [("A-current", PROMPT_CURRENT), ("B-conservative", PROMPT_CONSERVATIVE), ("C-grounded", PROMPT_GROUNDED)]
    scores: list[PromptScore] = []
    for label, prompt in prompts:
        result = call_model("mistral-small-2603", prompt, api_key, rate_limiter, data_url, prompt_label=label)
        if result.ok:
            items = parse_item_lines(result.text)
            precision, recall, f1 = precision_recall(items, ground_truth)
        else:
            precision = recall = f1 = 0.0
        scores.append(PromptScore(label=label, result=result, precision=precision, recall=recall, f1=f1))
    return scores


# --------------------------------------------------------------------------
# Check 4: model comparison
# --------------------------------------------------------------------------


@dataclass
class ModelScore:
    model: str
    result: VisionResult
    precision: float
    recall: float
    f1: float


def check_model_comparison(
    api_key: str, rate_limiter: RateLimiter, best_prompt_label: str, best_prompt_text: str
) -> list[ModelScore]:
    ground_truth = load_ground_truth("photo_01")
    path = IMAGES_DIR / "photo_01.jpg"
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data_url = build_data_url(path.read_bytes(), mime_type)

    scores: list[ModelScore] = []
    for model in CHECK4_MODELS:
        result = call_model(model, best_prompt_text, api_key, rate_limiter, data_url, prompt_label=best_prompt_label)
        if result.ok:
            items = parse_item_lines(result.text)
            precision, recall, f1 = precision_recall(items, ground_truth)
        else:
            precision = recall = f1 = 0.0
            logger.warning("Model %s unavailable for comparison: %s", model, result.error)
        scores.append(ModelScore(model=model, result=result, precision=precision, recall=recall, f1=f1))

    scores.sort(key=lambda s: s.f1, reverse=True)
    return scores


# --------------------------------------------------------------------------
# Check 5: resolution sensitivity
# --------------------------------------------------------------------------


@dataclass
class ResolutionScore:
    label: str
    width: int
    height: int
    result: VisionResult
    precision: float
    recall: float
    f1: float


def resize_to_data_url(image: Image.Image, scale: float, mime_type: str) -> tuple[str, int, int]:
    if scale == 1.0:
        resized = image
    else:
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        resized = image.resize(new_size, Image.LANCZOS)
    buffer = BytesIO()
    save_format = "JPEG" if mime_type == "image/jpeg" else "PNG"
    resized.convert("RGB").save(buffer, format=save_format)
    return build_data_url(buffer.getvalue(), mime_type), resized.width, resized.height


def check_resolution_sensitivity(
    api_key: str, rate_limiter: RateLimiter, best_model: str, best_prompt_label: str, best_prompt_text: str
) -> list[ResolutionScore]:
    ground_truth = load_ground_truth("photo_01")
    path = IMAGES_DIR / "photo_01.jpg"
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"

    scores: list[ResolutionScore] = []
    with Image.open(path) as img:
        img.load()
        for label, scale in [("native (100%)", 1.0), ("50% scale", 0.5), ("25% scale", 0.25)]:
            data_url, width, height = resize_to_data_url(img, scale, mime_type)
            result = call_model(best_model, best_prompt_text, api_key, rate_limiter, data_url, prompt_label=best_prompt_label)
            if result.ok:
                items = parse_item_lines(result.text)
                precision, recall, f1 = precision_recall(items, ground_truth)
            else:
                precision = recall = f1 = 0.0
            scores.append(
                ResolutionScore(
                    label=label, width=width, height=height, result=result, precision=precision, recall=recall, f1=f1
                )
            )
    return scores


# --------------------------------------------------------------------------
# Report writing
# --------------------------------------------------------------------------


def render_report(
    integrity_rows: list[ImageIntegrityRow],
    check2: Check2Result,
    check3_scores: list[PromptScore],
    check4_scores: list[ModelScore],
    check5_scores: list[ResolutionScore],
) -> str:
    lines: list[str] = []
    lines.append("# Vision Diagnostic Report")
    lines.append("")
    lines.append(
        "Investigating why mistral-small-2603's output on photo_01 barely overlapped "
        "with human-verified ground truth (3/16 items). Generated by "
        "`scripts/diagnose_vision.py`."
    )
    lines.append("")

    # Check 1
    lines.append("## Check 1 — Image Integrity")
    lines.append("")
    lines.append("| photo_id | file size | dimensions | mode | format | base64 size | flagged |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in integrity_rows:
        lines.append(
            f"| {row.photo_id} | {row.file_size_bytes:,}B | {row.width}x{row.height} | {row.mode} | "
            f"{row.format} | {row.base64_size_bytes:,}B | {'YES — ' + row.flag_reason if row.flagged else 'no'} |"
        )
    lines.append("")
    lines.append("Data URI prefixes (first 80 chars):")
    lines.append("")
    for row in integrity_rows:
        lines.append(f"- `{row.photo_id}`: `{row.data_uri_prefix}`")
    lines.append("")

    # Check 2
    lines.append("## Check 2 — Is the Model Seeing the Image?")
    lines.append("")
    lines.append(f"**VERDICT: {check2.verdict}**")
    lines.append("")
    lines.append("### Pairwise Jaccard similarity (image outputs)")
    lines.append("")
    for pair, sim in check2.pairwise_jaccard.items():
        lines.append(f"- {pair}: {sim:.3f}")
    lines.append("")
    lines.append("### Jaccard similarity vs no-image baseline")
    lines.append("")
    for photo_id, sim in check2.image_vs_no_image_jaccard.items():
        lines.append(f"- {photo_id} vs no-image: {sim:.3f}")
    lines.append("")
    lines.append("### Raw outputs")
    lines.append("")
    for photo_id, result in check2.per_image.items():
        lines.append(f"**{photo_id}** (latency {result.latency_seconds:.2f}s, usage {result.usage}):")
        lines.append("```")
        lines.append(result.text if result.ok else f"ERROR: {result.error}")
        lines.append("```")
    lines.append(f"**no-image call** (latency {check2.no_image.latency_seconds:.2f}s, usage {check2.no_image.usage}):")
    lines.append("```")
    lines.append(check2.no_image.text if check2.no_image.ok else f"ERROR: {check2.no_image.error}")
    lines.append("```")
    lines.append("")

    # Check 3
    lines.append("## Check 3 — Prompt Sensitivity (photo_01, mistral-small-2603)")
    lines.append("")
    lines.append("| prompt | precision | recall | F1 |")
    lines.append("|---|---|---|---|")
    for score in check3_scores:
        lines.append(f"| {score.label} | {score.precision:.2f} | {score.recall:.2f} | {score.f1:.2f} |")
    lines.append("")
    lines.append("### Raw outputs")
    lines.append("")
    for score in check3_scores:
        lines.append(f"**Prompt {score.label}** (latency {score.result.latency_seconds:.2f}s):")
        lines.append("```")
        lines.append(score.result.text if score.result.ok else f"ERROR: {score.result.error}")
        lines.append("```")
    lines.append("")

    # Check 4
    lines.append("## Check 4 — Model Comparison (photo_01, best prompt from Check 3)")
    lines.append("")
    lines.append("| rank | model | precision | recall | F1 | tokens (prompt/completion) | latency |")
    lines.append("|---|---|---|---|---|---|---|")
    for rank, score in enumerate(check4_scores, start=1):
        if score.result.ok:
            usage = score.result.usage
            tokens = f"{usage.get('prompt_tokens', '?')}/{usage.get('completion_tokens', '?')}"
            latency = f"{score.result.latency_seconds:.2f}s"
        else:
            tokens = "n/a"
            latency = "n/a"
        lines.append(
            f"| {rank} | {score.model} | {score.precision:.2f} | {score.recall:.2f} | {score.f1:.2f} | "
            f"{tokens} | {latency} |"
        )
    lines.append("")
    lines.append("### Raw outputs")
    lines.append("")
    for score in check4_scores:
        lines.append(f"**{score.model}**:")
        lines.append("```")
        lines.append(score.result.text if score.result.ok else f"ERROR: {score.result.error}")
        lines.append("```")
    lines.append("")

    # Check 5
    lines.append("## Check 5 — Resolution Sensitivity (best model + prompt)")
    lines.append("")
    lines.append("| resolution | dimensions | precision | recall | F1 |")
    lines.append("|---|---|---|---|---|")
    for score in check5_scores:
        lines.append(
            f"| {score.label} | {score.width}x{score.height} | {score.precision:.2f} | "
            f"{score.recall:.2f} | {score.f1:.2f} |"
        )
    lines.append("")
    f1_values = [s.f1 for s in check5_scores]
    if len(f1_values) >= 2 and max(f1_values) - min(f1_values) > 0.1:
        lines.append(
            "**Resolution matters**: F1 varies by more than 0.10 across scales tested here — "
            "any downscaling in the ingestion pipeline should be treated as a potential accuracy risk."
        )
    else:
        lines.append(
            "**Resolution doesn't appear to matter much** in this sample — F1 stayed within 0.10 "
            "across native/50%/25% scale, so downscaling in the pipeline is unlikely to be the main issue."
        )
    lines.append("")
    lines.append("### Raw outputs")
    lines.append("")
    for score in check5_scores:
        lines.append(f"**{score.label}**:")
        lines.append("```")
        lines.append(score.result.text if score.result.ok else f"ERROR: {score.result.error}")
        lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("MISTRAL_API_KEY")
    if not api_key:
        logger.error("MISTRAL_API_KEY not set in .env — cannot run vision diagnostics")
        return 1

    rate_limiter = RateLimiter()

    logger.info("Running Check 1: image integrity")
    integrity_rows = check_image_integrity([f"photo_{i:02d}" for i in range(1, 6)])
    for row in integrity_rows:
        if row.flagged:
            logger.warning("photo %s flagged: %s", row.photo_id, row.flag_reason)

    logger.info("Running Check 2: is the model seeing the image")
    check2 = check_model_seeing_image(api_key, rate_limiter, ["photo_01", "photo_02", "photo_03"])
    print(f"\nCHECK 2 VERDICT: {check2.verdict}\n")

    logger.info("Running Check 3: prompt sensitivity")
    check3_scores = check_prompt_sensitivity(api_key, rate_limiter)
    best_prompt = max(check3_scores, key=lambda s: s.f1)
    prompt_lookup = {"A-current": PROMPT_CURRENT, "B-conservative": PROMPT_CONSERVATIVE, "C-grounded": PROMPT_GROUNDED}
    logger.info("Best prompt from Check 3: %s (F1=%.2f)", best_prompt.label, best_prompt.f1)

    logger.info("Running Check 4: model comparison")
    check4_scores = check_model_comparison(api_key, rate_limiter, best_prompt.label, prompt_lookup[best_prompt.label])
    best_model_score = check4_scores[0]
    logger.info("Best model from Check 4: %s (F1=%.2f)", best_model_score.model, best_model_score.f1)

    logger.info("Running Check 5: resolution sensitivity")
    check5_scores = check_resolution_sensitivity(
        api_key, rate_limiter, best_model_score.model, best_prompt.label, prompt_lookup[best_prompt.label]
    )

    report = render_report(integrity_rows, check2, check3_scores, check4_scores, check5_scores)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    logger.info("Report written to %s", REPORT_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
