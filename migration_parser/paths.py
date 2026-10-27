"""Shared paths and configuration for the labour-migration pipeline.

Centralises every filesystem location and DoFE constant used by the
``migration_parser`` CLIs so that the package has no dependency on the
``parliament`` scripts. Path resolution is deterministic (relative to the
installed package, not the CWD).
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Project layout ---
REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Tracked data (committed) ---
MIGRATION_DIR = REPO_ROOT / "datasets" / "labour-migration"

# --- Scratch output (gitignored: raw PDFs, per-doc CSV, reports) ---
OUTPUT_DIR = REPO_ROOT / "output"
MIGRATION_OUTPUT_DIR = OUTPUT_DIR / "migration"
MIGRATION_REPORTS_DIR = MIGRATION_OUTPUT_DIR / "reports"
MIGRATION_OPENDATA_DIR = MIGRATION_OUTPUT_DIR / "opendatanepal"

# --- Manifest (scraper's working state, kept with the dataset) ---
MIGRATION_MANIFEST = MIGRATION_DIR / "manifests" / "migration_manifest.json"

# --- Archive.org backfill (separate tracked panel; see cmd_archive_panel) ---
MIGRATION_ARCHIVE_MANIFEST = MIGRATION_DIR / "manifests" / "migration_archive_manifest.json"
MIGRATION_ARCHIVE_PANEL = MIGRATION_DIR / "panel_archive.csv.gz"
MIGRATION_ARCHIVE_UNRESOLVED = MIGRATION_DIR / "panel_archive_unresolved.csv.gz"
MIGRATION_ARCHIVE_BUILD = MIGRATION_DIR / "panel_archive_build.json"
ARCHIVE_PANEL_COLUMNS = [
    "source_kind", "doc_id", "period_bs", "doc_type", "section", "row_type",
    "name", "sn", "approval_type", "entry_type", "gender", "count", "scope",
    "scope_class",
    "granularity", "source_page", "name_canonical", "iso3", "entity_resolved",
    "analysis_safe", "verified", "source_url", "source_pdf_sha256",
]

# --- DoFE (Department of Foreign Employment) ---
DOFE_BASE = "https://dofe.gov.np"
# Categories that carry statistical reports (grid or table listings).
DOFE_MIGRATION_CATEGORIES = (
    "monthly",
    "yearly",
    "labour-approval",
    "preapproval",
    "bulletin",
)
# Fallback detail-page PDF resolution (inline JS on /content/ pages).
DOFE_PDF_JS_RE = r"var\s+pdf\s*=\s*'([^']+)'"
DOFE_PDF_BARE_RE = r"(https?://[^\s'\"]+\.pdf)"

# Historical narrative reports (native vector text) — dest/origin year series
# and the migration_2020 labour-approval Annex tables.
MIGRATION_REPORTS = {
    "status_2013_14": "https://giwmscdnone.gov.np/media/pdf_upload/Document_2019010309550_9maqcnv.pdf",
    "status_2014_15": "https://giwmscdnone.gov.np/media/pdf_upload/Document_2019010309160_pzs8oqq.pdf",
    "status_2015_17": "https://giwmscdnone.gov.np/media/pdf_upload/Document_2019010309530_ibnx2zy.pdf",
    "country_intro_2019": "https://giwmscdnone.gov.np/media/pdf_upload/Document_2020021810320_p6gcbvr.pdf",
    "migration_2020": "https://giwmscdnone.gov.np/media/pdf_upload/Document_2020032211460_mujupxw.pdf",
    # MoLESS Nepal Labour Migration Report 2024 — extends the death series to
    # FY2023/24 (Table 4.1, cause × year) and adds 2022/23–2023/24 breakdowns.
    "migration_2024": "https://giwmscdnone.gov.np/media/pdf_upload/Nepal%20Labour%20Migration%202024_Final-Version%20for%20Approval%20(1)_peesvxa.pdf",
}

# Shared tidy-long schema for panel.csv (live wide tables + report Annex tables).
MIGRATION_PANEL_COLUMNS = [
    "doc_id", "period_bs", "period_ad_start", "period_ad_end", "doc_type",
    "section", "row_type", "name", "sn", "channel", "gender", "count",
    "source_page", "verified", "source_url",
]

def load_env() -> None:
    """Load the repository-root ``.env`` into ``os.environ`` (if present)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
