"""Centralized configuration for parliament scripts.

All constants that were previously duplicated across scripts live here.
Path resolution is deterministic (relative to script location, not CWD).

Usage:
    from config import GEMINI_MODEL, TRANSLATIONS_DIR, load_env
"""

import os
from pathlib import Path

# --- Project layout ---
PARLIAMENT_ROOT = Path(__file__).resolve().parent.parent  # parliament/
REPO_ROOT = PARLIAMENT_ROOT.parent

# --- Manifests ---
NOTICES_MANIFEST = PARLIAMENT_ROOT / "manifests" / "notices.json"
VERBATIMS_MANIFEST = PARLIAMENT_ROOT / "manifests" / "verbatims.json"

# --- Output paths ---
TRANSLATIONS_DIR = REPO_ROOT / "datasets" / "translations"
OUTPUT_DIR = REPO_ROOT / "output"
VERBATIMS_OUTPUT_DIR = OUTPUT_DIR / "verbatims"

# --- Parliament URLs ---
HR_BASE = "https://hr.parliament.gov.np"
HR_LIST_URL = f"{HR_BASE}/en/parliamentary-notices"
NA_LIST_URL = "https://na.parliament.gov.np/api/v1/verbatims"
NA_ATTACH_BASE = "https://na.parliament.gov.np/uploads/attachments"

# --- HTTP ---
HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30
VERBATIM_TIMEOUT = 90

# --- Gemini API ---
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
EMBED_MODEL = "gemini-embedding-001"
GEMINI_TEMPERATURE = 0.2
GEMINI_SYSTEM_INSTRUCTION = (
    "You are an expert translator of Nepali parliamentary documents. "
    "Output JSON only."
)
MAX_OUTPUT_TOKENS = 65536
ADAPTIVE_BUDGET_RETRIES = 4

# --- Verbatim segmentation ---
SEGMENT_CHARS = 10000

# --- Filters (parliament session boundaries) ---
MIN_BS_YEAR = 2082
MIN_BS_MONTH = 12
MIN_NA_SESSION = 19

# --- Scrape throttle ---
SCRAPE_DELAY = 0.3

# --- External tools ---
MARK_BOXES_DIR = Path.home() / "github" / "agent-tools" / "mark-boxes"


def load_env():
    """Load .env from the repository root into os.environ."""
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
