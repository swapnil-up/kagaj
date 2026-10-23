"""Tests for exact reference-outline bootstrapping."""

from cidmap import autoscope
from cidmap.mappings import get_value


def _probe():
    return {
        "pdf": "fake.pdf",
        "pages_scanned": 3,
        "fonts": [{
            "font_id": "K@cmap:1",
            "unknown_cids": [
                {"cid": 1, "pages": [1]},
                {"cid": 2, "pages": [2]},
                {"cid": 3, "pages": [3]},
                {"cid": 4, "pages": [3]},
                {"cid": 5, "pages": [3]},
                {"cid": 6, "pages": [3]},
            ],
            "candidates": {
                "1": [{"value": "\u0915", "glyph": "ka", "score": 0.0}],
                "2": [
                    {"value": "\u093f", "glyph": "i", "score": 0.0},
                    {"value": "\u0940", "glyph": "ii", "score": 0.2},
                ],
                "3": [{"value": "\u0916", "glyph": ".notdef.19",
                       "score": 0.0}],
                "4": [{"value": "\u0917", "glyph": "ga", "score": 2.0}],
                "5": [{"value": "\u0918", "glyph": "gha", "score": 0.0}],
                "6": [{"value": "\u0919", "glyph": "nga", "score": 0.0}],
            },
        }],
    }


def test_scope_plan_selects_only_unambiguous_exact_matches(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {
        "fonts": {"K@cmap:1": {}},
        "cids": {5: {"": "\u0918"}, 6: {"": "\u0915"}},
        "undecodable": [],
    }
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert [(item.cid, item.value) for item in plan.mappings] == [
        (1, "\u0915"),
        (5, "\u0918"),
    ]
    reasons = {item.cid: item.reason for item in plan.rejected}
    assert "ambiguous" in reasons[2]
    assert "score" in reasons[4]
    assert "fallback" in reasons[6]

    assert autoscope.apply_scope_plan(store, plan) == 2
    assert get_value(store, "K@cmap:1", 1) == "\u0915"
    assert store["fonts"]["K@cmap:1"][5] == "\u0918"
    assert "Exact reference matches: 2" in autoscope.format_plan(plan)


def test_scope_plan_skips_existing_font_scoped_value(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {"fonts": {"K@cmap:1": {1: "\u0915"}}, "cids": {},
             "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert all(item.cid != 1 for item in plan.mappings)


def test_scope_plan_rejects_invalid_fallback_conflict(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {"fonts": {"K@cmap:1": {}}, "cids": {6: {"": "\u0915"}},
             "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert all(item.cid != 6 for item in plan.mappings)
    assert any(item.cid == 6 and "fallback" in item.reason
               for item in plan.rejected)
