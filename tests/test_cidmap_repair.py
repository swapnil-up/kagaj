"""Tests for store-backed PDF ToUnicode repair."""

import fitz
import pytest

from cidmap.fonts import _cmap_mappings, cmap_mapping, document_fonts, font_identity
from cidmap.repair import (
    build_repair_plan,
    cmap_bytes,
    format_plan,
    write_repair,
    _codepoints_text,
    _install_cmap,
)


CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
2 beginbfchar
<0001> <0915>
<0002> <093F>
endbfchar
endcmap
"""


class FakePage:
    def __init__(self, doc, xref=10, contents=(11,)):
        self.parent = doc
        self.xref = xref
        self._contents = list(contents)

    def get_contents(self):
        return self._contents


class FakeDoc:
    name = "/definitely/not/a/real.pdf"

    def __init__(self):
        self.streams = {40: CMAP, 11: b""}
        self.resources = {
            10: {"Resources/Font": ("dict", "<< /F1 20 0 R >>")},
        }
        self.fonts = {
            20: {
                "BaseFont": ("name", "/Kalimati"),
                "Subtype": ("name", "/Type0"),
                "Encoding": ("name", "/Identity-H"),
                "ToUnicode": ("xref", "40 0 R"),
            },
        }

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return FakePage(self)

    def xref_get_key(self, xref, key):
        if xref in self.resources:
            return self.resources[xref].get(key, ("null", "null"))
        return self.fonts.get(xref, {}).get(key, ("null", "null"))

    def xref_stream(self, xref):
        return self.streams.get(xref, b"")

    def tobytes(self):
        return b"fake-pdf"


def test_cmap_bytes_round_trips_through_parser():
    data = cmap_bytes({2: "\u093f", 1: "\u0915", 3: "\u0915\u094d", 70000: "x"})
    parsed = dict(_cmap_mappings(data))
    assert parsed[1] == (0x0915,)
    assert parsed[2] == (0x093F,)
    assert parsed[3] == (0x0915, 0x094D)
    assert 70000 not in parsed
    assert b"beginbfchar" in data


def test_build_plan_distinguishes_additions_and_conflicts():
    doc = FakeDoc()
    font_id = font_identity(doc, "Kalimati", 20).font_id
    store = {"fonts": {font_id: {1: "\u0916", 3: "\u0917"}}}
    plan = build_repair_plan(doc, store)
    font = plan.fonts[0]
    assert font.additions == {3: "\u0917"}
    assert font.conflicts == {1: ("\u0915", "\u0916")}
    assert plan.changed is True
    assert plan.replace_conflicts is False

    conflict_only = build_repair_plan(doc, {"fonts": {font_id: {1: "\u0916"}}})
    assert conflict_only.additions == 0
    assert conflict_only.changed is False
    assert conflict_only.fonts[0].result(False)[1] == "\u0915"

    replace = build_repair_plan(doc, store, replace_conflicts=True)
    assert replace.changed is True
    assert replace.fonts[0].result(True)[1] == "\u0916"
    assert replace.fonts[0].result(True)[3] == "\u0917"
    assert "additions: 1" in format_plan(replace)
    assert "replace" in format_plan(replace)


def test_undecodable_cids_are_not_added():
    doc = FakeDoc()
    font_id = font_identity(doc, "Kalimati", 20).font_id
    store = {
        "fonts": {font_id: {3: "\u0917"}},
        "undecodable": [f"{font_id}\u25713"],
    }
    plan = build_repair_plan(doc, store)
    assert plan.fonts[0].additions == {}


def _font_paths():
    return [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]


def _make_pdf(path):
    font_path = next((p for p in _font_paths() if __import__("os").path.exists(p)),
                     None)
    if font_path is None:
        pytest.skip("DejaVuSans.ttf not available")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A", fontname="F0", fontfile=font_path,
                     fontsize=20)
    doc.save(path)
    doc.close()


def _text_value(codepoints):
    return _codepoints_text(codepoints)


def test_repair_replaces_wrong_cmap_and_preserves_source(tmp_path):
    source = tmp_path / "source.pdf"
    broken = tmp_path / "broken.pdf"
    output = tmp_path / "repaired.pdf"
    _make_pdf(source)

    doc = fitz.open(source)
    fonts = document_fonts(doc)
    xref = next(x for x, base in fonts.items() if base.startswith("DejaVu"))
    mapping = cmap_mapping(doc, xref)
    cid = next(cid for cid, cps in mapping.items()
               if _text_value(cps) == "A")
    bad = {cid: "X"}
    for other, cps in mapping.items():
        value = _text_value(cps)
        if value is not None and other not in bad:
            bad[other] = value
    _install_cmap(doc, xref, bad)
    doc.save(broken)
    doc.close()

    assert fitz.open(broken)[0].get_text().strip() == "X"

    bdoc = fitz.open(broken)
    bfonts = document_fonts(bdoc)
    bxref = next(x for x, base in bfonts.items() if base.startswith("DejaVu"))
    identity = font_identity(bdoc, bfonts[bxref], bxref)
    store = {"fonts": {identity.font_id: {cid: "A"}}}
    plan = build_repair_plan(bdoc, store, replace_conflicts=True)
    assert plan.conflicts == 1
    assert write_repair(bdoc, plan, output) == 1
    bdoc.close()

    assert fitz.open(output)[0].get_text().strip() == "A"
    assert fitz.open(source)[0].get_text().strip() == "A"


def test_cmd_repair_dry_run_does_not_require_rejected_out(monkeypatch, capsys):
    from types import SimpleNamespace

    from cidmap import cli
    from cidmap.repair import RepairPlan

    args = SimpleNamespace(
        pdf="fake.pdf", output=None, force=False, store="store.json",
        replace_conflicts=False, max_pages=None, json=None,
    )
    monkeypatch.setattr(cli, "_doc", lambda _args: object())
    monkeypatch.setattr(cli, "load", lambda _store: {})
    monkeypatch.setattr(
        "cidmap.repair.build_repair_plan",
        lambda *args, **kwargs: RepairPlan(pdf="fake.pdf"),
    )
    assert cli.cmd_repair(args) == 0
    assert "No patchable fonts" in capsys.readouterr().out


def test_unchanged_plan_writes_nothing(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "unused.pdf"
    _make_pdf(source)
    doc = fitz.open(source)
    fonts = document_fonts(doc)
    xref = next(x for x, base in fonts.items() if base.startswith("DejaVu"))
    mapping = cmap_mapping(doc, xref)
    cid = next(cid for cid, cps in mapping.items()
               if _text_value(cps) == "A")
    identity = font_identity(doc, fonts[xref], xref)
    plan = build_repair_plan(doc, {"fonts": {identity.font_id: {cid: "A"}}})
    assert not plan.changed
    assert write_repair(doc, plan, output) == 0
    assert not output.exists()
