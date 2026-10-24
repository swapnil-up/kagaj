import pytest

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from cidmap.infer import _infer_run, aggregate_cids, RunInference, RunCandidate, GlyphAssignment
from cidmap.lexicon import LexiconIndex
from cidmap.runs import WordRun
from cidmap.shaping import ReferenceShaper


def _glyph(draw):
    pen = TTGlyphPen(None)
    draw(pen)
    return pen.glyph()


def _box(width):
    def draw(pen):
        pen.moveTo((0, 0))
        pen.lineTo((width, 0))
        pen.lineTo((width, 100))
        pen.lineTo((0, 100))
        pen.closePath()
    return draw


def _build(path):
    builder = FontBuilder(1000, isTTF=True)
    glyphs = {
        ".notdef": None,
        "a": _box(100),
        "b": _box(80),
        "c": _box(120),
    }
    order = list(glyphs)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({
        ord("a"): "a", ord("b"): "b", ord("c"): "c",
    })
    builder.setupGlyf({
        name: _glyph(draw) if draw else _glyph(lambda pen: None)
        for name, draw in glyphs.items()
    })
    builder.setupHorizontalMetrics({name: (100, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.font.save(str(path))
    return path


@pytest.fixture
def shaper(tmp_path):
    return ReferenceShaper.from_path(_build(tmp_path / "reference.ttf"))


class _Embedded:
    def __init__(self, index):
        self.index = index

    def shape(self, xref, cid):
        return self.index.shape_for(self.index.order[cid + 1])


def _run(chars):
    glyphs = []
    for index, char in enumerate(chars):
        glyphs.append({
            "cid": index,
            "c": char,
            "origin": (index * 10.0, 100.0),
            "bbox": (index * 10.0, 90.0, index * 10.0 + 8.0, 100.0),
            "font_id": "f",
            "font_xref": 1,
        })
    return WordRun(page=1, font_id="f", font_xref=1, glyphs=tuple(glyphs))


class _Lexicon:
    words = ("ab", "bb")

    def __contains__(self, word):
        return word in self.words

    def score(self, word):
        return 1.0 if word in self.words else 0.0


def test_infer_run_assigns_unknown_from_shape_and_lexicon(shaper):
    lexicon = _Lexicon()
    index = LexiconIndex(lexicon, shaper)
    run = _run(["\ufffd", "b"])
    candidates = _infer_run(
        run, shaper, index, lexicon, _Embedded(shaper.index),
        max_candidates=5, max_word_candidates=50)
    assert candidates[0].word == "ab"
    assert candidates[0].assignments[0].cid == 0
    assert candidates[0].assignments[0].value == "a"


def test_aggregate_cids_counts_runs_and_keeps_best_value():
    inference = RunInference(
        page=1,
        font_id="f",
        font_xref=1,
        observed="\ufffd",
        candidates=(
            RunCandidate(
                word="ab", score=1.0, alignment=((0, 0),),
                assignments=(GlyphAssignment(0, 0, "a", 0.0),),
            ),
            RunCandidate(
                word="bb", score=9.0, alignment=((0, 0),),
                assignments=(GlyphAssignment(0, 0, "b", 9.0),),
            ),
        ),
    )
    rows = aggregate_cids([inference])
    assert len(rows) == 1
    assert rows[0].value == "a"
    assert rows[0].runs == 1


def test_derived_assignment_removes_adjacent_known_matra():
    from types import SimpleNamespace
    from cidmap.infer import _derived_assignments

    class FakeShaper:
        def cluster_span(self, word, cluster):
            return "\u0924\u094d\u0930\u093e"

    observed = [
        {"char": "\ufffd"},
        {"char": "\u093e"},
    ]
    shaped = [SimpleNamespace(cluster=3), SimpleNamespace(cluster=3)]
    derived = _derived_assignments(
        observed, shaped, ((0, 0), (1, 1)), FakeShaper(), "x")
    assert derived == {0: "\u0924\u094d\u0930"}
