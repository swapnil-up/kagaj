"""Reporting-period parsing for DoFE documents.

Two sources of period information:

* the **listing title** (Devanagari), e.g. "२०८३ श्रावण महिनाको श्रम स्वीकृति विवरण"
* the **PDF title block** (English), e.g.
  "Report on Final Approved List Country Wise from 2025-10-18 to 2025-11-16"

The "month" is a reporting *window* (~4 weeks), not a calendar/BS month, so we
record the exact AD window when the PDF provides it.
"""

import re

# Devanagari BS months (Shrawan = month 4 of the BS year).
BS_MONTHS_NP = {
    "बैशाख": 1, "वैशाख": 1, "जेठ": 2, "ज्येष्ठ": 2, "असार": 3, "अषाढ": 3,
    "साउन": 4, "श्रावण": 4, "सावन": 4, "भदौ": 5, "भाद्र": 5, "असोज": 6,
    "आश्विन": 6, "अशोज": 6, "कार्तिक": 7, "कात्तिक": 7, "मंसिर": 8, "मार्ग": 8,
    "पुष": 9, "पौष": 9, "माघ": 10, "फागुन": 11, "फाल्गुन": 11, "चैत": 12,
    "चैत्र": 12,
}

# Romanised BS months (English title blocks).
BS_MONTHS_EN = {
    "baishakh": 1, "baisakh": 1, "jestha": 2, "jeth": 2, "ashad": 3, "asar": 3,
    "shrawan": 4, "sawan": 4, "saun": 4, "bhadra": 5, "bhadau": 5, "ashoj": 6,
    "ashwin": 6, "kartik": 7, "mangsir": 8, "poush": 9, "push": 9, "magh": 10,
    "falgun": 11, "fagun": 11, "chaitra": 12, "chait": 12,
}

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_AD_WINDOW = re.compile(r"from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
                        re.IGNORECASE)


def _norm_digits(s: str) -> str:
    return (s or "").translate(_DEV_DIGITS)


def parse_ad_window(text: str) -> tuple[str, str]:
    """Extract the exact AD reporting window from the PDF title block."""
    m = _AD_WINDOW.search(_norm_digits(text or ""))
    if m:
        return m.group(1), m.group(2)
    return "", ""


def parse_bs_period(text: str) -> str:
    """Extract "<year> <Month>" from a Devanagari or English title."""
    if not text:
        return ""
    t = _norm_digits(text)
    # Devanagari month + 4-digit BS year (either order).
    for name, num in BS_MONTHS_NP.items():
        if name in t:
            m = re.search(r"(20\d\d)", t)
            if m:
                return f"{m.group(1)} {name}"
    # English "for <Month> <Year>"
    low = t.lower()
    for name, num in BS_MONTHS_EN.items():
        m = re.search(rf"\b{name}\b[^0-9]{{0,10}}(20\d\d)", low)
        if m:
            return f"{m.group(1)} {name.capitalize()}"
    return ""


def classify_doc_type(title: str) -> str:
    """Best-effort document-type classification from the title."""
    t = _norm_digits(title or "")
    if "प्रगति" in t or "progress" in t.lower():
        return "cumulative"
    if "महिना" in t or "month" in t.lower():
        return "single_month"
    if "वार्षिक" in t or "annual" in t.lower():
        return "annual"
    return ""
