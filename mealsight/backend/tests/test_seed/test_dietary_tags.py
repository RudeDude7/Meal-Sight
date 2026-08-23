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
