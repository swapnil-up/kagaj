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
