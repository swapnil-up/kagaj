"""Tests for the shared OCR adapter."""

from kagaj_core.ocr import (
    Word,
    devanagari_ratio,
    format_lines,
    is_devanagari,
    ocr_array,
    words_in_box,
)


class FakeEngine:
    def predict(self, image):
        return [{
            "rec_texts": ["नेपाल", "abc", "", "सरकार"],
            "rec_scores": [0.9, 0.2, 0.5, 0.8],
            "rec_boxes": [
                [0, 0, 10, 10],
                [10, 0, 20, 10],
                [20, 0, 30, 10],
                [0, 20, 12, 30],
            ],
        }]


def test_ocr_array_scales_and_filters_low_scores():
    words = ocr_array(FakeEngine(), object(), scale=2.0, min_score=0.3)
    assert [w.text for w in words] == ["नेपाल", "सरकार"]
    assert words[0].bbox == (0.0, 0.0, 5.0, 5.0)
    assert words[0].score == 0.9


def test_ocr_array_keeps_page_number():
    words = ocr_array(FakeEngine(), object(), page=7)
    assert all(w.page == 7 for w in words)


def test_devanagari_ratio_and_predicate():
    assert devanagari_ratio("नेपाल") == 1.0
    assert devanagari_ratio("abc") == 0.0
    assert devanagari_ratio("  ") == 0.0
    assert is_devanagari("नेपाल सरकार")
    assert not is_devanagari("Notice 2083")


def test_words_in_box_returns_first_match():
    words = [
        Word("नेपाल", (0, 0, 10, 10)),
        Word("सरकार", (10, 0, 20, 10)),
    ]
    assert words_in_box(words, 5, 5).text == "नेपाल"
    assert words_in_box(words, 50, 50) is None


def test_format_lines_groups_by_row_and_page():
    words = [
        Word("सरकार", (10, 0, 20, 10), page=1),
        Word("नेपाल", (0, 0, 10, 10), page=1),
        Word("दोस्रो", (0, 30, 10, 40), page=1),
        Word("अर्को", (0, 0, 10, 10), page=2),
    ]
    assert format_lines(words) == ["नेपाल सरकार", "दोस्रो", "अर्को"]
