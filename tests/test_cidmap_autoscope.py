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
                {"cid": 7, "pages": [3]},
                {"cid": 8, "pages": [3]},
                {"cid": 9, "pages": [3]},
            ],
            "candidates": {
                "1": [{"value": "\u0915", "glyph": "ka", "score": 0.0,
                       "exact": True}],
                "2": [
                    {"value": "\u093f", "glyph": "i", "score": 0.0,
                     "exact": True},
                    {"value": "\u0940", "glyph": "ii", "score": 0.2},
                ],
                "3": [{"value": "\u0916", "glyph": ".notdef.19",
                       "score": 0.0, "exact": True}],
                "4": [{"value": "\u0917", "glyph": "ga", "score": 2.0}],
                "5": [{"value": "\u0918", "glyph": "gha", "score": 0.0,
                       "exact": True}],
                "6": [{"value": "\u0919", "glyph": "nga", "score": 0.0,
                       "exact": True}],
                "7": [
                    {"value": "\u091a", "glyph": "ca", "score": 0.0,
                     "exact": True},
                    {"value": "\u091b", "glyph": "cha", "score": 0.0,
                     "exact": True},
                ],
                "8": [
                    {"value": "\u091f", "glyph": "tta", "score": 0.5},
                    {"value": "\u0920", "glyph": "ttha", "score": 2.0},
                ],
                "9": [
                    {"value": "\u0921", "glyph": "dda", "score": 0.5},
                    {"value": "\u0922", "glyph": "ddha", "score": 2.0},
                ],
            },
        }],
        "reference": {"family": "Kalimati", "style": "Regular",
                      "version": "1.0", "sha256": "a" * 64},
    }


def test_scope_plan_selects_only_unambiguous_exact_matches(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {
        "fonts": {"K@cmap:1": {}},
        "cids": {5: {"": "\u0918"}, 6: {"": "\u0915"},
                 9: {"": "\u0915"}},
        "undecodable": [],
    }
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert [(item.cid, item.value) for item in plan.mappings] == [
        (1, "\u0915"),
        (2, "\u093f"),
        (5, "\u0918"),
        (6, "\u0919"),
        (8, "\u091f"),
    ]
    assert plan.mappings[0].tier == "exact"
    assert plan.mappings[-1].tier == "near"
    assert plan.reference["family"] == "Kalimati"
    reasons = {item.cid: item.reason for item in plan.rejected}
    assert "ambiguous exact" in reasons[7]
    assert "score" in reasons[4]
    assert "fallback" in reasons[9]
    assert plan.mappings[3].fallback == "\u0915"

    assert autoscope.apply_scope_plan(store, plan) == 5
    assert get_value(store, "K@cmap:1", 1) == "\u0915"
    assert store["fonts"]["K@cmap:1"][5] == "\u0918"
    assert store["cids"][6]["_meta"]["fallback_overridden"] == "\u0915"
    assert store["cids"][8]["_meta"]["match"] == "near"
    assert "Reference matches: 5" in autoscope.format_plan(plan)
    assert "exact=4, near=1" in autoscope.format_plan(plan)
    lines = autoscope.rejected_jsonl(plan).splitlines()
    assert len(lines) == len(plan.rejected)
    assert '"reason"' in lines[0]


def test_scope_plan_skips_existing_font_scoped_value(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {"fonts": {"K@cmap:1": {1: "\u0915"}}, "cids": {},
             "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert all(item.cid != 1 for item in plan.mappings)


def test_scope_plan_rejects_near_fallback_conflict(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    store = {"fonts": {"K@cmap:1": {}}, "cids": {9: {"": "\u0915"}},
             "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert all(item.cid != 9 for item in plan.mappings)
    assert any(item.cid == 9 and "fallback" in item.reason
               for item in plan.rejected)


def _inference(cid, value):
    from cidmap.infer import CidInference
    return CidInference(
        font_id="K@cmap:1", cid=cid, value=value, score=0.0, runs=1)


def test_lexicon_resolves_ambiguous_exact(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    monkeypatch.setattr(
        autoscope, "_lexical_values",
        lambda *args, **kwargs: {("K@cmap:1", 7): _inference(7, "\u091b")})
    store = {"fonts": {"K@cmap:1": {}}, "cids": {}, "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    item = next(item for item in plan.mappings if item.cid == 7)
    assert item.value == "\u091b"
    assert item.lexicon == "\u091b"
    assert plan.lexicon_votes == 1


def test_lexicon_accepts_corroborated_near(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    monkeypatch.setattr(
        autoscope, "_lexical_values",
        lambda *args, **kwargs: {("K@cmap:1", 8): _inference(8, "\u091f")})
    store = {"fonts": {"K@cmap:1": {}}, "cids": {}, "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    item = next(item for item in plan.mappings if item.cid == 8)
    assert item.tier == "near"
    assert item.lexicon == "\u091f"


def test_lexicon_rejects_conflicting_near(monkeypatch):
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: _probe())
    monkeypatch.setattr(
        autoscope, "_lexical_values",
        lambda *args, **kwargs: {("K@cmap:1", 8): _inference(8, "\u0920")})
    store = {"fonts": {"K@cmap:1": {}}, "cids": {}, "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    assert all(item.cid != 8 for item in plan.mappings)
    assert any(item.cid == 8 and "lexicon" in item.reason
               for item in plan.rejected)


def test_lexicon_derives_exact_cluster_role(monkeypatch):
    probe = _probe()
    probe["fonts"][0]["unknown_cids"].append({"cid": 10, "pages": [1]})
    probe["fonts"][0]["candidates"]["10"] = [
        {"value": "\u0924\u0930\u094d", "glyph": "u093D", "score": 0.0,
         "exact": True},
        {"value": "\u093d", "glyph": "u093D", "score": 0.0,
         "exact": True},
    ]
    monkeypatch.setattr(autoscope, "probe_document",
                        lambda *args, **kwargs: probe)
    monkeypatch.setattr(
        autoscope, "_lexical_values",
        lambda *args, **kwargs: {
            ("K@cmap:1", 10): type(_inference(10, "\u0924\u094d\u0930"))(
                font_id="K@cmap:1", cid=10, value="\u0924\u094d\u0930",
                score=100.0, runs=1, shape_score=0.0)
        })
    store = {"fonts": {"K@cmap:1": {}}, "cids": {}, "undecodable": []}
    plan = autoscope.build_scope_plan(
        object(), store, reference_font="Kalimati.ttf")
    item = next(item for item in plan.mappings if item.cid == 10)
    assert item.value == "\u0924\u094d\u0930"
    assert item.glyph == "u093D"
    assert item.exact
    assert item.lexicon == "\u0924\u094d\u0930"
