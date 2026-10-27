"""Archive.org backfill — newer DoFE monthly templates (BS 2073–2075).

From BS 2073 Shrawan the monthly country tables switch from the old 12-column
period-scope layout to approval *stage* layouts:

* institutional (संस्थागत / ``Labour Approval via RA``): two blocks,
  ``Pre-Permission`` and ``Final Approved`` (6 or 8 columns, the 8-column
  variant adds a ``Total Demand`` column per stage);
* individual (व्यक्तिगत): either one 5-column block per entry type
  (``Re-entry`` / ``New`` / ``Legalization``), or a 14-column table with
  ``Renew`` / ``New`` / ``Legalized`` groups plus printed totals.

These rows carry ``scope`` = ``pre_permission`` / ``final_approved`` and, for
individual rows, ``entry_type`` = ``re_entry`` / ``new`` / ``legalization``.
They are **not** the old family's ``previous_cumulative`` / ``month`` /
``cumulative`` scopes.

Only the country-level summary pages are read; the long agency / district
listings that follow (hundreds of pages in later captures) are detected and
skipped.
"""

from __future__ import annotations

import re

import fitz

from . import normalize, preeti
from .historical import HistDoc, HistRow, SCOPE_CLASS
from .model import DocMeta

STAGE_SCOPES = ("pre_permission", "final_approved")
ENTRY_TYPES = ("re_entry", "new", "legalization")
LAYOUT = "new_country_stage_mft"

_STOP_RE = re.compile(
    r"districtwise|report on|recruitment agency|prepermission list|"
    r"final approved list|training", re.IGNORECASE)
_RA_RE = re.compile(r"Labour Approval via\s+RA\b", re.IGNORECASE)
_IND_RE = re.compile(
    r"(?:Labour Approval|Final Labour Approval) (?:via|for) "
    r"Individual\s*\(([^)]+)\)", re.IGNORECASE)
_INT_RE = re.compile(r"^\d+$")
_TOTAL_RE = re.compile(r"^(grand\s+)?total$", re.IGNORECASE)


def _cell(c) -> str:
    return ("" if c is None else str(c)).replace("\n", " ").strip()


def _num(s) -> int | None:
    s = _cell(s).replace(",", "").replace(" ", "")
    return int(s) if _INT_RE.match(s) else None


def _entry_type(text: str) -> str:
    low = text.lower()
    if ("legal" in low or "वैदेशिकरण" in text or "वैद्यानिकरण" in text
            or "j}Bflgs" in text or "j}Bflg" in text):
        return "legalization"
    if "re-entry" in low or "re entry" in low or "renew" in low:
        return "re_entry"
    if "पुनः" in text or "k'gM" in text:
        return "re_entry"
    if "new" in low or "नयाँ" in text or "नया" in text or "gof" in text:
        return "new"
    return ""


def section_of(text: str) -> tuple[str, str] | None:
    """Return ``(approval_type, entry_type)`` named by a page header."""
    if _RA_RE.search(text):
        return "institutional", ""
    dec = preeti.decode(text)
    for raw in (text, dec):
        if "संस्थागत" in raw or ";+:yf" in raw:
            return "institutional", ""
    m = _IND_RE.search(text)
    if m:
        return "individual", _entry_type(m.group(1))
    for raw in (text, dec):
        if "व्यक्तिगत" in raw or "व्यक्तिहरु" in raw or "JolQm" in raw:
            return "individual", _entry_type(raw)
    return None


def _header_kind(rows: list[list]) -> str | None:
    ncol = len(rows[0]) if rows else 0
    for r in rows[:8]:
        joined = " ".join(_cell(c).lower() for c in r)
        if not joined.strip():
            continue
        if "district" in joined:
            return "district"
        if ("recruitment agency" in joined or "lot no" in joined
                or "agency" in joined):
            return "agency"
        has_gender = any(k in joined for k in ("male", "female", "men", "women"))
        if "country" in joined and has_gender:
            pairs = len(re.findall(r"\b(?:male|men)\b", joined))
            if "remarks" in joined:
                return "eps" if ncol == 4 else "country_single"
            if ncol == 14 or pairs >= 2:
                return "country_two" if ncol != 14 else "country_multi"
            return "country_single"
    return None


def _data_row(cells: list[str]) -> tuple[str, str, int] | None:
    """Return ``(sn, name, first_numeric_col)`` for a detail row."""
    if not cells:
        return None
    c0 = cells[0]
    if _INT_RE.match(c0) and len(cells) > 1:
        return c0, cells[1], 2
    m = re.match(r"^(\d+)\s+(.+)$", c0)
    if m:
        return m.group(1), m.group(2).strip(), 1
    return None


def _blocks(ncol: int) -> list[tuple[str | None, tuple[int, int, int]]] | None:
    if ncol in (6, 8):
        return [("pre_permission", (2, 3, 4)),
                ("final_approved", (5, 6, 7))]
    if ncol == 5:
        return [(None, (2, 3, 4))]
    return None


def _add_row(out: HistDoc, sn: str, name: str, vals: list[str],
             approval_type: str, entry_type: str, scope: str,
             page: int) -> None:
    m, f, printed = (_num(v) for v in vals)
    if m is None or f is None:
        return
    total = m + f
    if printed is not None and printed != total:
        out.warnings.append(
            f"p{page} {name} [{approval_type}/{entry_type}/{scope}] "
            f"printed Total {printed} != M+F {total}")
    out.rows.append(HistRow(
        country=name, scope=scope, male=m, female=f, total=total,
        sn=sn, approval_type=approval_type, entry_type=entry_type,
        page=page))


def _parse_country_table(out: HistDoc, rows: list[list], section: tuple[str, str],
                         page: int, kind: str | None = None) -> bool:
    if not rows:
        return False
    ncol = len(rows[0])
    multi = None
    if kind == "country_single":
        blocks = [(None, (2, 3, 4))]
        approval_type, entry_type = section
    elif kind == "country_multi":
        blocks = [(None, (2, 3, 4)), (None, (5, 6, 7)), (None, (8, 9, 10))]
        multi = ENTRY_TYPES
        approval_type, entry_type = "individual", ""
    elif kind == "country_two":
        blocks = _blocks(ncol)
        approval_type, entry_type = "institutional", ""
    else:
        # Continuation page: infer from section + shape.
        if ncol == 14:
            blocks = [(None, (2, 3, 4)), (None, (5, 6, 7)), (None, (8, 9, 10))]
            multi = ENTRY_TYPES
            approval_type, entry_type = "individual", ""
        elif ncol in (5, 6) and section[0] == "individual":
            blocks = [(None, (2, 3, 4))]
            approval_type, entry_type = section
        elif ncol in (6, 8) and section[0] == "institutional":
            blocks = _blocks(ncol)
            approval_type, entry_type = "institutional", ""
        else:
            return False
    if blocks is None:
        return False
    parsed = 0
    for r in rows:
        cells = [_cell(c) for c in r]
        while len(cells) < ncol:
            cells.append("")
        row = _data_row(cells)
        if row is not None:
            sn, name, base = row
            name = re.sub(r"\s*total\b.*$", "", name, flags=re.IGNORECASE)
            name = normalize.restore_country_spacing(name.strip(" ,;"))
            if name and not _TOTAL_RE.match(name):
                off = base - 2
                for bi, (scope, idx) in enumerate(blocks):
                    if off + max(idx) >= len(cells):
                        continue
                    vals = [cells[i + off] for i in idx]
                    et = multi[bi] if multi else entry_type
                    _add_row(out, sn, name, vals, approval_type,
                             et, scope or "final_approved", page)
                    parsed += 1
            continue
        # printed total row
        name = cells[1] if len(cells) > 1 else ""
        label = name if _TOTAL_RE.match(name) else (
            cells[0] if _TOTAL_RE.match(cells[0]) else "")
        if not label:
            continue
        for bi, (scope, idx) in enumerate(blocks):
            if max(idx) >= len(cells):
                continue
            vals = [_num(cells[i]) for i in idx]
            if any(v is None for v in vals):
                continue
            et = multi[bi] if multi else entry_type
            key = f"{approval_type}|{et}|{scope or 'final_approved'}"
            out.totals.setdefault(key, []).append(tuple(vals))
    return parsed > 0


def _parse_eps(out: HistDoc, rows: list[list], page: int) -> bool:
    parsed = 0
    for r in rows:
        cells = [_cell(c) for c in r]
        if len(cells) < 4:
            continue
        name = normalize.restore_country_spacing(cells[0])
        if not name or _TOTAL_RE.match(name) or name.lower() == "country":
            continue
        m, f, t = _num(cells[1]), _num(cells[2]), _num(cells[3])
        if m is None or f is None:
            continue
        out.rows.append(HistRow(
            country=f"{name} (EPS)", scope="final_approved", male=m, female=f,
            total=m + f, approval_type="institutional", entry_type="eps",
            page=page))
        parsed += 1
    return parsed > 0


def _detail_sums(out: HistDoc) -> dict[str, tuple[int, int, int]]:
    sums: dict[str, list[int]] = {}
    for r in out.rows:
        key = f"{r.approval_type}|{r.entry_type}|{r.scope}"
        s = sums.setdefault(key, [0, 0, 0])
        s[0] += r.male
        s[1] += r.female
        s[2] += r.total
    return {k: tuple(v) for k, v in sums.items()}


def _validate(out: HistDoc) -> list[str]:
    problems: list[str] = []
    sums = _detail_sums(out)
    for key, candidates in out.totals.items():
        got = sums.get(key)
        if got is None:
            continue
        if got in candidates:
            continue
        # A 14-col total is printed only for all entry types combined.
        if key.endswith("|final_approved") and key.split("|")[1] == "":
            combined = [0, 0, 0]
            prefix = key.rsplit("|", 2)[0] + "|"
            for k, v in sums.items():
                if k.startswith(prefix):
                    combined = [combined[i] + v[i] for i in range(3)]
            if tuple(combined) in candidates:
                continue
        problems.append(
            f"{key} detail sum {got} != printed total(s) {candidates}")
    if not out.rows:
        problems.append("no country rows extracted")
    return problems


def _word_rows(page, ncol: int) -> list[list[str]]:
    """Recover a continuation table that ``find_tables`` failed to detect.

    Some captures put the final 1-3 country rows on a table-less page. The
    word stream is still a clean left-to-right row: serial, country, then the
    numeric cells. Only accept lines with the exact numeric arity expected by
    the preceding table shape.
    """
    expected = {5: 3, 6: 4, 8: 6, 14: 12}.get(ncol)
    if expected is None:
        return []
    lines: dict[int, list[tuple[float, str]]] = {}
    for w in page.get_text("words"):
        x0, y0, _x1, y1, text = w[:5]
        key = round((y0 + y1) / 2)
        lines.setdefault(key, []).append((x0, text))
    out: list[list[str]] = []
    for key in sorted(lines):
        words = [text for _x, text in sorted(lines[key])]
        if len(words) < 2 or not _INT_RE.match(words[0]):
            continue
        i = 1
        while i < len(words) and not _INT_RE.match(words[i]):
            i += 1
        name = " ".join(words[1:i]).strip()
        nums = words[i:]
        if (not name or len(nums) != expected
                or not all(_INT_RE.match(v) for v in nums)):
            continue
        out.append([words[0], name, *nums])
    return out


def extract_new(path: str, meta: DocMeta | None = None) -> HistDoc:
    doc = fitz.open(path)
    meta = meta or DocMeta(filename=str(path))
    fitz.TOOLS.mupdf_display_errors(False)
    out = HistDoc(meta=meta, layout=LAYOUT)
    current: tuple[str, str] = ("institutional", "")
    seen = False
    multi_rows: list[HistRow] = []
    multi_mode = False
    last_country_ncol: int | None = None
    for pi in range(doc.page_count):
        page = doc[pi]
        try:
            text = page.get_text()
            tables = page.find_tables().tables
        except Exception as e:  # noqa: BLE001
            out.problems.append(f"p{pi + 1}: {e}")
            continue
        sec = section_of(text)
        if sec:
            current = sec
        stop = bool(_STOP_RE.search(text))
        before = len(out.rows)
        for t in tables:
            try:
                rows = t.extract()
            except Exception as e:  # noqa: BLE001
                out.problems.append(f"p{pi + 1}: table extract failed: {e}")
                continue
            if not rows:
                continue
            kind = _header_kind(rows)
            if kind in ("district", "agency"):
                stop = True
                continue
            if kind == "eps":
                _parse_eps(out, rows, pi + 1)
                continue
            if kind in ("country_single", "country_two", "country_multi"):
                before_table = len(out.rows)
                last_country_ncol = len(rows[0])
                _parse_country_table(out, rows, current, pi + 1, kind)
                if kind == "country_multi":
                    multi_mode = True
                    multi_rows.extend(out.rows[before_table:])
                elif (kind == "country_single" and current[0] == "individual"
                      and current[1] and multi_rows):
                    stale = [r for r in multi_rows if r.entry_type == current[1]]
                    if stale:
                        gone = set(map(id, stale))
                        out.rows = [r for r in out.rows if id(r) not in gone]
                        multi_rows = [r for r in multi_rows
                                      if r.entry_type != current[1]]
                else:
                    multi_mode = False
            elif seen:
                # Continuation page: no repeated header, same section.
                before_table = len(out.rows)
                _parse_country_table(out, rows, current, pi + 1)
                if multi_mode:
                    multi_rows.extend(out.rows[before_table:])
        if (len(out.rows) == before and not stop and seen
                and last_country_ncol is not None):
            word_rows = _word_rows(page, last_country_ncol)
            if word_rows:
                before_table = len(out.rows)
                _parse_country_table(out, word_rows, current, pi + 1)
                if multi_mode:
                    multi_rows.extend(out.rows[before_table:])
        if len(out.rows) > before:
            seen = True
        if stop:
            break

    seen_rows: set[tuple[str, str, str, str]] = set()
    deduped: list[HistRow] = []
    for r in reversed(out.rows):
        key = (r.country, r.approval_type, r.entry_type, r.scope)
        if key in seen_rows:
            continue
        seen_rows.add(key)
        deduped.append(r)
    deduped.reverse()
    if len(deduped) != len(out.rows):
        out.warnings.append(
            f"{len(out.rows) - len(deduped)} duplicate country row(s) dropped")
    out.rows = deduped
    if not meta.period_bs and out.scope_labels:
        meta.period_bs = ""
    out.problems.extend(_validate(out))
    return out




_NEW_MARKERS = (
    "labour approval via ra",
    "labour approval via individual",
    "final labour approval for individual",
    "pre-permission",
    "pre-approved",
    "renew entry",
    "legalized entry",
)


def looks_new(path: str) -> bool:
    """Cheap template sniff: read only the first few pages."""
    doc = fitz.open(path)
    try:
        text = "\n".join(doc[i].get_text() for i in range(min(3, doc.page_count)))
    finally:
        doc.close()
    low = text.lower()
    if any(m in low for m in _NEW_MARKERS):
        return True
    dec = preeti.decode(text)
    return ("पूर्व स्वीकृति" in dec and "अन्तिम स्वीकृति" in dec) or \
        "वैदेशिकरण" in dec or "नयाँ श्रम स्वीकृति" in dec
