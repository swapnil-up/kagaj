"""Nepali labour-migration extraction (DoFE country/district approval tables)."""

from .model import (
    CHANNEL_GROUPS,
    GENDERS,
    GROUP_LABELS,
    NUMERIC_COLS,
    DocMeta,
    ExtractResult,
    WideRow,
)
from .parser import extract_doc, melt
from .periods import classify_doc_type, parse_ad_window, parse_bs_period
from .verify import Report, verify

__all__ = [
    "CHANNEL_GROUPS",
    "GENDERS",
    "GROUP_LABELS",
    "NUMERIC_COLS",
    "DocMeta",
    "ExtractResult",
    "WideRow",
    "extract_doc",
    "melt",
    "verify",
    "Report",
    "parse_ad_window",
    "parse_bs_period",
    "classify_doc_type",
]
