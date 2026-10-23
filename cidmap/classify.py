"""Classify decoded characters for hybrid-font diagnostics.

This is reporting only. ``decode.is_unknown`` keeps its existing behaviour until
there is evidence for tightening it.
"""

from __future__ import annotations

from collections import Counter

_ASCII_ARTIFACTS = set("><@^;,:=\"`")
_DEVANAGARI_RANGES = (
    (0x0900, 0x097F),
    (0xA8E0, 0xA8FF),
    (0x1CD0, 0x1CFF),
)
_PUA_RANGES = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)


def _in_ranges(code: int, ranges) -> bool:
    return any(start <= code <= end for start, end in ranges)


def char_class(char: str) -> str:
    """Return a coarse class for one decoded character."""
    if not char or len(char) != 1:
        return "other"
    code = ord(char)
    if code == 0xFFFD:
        return "replacement"
    if code < 0x20 or 0x7F <= code <= 0x9F:
        return "control"
    if _in_ranges(code, _DEVANAGARI_RANGES):
        return "devanagari"
    if _in_ranges(code, _PUA_RANGES):
        return "pua"
    if code < 0x80:
        if char.isalnum() or char.isspace():
            return "latin"
        if char in _ASCII_ARTIFACTS:
            return "ascii-artifact"
        return "latin"
    if code <= 0x024F or 0x1E00 <= code <= 0x1EFF:
        return "latin"
    return "other"


def class_counts(chars) -> dict[str, int]:
    """Count character classes, sorted by descending count then class name."""
    counts = Counter(char_class(char) for char in chars)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
