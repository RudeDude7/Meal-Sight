from mealsight.matching.avoid import dish_hits, implied_dietary_tags, ingredient_hits


def test_nut_group_hits_every_member_but_not_coconut() -> None:
    assert ingredient_hits(["nut"], ["Ground Almonds"]) == ["nut"]
    assert ingredient_hits(["nut"], ["Pine Nuts"]) == ["nut"]
    assert ingredient_hits(["nut"], ["coconut milk", "nutmeg"]) == []


def test_whole_word_not_substring() -> None:
    assert ingredient_hits(["egg"], ["eggplant"]) == []
    assert ingredient_hits(["egg"], ["Eggs"]) == ["egg"]


def test_shellfish_and_dairy_groups() -> None:
    assert ingredient_hits(["shellfish"], ["king prawns"]) == ["shellfish"]
    assert ingredient_hits(["dairy"], ["Grated Parmesan Cheese"]) == ["dairy"]


def test_dish_hits_whole_word() -> None:
    assert dish_hits(["salad"], "Greek Salad") == ["salad"]
    assert dish_hits(["tea"], "Steak") == []


def test_avoiding_nuts_implies_nut_free_tag() -> None:
    assert implied_dietary_tags(["nut"]) == ["nut-free"]
    assert implied_dietary_tags(["peanut"]) == []
