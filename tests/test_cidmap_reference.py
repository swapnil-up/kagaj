import pytest

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from cidmap.reference import (
    GlyphShape,
    ReferenceEnsemble,
    ReferenceIndex,
    ReferenceMatch,
    _shape,
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


def _build(path, glyphs, cmap, feature_text=None):
    builder = FontBuilder(1000, isTTF=True)
    order = list(glyphs)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap)
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
    if feature_text:
        addOpenTypeFeaturesFromString(builder.font, feature_text)
    builder.font.save(str(path))
    return path


@pytest.fixture
def reference_font(tmp_path):
    return _build(
        tmp_path / "reference.ttf",
        {
            ".notdef": None,
            "space": None,
            "a": _box(0, 0, 100, 100),
            "b": _box(0, 0, 80, 90),
            "a.alt": _box(0, 0, 90, 110),
            "a_b": _box(0, 0, 180, 100),
        },
        {ord("a"): "a", ord("b"): "b"},
        """
        feature liga { sub a b by a_b; } liga;
        feature salt { sub a by a.alt; } salt;
        """,
    )


def test_reference_index_inherits_alternate_and_ligature_roles(reference_font):
    index = ReferenceIndex.from_path(reference_font)
    roles = {name: values for _, name, values in index._shapes}
    assert roles["a"] == ("a",)
    assert roles["a.alt"] == ("a",)
    assert roles["a_b"] == ("ab",)


def test_reference_index_matches_renumbered_glyph(reference_font, tmp_path):
    embedded = _build(
        tmp_path / "embedded.ttf",
        {
            ".notdef": None,
            "g1": _box(0, 0, 90, 110),
        },
        {},
    )
    font = TTFont(str(embedded), lazy=False)
    shape = _shape(font.getGlyphSet(), "g1", font["hmtx"],
                   font["head"].unitsPerEm)
    index = ReferenceIndex.from_path(reference_font)
    match = index.suggest(shape)[0]
    assert match.value == "a"
    assert match.glyph == "a.alt"
    assert match.exact
    metadata = index.metadata()
    assert metadata["family"] == "Test"
    assert metadata["style"] == "Regular"
    assert metadata["path"] == str(reference_font)
    assert len(metadata["sha256"]) == 64


def test_reference_index_matches_ligature(reference_font):
    index = ReferenceIndex.from_path(reference_font)
    shape = next(shape for shape, name, _ in index._shapes if name == "a_b")
    assert index.suggest(shape)[0].value == "ab"
    assert index.suggest(shape)[0].exact


def test_reference_index_zero_distance_is_exact_with_different_point_count(
        reference_font):
    index = ReferenceIndex.from_path(reference_font)
    source = next(shape for shape, name, _ in index._shapes if name == "a.alt")
    shape = GlyphShape(source.value, source.advance, source.contours,
                       source.points + 4, source.bitmap)
    match = index.suggest(shape)[0]
    assert match.exact


def test_reference_index_near_zero_bitmap_diff_is_not_exact(reference_font):
    index = ReferenceIndex.from_path(reference_font)
    source = next(shape for shape, name, _ in index._shapes if name == "a.alt")
    bitmap = source.bitmap[:-1] if len(source.bitmap) > 1 else ()
    shape = GlyphShape(source.value, source.advance, source.contours,
                       source.points, bitmap)
    match = index.suggest(shape)[0]
    assert not match.exact
    assert 0 < match.score < 0.75


def test_reference_index_marks_near_match_as_non_exact(reference_font):
    index = ReferenceIndex.from_path(reference_font)
    source = next(shape for shape, name, _ in index._shapes if name == "a.alt")
    near = GlyphShape((0.0, 0.0, 91.0, 110.0), source.advance,
                      source.contours, source.points, source.bitmap)
    match = index.suggest(near)[0]
    assert match.value == "a"
    assert not match.exact


def test_reference_index_returns_no_match_for_unknown_shape(reference_font):
    index = ReferenceIndex.from_path(reference_font)
    source = next(shape for shape, name, _ in index._shapes if name == "a_b")
    shape = GlyphShape((5000.0, 5000.0, 6000.0, 6000.0),
                       source.advance, source.contours, source.points,
                       source.bitmap)
    assert index.suggest(shape) == []


def test_candidate_wrapping():
    from cidmap.glyph_review import _reference_candidates

    class FakeReference:
        def suggest(self, shape):
            assert shape == "shape"
            return [ReferenceMatch("a", "a.alt", 0.0, "a.alt · score 0.0")]

    class FakeEmbedded:
        def shape(self, xref, cid):
            assert (xref, cid) == (7, 42)
            return "shape"

    candidates = _reference_candidates(
        FakeReference(), FakeEmbedded(), {"font_xref": 7}, 42)
    assert candidates[0].value == "a"
    assert candidates[0].label == "ref a"


class _FakeIndex:
    def __init__(self, matches):
        self.matches = matches

    def suggest(self, shape, limit=5):
        return list(self.matches)

    def metadata(self):
        return {"family": "Fake", "style": "Regular", "sha256": "0" * 64}


def test_ensemble_requires_exact_agreement_across_references():
    exact = ReferenceMatch("a", "a", 0.0, "exact", exact=True)
    near = ReferenceMatch("a", "a.alt", 0.5, "near", exact=False)
    ensemble = ReferenceEnsemble([_FakeIndex([exact]), _FakeIndex([near])])
    match = ensemble.suggest("shape")[0]
    assert not match.exact
    assert match.score == 0.5
    assert match.references == 2


def test_ensemble_marks_value_exact_only_in_every_reference():
    exact = ReferenceMatch("a", "a", 0.0, "exact", exact=True)
    ensemble = ReferenceEnsemble([_FakeIndex([exact]), _FakeIndex([exact])])
    match = ensemble.suggest("shape")[0]
    assert match.exact
    assert "2/2 refs" in match.detail
