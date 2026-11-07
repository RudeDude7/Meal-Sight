"""`python -m eval` with no arguments must mean "every dimension"."""

from __future__ import annotations

import sys

import pytest

from eval.__main__ import _parse_args, main


def test_no_arguments_parses_to_an_empty_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["eval"])
    assert _parse_args().dimensions == []


def test_an_unknown_dimension_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["eval", "dimension9"])
    with pytest.raises(SystemExit, match="unknown dimension"):
        main()
