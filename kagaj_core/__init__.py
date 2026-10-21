"""Shared extraction primitives for Kagaj."""

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
]
