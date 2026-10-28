"""Tests for the KUKL water-schedule pipeline (water_parser).

Only pure, dependency-light logic is covered here (filename parsing, month
ordering, search-term expansion, and xlsx flattening behind a skip guard), so the
suite runs without PaddleOCR.
"""

import pytest

from water_parser import paths
from water_parser.scripts.cmd_build import _search_terms


def test_parse_filename_plain():
    got = paths.parse_filename("1106-Baneshwor_ Water_Schedule_2083_Ashoj.pdf")
    assert got == {
        "serial": "1106",
        "branch": "Baneshwor",
        "year": "2083",
        "month": "Ashoj",
        "month_key": "2083_Ashoj",
    }


def test_parse_filename_hyphenated_and_suffixed():
    got = paths.parse_filename("2325-Maharajgunj_-Water_Schedule_2081_Magh.pdf")
    assert got["branch"] == "Maharajgunj"
    assert got["month_key"] == "2081_Magh"

    got = paths.parse_filename("8346-Kritipur_ Water_Schedule_2083_Kartik1.pdf")
    assert got["branch"] == "Kritipur"
    assert got["month"] == "Kartik"


def test_parse_filename_rejects_other_files():
    assert paths.parse_filename("some-random-file.pdf") is None


def test_kind_for():
    assert paths.kind_for("a.PDF") == "pdf"
    assert paths.kind_for("a.xls") == "xlsx"
    assert paths.kind_for("a.docx") == "doc"


def test_month_sort_key_orders_within_year():
    keys = ["2083_Baishakh", "2083_Kartik", "2083_Magh", "2083_Ashoj"]
    assert sorted(keys, key=paths.month_sort_key) == [
        "2083_Baishakh", "2083_Ashoj", "2083_Kartik", "2083_Magh",
    ]


def test_month_sort_key_year_dominates():
    assert paths.month_sort_key("2083_Baishakh") > paths.month_sort_key("2082_Chaitra")


def test_search_terms_splits_and_dedupes():
    zone = {
        "areas_np": ["बानेश्वर, कालोपुल", "बानेश्वर"],
        "areas_en": ["Baneshwor, Kalopul", "Baneshwor"],
    }
    terms = _search_terms(zone)
    assert "Baneshwor" in terms
    assert "Kalopul" in terms
    assert terms.count("Baneshwor") == 1


def test_xlsx_to_text_flattens_sheets(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "tank A"
    ws.append(["DMA", "areas"])
    ws.append(["8.1", "Patan"])
    path = tmp_path / "sample.xlsx"
    wb.save(path)

    from water_parser.text import xlsx_to_text

    out = xlsx_to_text(path)
    assert out["kind"] == "xlsx"
    assert out["sheets"] == ["tank A"]
    assert "### sheet: tank A" in out["text"]
    assert "8.1 | Patan" in out["text"]


def test_flag_zone_marks_untranslated_areas():
    from water_parser.validate import flag_zone

    zone = {"areas_np": ["बानेश्वर"], "areas_en": [""], "source_columns": ["areas"]}
    assert "areas_translation_missing" in flag_zone(zone)


def test_flag_zone_does_not_require_english_when_nepali_present():
    from water_parser.validate import flag_zone

    zone = {"areas_np": ["बानेश्वर"], "areas_en": ["Baneshwor"],
            "source_columns": ["areas"]}
    assert "areas_translation_missing" not in flag_zone(zone)


def test_force_invalidates_raw_ocr_and_rendered_caches(tmp_path, monkeypatch):
    from water_parser import paths
    from water_parser.scripts import cmd_process

    monkeypatch.setattr(paths, "OCR_DIR", tmp_path / "ocr")
    monkeypatch.setattr(paths, "RENDER_DIR", tmp_path / "rendered")
    raw = tmp_path / "raw" / "branch.pdf"
    text = tmp_path / "text" / "branch.txt"
    ocr = tmp_path / "ocr" / "branch.ocr.json"
    rendered = tmp_path / "rendered" / "Branch" / "branch_page1.png"
    for path in (raw, text, ocr, rendered):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")

    cmd_process._invalidate_caches({"branch": "Branch"}, raw, text)

    assert not raw.exists()
    assert not text.exists()
    assert not ocr.exists()
    assert not rendered.exists()


def test_raw_path_is_url_scoped_and_keeps_suffix(monkeypatch, tmp_path):
    from water_parser import paths
    from water_parser.scripts.cmd_process import _raw_path

    monkeypatch.setattr(paths, "RAW_DIR", tmp_path)
    a = {"filename": "same file.pdf", "url": "https://example.test/a"}
    b = {"filename": "same file.pdf", "url": "https://example.test/b"}
    assert _raw_path(a) != _raw_path(b)
    assert _raw_path(a).suffix == ".pdf"
    assert _raw_path(a) == _raw_path(dict(a))
