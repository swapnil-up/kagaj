"""Tests for redbook_parser.parser — the v3 baseline state machine.

Includes xfail markers for the two documented bugs that Step 3 fixes, so a
future fix flips them to XPASS instead of silently changing behaviour.
"""

import pytest

from redbook_parser.parser import process_page_lines
from redbook_parser.spatial import PageTemplate


def amounts(*values):
    """Map an amounts list to the confirmed detail-page field order.

    Detail pages carry a FINANCING SPLIT (confirmed in the Step-2 spike):
    year_actual, year_revised, year_estimate, financial, baideshik_anudan,
    baideshik_rin. total/current_exp/capital_exp are not on detail pages.
    """
    out = {c: 0 for c in
           ("year_actual", "year_revised", "year_estimate", "total",
            "current_exp", "capital_exp", "financial",
            "baideshik_anudan", "baideshik_rin")}
    for i, k in enumerate(out):
        if i < len(values):
            out[k] = values[i]
    return out


class TestSimpleRow:
    def test_code_desc_and_six_amounts(self, detail_lines):
        rows = process_page_lines(detail_lines, 17, scale=1)
        assert len(rows) == 1
        r = rows[0]
        assert r.code == "111111"
        assert r.description == "अर्थ मन्त्रालय कार्यालय"
        assert r.year_actual == 1000
        assert r.year_revised == 2000
        assert r.year_estimate == 3000
        assert r.financial == 4000
        assert r.baideshik_anudan == 5000
        assert r.baideshik_rin == 6000
        assert r.total == 0
        assert r.current_exp == 0
        assert r.capital_exp == 0
        assert not r.is_total

    def test_scale_multiplies_amounts(self, detail_lines):
        rows = process_page_lines(detail_lines, 17, scale=100_000)
        assert rows[0].year_actual == 1000 * 100_000
        assert rows[0].baideshik_rin == 6000 * 100_000

    def test_fewer_amounts_fill_zero(self):
        lines = ["111111 शीर्ष", "1,000", "2,000"]
        rows = process_page_lines(lines, 17)
        assert rows[0].total == 0  # not a detail-page column
        assert rows[0].year_revised == 2000
        assert rows[0].financial == 0


class TestMultiLine:
    def test_desc_continuation_via_keyword(self):
        lines = ["111111 शीर्ष", "मन्त्रालय कार्यालय सामग्री", "1,000", "2,000"]
        rows = process_page_lines(lines, 17)
        assert len(rows) == 1
        assert rows[0].description == "शीर्ष मन्त्रालय कार्यालय सामग्री"

    def test_desc_without_keyword_is_kept(self):
        # Bug #2 fix: positional logic captures all non-keyword desc lines.
        lines = ["111111 शीर्ष", "आयोग", "1,000"]
        rows = process_page_lines(lines, 17)
        assert rows[0].description == "शीर्ष आयोग"


class TestTotals:
    def test_standalone_total_row(self):
        rows = process_page_lines(["जम्मा 5,000"], 17, scale=1)
        assert len(rows) == 1
        assert rows[0].is_total
        assert rows[0].total == 5000

    def test_total_after_amounts_is_not_dropped(self):
        # Regression test: Bug #1 fix ensures the total line is reprocessed.
        lines = ["111111 शीर्ष", "1,000", "2,000", "जम्मा 5,000"]
        rows = process_page_lines(lines, 17)
        totals = [r for r in rows if r.is_total]
        assert len(totals) == 1
        assert totals[0].total == 5000

    def test_total_after_amounts_is_kept(self):
        lines = ["111111 शीर्ष", "1,000", "2,000", "जम्मा 5,000"]
        rows = process_page_lines(lines, 17)
        totals = [r for r in rows if r.is_total]
        assert len(totals) == 1
        assert totals[0].total == 5000


class TestHeadings:
    def test_heading_row_captured(self):
        rows = process_page_lines(["शीर्षक १: अर्थ मन्त्रालय"], 17)
        assert len(rows) == 1
        assert rows[0].row_type == "heading"

    def test_header_keyword_skipped(self):
        assert process_page_lines(["यथार्थ"], 17) == []

    def test_srrot_subheader_becomes_heading(self):
        # Bug #3 (STRATEGY.md §5.3): स्रोत is in both HEADING_LABELS and
        # HEADER_KEYWORDS; the heading check runs first.
        rows = process_page_lines(["स्रोत जम्मा नेपाल"], 17)
        assert len(rows) == 1
        assert rows[0].row_type == "heading"


class TestPriorityCodes:
    def test_p_priority_with_raniti_laigik_lookahead(self):
        lines = ["123456 शीर्ष", "P1", "3", "2", "1,000", "2,000"]
        rows = process_page_lines(lines, 17)
        assert len(rows) == 1
        r = rows[0]
        assert r.prathamikta_sanket == "1"
        assert r.raniti_sanket == "3"
        assert r.laigik_sanket == "2"
        assert r.year_actual == 1000


class TestSkips:
    def test_year_label_skipped(self):
        assert process_page_lines(["2080/81 को"], 17) == []

    def test_standalone_number_skipped(self):
        assert process_page_lines(["42"], 17) == []

    def test_empty_page(self):
        assert process_page_lines([], 17) == []


class TestSourceAndNikasa:
    def test_source_captured(self):
        lines = ["111111 शीर्ष", "नेपाल सरकार", "1,000"]
        rows = process_page_lines(lines, 17)
        assert rows[0].source == "नेपाल सरकार"


class TestTotalColumns:
    def test_six_value_total_maps_columns(self):
        lines = ["जम्मा खर्च", "10", "20", "30", "30", "0", "0"]
        rows = process_page_lines(lines, 17, scale=1)
        assert len(rows) == 1
        r = rows[0]
        assert r.is_total
        assert r.description == "जम्मा खर्च"
        assert (r.year_actual, r.year_revised, r.year_estimate,
                r.financial) == (10, 20, 30, 30)
        assert r.total == 0

    def test_contribution_word_is_not_a_total(self):
        lines = ["21213 योगदानमा आधारित बीमा कोष खर्च", "1,000"]
        rows = process_page_lines(lines, 17)
        assert len(rows) == 1
        assert not rows[0].is_total
        assert rows[0].code == "21213"

    def test_budget_table_tagged_on_all_rows(self):
        rows = process_page_lines(
            ["101 मन्त्रालय", "जम्मा 5,000"], 17,
            template=PageTemplate.DETAIL, budget_table="expenditure")
        assert all(r.budget_table == "expenditure" for r in rows)
