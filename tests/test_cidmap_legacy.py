import pytest

from cidmap import legacy


@pytest.mark.parametrize("base, family", [
    ("ABCDEE+Preeti", "preeti"),
    ("Preeti,Bold", "preeti"),
    ("CMNNHG+Himalb", "preeti"),
    ("BCDEEE+Nagarik", "preeti"),
    ("OGPBEA+Gen_Aakriti", "gen-aakriti"),
    ("IEKMHF+FONTASY_HIMALI_TT", "fontasy"),
    ("HEKBJO+Gen_Preeti", "preeti"),
    ("HEJPPI+Gen_FONTASY_-HIMALI_-TT", "fontasy"),
    ("PBBLON+Kantipur", "kantipur"),
    ("ABCDEE+Kalimati", None),
])
def test_family_detection(base, family):
    assert legacy.family(base) == family


def test_preeti_compatible_families_decode():
    assert legacy.decode("g]kfn ;/sf/", "preeti") == "नेपाल सरकार"
    assert legacy.decode_font("jflif{s k|ltj]bg", "ABCDEE+Preeti") == \
        "वार्षिक प्रतिवेदन"


def test_fontasy_preserves_ascii_numbers():
    assert legacy.decode("2022", "fontasy") == "2022"
    assert legacy.decode("-7.3", "fontasy") == "-7.3"
    assert legacy.decode("jflif{s k|ltj]bg", "fontasy") == "वार्षिक प्रतिवेदन"


def test_fontasy_applies_legacy_letter_overrides():
    assert legacy.decode("d'@f", "fontasy") == "मुद्दा"
    assert legacy.decode(r"km%\of}{^", "fontasy") == "फर्छ्यौट"
    assert legacy.decode("a(L", "fontasy") == "बढी"
    assert legacy.decode("ljj/)f", "fontasy") == "विवरण"


def test_fontasy_preserves_decimals_inside_numbers():
    assert legacy.decode("cf=j= -2064.65_", "fontasy") == \
        "आ.व. (2064.65)"
    assert legacy.decode("hDdf 30.2", "fontasy") == "जम्मा 30.2"


def test_unsupported_legacy_families_are_not_decoded():
    assert legacy.decode("g]kfn", "kantipur") is None
    assert not legacy.supported("kantipur")


def test_gen_fonts_decode_pdf_cids():
    assert legacy.decode_cids([4, 3, 5, 1, 6, 3, 5, 2], "gen-ganess") == \
        "२०६४/०६५"
    assert legacy.decode_cids(
        [2, 10, 7, 4, 17, 3, 14, 1], "gen-rukmini") == "सर्वोच्च "
    assert legacy.decode_cids([19], "gen-sumod") == "ढ"
    assert legacy.decode_cids([999], "gen-ganess") is None
    assert legacy.table_family("gen-ganess")

    text = "".join(chr(cid) for cid in [2, 10, 7, 4, 17, 3, 14, 1])
    assert legacy.decode_font(text, "OGPBEA+Gen_RukminiBold") == \
        "सर्वोच्च "
    assert legacy.supported("OGPBEA+Gen_Aakriti")
