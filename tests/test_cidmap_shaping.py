import pytest

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from cidmap.shaping import ReferenceShaper


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


def _build(path):
    builder = FontBuilder(1000, isTTF=True)
    glyphs = {
        ".notdef": None,
        "space": None,
        "a": _box(0, 0, 100, 100),
        "b": _box(0, 0, 80, 90),
        "a_b": _box(0, 0, 180, 100),
    }
    order = list(glyphs)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({ord("a"): "a", ord("b"): "b"})
    builder.setupGlyf({
        name: _glyph(draw) if draw else _glyph(lambda pen: None)
        for name, draw in glyphs.items()
    })
    builder.setupHorizontalMetrics({
        name: (200 if name == "a_b" else 100, 0) for name in order
    })
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    addOpenTypeFeaturesFromString(
        builder.font, "feature liga { sub a b by a_b; } liga;")
    builder.font.save(str(path))
    return path


@pytest.fixture
def shaper(tmp_path):
    return ReferenceShaper.from_path(_build(tmp_path / "reference.ttf"))


def test_shape_returns_visual_glyphs_with_clusters(shaper):
    glyphs = shaper.shape("ab")
    assert [glyph.name for glyph in glyphs] == ["a_b"]
    assert glyphs[0].cluster == 0
    assert glyphs[0].values == ("ab",)


def test_shape_cache_and_value_for_ligature(shaper):
    first = shaper.shape_cached("ab")
    assert first is shaper.shape_cached("ab")
    glyph = first[0]
    assert shaper.value_for("ab", glyph) == "ab"
    assert shaper.cluster_span("ab", 0) == "ab"


def test_shape_without_ligature_keeps_order(shaper):
    glyphs = shaper.shape("ba")
    assert [glyph.name for glyph in glyphs] == ["b", "a"]
    assert [glyph.cluster for glyph in glyphs] == [0, 1]
