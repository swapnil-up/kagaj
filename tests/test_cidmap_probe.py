from types import SimpleNamespace

from cidmap import cli
from cidmap import probe as probe_mod
from cidmap.reference import ReferenceMatch


class FakeDoc:
    name = "fake.pdf"

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return object()

    def xref_get_key(self, xref, key):
        return ("null", "null")


def test_probe_reports_coverage_classes_and_unknown_cids(monkeypatch):
    glyphs = [
        {"font_id": "F@cmap:1", "base_font": "F", "font_xref": 10,
         "font_id_scheme": "cmap-hash", "cid": 1, "c": "\u0915"},
        {"font_id": "F@cmap:1", "base_font": "F", "font_xref": 10,
         "font_id_scheme": "cmap-hash", "cid": 2, "c": "\ufffd"},
        {"font_id": "F@cmap:1", "base_font": "F", "font_xref": 10,
         "font_id_scheme": "cmap-hash", "cid": 2, "c": "\ufffd"},
        {"font_id": "F@cmap:1", "base_font": "F", "font_xref": 10,
         "font_id_scheme": "cmap-hash", "cid": 3, "c": "\ue000"},
    ]
    monkeypatch.setattr(probe_mod, "extract_glyphs",
                        lambda page, dedup=True: glyphs)

    result = probe_mod.probe_document(FakeDoc())
    assert result["pages_scanned"] == 1
    assert result["issues"] == []
    font = result["fonts"][0]
    assert font["font_id"] == "F@cmap:1"
    assert font["observed"] == 4
    assert font["known"] == 2
    assert font["unknown"] == 2
    assert font["coverage"] == 0.5
    assert font["classes"] == {
        "devanagari": 1,
        "pua": 1,
        "replacement": 2,
    }
    assert font["unknown_cids"] == [
        {"cid": 2, "count": 2, "pages": [1]},
    ]
    assert font["cmap_entries"] == 0
    assert "unknown CIDs: 2\u00d72" in probe_mod.format_probe(result)


def test_probe_candidates_use_reference_matches():
    class Reference:
        def suggest(self, shape):
            assert shape == "shape"
            return [ReferenceMatch("a", "a.alt", 1.5, "a.alt")]

    class Embedded:
        def shape(self, xref, cid):
            assert (xref, cid) == (7, 42)
            return "shape"

    found = probe_mod._candidates(Reference(), Embedded(), 7, 42)
    assert found == [{"value": "a", "glyph": "a.alt", "score": 1.5,
                      "detail": "a.alt"}]


def test_cmd_probe_writes_json(monkeypatch, tmp_path):
    result = {
        "pdf": "fake.pdf", "pages_scanned": 1, "issues": [],
        "fonts": [],
    }
    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(probe_mod, "probe_document",
                        lambda doc, max_pages=None, reference_font=None:
                        result)
    out = tmp_path / "probe.json"
    args = SimpleNamespace(pdf="fake.pdf", max_pages=None,
                           reference_font=None, json=str(out))

    assert cli.cmd_probe(args) == 0
    assert out.exists()
    assert "fake.pdf" in out.read_text(encoding="utf-8")


def test_probe_formats_registry_evidence():
    result = {
        "pdf": "fake.pdf",
        "pages_scanned": 1,
        "issues": [],
        "fonts": [{
            "font_id": "F@cmap:1",
            "base_font": "F",
            "font_xref": 1,
            "font_id_scheme": "cmap-hash",
            "observed": 1,
            "known": 0,
            "unknown": 1,
            "coverage": 0.0,
            "classes": {"replacement": 1},
            "cmap_entries": 0,
            "glyph_count": None,
            "subset_signature": None,
            "font_signature": None,
            "unknown_cids": [{
                "cid": 2, "count": 1, "pages": [1],
                "registry": {"value": "ि", "status": "confirmed",
                             "support": 2},
            }],
            "candidates": {},
        }],
    }
    assert "cid 2: registry ि (confirmed, 2 doc)" in \
        probe_mod.format_probe(result)
