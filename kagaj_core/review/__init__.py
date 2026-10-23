"""Shared unknown-glyph review harness.

Adapters describe review items; this package owns the static HTML shell,
keyboard flow, per-session persistence, filters, progress, and neutral
import/export. It is stdlib-only and never imports PDF or OCR libraries.
"""

from .model import (
    ReviewCandidate,
    ReviewCrop,
    ReviewDecision,
    ReviewItem,
    parse_decisions,
)
from .render import render_review, storage_key

__all__ = [
    "ReviewCandidate",
    "ReviewCrop",
    "ReviewDecision",
    "ReviewItem",
    "parse_decisions",
    "render_review",
    "storage_key",
]
