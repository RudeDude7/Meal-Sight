"""The Dimension 4 and 5 scorers and the isolation layer, with known answers (no model calls)."""

import pytest

from eval.analysis import Candidate, composite
from eval.cases4 import FRESHNESS_CASES
from eval.cases5 import PERSONALIZATION_CASES, Aspect
from eval.dimension4 import classify_situation, verdict_for
from eval.dimension5 import in_aligned_set, repetition_score
from eval.dimension5 import verdict_for as verdict5
from eval.isolation import IsolatedWorld, MealSeed, PantrySeed, ProfileSeed


def _cand(
    name: str, comp: float, uses: list[str] | None = None, *, cook: bool = True, **kw: object
) -> Candidate:
    c = Candidate(
        recipe_id=name,
        name=name,
        cuisine=str(kw.get("cuisine", "X")),
        cook_time=int(kw.get("cook_time", 20)),  # type: ignore[call-overload]
        ingredient_names=list(kw.get("ingredients", [])),  # type: ignore[call-overload]
        match_score=1.0,
        can_cook=cook,
        matched_names=[],
        uses_expiring=uses or [],
    )
    c.composite = comp
    return c


def test_d4_no_cookable_user_of_the_expiring_item_is_not_a_failure() -> None:
    cooks = [_cand("A", 0.8), _cand("B", 0.7)]
    assert classify_situation(cooks) == "no_opportunity"
    assert verdict_for(cooks[0], cooks)[0] == "no_opportunity"


def test_d4_using_the_expiring_item_passes_and_ignoring_it_fails() -> None:
    user, other = _cand("User", 0.8, ["thyme"]), _cand("Other", 0.5)
    cooks = [user, other]
    assert verdict_for(user, cooks)[0] == "used"
    assert verdict_for(other, cooks)[0] == "failed_to_prioritize"


def test_d4_a_far_better_recipe_correctly_beats_a_marginal_user_of_the_item() -> None:
    marginal, better = _cand("Marginal", 0.525, ["cabbage"]), _cand("Better", 0.675)
    cooks = [better, marginal]
    assert classify_situation(cooks) == "justified_deprioritization"
    assert verdict_for(better, cooks)[0] == "justified_deprioritization"


def test_d4_a_tie_is_not_justification_and_a_refusal_with_an_opportunity_fails() -> None:
    user, other = _cand("User", 0.7, ["x"]), _cand("Other", 0.7)
    assert verdict_for(other, [user, other])[0] == "failed_to_prioritize"
    assert verdict_for(None, [user, other])[0] == "failed_to_prioritize"


def test_d4_cases_are_well_formed() -> None:
    assert len(FRESHNESS_CASES) == 15
    kinds = {c.expected_situation for c in FRESHNESS_CASES}
    assert kinds == {"must_prioritize", "no_opportunity", "justified_deprioritization"}
    assert any(c.expected_waste for c in FRESHNESS_CASES), "a long-expired case is required"


def test_hand_composite_matches_the_documented_terms() -> None:
    c = _cand("A", 0.0, ["x"], cook_time=20)
    # 0.6*1.0 + 0.15 fresh + 0.15*0.5 neutral cuisine + 0.15 time fit
    assert composite(c, default_time_minutes=30) == pytest.approx(0.975)
    assert composite(c, cuisine_scores={"X": 1.0}, default_time_minutes=None) == pytest.approx(0.9)
    # 0.6 + 0.15 + 0.075 - 0.10
    assert composite(c, repetition_score=1.0, default_time_minutes=None) == pytest.approx(0.725)


def test_d5_aligned_set_membership() -> None:
    bacon = _cand("Carbonara", 0, ingredients=["spaghetti", "bacon"], cuisine="Italian", cook_time=15)
    assert not in_aligned_set(Aspect("dislike", "bacon"), bacon)
    assert in_aligned_set(Aspect("dislike", "cream"), bacon)
    assert in_aligned_set(Aspect("cuisine", "italian"), bacon)
    assert in_aligned_set(Aspect("quick", 20), bacon) and not in_aligned_set(Aspect("quick", 10), bacon)
    assert not in_aligned_set(Aspect("repeat_recipe", "Carbonara"), bacon)


def test_d5_dislike_is_never_a_trade_off_but_a_cuisine_preference_can_be_outweighed() -> None:
    case_dislike = next(c for c in PERSONALIZATION_CASES if c.aspect.kind == "dislike")
    liked, disliked = _cand("Liked", 0.5, ingredients=["rice"]), _cand("Disliked", 0.9, ingredients=["bacon"])
    v, _, ok = verdict5(case_dislike, disliked, [liked, disliked])
    assert (v, ok) == ("misaligned", False), "a higher composite must not excuse a disliked ingredient"
    case_cuisine = next(c for c in PERSONALIZATION_CASES if c.aspect.kind == "cuisine")
    pref, other = _cand("Pref", 0.5, cuisine="Italian"), _cand("Other", 0.9, cuisine="Japanese")
    assert verdict5(case_cuisine, other, [pref, other])[0] == "justified"


def test_d5_refusing_when_only_slow_recipes_exist_fails_the_soft_default_case() -> None:
    case = next(c for c in PERSONALIZATION_CASES if c.aspect.kind == "soft_time")
    assert verdict5(case, None, [_cand("Slow", 0.6, cook_time=60)])[2] is False
    assert verdict5(case, _cand("Slow", 0.6, cook_time=60), [])[2] is True


def test_d5_repetition_score_follows_the_documented_rules() -> None:
    case = next(c for c in PERSONALIZATION_CASES if c.case_id == "d5_13")
    repeated = _cand("Carbonara", 0)
    repeated.recipe_id = "52982"
    assert repetition_score(case, repeated) == 1.0
    fresh = _cand("Salmon", 0)
    fresh.recipe_id = "52773"
    assert repetition_score(case, fresh) == 0.0


def test_d5_cases_are_well_formed_and_cover_every_requested_area() -> None:
    assert len(PERSONALIZATION_CASES) == 18
    kinds = {c.aspect.kind for c in PERSONALIZATION_CASES}
    assert {
        "cuisine",
        "dislike",
        "protein",
        "household",
        "quick",
        "soft_time",
        "repeat_recipe",
        "repeat_protein",
    } <= kinds
    # d5_03 is the low-confidence control: 10 Italian ratings against a single Japanese one.
    d3 = next(c for c in PERSONALIZATION_CASES if c.case_id == "d5_03")
    assert sorted(m.cuisine for m in d3.profile.meals if m.rating).count("Japanese") == 1


async def test_isolated_world_reset_is_verified_empty_and_seeding_reads_back() -> None:
    world = IsolatedWorld()
    try:
        counts = await world.reset()
        assert counts and all(v == 0 for v in counts.values())
        pantry = [PantrySeed("thyme", 1), PantrySeed("potato"), PantrySeed("old", -5)]
        await world.seed_pantry(pantry)
        got = await world.verify_pantry(pantry)
        assert got["days_remaining"] == {"thyme": 1, "old": -5}
        profile = ProfileSeed(
            household_size=4, meals=tuple(MealSeed(f"m{i}", "Italian", 40 + i, 5) for i in range(10))
        )
        await world.seed_profile(profile)
        read = await world.verify_profile(profile)
        assert read["household_size"] == 4 and read["cuisine_data_points"] == {"Italian": 10}
        # reset really wipes everything seeded
        again = await world.reset()
        assert all(v == 0 for v in again.values())
        assert (await world.verify_pantry([]))["rows"] == 0
    finally:
        await world.cleanup()


async def test_isolated_world_detects_a_seed_that_did_not_take() -> None:
    world = IsolatedWorld()
    try:
        await world.reset()
        await world.seed_pantry([PantrySeed("thyme", 1)])
        with pytest.raises(AssertionError):
            await world.verify_pantry([PantrySeed("thyme", 5)])
    finally:
        await world.cleanup()


def test_d5_restriction_aspect_uses_tags_for_tag_backed_and_ingredient_rules_otherwise() -> None:
    meat = _cand("Carbonara", 0, ingredients=["bacon", "spaghetti"])
    meat.tags = ["nut_free"]
    veg = _cand("Boulangere", 0, ingredients=["potato"])
    veg.tags = ["vegetarian", "nut_free"]
    assert not in_aligned_set(Aspect("restriction", "vegetarian"), meat)
    assert in_aligned_set(Aspect("restriction", "vegetarian"), veg)
    pb = _cand("Cookies", 0, ingredients=["peanut butter", "sugar"])
    assert not in_aligned_set(Aspect("restriction", "peanut_free"), pb)
    assert in_aligned_set(Aspect("restriction", "peanut_free"), veg)


def test_d5_a_saved_restriction_is_never_a_trade_off() -> None:
    case = next(c for c in PERSONALIZATION_CASES if c.case_id == "d5_16")
    forbidden = _cand("Carbonara", 0.9, ingredients=["bacon"])
    forbidden.tags = []
    allowed = _cand("Boulangere", 0.5, ingredients=["potato"])
    allowed.tags = ["vegetarian"]
    v, _, ok = verdict5(case, forbidden, [forbidden, allowed])
    assert (v, ok) == ("misaligned", False), "a better composite must not excuse breaking a saved restriction"
    assert verdict5(case, allowed, [forbidden, allowed])[2] is True


def test_d5_a_dislike_with_no_alternative_must_still_be_recommended_not_refused() -> None:
    case = next(c for c in PERSONALIZATION_CASES if c.case_id == "d5_18")
    only = _cand("Carbonara", 0.8, ingredients=["bacon"])
    assert verdict5(case, only, [only])[2] is True
    assert verdict5(case, None, [only])[2] is False


def test_d5_the_original_fifteen_cases_are_unchanged_and_the_additions_are_recorded() -> None:
    ids = [c.case_id for c in PERSONALIZATION_CASES]
    assert ids[:15] == [f"d5_{i:02d}" for i in range(1, 16)]
    assert ids[15:] == ["d5_16", "d5_17", "d5_18"]


def test_fingerprint_ignores_wal_checkpoints_but_sees_a_real_row_change(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3
    from pathlib import Path

    from eval import isolation

    db = Path(str(tmp_path)) / "x.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'x')")
    conn.commit()
    conn.close()
    for name in ("pantry_db_path", "user_intelligence_db_path", "recipes_db_path"):
        monkeypatch.setattr(isolation.settings, name, db)
    before = isolation.file_fingerprints()
    # merely opening and closing in WAL mode (what any other process does) must not look like a change
    other = sqlite3.connect(db)
    other.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    other.close()
    assert isolation.file_fingerprints() == before
    conn = sqlite3.connect(db)
    conn.execute("UPDATE t SET b = 'y'")
    conn.commit()
    conn.close()
    assert isolation.file_fingerprints() != before
