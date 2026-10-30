"""Shared extraction primitives for Kagaj."""

from . import devanagari, eval, llm, ocr, pdf, provenance, tables
from .devanagari import (
    Issue,
    canonical_key,
    normalize,
    segment_aksaras,
    validate,
)

__all__ = [
    "Issue",
    "canonical_key",
    "normalize",
    "segment_aksaras",
    "validate",
    "devanagari",
    "eval",
    "llm",
    "ocr",
    "pdf",
    "provenance",
    "tables",
]
