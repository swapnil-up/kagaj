"""Configuration for the DDA drug-price extraction scripts.

Kept separate from the parliament pipeline so the experimental drug-price
work can evolve without leaking its constants into the parliamentary scraper.
Path resolution is deterministic (relative to script location, not CWD).
"""

import os
from pathlib import Path

# --- Project layout ---
DRUG_PRICES_ROOT = Path(__file__).resolve().parent.parent  # drug_prices/
REPO_ROOT = DRUG_PRICES_ROOT.parent

# --- Manifests and inputs ---
DDA_MANIFEST = DRUG_PRICES_ROOT / "manifests" / "dda_medicines.json"
DDA_COLUMN_REGIONS = DRUG_PRICES_ROOT / "dda_column_regions.json"

# --- Output paths ---
TRANSLATIONS_DIR = REPO_ROOT / "datasets" / "translations"
OUTPUT_DIR = REPO_ROOT / "output"
DDA_OUTPUT_DIR = OUTPUT_DIR / "dda"

# --- DDA URLs ---
DDA_BASE = "https://dda.gov.np"
DDA_MRP_PAGE = f"{DDA_BASE}/category/mrp-of-medicines/"
DDA_MEDIA_BASE = "https://giwmscdnone.gov.np/media"

# --- HTTP ---
HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30

# --- Scrape throttle ---
SCRAPE_DELAY = 0.3

# --- Gemini API ---
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 65536


def load_env():
    """Load .env from the repository root into os.environ."""
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
