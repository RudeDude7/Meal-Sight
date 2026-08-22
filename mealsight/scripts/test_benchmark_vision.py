#!/usr/bin/env python3
"""Unit tests for the ground-truth matcher in benchmark_vision.py.

These pin down the confirmed failures from the earlier benchmark run (milk
carton not matching milk, Chavroux not crediting goat cheese, sweet potato
vs potato) so a future matcher change can't silently regress them.

Run with: uv run --with Pillow python3 scripts/test_benchmark_vision.py
"""

from __future__ import annotations

import unittest

from benchmark_vision import (
    assign_matches,
    match_phrases,
    normalize_phrase,
    strip_containers,
    normalize_words,
)


class TestContainerStripping(unittest.TestCase):
    def test_milk_carton_strips_to_milk(self) -> None:
        self.assertEqual(normalize_phrase("Milk carton"), "milk")

    def test_jar_of_peanut_butter_strips_to_peanut_butter(self) -> None:
        self.assertEqual(normalize_phrase("Jar of peanut butter"), "peanut butter")

    def test_packaged_meat_strips_to_meat(self) -> None:
        self.assertEqual(normalize_phrase("Packaged meat"), "meat")

    def test_strip_containers_removes_only_listed_words(self) -> None:
        words = normalize_words("a canned box of tomatoes in a bag")
        self.assertEqual(strip_containers(words), ["tomato", "in"])


class TestSynonymMapEntries(unittest.TestCase):
    """One assertion per SYNONYM_MAP / BRAND_SYNONYMS entry, so a dead
    entry shows up as a failing test rather than silent non-coverage."""

    def test_half_and_half_matches_heavy_cream(self) -> None:
        self.assertTrue(match_phrases("half and half", "heavy cream"))

    def test_half_hyphen_and_hyphen_half_matches_heavy_cream(self) -> None:
        self.assertTrue(match_phrases("half-and-half", "heavy cream"))

    def test_whipping_cream_matches_heavy_cream(self) -> None:
        self.assertTrue(match_phrases("whipping cream", "heavy cream"))

    def test_plain_cream_matches_heavy_cream(self) -> None:
        self.assertTrue(match_phrases("cream", "heavy cream"))

    def test_carton_of_cream_matches_heavy_cream(self) -> None:
        self.assertTrue(match_phrases("carton of cream", "heavy cream"))

    def test_granulated_sugar_matches_sugar(self) -> None:
        self.assertTrue(match_phrases("granulated sugar", "sugar"))

    def test_margarine_matches_butter(self) -> None:
        self.assertTrue(match_phrases("margarine", "butter"))

    def test_butter_spread_matches_butter(self) -> None:
        self.assertTrue(match_phrases("butter spread", "butter"))

    def test_chavroux_alone_matches_goat_cheese(self) -> None:
        self.assertTrue(match_phrases("Chavroux", "goat cheese"))

    def test_chavroux_embedded_in_longer_phrase_matches_goat_cheese(self) -> None:
        self.assertTrue(match_phrases("Butter (Chavroux brand)", "goat cheese"))
        self.assertTrue(match_phrases("Yogurt (Chavroux brand)", "goat cheese"))


class TestGenericProteinFallback(unittest.TestCase):
    def test_packaged_meat_matches_beef(self) -> None:
        self.assertTrue(match_phrases("Packaged meat", "beef"))

    def test_meat_matches_ham(self) -> None:
        self.assertTrue(match_phrases("meat", "ham"))

    def test_meat_matches_chicken(self) -> None:
        self.assertTrue(match_phrases("meat", "chicken"))

    def test_meat_does_not_match_unrelated_item(self) -> None:
        self.assertFalse(match_phrases("meat", "banana"))


class TestConfirmedBugRegressions(unittest.TestCase):
    def test_milk_carton_matches_milk(self) -> None:
        self.assertTrue(match_phrases("Milk carton", "milk"))

    def test_sweet_potato_still_distinct_from_potato(self) -> None:
        self.assertFalse(match_phrases("sweet potato", "potato"))
        self.assertFalse(match_phrases("Sweet potatoes", "potato"))

    def test_butter_still_distinct_from_peanut_butter(self) -> None:
        self.assertFalse(match_phrases("butter", "peanut butter"))
        self.assertFalse(match_phrases("Jar of peanut butter", "butter"))

    def test_cream_synonym_does_not_leak_into_cream_cheese(self) -> None:
        self.assertFalse(match_phrases("cream cheese", "heavy cream"))

    def test_granola_stays_unmatched_hallucination(self) -> None:
        self.assertFalse(match_phrases("granola", "sugar"))
        self.assertFalse(match_phrases("granola", "corn"))


class TestBipartiteAssignment(unittest.TestCase):
    def test_specific_and_general_both_match_when_both_predicted(self) -> None:
        predicted = ["Sweet potatoes", "Potatoes"]
        ground_truth = ["potato", "sweet potato"]
        matched_pred, matched_truth = assign_matches(predicted, ground_truth)
        self.assertEqual(len(matched_pred), 2)
        self.assertEqual(len(matched_truth), 2)

    def test_general_term_stays_unmatched_when_only_specific_is_predicted(self) -> None:
        predicted = ["Sweet potatoes"]
        ground_truth = ["potato", "sweet potato"]
        matched_pred, matched_truth = assign_matches(predicted, ground_truth)
        self.assertEqual(len(matched_pred), 1)
        self.assertEqual(len(matched_truth), 1)
        # the matched truth index should be "sweet potato" (index 1), not "potato" (index 0)
        self.assertIn(1, matched_truth)
        self.assertNotIn(0, matched_truth)

    def test_single_meat_item_does_not_double_count_two_proteins(self) -> None:
        predicted = ["Packaged meat"]
        ground_truth = ["beef", "ham"]
        matched_pred, matched_truth = assign_matches(predicted, ground_truth)
        self.assertEqual(len(matched_pred), 1)
        self.assertEqual(len(matched_truth), 1)


if __name__ == "__main__":
    unittest.main()
