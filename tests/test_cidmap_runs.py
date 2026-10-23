from cidmap.runs import runs_with_unknown, word_runs


def _glyph(cid, char, x, y=100.0, width=10.0, font_id="f", xref=7):
    return {
        "cid": cid,
        "c": char,
        "origin": (x, y),
        "bbox": (x, y - 10, x + width, y),
        "font_id": font_id,
        "font_xref": xref,
    }


def test_word_runs_split_on_gap_and_punctuation():
    glyphs = [
        _glyph(1, "\ufffd", 0),
        _glyph(2, "a", 10),
        _glyph(3, "(", 40),
        _glyph(4, "b", 50),
        _glyph(5, ")", 60),
    ]
    runs = word_runs(glyphs, page=3)
    assert [len(run.glyphs) for run in runs] == [2, 1]
    assert runs[0].page == 3
    assert runs[0].has_unknown
    assert runs[1].glyphs[0]["c"] == "b"


def test_word_runs_sort_by_x_when_baselines_jitter():
    glyphs = [
        _glyph(1, "\ufffd", 20, y=100.6),
        _glyph(2, "a", 10, y=100.0),
    ]
    run = word_runs(glyphs)[0]
    assert [g["c"] for g in run.glyphs] == ["a", "\ufffd"]


def test_word_runs_dedup_same_glyph_at_same_spot():
    glyphs = [
        _glyph(7, "a", 10, y=100.0),
        _glyph(7, "a", 10.4, y=100.2),
        _glyph(8, "b", 20, y=100.0),
    ]
    run = word_runs(glyphs)[0]
    assert [g["cid"] for g in run.glyphs] == [7, 8]


def test_runs_with_unknown_filters_known_words():
    glyphs = [
        _glyph(1, "a", 0),
        _glyph(2, "\ufffd", 10),
    ]
    runs = word_runs(glyphs)
    assert len(runs) == 1
    assert runs_with_unknown(runs) == runs
