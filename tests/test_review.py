"""Tests for the redbook review adapter."""

import json
import os
import re

import pytest

from cidmap import glyph_collection as collection
from cidmap import glyph_review
from cidmap.glyph_collection import _word_bbox, collect_review_data
from kagaj_core.review import ReviewCrop
from redbook_parser import review
from redbook_parser.derive import load_corrections

PDF = "redbook_parser/output/redbook8283.pdf"


class FakePage:
    def __init__(self):
        self.get_texttrace = lambda: []


class FakeDoc:
    def __init__(self, pages):
        self.pages = pages
        self.name = "fake.pdf"

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, index):
        return self.pages[index]


def _glyph(cid, c, font="Kalimati", x=10, y=20, w=8, h=12, **extra):
    return {"cid": cid, "c": c, "font": font, "font_id": font,
            "origin": (x, y), "bbox": (x, y, x + w, y + h), **extra}


def _page_glyphs():
    return [
        _glyph(1, "\u0915", x=10, y=20),
        _glyph(42, "\ufffd", x=20, y=20),
        _glyph(2, "\u093f", x=30, y=20),
    ]


@pytest.fixture
def fake_doc(monkeypatch):
    pages = [FakePage(), FakePage()]
    calls = []

    def fake_extract(page, dedup=True):
        calls.append(pages.index(page))
        return _page_glyphs()

    monkeypatch.setattr(collection, "extract_glyphs", fake_extract)
    return FakeDoc(pages), calls


@pytest.fixture
def no_pdf(monkeypatch):
    def fake_crop(*args, **kwargs):
        return ReviewCrop(
            glyph="data:image/png;base64,GGGG",
            word="data:image/png;base64,WWWW",
            overlay={"left": "10%", "top": "20%",
                     "width": "30%", "height": "40%"},
        )

    monkeypatch.setattr(glyph_review, "render_review_crop", fake_crop)


def test_word_bbox_stops_at_column_and_space_gaps():
    line = [
        _glyph(1, "\u0915", x=10, y=20),
        _glyph(42, "\ufffd", x=20, y=20),
        _glyph(2, "\u093f", x=30, y=20),
        _glyph(3, " ", x=40, y=20, w=6),
        _glyph(4, "\u0916", x=46, y=20),
        _glyph(5, "\u0917", x=300, y=20),
    ]
    assert _word_bbox(line, 1) == (10, 20, 38, 32)


def test_collection_scans_each_page_once(fake_doc):
    doc, calls = fake_doc
    data = collect_review_data(doc, max_samples_per_cid=2)
    assert calls == [0, 1]
    record = data[("Kalimati", 42)]
    assert record["count"] == 2
    assert record["pages"] == [1, 2]
    assert record["font_id"] == "Kalimati"
    assert record["base_font"] == "Kalimati"
    assert record["font_id_scheme"] == "unresolved"
    assert len(record["samples"]) == 2
    assert [s["page"] for s in record["samples"]] == [1, 2]
    assert all("\u27e642\u27e7" in c for c in record["contexts"])


def test_same_cid_in_two_fonts_becomes_two_cards(fake_doc, no_pdf, monkeypatch):
    doc, _ = fake_doc

    def two_fonts(page, dedup=True):
        return [
            _glyph(42, "\ufffd", font="Kalimati", font_id="Kalimati@p1",
                   font_xref=20, font_id_scheme="pdf-local"),
            _glyph(42, "\ufffd", font="Kalimati", font_id="Kalimati@p2",
                   font_xref=21, font_id_scheme="pdf-local", x=60),
        ]

    monkeypatch.setattr(collection, "extract_glyphs", two_fonts)
    items = review.build_review_items(doc, sample_per_cid=3)
    assert {item.key for item in items} == {
        "Kalimati@p1\u257142", "Kalimati@p2\u257142"}


def test_review_generation_scans_each_page_once(fake_doc, no_pdf):
    doc, calls = fake_doc
    review.build_review_html(doc, sample_per_cid=2)
    assert calls == [0, 1]


def test_collection_respects_sample_count(fake_doc):
    doc, _ = fake_doc
    data = collect_review_data(doc, max_samples_per_cid=1)
    assert len(data[("Kalimati", 42)]["samples"]) == 1


def test_items_carry_cid_font_and_crops(fake_doc, no_pdf):
    doc, _ = fake_doc
    items = review.build_review_items(doc, sample_per_cid=2)
    assert len(items) == 1
    item = items[0]
    assert item.key == "Kalimati\u257142"
    assert item.label == "CID 42"
    assert item.group == "Kalimati"
    assert item.data["cid"] == 42
    assert item.data["font_id"] == "Kalimati"
    assert item.data["base_font"] == "Kalimati"
    assert item.data["source_pdf"] == "fake.pdf"
    assert item.data["legacy_value"] == "\u0938\u094d\u0925"
    assert len(item.crops) == 2
    assert item.crops[0].glyph.startswith("data:image/png")
    assert item.crops[0].overlay["left"] == "10%"
    assert item.crops[0].caption == "p1 \u00b7 occurrence 1/2"
    assert item.crops[1].caption == "p2 \u00b7 occurrence 2/2"
    assert item.context.startswith("2 occurrence(s) \u00b7 p1, p2 \u00b7")
    assert item.input_placeholder.startswith("glyph / cluster")


def test_cidmap_review_omits_redbook_legacy_hints(fake_doc, no_pdf):
    doc, _ = fake_doc
    items = glyph_review.build_review_items(doc)
    assert "legacy_value" not in items[0].data


def test_only_filter_restricts_cids(fake_doc, no_pdf):
    doc, _ = fake_doc
    assert review.build_review_items(doc, only={99}) == []


def test_html_uses_core_shell_with_neutral_export(fake_doc, no_pdf):
    doc, _ = fake_doc
    htmlout = review.build_review_html(doc, session="redbook:fake.pdf")
    assert 'data-key="Kalimati\u257142"' in htmlout
    assert '<script id="review-data" type="application/json">' in htmlout
    assert "Export cid_corrections.json" in htmlout
    assert "all fonts" in htmlout
    assert "kagaj.review.v1." in htmlout
    assert "Judge the glyph crop, not the surrounding word" in htmlout
    assert "different glyph shape in different samples" in htmlout
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        htmlout, re.S)
    records = json.loads(match.group(1))
    assert records[0]["key"] == "Kalimati\u257142"
    assert records[0]["current"] == ""
    assert records[0]["data"]["cid"] == 42
    assert records[0]["data"]["font_id"] == "Kalimati"
    assert records[0]["data"]["source_pdf"] == "fake.pdf"


def test_html_sessions_are_document_specific(fake_doc, no_pdf):
    doc, _ = fake_doc
    a = review.build_review_html(doc, session="redbook:/a.pdf")
    b = review.build_review_html(doc, session="redbook:/b.pdf")
    assert a != b


def test_load_corrections_accepts_neutral_and_legacy():
    records = [
        {"key": "42", "value": "\u0915", "undecodable": False,
         "data": {"cid": 42}},
        {"key": "43", "value": "", "undecodable": True,
         "data": {"cid": 43}},
        {"cid": 7, "correct": "\u0916"},
        {"cid": 8, "correct": ""},
    ]
    assert load_corrections(records) == {42: "\u0915", 7: "\u0916"}


def test_crop_failures_are_skipped(monkeypatch, fake_doc):
    doc, _ = fake_doc

    def boom(*args, **kwargs):
        raise RuntimeError("bad page")

    monkeypatch.setattr(glyph_review, "render_review_crop", boom)
    items = review.build_review_items(doc)
    assert items[0].crops == ()


@pytest.mark.skipif(not os.path.exists(PDF), reason="redbook PDF not available")
def test_real_redbook_smoke():
    import fitz

    doc = fitz.open(PDF)
    htmlout = review.build_review_html(doc, sample_per_cid=1,
                                       session="redbook:test")
    assert 'data-key="' in htmlout
    assert "data:image/png;base64" in htmlout
