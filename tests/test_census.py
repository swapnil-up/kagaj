"""Tests for the unknown-CID census (redbook_parser/census.py)."""

from pathlib import Path

import pytest

from redbook_parser.census import build_unknown_census, census_to_rows
from redbook_parser.legacy import CID_CHAR_MAP

PDF = "redbook_parser/output/redbook8283.pdf"


@pytest.fixture(scope="module")
def census():
    import fitz

    if not Path(PDF).exists():
        pytest.skip(f"missing cached source PDF: {PDF}")
    doc = fitz.open(PDF)
    return build_unknown_census(doc)


def test_census_reports_unknown_cids(census):
    # The known FFFD set spans the doc; page 18 alone had 16 unknown cids.
    assert len(census) >= 100
    assert 4 in census  # 18,848 occurrences, the single most common unknown


def test_census_attaches_context(census):
    cid4 = census[4]
    assert cid4["count"] > 1000
    assert cid4["pages"][0] == 3 or cid4["pages"][0] == 1
    assert any("क" in c for c in cid4["contexts"]), cid4["contexts"][:3]


def test_census_flags_legacy_map_coverage(census):
    mapped = [cid for cid, d in census.items() if d["has_value"]]
    assert len(mapped) >= 30, "most common unknowns are already in CID_CHAR_MAP"
    for cid in mapped:
        assert CID_CHAR_MAP[cid] == census[cid]["current_value"]


def test_census_to_rows_fill_in_shape(census):
    rows = census_to_rows(census)
    assert len(rows) == len(census)
    assert all(r["correct"] == "" for r in rows)
    assert all(isinstance(r["cid"], int) for r in rows)
    assert rows[0]["cid"] < rows[-1]["cid"]  # sorted ascending


def test_census_reports_missing_mappings(census):
    unmapped = [cid for cid, d in census.items() if not d["has_value"]]
    assert len(unmapped) > 100, "most unknowns are still unmapped"
