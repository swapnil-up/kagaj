from cidmap import glyph_review, registry


def test_registry_candidate_is_injected(monkeypatch):
    monkeypatch.setattr(registry, "resolve_glyph", lambda *args, **kwargs: {
        "entry": {
            "value": "ि",
            "status": "confirmed",
            "support": 2,
        },
    })
    found = glyph_review._registry_candidates(
        {"glyphs": {}}, object(), {"font_xref": 3, "base_font": "Kalimati"}, 7)
    assert len(found) == 1
    assert found[0].value == "ि"
    assert "registry" in found[0].detail


def test_conflicted_registry_entry_is_not_a_candidate(monkeypatch):
    monkeypatch.setattr(registry, "resolve_glyph", lambda *args, **kwargs: {
        "entry": {"value": "", "status": "conflict", "support": 2},
    })
    found = glyph_review._registry_candidates(
        {"glyphs": {}}, object(), {"font_xref": 3, "base_font": "Kalimati"}, 7)
    assert found == ()
