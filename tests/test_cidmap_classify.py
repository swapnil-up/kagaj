import pytest

from cidmap.classify import char_class, class_counts


@pytest.mark.parametrize("char, expected", [
    ("\u0915", "devanagari"),
    ("\u093f", "devanagari"),
    ("\ua8e0", "devanagari"),
    ("a", "latin"),
    ("\u00e9", "latin"),
    ("\ue000", "pua"),
    ("\U000f0000", "pua"),
    ("\ufffd", "replacement"),
    ("\x00", "control"),
    (">", "ascii-artifact"),
    ("^", "ascii-artifact"),
    ("\u4e00", "other"),
    ("", "other"),
    ("ab", "other"),
])
def test_char_class(char, expected):
    assert char_class(char) == expected


def test_class_counts_sorts_by_count_then_name():
    counts = class_counts(["\u0915", "\u0916", "\ufffd", "\ue000"])
    assert counts == {
        "devanagari": 2,
        "pua": 1,
        "replacement": 1,
    }
