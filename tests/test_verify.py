"""Tests for redbook_parser.verify — the math audit engine."""

from redbook_parser.model import BudgetRow
from redbook_parser.verify import BudgetVerificationEngine


def detail(code, page, total, **kw):
    r = BudgetRow(code=code, page=page, total=total, **kw)
    return r


class TestSinglePage:
    def test_detail_sum_matches_total(self):
        rows = [
            detail("111", 17, 1000),
            detail("112", 17, 2000),
            detail("113", 17, 3000),
            BudgetRow(page=17, total=6000, is_total=True),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert report.ok, report.failures
        assert len(report.checks) == 1  # only `total` column filled on total row
        assert report.checks[0].ok

    def test_mismatch_fails(self):
        rows = [
            detail("111", 17, 1000),
            detail("112", 17, 2000),
            BudgetRow(page=17, total=9999, is_total=True),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert not report.ok
        assert len(report.failures) == 1
        assert report.failures[0].diff == 3000 - 9999

    def test_multiple_columns_verified(self):
        rows = [
            BudgetRow(code="111", page=17, year_actual=10, total=20),
            BudgetRow(code="112", page=17, year_actual=15, total=25),
            BudgetRow(page=17, year_actual=25, total=45, is_total=True),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert report.ok, report.failures
        cols = {c.column for c in report.checks}
        assert cols == {"year_actual", "total"}


class TestPageIsolation:
    def test_totals_scoped_to_their_page(self):
        rows = [
            detail("111", 17, 1000),
            BudgetRow(page=17, total=1000, is_total=True),
            detail("211", 18, 500),
            BudgetRow(page=18, total=999, is_total=True),  # wrong on purpose
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert len(report.failures) == 1
        assert report.failures[0].page == 18


class TestSectionGrouping:
    def test_sections_scope_totals(self):
        rows = [
            detail("111", 17, 1000, section="अर्थ"),
            BudgetRow(page=17, section="अर्थ", total=1000, is_total=True),
            detail("211", 17, 700, section="स्वास्थ्य"),
            BudgetRow(page=17, section="स्वास्थ्य", total=700, is_total=True),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert report.ok, report.failures

    def test_no_section_and_two_totals_needs_review(self):
        # Without section inference, two total rows on one page can't be
        # checked unambiguously; flagged, not silently accepted.
        rows = [
            detail("111", 17, 1000),
            BudgetRow(page=17, total=1000, is_total=True),
            BudgetRow(page=17, total=1000, is_total=True),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert report.need_review
        assert report.ok  # no hard failures, but flagged


class TestEmpty:
    def test_no_data(self):
        report = BudgetVerificationEngine().verify_rows([])
        assert report.ok
        assert report.checks == []


class TestTableScope:
    def test_same_section_in_two_tables_is_isolated(self):
        rows = [
            BudgetRow(code="111", page=17, section="101",
                      budget_table="expenditure", year_estimate=1000),
            BudgetRow(page=17, section="101", budget_table="expenditure",
                      year_estimate=1000, is_total=True, description="जम्मा"),
            BudgetRow(code="111", page=73, section="101",
                      budget_table="allocation", year_estimate=2000),
            BudgetRow(page=73, section="101", budget_table="allocation",
                      year_estimate=2000, is_total=True, description="जम्मा"),
        ]
        report = BudgetVerificationEngine().verify_rows(rows)
        assert report.ok, report.failures
        assert len(report.checks) == 2


class TestCrossPage:
    def test_block_grants_are_not_missing_detail(self):
        rows = [
            BudgetRow(page=13, code="101", section="101",
                      budget_table="expenditure", year_estimate=1000),
            BudgetRow(page=17, code="101", section="101",
                      budget_table="expenditure", year_estimate=1000),
            BudgetRow(page=17, code="1010000", section="101",
                      budget_table="expenditure"),
            BudgetRow(page=38, code="801", section="801",
                      budget_table="allocation", year_estimate=2000),
        ]
        checks = BudgetVerificationEngine().verify_cross_page(rows)
        assert [c for c in checks if not c.ok] == []
        assert any(c.kind == "amount_match" and c.ok for c in checks)

    def test_amount_mismatch_fails(self):
        rows = [
            BudgetRow(page=13, code="101", section="101",
                      budget_table="expenditure", year_estimate=1000),
            BudgetRow(page=17, code="101", section="101",
                      budget_table="expenditure", year_estimate=999),
            BudgetRow(page=17, code="1010000", section="101",
                      budget_table="expenditure"),
        ]
        checks = BudgetVerificationEngine().verify_cross_page(rows)
        assert any(c.kind == "amount_match" and not c.ok for c in checks)
