import pytest

from eval.provenance import component_versions, digest, prompt_versions
from mealsight.perception import prompt as prompt_module


def test_digest_is_stable_and_order_insensitive() -> None:
    assert digest({"a": {1, 2, 3}, "b": [1]}) == digest({"b": [1], "a": {3, 2, 1}})
    assert digest({"a": 1}) != digest({"a": 2})


def test_a_prompt_string_is_hashed_as_is_so_older_scorecards_stay_comparable() -> None:
    import hashlib

    assert digest("hello") == hashlib.sha256(b"hello").hexdigest()[:12]


def test_extraction_prompt_is_recorded_and_changes_when_it_is_edited(monkeypatch: pytest.MonkeyPatch) -> None:
    before = prompt_versions()
    assert set(before) == {"vision_perception_prompt", "reasoning_prompt", "extraction_prompt"}
    original = prompt_module.build_extraction_prompt
    monkeypatch.setattr("eval.provenance.build_extraction_prompt", lambda t: original(t) + " one more rule")
    assert prompt_versions()["extraction_prompt"] != before["extraction_prompt"]
    assert prompt_versions()["vision_perception_prompt"] == before["vision_perception_prompt"]


def test_each_component_changes_alone_when_its_lexicon_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    before = component_versions()
    expected = {
        "diet_groups",
        "dietary_vocabulary",
        "protein_lexicon",
        "cuisine_families",
        "avoid_groups",
        "restriction_backstop_patterns",
        "matcher_normalization",
        "matcher_thresholds",
        "ranking_weights",
    }
    assert set(before) == expected

    from mealsight.matching import cuisine, protein

    monkeypatch.setattr(cuisine, "_FAMILIES", (*cuisine._FAMILIES, ("Ethiopian", "ethiopia")))
    monkeypatch.setattr(protein, "FLAVOURING_WORDS", protein.FLAVOURING_WORDS | {"zest"})
    after = component_versions()
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"cuisine_families", "protein_lexicon"}
