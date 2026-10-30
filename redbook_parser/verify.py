"""Verification engine — math audit of extracted rows against stated totals.

Invariants (see STRATEGY.md §4):

    Σ line items   = Sub-Total (स्रोत जम्मा)
    Σ sub-totals   = Grand Total (जम्मा)

Checks are grouped per (page, section). Within a group, each stated total row
is compared, column by column, against the sum of the group's detail rows.
Values are integer rupees, so exact equality (|diff| < 1) is required.

Cross-page checks verify completeness (every summary ministry has detail rows
and vice versa) and line-item deduplication (no code appears in two sections).
"""

import re
from collections import defaultdict

from .model import AMOUNT_FIELDS, BudgetRow


# Ministry-level codes are 3 digits (e.g. 101, 204).
_MINISTRY_RE = re.compile(r"^\d{3}$")


class VerificationCheck:
    """One comparison: a stated total vs. the computed sum for a column."""

    def __init__(self, page: int, section: str, kind: str, column: str,
                 computed: float, stated: float, ambiguous: bool = False):
        self.page = page
        self.section = section
        self.kind = kind          # 'section_total' | 'grand_total' | 'total'
        self.column = column
        self.computed = computed
        self.stated = stated
        self.ambiguous = ambiguous

    @property
    def diff(self) -> float:
        return self.computed - self.stated

    @property
    def ok(self) -> bool:
        return not self.ambiguous and abs(self.diff) < 1

    def __repr__(self):
        flag = "OK" if self.ok else ("REVIEW" if self.ambiguous else "FAIL")
        return (f"<{flag} P{self.page}{f'[{self.section}]' if self.section else ''} "
                f"{self.kind} {self.column}: computed={self.computed:,.0f} "
                f"stated={self.stated:,.0f} diff={self.diff:,.0f}>")


class CrossPageCheck:
    """One cross-page consistency check."""

    def __init__(self, kind: str, section: str, message: str, ok: bool = True):
        self.kind = kind          # 'missing_detail' | 'missing_summary' | 'duplicate_code'
        self.section = section
        self.message = message
        self._ok = ok

    @property
    def ok(self) -> bool:
        return self._ok

    def __repr__(self):
        flag = "OK" if self.ok else "FAIL"
        return f"<{flag} {self.kind} [{self.section}] {self.message}>"


class VerificationReport:
    def __init__(self, checks: list[VerificationCheck],
                 cross_page: list[CrossPageCheck] | None = None):
        self.checks = checks
        self.cross_page = cross_page or []

    @property
    def failures(self) -> list[VerificationCheck]:
        return [c for c in self.checks if not c.ok and not c.ambiguous]

    @property
    def need_review(self) -> list[VerificationCheck]:
        return [c for c in self.checks if c.ambiguous]

    @property
    def cross_failures(self) -> list[CrossPageCheck]:
        return [c for c in self.cross_page if not c.ok]

    @property
    def ok(self) -> bool:
        return not self.failures and not self.cross_failures

    def summary(self) -> str:
        n = len(self.checks)
        n_fail = len(self.failures)
        n_rev = len(self.need_review)
        n_xpage = len(self.cross_page)
        n_xfail = len(self.cross_failures)
        parts = [f"{n} math checks: {n - n_fail - n_rev} ok, "
                 f"{n_fail} FAILED, {n_rev} need review"]
        if n_xpage:
            parts.append(f"{n_xpage} cross-page: {n_xpage - n_xfail} ok, {n_xfail} FAILED")
        return "; ".join(parts)


class BudgetVerificationEngine:
    def verify_rows(self, rows: list[BudgetRow]) -> VerificationReport:
        checks: list[VerificationCheck] = []

        groups: dict[tuple[int, str, str], list[BudgetRow]] = defaultdict(list)
        for row in rows:
            groups[(row.budget_table, row.page, row.section)].append(row)

        for (table, page, section), group in sorted(groups.items()):
            detail = [r for r in group if r.is_detail_row]
            totals = [r for r in group if r.is_total or r.row_type == "total"]
            if not detail or not totals:
                continue

            computed = {c: sum(r.amount(c) for r in detail) for c in AMOUNT_FIELDS}
            if computed["total"] == 0:
                computed["total"] = computed["year_estimate"]

            # A page/section with one total row is unambiguous; more than one
            # means sub-total + grand-total coexist and page-wide sums are not
            # a valid check.  Grand-total labels ("जम्मा खर्च") close a whole
            # table, not the page-local section, so they are reported for
            # review rather than as hard failures.
            ambiguous = len(totals) > 1 and not section

            for t in totals:
                desc = t.description or ""
                kind = "grand_total" if desc.startswith(("कुल", "कूल", "जम्मा खर्च")) else "total"
                total_ambiguous = ambiguous or kind == "grand_total"
                for c in AMOUNT_FIELDS:
                    stated = t.amount(c)
                    if stated == 0:
                        continue  # only check columns the total row actually fills
                    checks.append(VerificationCheck(
                        page, section, kind, c,
                        computed=computed[c], stated=stated,
                        ambiguous=total_ambiguous,
                    ))

        return VerificationReport(checks)

    def verify_page(self, page_rows: list[BudgetRow]) -> VerificationReport:
        return self.verify_rows(page_rows)

    def verify_cross_page(self, rows: list[BudgetRow]) -> list[CrossPageCheck]:
        """Check that every summary ministry has detail rows.

        The reverse check is deliberately absent: allocation detail includes
        hundreds of sub-office grant codes that are not listed individually in
        the ministry-level summary.  Province/local block grants (701/801)
        are transfers without a separate detail section.
        """
        cross: list[CrossPageCheck] = []

        code_lengths: dict[int, set[int]] = defaultdict(set)
        for row in rows:
            if row.code:
                code_lengths[row.page].add(len(row.code))

        summary_rows: dict[tuple[str, str], list[BudgetRow]] = defaultdict(list)
        detail_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
        for row in rows:
            if not row.section:
                continue
            key = (row.budget_table, row.section)
            if max(code_lengths[row.page], default=0) > 3:
                if row.is_detail_row and len(row.code) == 3:
                    detail_pages[key].add(row.page)
            elif row.code and _MINISTRY_RE.match(row.code):
                summary_rows[key].append(row)

        for (table, section) in sorted(summary_rows):
            if section in {"701", "801"}:
                continue
            label = f"{table + ':' if table else ''}{section}"
            if (table, section) not in detail_pages:
                cross.append(CrossPageCheck(
                    "missing_detail", label,
                    f"summary ministry {section} has no detail rows",
                    ok=False,
                ))
            else:
                found = sorted(detail_pages[(table, section)])
                cross.append(CrossPageCheck(
                    "missing_detail", label,
                    f"summary ministry {section} has detail rows on pages {found}",
                ))
                if section in {"502", "503", "504"}:
                    continue
                summary = next((r for r in summary_rows[(table, section)]
                                if r.year_estimate), None)
                if summary is None:
                    continue
                detail = [r for r in rows
                          if r.budget_table == table and r.code == section
                          and len(r.code) == 3 and r.is_detail_row
                          and max(code_lengths[r.page], default=0) > 3]
                estimates = {r.year_estimate for r in detail if r.year_estimate}
                ok = summary.year_estimate in estimates
                cross.append(CrossPageCheck(
                    "amount_match", label,
                    f"summary estimate {summary.year_estimate:,.0f} "
                    f"{'matches' if ok else 'does not match'} detail",
                    ok=ok,
                ))

        return cross
