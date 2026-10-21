from cidmap import compare, quorum


def test_line_text_is_stored_normalized():
    assert compare._line_text([{"c": "\u0958"}], {}) == "\u0915\u093c"


def test_agree_folds_devanagari_and_ascii_digits():
    assert compare._agree("\u0968\u0966\u096e\u0969", "2083")


def test_agree_folds_documented_nukta_variants():
    assert compare._agree("\u0958", "\u0915\u093c")
    assert compare._agree("\u095c", "\u0921\u093c")


def test_agree_ignores_whitespace():
    assert compare._agree("\u0928\u0947\u092a\u093e\u0932 \u0938\u0930\u0915\u093e\u0930",
                          "\u0928\u0947\u092a\u093e\u0932\u0938\u0930\u0915\u093e\u0930")


def test_line_key_preserves_joiners_by_default():
    assert compare._line_key("\u0915\u094d\u200d\u0937") != compare._line_key(
        "\u0915\u094d\u0937")


def test_visual_order_still_disagrees():
    assert compare._line_key("\u093f\u0915") == "\u093f\u0915"
    assert not compare._agree("\u093f\u0915", "\u0915\u093f")


def test_quorum_read_key_handles_digits_punctuation_and_variants():
    assert "\u0935\u094d\u092f\u092f" in quorum._key(
        "(\u0968)\u0935\u094d\u092f\u092f\u0964")
    assert quorum._key("\u0958") == quorum._key("\u0915\u093c")
    assert quorum._key("\u0915\u094d\u200c\u0937") == "\u0915\u094d\u200c\u0937"


def test_quorum_read_counts_fold_digits_punctuation_and_variants():
    reads = {"(२)व्यय।": 2, "2083": 1}
    assert quorum._read_counts(reads, "व्यय") == (2, 1, 0)

    reads = {"क़": 2, "क़": 1, "ख": 1}
    assert quorum._read_counts(reads, "क़") == (3, 1, 0)
