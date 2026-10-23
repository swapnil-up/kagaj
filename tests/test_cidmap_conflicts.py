import pytest

from cidmap import ocr
from cidmap.conflicts import build_conflicts, build_conflicts_from_census
from cidmap.mappings import empty_store, set_fallback, set_value

FONT = "ABCDEF+Kalimati-1"


def _rec(count, pages, context="\u27e61\u27e7", bbox=(10, 20, 18, 30)):
    return {
        "count": count,
        "pages": list(pages),
        "contexts": [context],
        "samples": [{"page": pages[0], "bbox": bbox}],
        "range": f"p{pages[0]}\u2013p{pages[-1]}",
    }


@pytest.fixture
def cen():
    return {FONT: {
        1: _rec(3, [1, 2]),
        2: _rec(3, [1]),
        3: _rec(2, [2]),
        4: _rec(1, [3]),
        5: _rec(2, [4]),
        6: _rec(1, [5]),
        7: _rec(1, [6]),
    }}


@pytest.fixture
def store():
    store = empty_store()
    set_value(store, FONT, 1, "\u0938\u0930\u0915\u093e\u0930")
    set_value(store, FONT, 2, "\u0935\u094d\u092f\u092f")
    set_value(store, FONT, 4, "\u0915")
    set_value(store, FONT, 5, "\u0916")
    set_value(store, FONT, 6, "\u0915\u093c")
    set_fallback(store, 7, "\u0921")
    return store


@pytest.fixture
def ocr_data():
    return {
        "reads": {FONT: {
            1: [{"page": 1, "word": "\u0938\u0930\u0915\u093e\u0930",
                 "bbox": (100, 200, 160, 220)}],
            2: [
                {"page": 1, "word": "\u0935\u094d\u092f\u092f",
                 "bbox": (110, 210, 150, 230)},
                {"page": 1, "word": "\u0935\u094d\u092f\u092a",
                 "bbox": (111, 211, 151, 231)},
            ],
            3: [{"page": 2, "word": "\u0928\u0947\u092a\u093e\u0932",
                 "bbox": (120, 220, 180, 240)}],
            5: [
                {"page": 4, "word": "\u0916", "bbox": (130, 230, 140, 250)},
                {"page": 4, "word": "\u0917", "bbox": (131, 231, 141, 251)},
            ],
            6: [{"page": 5, "word": "\u0958",
                 "bbox": (140, 240, 150, 260)}],
            7: [{"page": 6, "word": "\u0921",
                 "bbox": (150, 250, 160, 270)}],
        }},
        "counts": {FONT: {
            1: {"\u0938\u0930\u0915\u093e\u0930": 3},
            2: {"\u0935\u094d\u092f\u092a": 2, "\u0935\u094d\u092f\u092f": 1},
            3: {"\u0928\u0947\u092a\u093e\u0932": 2},
            5: {"\u0916": 1, "\u0917": 1},
            6: {"\u0958": 1},
            7: {"\u0921": 1},
        }},
    }


def _by_cid(conflicts):
    return {conflict.cid: conflict for conflict in conflicts}


def test_build_conflicts_wrapper_scans_with_census(monkeypatch, cen, store,
                                                   ocr_data):
    monkeypatch.setattr("cidmap.conflicts.census", lambda doc: cen)
    conflicts = build_conflicts(object(), store, ocr_data)
    assert {c.cid for c in conflicts} == set(cen[FONT])


def test_candidates_are_separate_and_carry_word_boxes(cen, store, ocr_data):
    conflicts = _by_cid(build_conflicts(
        None, store, ocr_data, census_result=cen))
    cid2 = conflicts[2]

    assert [c["word"] for c in cid2.ocr_candidates] == [
        "\u0935\u094d\u092f\u092a", "\u0935\u094d\u092f\u092f"]
    assert [c["count"] for c in cid2.ocr_candidates] == [2, 1]
    assert cid2.ocr_candidates[0]["bbox"] == (111, 211, 151, 231)
    assert cid2.word_bbox == (111, 211, 151, 231)
    assert cid2.glyph_bbox == (10, 20, 18, 30)
    assert cid2.page == 1
    assert cid2.n_occ == 3
    assert cid2.page_range == "p1\u2013p1"
    assert cid2.context == "\u27e61\u27e7"


def test_verdicts_cover_every_state(cen, store, ocr_data):
    conflicts = _by_cid(build_conflicts(
        None, store, ocr_data, census_result=cen))

    assert conflicts[1].verdict == "agree"
    assert conflicts[2].verdict == "disagree"
    assert conflicts[3].verdict == "missing"
    assert conflicts[4].verdict == "no-ocr"
    assert conflicts[5].verdict == "tie"
    assert conflicts[6].verdict == "agree"
    assert conflicts[7].verdict == "agree"


def test_store_and_derive_values_are_reported(cen, store, ocr_data):
    conflicts = _by_cid(build_conflicts(
        None, store, ocr_data, census_result=cen))

    assert conflicts[1].store_value == "\u0938\u0930\u0915\u093e\u0930"
    assert conflicts[1].derive_value is None
    assert conflicts[7].store_value is None
    assert conflicts[7].derive_value == "\u0921"
    assert conflicts[3].agreement["evidence"] == 2
    assert conflicts[1].agreement["agree"] == 3


def test_plain_counts_are_accepted(cen, store):
    plain = {FONT: {1: {"\u0938\u0930\u0915\u093e\u0930": 2}}}
    conflict = build_conflicts_from_census(cen, store, plain)[0]

    assert conflict.ocr_candidates == [{
        "word": "\u0938\u0930\u0915\u093e\u0930", "count": 2,
        "pages": [], "bbox": None,
    }]
    assert conflict.word_bbox is None


def test_pages_filter_limits_rows(cen, store, ocr_data):
    conflicts = build_conflicts(
        None, store, ocr_data, pages=[1], census_result=cen)
    assert {c.cid for c in conflicts} == {1, 2}


@pytest.mark.parametrize("value,ocr_word", [
    ("\u093f", "\u0915\u093f"),
    ("\u094d", "\u0915\u094d"),
    ("\u093c", "\u0915\u093c"),
    ("\u094b", "\u0915\u094b"),
    ("\u0930\u094d", "\u0915\u0930\u094d\u092e"),
])
def test_glyph_fragments_are_valid_store_values(cen, store, value, ocr_word):
    set_value(store, FONT, 3, value)
    conflict = _by_cid(build_conflicts_from_census(
        cen, store, {FONT: {3: {ocr_word: 2}}}))[3]

    assert conflict.agreement["value_valid"] is True
    assert conflict.verdict == "agree"


def test_invalid_glyph_value_is_reported_as_disagree(cen, store):
    set_value(store, FONT, 3, "\u093f\u093e")
    conflicts = _by_cid(build_conflicts_from_census(
        cen, store, {FONT: {3: {"\u0915\u093f\u093e": 1}}}))
    assert conflicts[3].verdict == "disagree"
    assert "matra-on-matra" in conflicts[3].agreement["value_issues"]


def test_word_box_at_returns_the_printed_word_box():
    words = [("\u0938\u0930\u0915\u093e\u0930", 1.0, 2.0, 30.0, 12.0)]
    assert ocr.word_box_at(words, 5.0, 5.0) == words[0]
    assert ocr.word_at(words, 5.0, 5.0) == "\u0938\u0930\u0915\u093e\u0930"
    assert ocr.word_box_at(words, 50.0, 50.0) is None
