"""Domain model for redbook budget rows."""

from dataclasses import dataclass, field

# The 12 data columns in DB order (see AGENTS.md "Data Columns").
# On DETAIL pages the 6 amount columns are a FINANCING SPLIT (confirmed in
# the Step-2 spike): year_actual (यथार्थ), year_revised (संशोधित),
# year_estimate (जम्मा बजेट 2082/83), financial (नेपाल सरकार),
# baideshik_anudan (वैदेशिक अनुदान), baideshik_rin (ऋण).
# total/current_exp/capital_exp are NOT populated on detail pages.
# Columns 10-12 are priority/strategy/gender codes (string flags).
AMOUNT_FIELDS = (
    "year_actual",
    "year_revised",
    "year_estimate",
    "total",
    "current_exp",
    "capital_exp",
    "financial",
    "baideshik_anudan",
    "baideshik_rin",
)

CODE_FIELDS = ("prathamikta_sanket", "raniti_sanket", "laigik_sanket")

ALL_FIELDS = AMOUNT_FIELDS + CODE_FIELDS


@dataclass
class BudgetRow:
    """One extracted budget line (data row, total row, or section heading)."""

    code: str = ""
    description: str = ""
    source: str = ""
    nikasa_vidhi: str = ""
    year_actual: float = 0
    year_revised: float = 0
    year_estimate: float = 0
    total: float = 0
    current_exp: float = 0
    capital_exp: float = 0
    financial: float = 0
    baideshik_anudan: float = 0
    baideshik_rin: float = 0
    prathamikta_sanket: str = ""
    raniti_sanket: str = ""
    laigik_sanket: str = ""
    is_total: bool = False
    row_type: str = "budget"  # 'budget' | 'total' | 'heading'
    page: int = 0
    # Budget table this row belongs to. The redbook repeats the same ministry
    # codes in the expenditure and allocation schedules, so section alone is
    # not a unique scope.
    budget_table: str = ""
    # Section scope for verification. v3 does not yet infer sections; this is
    # populated by the spatial layer in Step 2, or by the DB loader when a
    # schema supports it.
    section: str = ""

    @property
    def is_detail_row(self) -> bool:
        return self.row_type == "budget" and not self.is_total

    def amount(self, column: str) -> float:
        return getattr(self, column)

    def amounts(self) -> dict:
        return {c: getattr(self, c) for c in AMOUNT_FIELDS}
