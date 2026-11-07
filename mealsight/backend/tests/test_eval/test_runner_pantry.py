"""The runner records a missing pantry honestly instead of crashing a fresh checkout."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.runner import pantry_snapshot
from mealsight.config.settings import settings
from mealsight.db import close_all


@pytest.fixture
async def _empty_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await close_all()
    monkeypatch.setattr(settings, "pantry_db_path", tmp_path / "data" / "pantry.db")
    yield  # type: ignore[misc]
    await close_all()


@pytest.mark.usefixtures("_empty_data_dir")
async def test_a_missing_pantry_is_recorded_not_raised_and_not_hashed() -> None:
    snap = await pantry_snapshot()
    assert snap["pantry_present"] is False
    assert snap["rows_at_run_start"] is None
    assert snap["pantry_content_sha256"] is None, "never the hash of nothing"
    assert "no such table" in snap["pantry_absent_reason"]
    assert snap["fixture_sha256"], "the fixture description is still recorded"
