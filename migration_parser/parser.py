"""Vector-table extraction for DoFE country/district approval reports.

Strategy (see MIGRATION_NOTES.md §8.3): the PDFs are native vector tables, so we
use PyMuPDF ``find_tables()`` — no OCR, no CID decoding. Section state is carried
across pages because continuation pages repeat or omit the header.
"""

import re

import fitz

from .model import (
    CHANNEL_GROUPS,
    GENDERS,
    MAX_NUMERIC_COLS,
    NUMERIC_COLS,
    WIDE_SECTIONS,
    DocMeta,
    ExtractResult,
    WideRow,
    channels_for,
)
from .periods import classify_doc_type, parse_ad_window, parse_bs_period

_HEADER_COL1 = {"Country": "country", "District": "district"}
_INT_RE = re.compile(r"^-?\d+$")

# Accepted wide-table column counts: 23 (modern) or 20 (older annual), plus a
# spurious blank 24th column seen in some vintages.
WIDE_TABLE_COLS = (20, 23, 24)


def _to_int(cell) -> int:
    """Parse one numeric cell. Blank cells count as 0 (government convention).

    Tolerates stray text leaked from a wrapped neighbour cell (e.g. "b 2194")
    and space/, thousands separators (e.g. "1 363", "1,363").
    """
    v = ("" if cell is None else str(cell)).replace("\u00a0", " ").strip()
    v = re.sub(r"(?<=\d)[ ,](?=\d)", "", v)
    if not v:
        return 0
    if _INT_RE.match(v):
        return int(v)
    m = re.search(r"-?\d+", v)
    return int(m.group(0)) if m else 0


def _split_leading_text(cell) -> tuple[str, str]:
    """Split "b 2194" into ("b", "2194"); ("", v) when the cell is numeric."""
    v = ("" if cell is None else str(cell)).strip()
    m = re.match(r"^([^\d\-]+?)\s*(-?\d.*)$", v)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", v


def _repair_wrapped_name(name: str, first_num_cell) -> tuple[str, object]:
    """Re-join a country name that overflowed into the first numeric cell.

    e.g. name="Saudi Ara", cell="b 2194"  ->  ("Saudi Arabia", "2194").
    """
    prefix, rest = _split_leading_text(first_num_cell)
    if not prefix:
        return name, first_num_cell
    joined = name.rstrip() + (" " if prefix[:1].isupper() else "") + prefix
    return joined, rest


def _split_sn_names(cell) -> list[tuple[str, str]]:
    """Parse one cell that may hold several "SN NAME" lines (merged rows)."""
    out: list[tuple[str, str]] = []
    for line in str(cell or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+(\S.*)$", line)
        if m:
            out.append((m.group(1), m.group(2)))
        elif _INT_RE.match(line):
            out.append((line, ""))
        else:
            out.append(("", line))
    return out


_NAME_AFTER_SN = re.compile(
    r"(?m)^(\d{1,3})\n([A-Za-z][A-Za-z0-9 .,&'()/\-]*)$")


def _page_name_map(page_text: str) -> dict[str, str]:
    """Recover S.N. → name pairs from raw text (fallback for dropped cells)."""
    out: dict[str, str] = {}
    for sn, name in _NAME_AFTER_SN.findall(page_text or ""):
        out.setdefault(sn, name.strip())
    return out


def _classify_header(row) -> str:
    c1 = (str(row[1]).strip() if len(row) > 1 and row[1] is not None else "")
    return _HEADER_COL1.get(c1, "")


def _is_total_label(name: str) -> bool:
    return "total" in name.strip().lower()


def _extract_page_tables(page):
    """Yield (rows, header_index, numeric_cols) for each wide table on the page."""
    for table in page.find_tables().tables:
        if table.col_count not in WIDE_TABLE_COLS:
            continue
        rows = table.extract()
        if not rows:
            continue
        ncols = MAX_NUMERIC_COLS if table.col_count >= 2 + MAX_NUMERIC_COLS \
            else table.col_count - 2
        hdr_idx = None
        for i, row in enumerate(rows):
            if _classify_header(row):
                hdr_idx = i
                break
        yield rows, hdr_idx, ncols


def extract_doc(path: str, meta: DocMeta | None = None) -> ExtractResult:
    """Extract all country/district rows + totals from a report PDF."""
    doc = fitz.open(path)
    meta = meta or DocMeta(filename=path)
    if not meta.title:
        meta.title = _first_page_title(doc)
    if not meta.period_ad_start or not meta.period_ad_end:
        text = "\n".join(doc[p].get_text() for p in range(min(3, len(doc))))
        s, e = parse_ad_window(text)
        meta.period_ad_start = meta.period_ad_start or s
        meta.period_ad_end = meta.period_ad_end or e
    if not meta.period_bs:
        meta.period_bs = parse_bs_period(meta.title)
    if not meta.doc_type:
        meta.doc_type = classify_doc_type(meta.title)

    rows: list[WideRow] = []
    orphans: list[tuple[str, int, list[int]]] = []
    current_section = ""
    for pi in range(len(doc)):
        page_names = _page_name_map(doc[pi].get_text())
        for table_rows, hdr_idx, ncols in _extract_page_tables(doc[pi]):
            if hdr_idx is not None:
                current_section = _classify_header(table_rows[hdr_idx])
                start = hdr_idx + 1
            else:
                start = 0
            if current_section not in WIDE_SECTIONS:
                continue
            pending: list[tuple[str, str]] = []
            for r in table_rows[start:]:
                c0 = (str(r[0]).strip() if len(r) > 0 and r[0] is not None else "")
                c1 = (str(r[1]).strip() if len(r) > 1 and r[1] is not None else "")
                total_label = c1 if _is_total_label(c1) else (
                    c0 if _is_total_label(c0) and not _INT_RE.match(c0) else "")
                if total_label:
                    rows.append(WideRow(
                        section=current_section, name=total_label, sn="",
                        nums=[_to_int(c) for c in r[2:2 + ncols]],
                        is_total=True, page=pi + 1))
                    continue
                if c1:
                    if "\n" in c1:
                        parts = [p.strip() for p in c1.split("\n") if p.strip()]
                        name = parts[0]
                        sn = c0 if _INT_RE.match(c0) else ""
                        pending.extend(("", p) for p in parts[1:])
                    else:
                        name, sn = c1, (c0 if _INT_RE.match(c0) else "")
                elif c0 and re.search(r"[A-Za-z]", c0):
                    parsed = _split_sn_names(c0)
                    if not parsed:
                        continue
                    sn, name = parsed[0]
                    pending.extend(parsed[1:])
                elif pending:
                    sn, name = pending.pop(0)
                    if c0 and _INT_RE.match(c0):
                        sn = c0
                elif c0 and _INT_RE.match(c0) and c0 in page_names:
                    sn, name = c0, page_names[c0]
                elif c0:
                    continue
                else:
                    nums = [_to_int(c) for c in r[2:2 + ncols]]
                    if any(nums):
                        orphans.append((current_section, pi + 1, nums))
                    continue
                if not name:
                    continue
                num_cells = list(r[2:2 + ncols])
                name, first = _repair_wrapped_name(name, num_cells[0] if num_cells else "")
                if num_cells:
                    num_cells[0] = first
                rows.append(WideRow(
                    section=current_section, name=name, sn=sn,
                    nums=[_to_int(c) for c in num_cells],
                    is_total=False, page=pi + 1))

    problems: list[str] = []
    for section, page, nums in orphans:
        if section not in WIDE_SECTIONS:
            continue
        if any(x.section == section and x.is_total for x in rows):
            continue
        detail = [x for x in rows if x.section == section and not x.is_total]
        if nums and detail:
            ncols = len(nums)
            colsum = [sum(x.nums[i] for x in detail if i < len(x.nums))
                      for i in range(ncols)]
            if nums == colsum:
                rows.append(WideRow(section=section, name="Total", sn="",
                                    nums=nums, is_total=True, page=page))
                continue
        problems.append(
            f"unlabeled numeric row p{page} [{section}] does not match "
            f"section column sums")
    return ExtractResult(meta=meta, wide_rows=rows, problems=problems)


def _first_page_title(doc) -> str:
    """Pull a plausible document title from the first page text."""
    if not len(doc):
        return ""
    lines = [ln.strip() for ln in doc[0].get_text().splitlines() if ln.strip()]
    for ln in lines:
        if "Report on" in ln or "Countrywise" in ln or "Labour Approval" in ln:
            return ln
    return lines[0] if lines else ""


def melt(result: ExtractResult) -> list[dict]:
    """Expand wide rows into tidy long rows (one per section, name, channel, gender)."""
    out = []
    base = result.meta.as_dict()
    for row in result.wide_rows:
        for channel in channels_for(len(row.nums)):
            for gender in GENDERS:
                out.append({
                    **base,
                    "row_type": "total" if row.is_total else "detail",
                    "section": row.section,
                    "name": row.name,
                    "sn": row.sn,
                    "channel": channel,
                    "gender": gender,
                    "count": row.value(channel, gender),
                    "source_page": row.page,
                })
    return out
