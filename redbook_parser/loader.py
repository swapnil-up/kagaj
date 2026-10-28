"""Validated loader for cidmap/data/cid_mappings.json → FONT_CID_MAPS.

The cidmap store was produced by the derive tool (word-diff alignment) and
contains cluster values (multi-char), conflicting CIDs, and ASCII artifacts.
This loader admits only entries that are safe for the pipeline:

  1. Exactly one Devanagari codepoint (len == 1, U+0900–097F).
  2. Not already in legacy.CID_CHAR_MAP (hand-verified, gold-source).
  3. Not an ASCII artifact (no chr(cid) collision with EXACT_FIXES targets).

Rejected entries are reported in a dict returned alongside the loaded map.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("redbook_parser.loader")

DEFAULT_STORE = Path(__file__).parent.parent / "cidmap" / "data" / "cid_mappings.json"

# Unicode range for Devanagari (U+0900–U+097F).  The store values are all
# single codepoints but this catches any stray multi-char or non-Devanagari.
_DEVANAGARI_RANGE = range(0x0900, 0x0980)


def _is_single_devanagari(ch: str) -> bool:
    """True iff ch is exactly one Devanagari codepoint."""
    return len(ch) == 1 and ord(ch) in _DEVANAGARI_RANGE


def load_store(
    path: str | Path | None = None,
) -> tuple[dict[int, str], dict[str, list[dict]]]:
    """Load the cidmap store and return (approved_map, rejection_report).

    approved_map:   {cid → Devanagari} approved for the font-agnostic fallback.
    rejection_report: {reason_string → [list of rejected CID dicts]}.
    """
    from .legacy import CID_CHAR_MAP, EXACT_FIXES

    path = Path(path or DEFAULT_STORE)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cids = data.get("cids", {})

    # ASCII chars that appear in EXACT_FIXES targets — these are Identity-H
    # chr(cid) artifacts that EXACT_FIXES handles at word level.  Per-glyph
    # decode of these would corrupt real digits/letters (e.g. '9' in amounts).
    exact_fixes_chars: set[str] = set()
    for target in EXACT_FIXES.values():
        exact_fixes_chars.update(ch for ch in target if ord(ch) < 128)

    approved: dict[int, str] = {}
    rejections: dict[str, list[dict]] = {}

    for cid_str, entry in cids.items():
        cid = int(cid_str)
        values = {v for key, v in entry.items() if key != "_meta"}
        # A CID may be scoped to several font subsets. Only apply it globally
        # when every observed subset agrees; otherwise the flat-text decode
        # cannot know which glyph the CID really is.
        value = next(iter(values)) if len(values) == 1 else ""
        reject: str | None = None

        if len(values) > 1:
            reject = "conflicting_font_scopes"
        elif not _is_single_devanagari(value):
            reject = "not_single_devanagari"
        elif cid in CID_CHAR_MAP:
            # Hand-verified legacy map wins.  If values agree it's redundant;
            # if they disagree the store is wrong.  Either way, skip.
            reject = "in_legacy_cid_char_map"
        elif len(value) == 1 and ord(value) < 128 and value in exact_fixes_chars:
            # ASCII artifact char (e.g. cid 57 → '9' which appears in
            # EXACT_FIXES targets like 'रा9प\tत').  EXACT_FIXES handles
            # these at word level; per-glyph decode would corrupt real digits.
            reject = "ascii_artifact_in_exact_fixes"

        if reject:
            rejections.setdefault(reject, []).append(
                {"cid": cid, "value": value, "source": "derive"}
            )
        else:
            approved[cid] = value

    log.info(
        "cid store loaded: %d approved, %d rejected from %d total",
        len(approved),
        sum(len(v) for v in rejections.values()),
        len(cids),
    )

    return approved, rejections
