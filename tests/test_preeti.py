"""Independent Preeti fixtures; these do not depend on the redbook corpus."""

from migration_parser.preeti import ascii_digits, decode, has_devanagari


def test_preeti_known_words():
    cases = {
        "g]kfn ;/sf/": "नेपाल सरकार",
        "k'?if": "पुरुष",
        "dlxnf": "महिला",
        "sf7df8f+}": "काठमाडौं",
    }
    for raw, expected in cases.items():
        assert decode(raw) == expected, raw


def test_preeti_reorders_leading_i_matra():
    assert decode("ls") == "कि"
    assert decode("lzIfs") == "शिक्षक"
    assert decode("ljBf") == "विद्या"


def test_preeti_reorders_anusvara_and_reph():
    assert decode("l;+u") == "सिंग"
    assert decode("k|sf/") == "प्रकार"


def test_preeti_digits_and_detection():
    assert decode("") == ""
    assert ascii_digits("१२३") == "123"
    assert has_devanagari("नेपाल")
    assert not has_devanagari("g]kfn")
