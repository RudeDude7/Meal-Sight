"""Tests for mealsight.seed.recipe_parsing.derive_dietary_tags."""

from __future__ import annotations

from mealsight.seed.recipe_parsing import derive_dietary_tags


def test_recipe_with_butter_is_not_tagged_dairy_free() -> None:
    tags = derive_dietary_tags(["Chicken", "Butter", "Garlic"])
    assert "dairy_free" not in tags


def test_recipe_with_no_animal_products_is_tagged_vegan() -> None:
    tags = derive_dietary_tags(["Rice", "Beans", "Olive Oil", "Onion", "Garlic"])
    assert "vegan" in tags
    assert "vegetarian" in tags


def test_recipe_with_meat_is_not_vegetarian_or_vegan() -> None:
    tags = derive_dietary_tags(["Chicken Breast", "Garlic", "Salt"])
    assert "vegetarian" not in tags
    assert "vegan" not in tags


def test_recipe_with_dairy_but_no_meat_is_vegetarian_not_vegan() -> None:
    tags = derive_dietary_tags(["Butter", "Flour", "Sugar", "Milk"])
    assert "vegetarian" in tags
    assert "vegan" not in tags
    assert "dairy_free" not in tags


def test_recipe_with_honey_is_not_vegan() -> None:
    tags = derive_dietary_tags(["Oats", "Honey", "Water"])
    assert "vegan" not in tags


def test_gluten_free_flour_variants_are_not_flagged_as_containing_gluten() -> None:
    tags = derive_dietary_tags(["Rice Flour", "Chickpeas", "Olive Oil"])
    assert "gluten_free" in tags


def test_plain_flour_blocks_gluten_free_tag() -> None:
    tags = derive_dietary_tags(["Plain Flour", "Eggs", "Milk"])
    assert "gluten_free" not in tags


def test_coconut_does_not_block_nut_free_tag() -> None:
    tags = derive_dietary_tags(["Coconut Milk", "Rice", "Chicken"])
    assert "nut_free" in tags


def test_peanuts_block_nut_free_tag() -> None:
    tags = derive_dietary_tags(["Peanuts", "Rice", "Soy Sauce"])
    assert "nut_free" not in tags


def test_unrecognized_ingredient_does_not_falsely_grant_a_tag() -> None:
    # An ingredient this function has never heard of shouldn't, on its
    # own, be treated as proof of anything — but it also shouldn't block
    # a tag that would otherwise apply, since it matches no blocklist term.
    tags = derive_dietary_tags(["Some Completely Unknown Ingredient", "Rice"])
    assert "vegan" in tags
    assert "vegetarian" in tags


def test_eggplant_does_not_falsely_match_egg_terms() -> None:
    # KNOWN_ISSUES.md #1, reproduced directly: "egg" is a substring of
    # "eggplant", so raw substring matching would wrongly treat a
    # vegetable as if it contained real eggs. Whole-word matching means
    # a genuinely egg-free, vegan recipe stays tagged that way.
    tags = derive_dietary_tags(["Eggplant", "Garlic", "Olive Oil", "Tomato"])
    assert "vegan" in tags


def test_real_egg_still_blocks_vegan_tag() -> None:
    # The fix must not overcorrect into never matching "egg" at all.
    tags = derive_dietary_tags(["Egg", "Flour", "Milk"])
    assert "vegan" not in tags


def test_buckwheat_does_not_falsely_match_gluten_terms() -> None:
    # The sixth term-list pair (GLUTEN_TERMS / _GLUTEN_SAFE_QUALIFIERS)
    # found while fixing the five KNOWN_ISSUES.md named: raw substring
    # matching would let GLUTEN_TERMS' own "wheat" match inside
    # "buckwheat" — a real pseudocereal that is genuinely gluten-free.
    # "Buckwheat" alone (not "buckwheat flour") isolates this from the
    # separate, correct "flour" match GLUTEN_TERMS also carries.
    tags = derive_dietary_tags(["Buckwheat", "Water", "Salt"])
    assert "gluten_free" in tags


def test_real_wheat_still_blocks_gluten_free_tag() -> None:
    tags = derive_dietary_tags(["Wheat Flour", "Water", "Yeast"])
    assert "gluten_free" not in tags


def test_butternut_squash_does_not_falsely_match_butter() -> None:
    # A real collision found by re-scanning the seeded corpus after this
    # fix (Lamb Tagine, Squash Linguine): DAIRY_TERMS' own "butter" is a
    # literal substring of "butternut" — a vegetable, not dairy.
    tags = derive_dietary_tags(["Butternut Squash", "Garlic", "Olive Oil"])
    assert "dairy_free" in tags


def test_real_butter_still_blocks_dairy_free_tag() -> None:
    tags = derive_dietary_tags(["Butter", "Flour", "Sugar"])
    assert "dairy_free" not in tags


def test_gelatine_british_spelling_still_blocks_vegetarian_tag() -> None:
    # A real regression this same fix would otherwise have introduced,
    # caught by re-scanning the real corpus (Peanut Butter Cheesecake):
    # whole-word matching against MEAT_TERMS' own "gelatin" no longer
    # catches the British "gelatine" spelling (the trailing "e" isn't
    # covered by the s/es pluralization tolerance) unless "gelatine" is
    # ALSO listed explicitly, the same way DAIRY_TERMS already lists
    # both "yogurt" and "yoghurt".
    tags = derive_dietary_tags(["Gelatine Leafs", "Cream", "Sugar"])
    assert "vegetarian" not in tags


def test_mincemeat_does_not_falsely_match_mince() -> None:
    # A real corpus finding (Mince Pies): MEAT_TERMS' own "mince" no
    # longer matches inside "mincemeat" once matching is whole-word —
    # correct, since traditional mincemeat (the dessert filling) is a
    # spiced dried-fruit preserve, not ground meat, despite the name.
    tags = derive_dietary_tags(["Mincemeat", "Flour", "Sugar", "Egg"])
    assert "vegetarian" in tags
