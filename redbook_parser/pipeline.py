"""Extraction pipeline: PDF → list[BudgetRow] (v3 baseline behaviour)."""

import re
import sys

from .extraction import extract_page_text
from .fonts import FONT_CID_MAPS, decode_char, is_clean_char, reset_unmapped_log
from .legacy import EXACT_FIXES, CID_CHAR_MAP, fix_text, sanitize_devanagari
from .model import BudgetRow
from .numbers import detect_scale
from .parser import process_page_lines
from .spatial import detect_template
from .verify import BudgetVerificationEngine, VerificationReport


def decode_text(text: str, font: str = "") -> str:
    """Font-scoped decode replacing fix_text's CID lookup.

    Same chain as fix_text — EXACT_FIXES → CID lookup → EXACT_FIXES — but
    step 2 consults FONT_CID_MAPS (store-backed) instead of the legacy
    CID_CHAR_MAP.  Unmapped CIDs keep a visible ``⟦cid:N⟧`` marker
    (STRATEGY §2: no silent stripping).

    Falls back to legacy CID_CHAR_MAP for any CID not in the store.
    Only control chars (ord < 32, excluding newline) are treated as CID
    carriers — ASCII printable chars (commas, colons, etc.) pass through.
    """
    # 1. Exact word fixes first (longest match wins).
    sorted_fixes = sorted(EXACT_FIXES.items(), key=lambda x: -len(x[0]))
    for broken, correct in sorted_fixes:
        text = text.replace(broken, correct)

    # 2. CID lookup for control chars: FONT_CID_MAPS (store) → CID_CHAR_MAP.
    #    Control chars (ord < 32, not newline) and DEL (0x7F) are CID
    #    carriers in the flat text path.  ASCII printable chars are NOT
    #    treated as artifacts here (commas in numbers, colons in labels
    #    are real).
    scoped = FONT_CID_MAPS.get(font, {})
    chars = []
    for c in text:
        code = ord(c)
        if (code < 32 and code != 10) or code == 0x7F:  # control / DEL
            cid = code
            if cid in scoped:
                chars.append(scoped[cid])
            elif cid in CID_CHAR_MAP:
                chars.append(CID_CHAR_MAP[cid])
            else:
                chars.append(f"\u27e6cid:{cid}\u27e7")
        else:
            chars.append(c)

    result = "".join(chars)

    # 3. EXACT_FIXES again (post-CID).
    for old, new in sorted_fixes:
        result = result.replace(old, new)

    return result


# ---- Section inference ----

# Ministry-level codes are 3 digits (e.g. 101, 102, 204).  All subsequent
# rows with longer codes belong to that ministry's section until the next
# 3-digit code appears.  This lets the verification engine check sub-totals
# against their own detail rows instead of a page-wide sum.
_MINISTRY_CODE_RE = re.compile(r"^\d{3}$")


def infer_sections(rows: list[BudgetRow]) -> None:
    """Assign ``section`` to each row based on 3-digit ministry codes.

    Mutates rows in place.  Headings and total rows without codes inherit
    the last seen section so they stay scoped correctly for verification.
    """
    current_section = ""
    for row in rows:
        if row.code and _MINISTRY_CODE_RE.match(row.code):
            current_section = row.code
        if current_section:
            row.section = current_section


def extract_pdf(pdf_path: str, max_pages: int | None = None,
                start_page: int = 1, progress=True,
                cid_map: dict[int, str] | None = None,
                verify: bool = False) -> list[BudgetRow] | tuple[list[BudgetRow], VerificationReport]:
    """Extract budget rows from a PDF (behaviour-preserving port of v3.main).

    Args:
        cid_map: store-backed CID→Devanagari map.  When provided, fonts.FONT_CID_MAPS
                 is populated under the key "Kalimati" and the font-scoped
                 ``decode_text`` path is used instead of legacy ``fix_text``.
        verify: when True, run the math audit and return (rows, report).
    """
    import fitz  # lazy

    doc = fitz.open(pdf_path)
    start_idx = max(0, start_page - 1)
    total_pages = len(doc)
    if max_pages:
        total_pages = min(total_pages, start_idx + max_pages)

    # Populate font-scoped CID maps if store provided.
    if cid_map is not None:
        # The store loader only admits values that every observed font subset
        # agrees on, so this is a font-agnostic fallback — not a claim that the
        # document uses Kalimati.
        FONT_CID_MAPS[""] = cid_map
        decode = lambda text: decode_text(text, font="")
    else:
        decode = fix_text

    all_rows: list[BudgetRow] = []
    unknown_glyphs = 0
    # Continuation pages inherit scale from first detail page.
    current_scale = 1
    first_detail_page = None

    for pno in range(start_idx, total_pages):
        if progress:
            sys.stderr.write(f"\rPage {pno + 1}/{total_pages}")
            sys.stderr.flush()

        raw_text = extract_page_text(doc, pno)
        fixed_text = decode(raw_text)
        fixed_text = sanitize_devanagari(fixed_text)
        unknown_glyphs += fixed_text.count("⟦")

        page_scale = detect_scale(fixed_text)
        if page_scale != 1 or first_detail_page is None:
            current_scale = page_scale
        if page_scale != 1 and first_detail_page is None:
            first_detail_page = pno

        template = detect_template(fixed_text)
        lines = fixed_text.split("\n")
        all_rows.extend(process_page_lines(lines, pno + 1, current_scale, template))

    if progress:
        sys.stderr.write("\n")
    if unknown_glyphs:
        sys.stderr.write(
            f"[warning] {unknown_glyphs} unmapped glyph marker(s) kept in output; "
            "run `cidmap census`/`review` to resolve them\n")
        sys.stderr.flush()

    infer_sections(all_rows)

    if verify:
        engine = BudgetVerificationEngine()
        report = engine.verify_rows(all_rows)
        report.cross_page = engine.verify_cross_page(all_rows)
        return all_rows, report
    return all_rows
