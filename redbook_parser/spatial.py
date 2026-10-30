"""Spatial column/row classification — the Step-2 replacement for regex cuts.

Page templates are detected FIRST (TOC / detail / summary), because the
redbook's three templates do not share column boundaries:

    | Template            | Pages  | Columns                              |
    |---------------------|--------|--------------------------------------|
    | TOC / index         | 1-16   | no table                             |
    | Detail budget       | 17-34  | code + desc + 6 amounts + 2 flags    |
    | Summary by ministry | 35-60  | different column order/count (8)     |

Coordinates are absolute PDF points (Fitz uses 72/inch). The detail-template
values below are MEASURED on real pages 17-34 of redbook8283.pdf (spike):
amount columns are right-aligned numbers whose right edges cluster at
392/452/527/602/643/671; priority flags (प्राथमिकता/दिगो/लैङ्गिक संकेत) sit at
732/768. Summary-page bounds are NOT yet measured — do not reuse the detail grid.
"""

from enum import Enum

import re

# Page-template classification.
#   TOC pages have an index keyword.
#   DETAIL pages carry the शीर्षक/विवरण विविध column and the financing split.
#   SUMMARY pages carry the मन्त्रालय / निकाय column (ministry roll-up) and
#   the current/capital split. "मन्त्रालय" alone also appears in body
#   descriptions, so match the column-header phrase (with the slash), which
#   only occurs on summary template pages.
TOC_KEYWORDS = ["सूची-पत्र", "सूची", "अनुक्रमणिका", "विषय सूची", "सूचीपत्र"]
DETAIL_KEYWORDS = ["विवरण विविध", "शीर्षक", "स्रोत"]
SUMMARY_COLUMN = "मन्त्तालय / िनकाय"  # garbled form of मन्त्रालय / निकाय
SUMMARY_COLUMN_CLEAN = "मन्त्रालय / निकाय"
SUMMARY_COLUMN_MIXED = "मन्त्रालय / िनकाय"  # after word-fix of मन्त्तालय->मन्त्रालय
SUMMARY_KEYWORDS = ["सारांश", "जम्मा", "कुल"]


class PageTemplate(Enum):
    TOC = "toc"
    DETAIL = "detail"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


# X boundaries for the DETAIL template, MEASURED on redbook8283.pdf page 17
# and CONFIRMED by hand-marking the page in the spike (boxes.json):
#   b1 37-208  शीर्षक/code+desc     b2 208-277  स्रोत
#   b3 277-336  नकासा विधि          b4 336-395  यथार्थ खर्च (2080/81)
#   b5 395-454  संशोधित अनुमान (2081/82)   b6 454-530  जम्मा बजेट (2082/83)
#   b7 530-605  नेपाल सरकार         b8 605-647  वैदेशिक अनुदान
#   b9 647-673  ऋण                  b10 673-711 प्राथमिकता संकेत
#   b11 711-747 दिगो विकास संकेत    b12 747-786 लैङ्गिक संकेत
# Header (y≈43-104) confirms: 6 amount columns = financing split
# (यथार्थ → संशोधित → 2082/83 जम्मा → नेपाल सरकार → अनुदान → ऋण).
# This is NOT the current/capital split legacy v3 assumed.
GRID_BOUNDS = {
    "budget_code": (30.0, 90.0),
    "description": (90.1, 205.0),
    "source": (205.1, 272.0),
    "nikasa_vidhi": (272.1, 333.0),
    "column_1": (333.1, 397.0),   # यथार्थ खर्च  -> year_actual
    "column_2": (397.1, 457.0),   # संशोधित अनुमान -> year_revised
    "column_3": (457.1, 533.0),   # जम्मा बजेट  -> year_estimate
    "column_4": (533.1, 608.0),   # नेपाल सरकार -> financial
    "column_5": (608.1, 650.0),   # वैदेशिक अनुदान -> baideshik_anudan
    "column_6": (650.1, 676.0),   # ऋण           -> baideshik_rin
    "column_7": (676.1, 714.0),   # प्राथमिकता संकेत
    "column_8": (714.1, 750.0),   # दिगो विकास संकेत
    "column_9": (750.1, 820.0),   # लैङ्गिक संकेत
}

# How many amount columns a template expects.
TEMPLATE_AMOUNT_COLS = {
    PageTemplate.DETAIL: 6,
    PageTemplate.SUMMARY: 8,  # measured count, ORDERING NOT YET VERIFIED
    PageTemplate.TOC: 0,
    PageTemplate.UNKNOWN: 6,
}

# SUMMARY-template x-bounds, MEASURED by hand-marking page 36 (boxes-summary.json
# at 200dpi, converted px->pt via px_per_pt=0.36). Columns (b1..b10):
#   b1  36.7-74.2    अनुदान संख्या (code)
#   b2  74.2-298.8   मन्त्रालय / निकाय (description)
#   b3  298.8-360.0  2080/81 यथार्थ खर्च   -> year_actual
#   b4  360.0-420.5  2081/82 संशोधित अनुमान-> year_revised
#   b5  420.5-481.0  2082/83 जम्मा बजेट     -> year_estimate
#   b6  481.0-542.2  चालु                  -> current_exp
#   b7  542.2-601.9  पुँजीगत तथा वित्तिय व्यवस्था -> capital_exp
#   b8  601.9-663.1  नेपाल सरकार           -> financial
#   b9  663.1-724.3  वैदेशिक अनुदान        -> baideshik_anudan
#   b10 724.3-785.5  वैदेशिक ऋण            -> baideshik_rin
SUMMARY_GRID_BOUNDS = {
    "budget_code": (36.7, 74.2),
    "description": (74.2, 298.8),
    "column_1": (298.8, 360.0),   # यथार्थ खर्च -> year_actual
    "column_2": (360.0, 420.5),   # संशोधित     -> year_revised
    "column_3": (420.5, 481.0),   # जम्मा       -> year_estimate
    "column_4": (481.0, 542.2),   # चालु        -> current_exp
    "column_5": (542.2, 601.9),   # पुँजीगत     -> capital_exp
    "column_6": (601.9, 663.1),   # नेपाल सरकार -> financial
    "column_7": (663.1, 724.3),   # अनुदान      -> baideshik_anudan
    "column_8": (724.3, 785.5),   # ऋण          -> baideshik_rin
}

# Per-template grids. SUMMARY bounds now measured from page 36.
TEMPLATE_GRID_BOUNDS = {
    PageTemplate.DETAIL: GRID_BOUNDS,
    PageTemplate.SUMMARY: SUMMARY_GRID_BOUNDS,
}


def detect_template(text: str) -> PageTemplate:
    """Classify a page from its column-header/body text."""
    if any(kw in text for kw in TOC_KEYWORDS):
        return PageTemplate.TOC
    if (SUMMARY_COLUMN in text or SUMMARY_COLUMN_CLEAN in text
            or SUMMARY_COLUMN_MIXED in text):
        return PageTemplate.SUMMARY
    if any(kw in text for kw in DETAIL_KEYWORDS):
        return PageTemplate.DETAIL
    return PageTemplate.UNKNOWN


ANNEX_MARKERS = ("अनुसूची",)
EXPENDITURE_TABLE = "expenditure"
ALLOCATION_TABLE = "allocation"
SUMMARY_ALLOCATION_MARKERS = ("विनियोजन", "विनयोजन", "नयोजन")


def starts_annex(text: str) -> bool:
    """True when a page opens the schedules/annex section.

    Only the page heading is inspected: annex titles are also listed in the
    table of contents, which must not end extraction.
    """
    for line in text.splitlines():
        if line.strip():
            return any(marker in line for marker in ANNEX_MARKERS)
    return False


def summary_table(text: str) -> str:
    """Classify a summary page as expenditure or allocation."""
    if any(marker in text for marker in SUMMARY_ALLOCATION_MARKERS):
        return ALLOCATION_TABLE
    return EXPENDITURE_TABLE


def assign_column(x0: float, x1: float, template: PageTemplate = PageTemplate.DETAIL) -> str:
    """Map a span's x-extent to a column name by mid-x."""
    x_mid = (x0 + x1) / 2.0
    bounds = TEMPLATE_GRID_BOUNDS.get(template, GRID_BOUNDS)
    for col_name, (lo, hi) in bounds.items():
        if lo <= x_mid <= hi:
            return col_name
    return "unknown"


def row_band(y: float, y_step: float = 12.0) -> int:
    """Bucket a y-coordinate into a row index (placeholder; cluster by gap in spike)."""
    return int(y // y_step)
