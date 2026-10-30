"""Tests for table specs, adapters, and verification hooks."""

import pytest

from kagaj_core.tables import (
    Column,
    TableSpec,
    extract_grid,
    extract_words,
    row_sums_equal,
    sum_to_total,
)


def _bands():
    return {"left": (0, 10), "right": (10, 20)}


def test_spec_orders_columns_and_rejects_overlap():
    spec = TableSpec.from_bands("t", {"right": (10, 20), "left": (0, 10)})
    assert spec.column_names == ("left", "right")
    assert spec.column_at(5).name == "left"
    assert spec.column_at(10).name == "right"
    assert spec.column_at(99) is None
    with pytest.raises(ValueError):
        TableSpec(name="bad", columns=(Column("a", 0, 20),
                                       Column("b", 10, 30)))


def test_extract_words_assigns_columns_and_rows():
    words = [
        {"text": "क", "bbox": (2, 0, 8, 8)},
        {"text": "ख", "bbox": (12, 1, 18, 9)},
        {"text": "ग", "bbox": (2, 20, 8, 28)},
        {"text": "घ", "bbox": (12, 20, 18, 28)},
    ]
    spec = TableSpec.from_bands("t", _bands())
    assert extract_words(words, spec) == [
        {"left": "क", "right": "ख"},
        {"left": "ग", "right": "घ"},
    ]


def test_extract_grid_maps_by_position_and_skips_header():
    spec = TableSpec.from_bands("t", _bands(), header_rows=1)
    rows = [["head-left", "head-right"], ["क", "ख"]]
    assert extract_grid(rows, spec) == [{"left": "क", "right": "ख"}]


def test_sum_to_total_accepts_matching_and_rejects_mismatch():
    spec = TableSpec.from_bands("t", _bands())
    verifier = sum_to_total(
        value_columns=["m", "f"], total_column="t", label_column="label")
    good = [
        {"label": "a", "m": "2", "f": "3", "t": ""},
        {"label": "b", "m": "4", "f": "5", "t": ""},
        {"label": "जम्मा", "m": "", "f": "", "t": "14"},
    ]
    assert verifier(good) == []

    bad = [dict(row) for row in good]
    bad[-1]["t"] = "15"
    violations = verifier(bad)
    assert len(violations) == 1
    assert violations[0].kind == "sum-mismatch"

    no_total = good[:-1]
    assert verifier(no_total)[0].kind == "missing-total"


def test_sum_to_total_is_a_spec_verifier():
    verifier = sum_to_total(
        value_columns=["m", "f"], total_column="t", label_column="label")
    spec = TableSpec.from_bands("t", _bands(), verifier=verifier)
    report = spec.verify([
        {"label": "a", "m": "1", "f": "1", "t": ""},
        {"label": "total", "m": "", "f": "", "t": "2"},
    ])
    assert report.ok


def test_row_sums_equal_skips_total_rows():
    verifier = row_sums_equal(value_columns=["m", "f"], total_column="t")
    rows = [
        {"m": "1", "f": "2", "t": "3"},
        {"m": "total", "f": "", "t": "3"},
        {"m": "2", "f": "2", "t": "5"},
    ]
    violations = verifier(rows)
    assert len(violations) == 1
    assert violations[0].row == 2
