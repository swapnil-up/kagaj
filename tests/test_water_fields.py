"""Pure tests for the deterministic PDF-extraction core.

Covers field parsing (days/DMA/time windows) and geometry assembly
(columns + spatial). No PaddleOCR / pymupdf needed.
"""

from water_parser import columns, fields, spatial


# --- fields ------------------------------------------------------------------

def test_parse_days_devanagari_and_ascii():
    assert fields.parse_days("३,१, २०")[0] == [1, 3, 20]
    assert fields.parse_days("2 8 14 20 26")[0] == [2, 8, 14, 20, 26]


def test_parse_days_repairs_merged_run():
    days, repaired = fields.parse_days("१०१४")
    assert days == [10, 14]
    assert repaired is True


def test_parse_days_filters_out_of_range():
    assert fields.parse_days("0 33 5")[0] == [5]


def test_parse_dma():
    assert fields.parse_dma("डीएमए ३.१") == "3.1"
    assert fields.parse_dma("8.1.2") == "8.1.2"
    assert fields.parse_dma("no code") is None


def test_window_morning_to_afternoon():
    w = fields.resolve_window("बिहान ६:००", "दिउँसो १२:००")
    assert w["time_from"] == "06:00"
    assert w["time_to"] == "12:00"
    assert w["duration"] == 360
    assert not w["crosses_midnight"]


def test_window_evening_to_night_crosses_midnight():
    w = fields.resolve_window("बेलुका ७:००", "राति १:००")
    assert w["time_from"] == "19:00"
    assert w["time_to"] == "01:00"
    assert w["duration"] == 360
    assert w["crosses_midnight"]


def test_window_tomorrow_marker():
    w = fields.resolve_window("बेलुका ८ बजे", "भोलिपल्ट बिहान ५ बजे")
    assert w["time_from"] == "20:00"
    assert w["time_to"] == "05:00"
    assert w["duration"] == 540


def test_window_flags_zero_length():
    w = fields.resolve_window("बिहान ७:३०", "बिहान ७:३०")
    assert "time_zero_length" in w["flags"]


def test_window_flags_missing():
    w = fields.resolve_window("", "")
    assert w["time_from"] is None
    assert "time_missing" in w["flags"]


# --- columns -----------------------------------------------------------------

def _region(**over):
    base = columns.make_region(
        branch="Baneshwor", page=1, dpi=300.0,
        columns={
            "dma": {"px": [0, 0, 100, 100]},
            "days": {"px": [100, 0, 200, 100]},
            "areas": {"px": [200, 0, 400, 100]},
        },
        reservoir_np="नयाँ", reservoir_en="Naya",
    )
    base.update(over)
    return base


def test_from_markboxes_maps_order():
    boxes = {"boxes": [{"label": f"b{i}", "px": [i * 10, 0, i * 10 + 10, 10]}
                       for i in range(1, 7)]}
    cols = columns.from_markboxes(boxes, ("dma", "days", "time_from",
                                          "time_to", "areas", "contacts"))
    assert set(cols) == {"dma", "days", "time_from", "time_to", "areas", "contacts"}
    assert cols["dma"]["px"] == [10, 0, 20, 10]


# --- spatial -----------------------------------------------------------------

def test_spatial_anchor_groups_wrapped_rows():
    region = _region()
    lines = [
        {"text": "3.1", "x": 10, "y": 10, "w": 40, "h": 10, "page": 1},
        {"text": "1,3,5", "x": 110, "y": 10, "w": 60, "h": 10, "page": 1},
        {"text": "Baneshwor", "x": 210, "y": 10, "w": 80, "h": 10, "page": 1},
        {"text": "Height", "x": 210, "y": 24, "w": 60, "h": 10, "page": 1},
        {"text": "3.2", "x": 10, "y": 40, "w": 40, "h": 10, "page": 1},
        {"text": "2,4", "x": 110, "y": 40, "w": 50, "h": 10, "page": 1},
    ]
    recs = spatial.extract_records(lines, region)
    assert [r["dma"] for r in recs] == [["3.1"], ["3.2"]]
    assert recs[0]["areas"] == ["Baneshwor", "Height"]
    assert recs[1]["days"] == ["2,4"]


def test_spatial_ignores_lines_outside_columns():
    region = _region()
    lines = [
        {"text": "header junk", "x": 450, "y": 5, "w": 50, "h": 10, "page": 1},
        {"text": "3.1", "x": 10, "y": 10, "w": 40, "h": 10, "page": 1},
        {"text": "1", "x": 110, "y": 10, "w": 20, "h": 10, "page": 1},
    ]
    recs = spatial.extract_records(lines, region)
    assert len(recs) == 1
    assert recs[0]["areas"] == []
