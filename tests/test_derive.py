"""Tests for the word-diff CID derive tool (redbook_parser/derive.py)."""

import json

import pytest

from redbook_parser.derive import (collect_windows, derive, joint_match,
                                   solve_span, tokens_of)

PDF = "redbook_parser/output/redbook8283.pdf"


@pytest.fixture(scope="module")
def doc():
    import fitz

    return fitz.open(PDF)


def test_tokens_of_marks_unknowns():
    assert tokens_of("आ⟦2⟧थ⟦4⟧क") == [
        (False, "आ"), (True, 2), (False, "थ"), (True, 4), (False, "क"),
    ]


def test_joint_match_solves_unknown_slots():
    tt = tokens_of("आ⟦2⟧थ⟦4⟧क")
    got = joint_match(tt, "आर्थिक")
    assert (2, "र्") in got[0] or any(dict(s).get(2) == "र्" for s in got)


def test_joint_match_returns_empty_when_impossible():
    assert joint_match(tokens_of("आ⟦2⟧थ⟦4⟧क"), "क") == []


def test_joint_match_never_assigns_an_empty_glyph():
    assert joint_match(tokens_of("⟦2⟧⟦4⟧"), "आ") == []


def test_solve_span_handles_reph_transpose():
    # खच⟦3⟧ -> खर्च needs the reph swap (⟦3⟧ belongs before the च).
    got = solve_span(tokens_of("खच⟦3⟧"), "खर्च")
    assert any(dict(s).get(3) == "र्" for s in got)


def test_derive_resolves_typed_word(doc):
    results = derive(doc, {4: "आर्थिक वर्ष"}, max_span_evidence=20,
                     max_pages=60)
    r = results["4"]
    # आर्थिक वर्ष contains both ि and र् as unknown CIDs -> multi-value signal.
    assert r["windows_total"] > 0
    assert any(c in ("ि", "र्") for c in r["candidates"])


def test_derive_collects_windows_for_cid(doc):
    windows = collect_windows(doc, [2], max_pages=60)
    assert len(windows[2]) > 0
    assert any("⟦2⟧" in span for _, span in windows[2])


def test_derive_no_windows_for_absent_cid(doc):
    results = derive(doc, {999: "व्यय"}, max_span_evidence=5, max_pages=60)
    assert results["999"]["mode"] == "no-windows"
