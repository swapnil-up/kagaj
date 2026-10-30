"""Tests for shared metrics and scorecards."""

import pytest

from kagaj_core.eval import (
    ScoreError,
    Scorecard,
    character_error_rate,
    exact_match,
    levenshtein,
    precision_recall_f1,
    score_rows,
    word_error_rate,
)


def test_edit_distance_and_error_rates():
    assert levenshtein("kitten", "sitting") == 3
    assert character_error_rate("kitten", "sitting") == 0.5
    assert word_error_rate("a b c", "a x c") == 1 / 3
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("", "x") == 1.0


def test_exact_match_supports_normalization():
    assert exact_match("नेपाल", "नेपाल")
    assert not exact_match("नेपाल ", "नेपाल")
    assert exact_match("नेपाल ", "नेपाल", normalize=str.strip)


def test_precision_recall_f1():
    assert precision_recall_f1(1, 1, 1) == {
        "precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_score_rows_reports_missing_extra_and_field_accuracy():
    expected = [
        {"id": 1, "name": "क", "n": "1"},
        {"id": 2, "name": "ख", "n": "2"},
    ]
    actual = [
        {"id": 1, "name": "ग", "n": "1"},
        {"id": 3, "name": "घ", "n": "3"},
    ]
    card = score_rows(expected, actual, key="id", fields=["name", "n"])
    assert card.metrics["coverage"] == 0.5
    assert card.metrics["row_accuracy"] == 0.0
    assert card.metrics["field_accuracy"] == 0.5
    assert card.metrics["field_accuracy.name"] == 0.0
    assert card.metrics["field_accuracy.n"] == 1.0
    assert card.details["missing"] == [2]
    assert card.details["extra"] == [3]


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError):
        score_rows([{"id": 1}, {"id": 1}], [], key="id", fields=[])


def test_require_raises_for_low_scores():
    card = Scorecard("x", {"accuracy": 0.5})
    assert card.require(accuracy=0.5) is card
    with pytest.raises(ScoreError):
        card.require(accuracy=0.6)
    with pytest.raises(ScoreError):
        card.require(missing=0.0)
