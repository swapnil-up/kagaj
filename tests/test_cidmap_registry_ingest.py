from cidmap import registry


DOC = "a" * 64
FONT = "KLMNGO+Kalimati"


def _store():
    return {
        "fonts": {FONT: {1: "ि"}},
        "cids": {1: {"_meta": {"source": "review",
                               "evidence": ["p1 ⟦1⟧"]}}},
        "undecodable": [],
        "meta": {},
    }


def _doc():
    return [object()]


def test_ingest_records_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(registry, "extract_glyphs", lambda page, dedup=True: [{
        "font_id": FONT,
        "base_font": "Kalimati",
        "font_xref": 3,
        "font_id_scheme": "cmap-hash",
    }])
    monkeypatch.setattr(registry, "source_hash", lambda doc: DOC)
    monkeypatch.setattr(registry, "EmbeddedFontCache", lambda doc: object())
    monkeypatch.setattr(
        registry, "glyph_identity",
        lambda embedded, xref, cid, base_font="": (
            "f" * 64, "e" * 64, object()))

    reg = registry.empty_registry()
    assert registry.ingest_document(_doc(), _store(), registry=reg) == 1
    entry = registry.lookup(reg, "f" * 64, "e" * 64)
    assert entry["value"] == "ि"
    assert entry["status"] == "confirmed"
    assert entry["observations"][0]["source"] == "review"

    assert registry.ingest_document(_doc(), _store(), registry=reg) == 0
    assert len(entry["observations"]) == 1
