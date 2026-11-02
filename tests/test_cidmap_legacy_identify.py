from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from cidmap.legacy_identify import (
    LegacyReferenceIndex,
    identify_font,
)


def _glyph(draw):
    pen = TTGlyphPen(None)
    draw(pen)
    return pen.glyph()


def _box(x0, y0, x1, y1):
    def draw(pen):
        pen.moveTo((x0, y0))
        pen.lineTo((x1, y0))
        pen.lineTo((x1, y1))
        pen.lineTo((x0, y1))
        pen.closePath()
    return draw


def _build(path, glyphs, cmap=None, family="Test", style="Regular"):
    builder = FontBuilder(1000, isTTF=True)
    order = list(glyphs)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap or {})
    builder.setupGlyf({
        name: _glyph(draw) if draw else _glyph(lambda pen: None)
        for name, draw in glyphs.items()
    })
    builder.setupHorizontalMetrics({name: (100, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": style})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(str(path))
    return TTFont(str(path), lazy=False)


def test_internal_name_identifies_renamed_base_font(tmp_path):
    font = _build(
        tmp_path / "font.ttf",
        {".notdef": None, "a": _box(0, 0, 100, 100)},
        {ord("a"): "a"},
        family="Preeti",
    )
    identity = identify_font("ABCDEF+Foo", font)
    assert identity.family == "preeti"
    assert identity.source == "font-name"
    assert identity.supported
    assert identity.confidence == "high"


def test_base_font_identification_precedes_embedded_name(tmp_path):
    font = _build(
        tmp_path / "font.ttf",
        {".notdef": None, "a": _box(0, 0, 100, 100)},
        {ord("a"): "a"},
        family="Kantipur",
    )
    identity = identify_font("ABCDEF+Preeti", font)
    assert identity.family == "preeti"
    assert identity.source == "base-font"


def test_unsupported_named_family_is_flagged_for_table():
    identity = identify_font("ABCDEF+Sagarmatha")
    assert identity.family == "sagarmatha"
    assert not identity.supported
    assert identity.needs_table


def test_committed_table_family_reports_cid_encoding():
    identity = identify_font("ABCDEF+Gen_Ganess")
    assert identity.family == "gen-ganess"
    assert identity.source == "table"
    assert identity.supported
    assert identity.encoding == "cid"


def test_reference_outlines_identify_arbitrary_font_names(tmp_path):
    reference = _build(
        tmp_path / "Preeti.ttf",
        {
            ".notdef": None,
            "a": _box(0, 0, 100, 100),
            "b": _box(20, 0, 80, 90),
            "c": _box(10, 10, 70, 70),
        },
        {ord("a"): "a", ord("b"): "b", ord("c"): "c"},
        family="Preeti",
    )
    embedded = _build(
        tmp_path / "embedded.ttf",
        {
            ".notdef": None,
            "x": _box(0, 0, 100, 100),
            "y": _box(20, 0, 80, 90),
            "z": _box(10, 10, 70, 70),
        },
        {ord("a"): "x", ord("b"): "y", ord("c"): "z"},
        family="Renamed",
    )
    references = LegacyReferenceIndex(
        [tmp_path / "Preeti.ttf"], min_matches=3, min_ratio=1.0)
    identity = identify_font(
        "ABCDEF+Embedded", embedded, simple=True, references=references)
    assert identity.family == "preeti"
    assert identity.source == "reference-outline"
    assert identity.reference == str(tmp_path / "Preeti.ttf")
    assert identity.matches == 3
    assert identity.total == 3


def test_unknown_simple_ascii_font_is_flagged_not_decoded(tmp_path):
    font = _build(
        tmp_path / "font.ttf",
        {".notdef": None, "a": _box(0, 0, 100, 100)},
        {ord("a"): "a"},
        family="Mystery",
    )
    identity = identify_font(
        "ABCDEF+Mystery", font, simple=True,
        references=LegacyReferenceIndex([]))
    assert identity.family is None
    assert identity.legacy_like
    assert identity.needs_table
    assert identity.source == "ascii-structure"


def test_unicode_font_is_not_flagged_as_legacy_like(tmp_path):
    font = _build(
        tmp_path / "font.ttf",
        {".notdef": None, "ka": _box(0, 0, 100, 100)},
        {0x0915: "ka"},
        family="Kalimati",
    )
    identity = identify_font(
        "ABCDEF+Kalimati", font, simple=False,
        references=LegacyReferenceIndex([]))
    assert identity.family is None
    assert not identity.legacy_like
    assert not identity.needs_table
