#!/usr/bin/env python3
"""Synthesize MealSight's synthetic voice-memo test corpus with edge-tts.

Reads the scripts from test_data/text/voice_scripts.json (already authored —
this file just narrates them), synthesizes each one to an mp3 rotating across
several edge-tts voices, and records which voice was used back into the JSON.
Also writes test_data/text/text_inputs.json, the typed-input counterpart.

Run with: uv run --with edge-tts scripts/generate_voice_memos.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import edge_tts

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = REPO_ROOT / "test_data" / "text"
AUDIO_DIR = REPO_ROOT / "test_data" / "audio"
VOICE_SCRIPTS_PATH = TEXT_DIR / "voice_scripts.json"

# Deliberately spans US/UK/Australian/Irish accents and both genders, well
# past the "at least 6 voices" bar, so the fixture doesn't sound like one
# person reading twenty lines.
VOICES = [
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-GB-RyanNeural",
    "en-GB-SoniaNeural",
    "en-AU-WilliamMultilingualNeural",
    "en-AU-NatashaNeural",
    "en-IN-PrabhatNeural",
    "en-IE-EmilyNeural",
]


def load_voice_scripts() -> list[dict[str, Any]]:
    if not VOICE_SCRIPTS_PATH.exists():
        raise FileNotFoundError(
            f"{VOICE_SCRIPTS_PATH} is missing — it should already contain the 20 authored scripts."
        )
    return json.loads(VOICE_SCRIPTS_PATH.read_text())


def save_voice_scripts(entries: list[dict[str, Any]]) -> None:
    VOICE_SCRIPTS_PATH.write_text(json.dumps(entries, indent=2) + "\n")


async def synthesize(text: str, voice: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


async def generate_all(entries: list[dict[str, Any]]) -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    for index, entry in enumerate(entries):
        memo_id = entry["id"]
        out_path = AUDIO_DIR / f"{memo_id}.mp3"
        voice = VOICES[index % len(VOICES)]

        # Skip files we've already made — a second run of this script
        # shouldn't re-hit the TTS service for lines that already synthesized fine.
        if out_path.exists() and out_path.stat().st_size > 0:
            logger.info("Skipping %s (already exists, voice recorded as %s)", memo_id, entry.get("voice_used"))
            entry["voice_used"] = entry.get("voice_used") or voice
            continue

        logger.info("Synthesizing %s with voice %s", memo_id, voice)
        try:
            await synthesize(entry["script"], voice, out_path)
        except (edge_tts.exceptions.EdgeTTSException, ConnectionError, OSError) as exc:
            logger.error("Failed to synthesize %s: %s", memo_id, exc)
            if out_path.exists():
                out_path.unlink()
            continue

        entry["voice_used"] = voice


def main() -> int:
    entries = load_voice_scripts()
    if len(entries) != 20:
        logger.warning("Expected 20 voice scripts, found %d — continuing anyway.", len(entries))

    asyncio.run(generate_all(entries))
    save_voice_scripts(entries)

    synthesized = sum(1 for e in entries if (AUDIO_DIR / f"{e['id']}.mp3").exists())
    logger.info("Voice memos ready: %d/%d audio files present in %s", synthesized, len(entries), AUDIO_DIR)

    return 0 if synthesized == len(entries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
