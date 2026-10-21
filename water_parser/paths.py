"""Shared paths, KUKL constants, and filename parsing for the water pipeline.

All filesystem locations are resolved relative to the installed package, not the
CWD, so the CLI behaves identically from anywhere in the repo.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# --- Project layout ---------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Tracked output (committed): manifests + normalised schedule JSON --------
WATER_DIR = REPO_ROOT / "datasets" / "water"
MANIFEST = WATER_DIR / "manifest.json"
SCHEDULE = WATER_DIR / "schedule.json"
# Human-marked PDF column regions (created with agent-tools/mark-boxes).
COLUMN_REGIONS = REPO_ROOT / "water_parser" / "column_regions.json"

# --- Scratch output (gitignored): raw downloads, OCR text, per-doc dumps -----
OUTPUT_DIR = REPO_ROOT / "output"
WATER_OUTPUT_DIR = OUTPUT_DIR / "water"
RAW_DIR = WATER_OUTPUT_DIR / "raw"
TEXT_DIR = WATER_OUTPUT_DIR / "text"
RENDER_DIR = WATER_OUTPUT_DIR / "rendered"
OCR_DIR = WATER_OUTPUT_DIR / "ocr"

# --- KUKL --------------------------------------------------------------------
KUKL_BASE = "https://kukl.org.np"
KUKL_SCHEDULE_URL = f"{KUKL_BASE}/downloads/water-distribution-schedule"

# Anchor href / file name pattern, e.g.
#   1106-Baneshwor_ Water_Schedule_2083_Ashoj.pdf
#   2325-Maharajgunj_-Water_Schedule_2081_Magh.pdf
#   8346-Kritipur_ Water_Schedule_2083_Kartik1.pdf
FILE_RE = re.compile(
    r"^(\d+)-(?P<branch>.+?)[_ ]-?Water_Schedule_"
    r"(?P<year>\d{4})_(?P<month>[A-Za-z]+)",
    re.IGNORECASE,
)

SUPPORTED_SUFFIXES = (".pdf", ".xlsx", ".xls", ".doc", ".docx")

# Nepali (Bikram Sambat) month order, for picking the latest schedule per branch.
MONTH_ORDER = {
    "baishakh": 1, "baishakha": 1, "baisakh": 1,
    "jestha": 2, "jeth": 2,
    "asar": 3, "ashad": 3, "asad": 3, "ashad": 3,
    "saun": 4, "shrawan": 4, "sawan": 4,
    "bhadra": 5, "bhadau": 5, "bhadra": 5,
    "ashoj": 6, "asoj": 6, "ahoj": 6, "asoj": 6,
    "kartik": 7,
    "mangshir": 8, "mansir": 8, "mangsir": 8, "manghir": 8,
    "poush": 9, "paush": 9,
    "magh": 10,
    "falgun": 11, "phagun": 11, "fagun": 11,
    "chaitra": 12, "chait": 12,
}


def month_sort_key(month_key: str) -> tuple[int, int, str]:
    """Sort key for ``"<year>_<Month>"``; unknown months sort last within a year."""
    year, _, month = month_key.partition("_")
    try:
        y = int(year)
    except ValueError:
        y = 0
    idx = MONTH_ORDER.get(month.lower(), 99)
    return (y, idx, month.lower())


def load_env() -> None:
    """Load the repository-root ``.env`` into ``os.environ`` (Gemini key lives there)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def parse_filename(filename: str) -> dict | None:
    """Return ``{serial, branch, month_key, year, month}`` or None if unmatched."""
    m = FILE_RE.match(Path(filename).name)
    if not m:
        return None
    return {
        "serial": m.group(1),
        "branch": m.group("branch").strip(" _-"),
        "year": m.group("year"),
        "month": m.group("month"),
        "month_key": f"{m.group('year')}_{m.group('month')}",
    }


def kind_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return {"xls": "xlsx", "docx": "doc"}.get(suffix, suffix)


# Roman month -> Nepali (for the deterministic PDF path, which never sees the LLM)
MONTH_NP = {
    "baishakh": "बैशाख", "baisakh": "बैशाख", "jestha": "जेठ", "jeth": "जेठ",
    "asar": "असार", "ashad": "असार", "saun": "साउन", "shrawan": "साउन",
    "bhadra": "भदौ", "bhadau": "भदौ", "ashoj": "असोज", "asoj": "असोज",
    "kartik": "कार्तिक", "mangshir": "मंसिर", "mangsir": "मंसिर",
    "poush": "पुष", "paush": "पुष", "magh": "माघ", "falgun": "फाल्गुन",
    "phagun": "फाल्गुन", "chaitra": "चैत", "chait": "चैत",
}

# Known branch offices -> Nepali name (best-effort; extends as branches appear).
BRANCH_NP = {
    "baneshwor": "बानेश्वर", "mahankalchaur": "महांकालचौर",
    "maharajgunj": "महाराजगंज", "bhaktpur": "भक्तपुर", "bhaktapur": "भक्तपुर",
    "lalitpur": "ललितपुर", "tripureshwor": "त्रिपुरेश्वर",
    "kritipur": "कीर्तिपुर", "thimi": "ठिमी",
    "madhyapur thimi": "मध्यपुर ठिमी", "madhyapur": "मध्यपुर ठिमी",
}


def branch_np(name: str) -> str | None:
    return BRANCH_NP.get((name or "").strip().lower())


def month_bs(month_key: str) -> str | None:
    year, _, month = month_key.partition("_")
    np_name = MONTH_NP.get(month.lower())
    if not np_name:
        return None
    deva_year = str(year).translate({ord(str(i)): d for i, d in enumerate("०१२३४५६७८९")})
    return f"{deva_year} {np_name}"
