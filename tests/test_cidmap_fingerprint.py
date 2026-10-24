from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from cidmap.fingerprint import (
    font_signature,
    glyph_fingerprint,
    subset_signature,
)


def _glyph(draw, glyph_set=None):
    pen = TTGlyphPen(glyph_set)
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


def _build(path, glyphs, cmap=None, name=True):
    builder = FontBuilder(1000, isTTF=True)
    order = list(glyphs)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap or {})
    builder.setupGlyf({
        name: _glyph(draw, order) if draw else _glyph(lambda pen: None, order)
        for name, draw in glyphs.items()
    })
    builder.setupHorizontalMetrics({name: (100, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    if name:
        builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(str(path))
    return TTFont(str(path), lazy=False)


def _fingerprint(font, glyph_name):
    return glyph_fingerprint(
        font.getGlyphSet(), glyph_name, font["hmtx"],
        font["head"].unitsPerEm)


def test_glyph_fingerprint_ignores_name_and_order(tmp_path):
    left = _build(tmp_path / "left.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
    })
    right = _build(tmp_path / "right.ttf", {
        ".notdef": None,
        "renamed": _box(0, 0, 100, 100),
    })
    assert _fingerprint(left, "a") == _fingerprint(right, "renamed")


def test_glyph_fingerprint_distinguishes_outlines(tmp_path):
    font = _build(tmp_path / "font.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
        "b": _box(0, 0, 80, 90),
    })
    assert _fingerprint(font, "a").outline_hash != \
        _fingerprint(font, "b").outline_hash


def test_glyph_fingerprint_decomposes_component_glyphs(tmp_path):
    def component(pen):
        pen.addComponent("a", (1, 0, 0, 1, 0, 0))

    font = _build(tmp_path / "font.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
        "composite": component,
    })
    assert _fingerprint(font, "composite").outline_hash == \
        _fingerprint(font, "a").outline_hash


def test_subset_signature_changes_with_glyph_set(tmp_path):
    small = _build(tmp_path / "small.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
    })
    large = _build(tmp_path / "large.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
        "b": _box(0, 0, 80, 90),
    })
    assert subset_signature(small) != subset_signature(large)


def test_font_signature_survives_missing_name_table(tmp_path):
    font = _build(tmp_path / "font.ttf", {
        ".notdef": None,
        "a": _box(0, 0, 100, 100),
    })
    del font["name"]
    signature = font_signature(font, "ABCDEF+Test")
    assert signature.family == ""
    assert signature.base_font == "ABCDEF+Test"
    assert signature.glyph_count == 2
    assert len(signature.family_hash) == 64
