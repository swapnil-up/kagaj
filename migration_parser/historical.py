"""Archive.org backfill — family (a): monthly country × period-scope M/F/T.

Older DoFE monthly progress reports print one country-wise final-approval table
with **three period-scope blocks**, each a Male/Female/Total triple:

    | prev_cumulative | <month> | cumulative |

i.e. approvals through the previous month-end, the current month's increment, and
approvals through the current month-end (FY-to-date). Countries are Latin names
(Times/Helvetica); the period labels and gender headers are Preeti-encoded; the
numerals are ASCII codepoints in a PCSNEPALI font. Decoding is therefore
**selective** — headers are Preeti-decoded, Latin country names are left alone,
numeric cells are parsed directly (never run through ``preeti.decode``).

The monthly increment (``scope="month"``) is the high-frequency datum; the other
two are the surrounding cumulative levels. See ``migration/README.md``
(archive-backfill scope-check) for the family taxonomy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz

from . import preeti
from .model import DocMeta
from .periods import BS_MONTHS_NP, _norm_digits

SCOPES = ("previous_cumulative", "month", "cumulative")
# Period-scope class: is this block a window, a year-to-date level, or the
# prior year-to-date level? Kept beside SCOPES so the archive panel and any
# future consumer agree on the vocabulary.
SCOPE_CLASS = {
    "previous_cumulative": "prior_ytd",
    "month": "window",
    "cumulative": "ytd",
}
GENDERS = ("male", "female", "total")
BLOCKS = len(SCOPES)

_TOTAL_RE = re.compile(r"जम्मा|total", re.IGNORECASE)
_INT_RE = re.compile(r"^\d+$")


@dataclass
class HistRow:
    country: str
    scope: str
    male: int
    female: int
    total: int
    sn: str = ""
    approval_type: str = ""
    is_total: bool = False
    page: int = 0

    def value(self, gender: str) -> int:
        return getattr(self, gender)


@dataclass
class HistDoc:
    meta: DocMeta
    layout: str = "monthly_country_scope_mft"
    rows: list[HistRow] = field(default_factory=list)
    totals: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    scope_labels: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.rows)

    @property
    def verified(self) -> bool:
        """True when rows exist and every math invariant holds (see ``_validate``)."""
        return bool(self.rows) and not self.problems


def _cell(c) -> str:
    return ("" if c is None else str(c)).replace("\n", " ").strip()


def _decode(s: str) -> str:
    return preeti.decode(s)


def _num(s: str) -> int:
    s = s.replace(",", "").replace(" ", "")
    if not s:
        return 0
    m = re.search(r"-?\d+", s)
    return int(m.group(0)) if m else 0


def _is_gender_cell(s: str) -> bool:
    """True for a Male/Female/Total header cell (tolerant of Preeti reorder)."""
    d = _decode(s)
    return ("महिला" in d) or ("जम्मा" in d) or ("रुष" in d)


def _is_scope_word(s: str) -> bool:
    d = _decode(s)
    return ("महिना" in d) or ("मसान्त" in d)


def _approval_type(s: str) -> str:
    """Classify the श्रम स्वीकृतिको किसिम cell (col 2 of the 12-col table).

    ``;+:Yffut`` → institutional, ``AolQmut``/``AolQmutf`` → individual, and the
    per-country ``hDdf`` subtotal. Anything else (blank header/grand-total cells)
    returns ``""``.

    NOTE: this is the *approval type* axis printed by the old labour-approval
    table — it is **not** the modern delivery-channel axis (recruiting_agency /
    individual_new / g2g / ...). See ``channel_map`` in ``channels.json``.
    """
    d = _decode(s)
    if "संस्थागत" in d:
        return "institutional"
    if "व्यक्तिगत" in d or "ब्यक्तिगत" in d:
        return "individual"
    if "जम्मा" in d:
        return "subtotal"
    return ""


def _is_total_row(c0: str, c1: str) -> bool:
    """True for a printed grand-total row.

    Checked on both the raw cell and its Preeti decode: some vintages print a
    Latin ``Total`` label, which ``_decode`` would otherwise mangle into
    Devanagari noise (hiding the row and inflating the country sums).
    """
    return (_TOTAL_RE.search(c0) or _TOTAL_RE.search(_decode(c0))
            or c1.strip().lower() == "total" or _TOTAL_RE.search(_decode(c1)))


def _table_layout(rows: list[list]) -> tuple[int, int, list[str]] | None:
    """Locate the family-(a) layout in a table's rows.

    Returns ``(data_start_row, first_block_col, scope_labels)`` or ``None``. The
    gender sub-header gives the block boundary; the (possibly wrapped) rows above
    it must name a period scope at the start of each Male/Female/Total triple
    (``col 2/5/8``), which distinguishes this table from the many other layouts
    in the same report.
    """
    for gidx, row in enumerate(rows[:4]):
        idx = [i for i, c in enumerate(row) if _is_gender_cell(_cell(c))]
        if len(idx) < 3 * BLOCKS or len(idx) % 3:
            continue
        if any(idx[j] != idx[0] + j for j in range(len(idx))):
            continue
        b0 = idx[0]
        if b0 + 3 * BLOCKS > len(row):
            continue
        labels = []
        for b in range(BLOCKS):
            ci = b0 + 3 * b
            raw = " ".join(_cell(rows[k][ci])
                           for k in range(gidx) if ci < len(rows[k])).strip()
            if not _is_scope_word(raw):
                break
            labels.append(_decode(raw))
        if len(labels) != BLOCKS:
            continue
        return gidx + 1, b0, labels
    return None


# Broken Preeti renderings seen in the scope headers (space-stripped before lookup).
_MONTH_ALIASES = {"फागनु": "फागुन"}
_FY_TOKEN = re.compile(r"(\d{2,4})\s*/\s*(\d{2,4})")


def parse_report_month(labels: list[str]) -> tuple[str, str]:
    """Return ``("<bs year> <np month>", "<np month>")`` from the scope labels.

    Two header shapes are supported:

    * ``"... कार्तिक महिनाको जम्मा"`` — a printed month name with the BS year
      (e.g. ``०६९`` → 2069).
    * ``"आ.व.०७१/७२ को बैशाख मसान्तसम्मको जम्मा"`` — a fiscal-year token plus the
      report month, with no ``महिना`` word. The report month is taken from the
      *last* (this-period cumulative) label; the BS calendar year is derived
      from the fiscal start (months Shrawan–Chaitra share the start year,
      Baishakh–Asar fall in the following calendar year).
    """
    for lbl in reversed(labels):
        mono = _norm_digits(lbl).replace(" ", "")
        name = ""
        for cand in sorted((*BS_MONTHS_NP, *_MONTH_ALIASES), key=len, reverse=True):
            if cand in mono:
                name = _MONTH_ALIASES.get(cand, cand)
                break
        if not name:
            continue
        mnum = BS_MONTHS_NP[name]
        fy = _FY_TOKEN.search(mono)
        if fy:
            start = int(fy.group(1))
            if start < 100:
                start += 2000
            year = start if mnum >= 4 else start + 1
        else:
            m = re.search(r"(\d{2,4})", mono)
            if not m:
                continue
            year = int(m.group(1))
            if year < 100:
                year += 2000
        return f"{year} {name}", name
    return "", ""


def _country_name(c0: str, c1: str) -> tuple[str, str]:
    """Return ``(sn, name)`` for a data row, or ``("", "")`` if not a country."""
    if c1 and re.match(r"^[A-Za-z]", c1):
        return (c0 if _INT_RE.match(c0) else ""), c1
    if c1 and not _INT_RE.match(c1):
        return (c0 if _INT_RE.match(c0) else ""), _decode(c1)
    if c0 and not _INT_RE.match(c0):
        return "", _decode(c0)
    return "", ""


def extract_monthly(path: str, meta: DocMeta | None = None) -> HistDoc:
    """Extract all country × period-scope rows and printed totals from one PDF."""
    doc = fitz.open(path)
    meta = meta or DocMeta(filename=str(path))
    fitz.TOOLS.mupdf_display_errors(False)
    out = HistDoc(meta=meta)
    skipped: dict[int, int] = {}
    total_candidates: list[dict[str, tuple[int, int, int]]] = []

    for pi in range(doc.page_count):
        try:
            tables = doc[pi].find_tables().tables
        except Exception as e:  # noqa: BLE001
            out.problems.append(f"p{pi + 1}: find_tables failed: {e}")
            continue
        for t in tables:
            ex = t.extract()
            lay = _table_layout(ex)
            if lay is None:
                continue
            data_start, b0, labels = lay
            # Family (a) is the 12-col "कामदार गएको मुलुक" table: a
            # labour-approval-type column at b0-1 (संस्थागत/व्यक्तिगत/जम्मा) with
            # the three period-scope blocks at col 3/6/9. The 11-col table at
            # b0=2 is the *pre-approval* product and is not this family.
            if b0 != 3:
                skipped[b0] = skipped.get(b0, 0) + 1
                continue
            if b0 + 3 * BLOCKS > len(ex[data_start - 1]):
                continue
            if not out.scope_labels:
                out.scope_labels = labels
            country = ""
            sn = ""
            for r in ex[data_start:]:
                if len(r) < b0 + 3 * BLOCKS:
                    continue
                vals = [_num(_cell(r[b0 + 3 * b + g]))
                        for b in range(BLOCKS) for g in range(3)]
                c0 = _cell(r[0])
                c1 = _cell(r[1]) if len(r) > 1 else ""
                c2 = _cell(r[2]) if len(r) > 2 else ""
                if _is_total_row(c0, c1):
                    # The grand-total row may or may not carry the (blank)
                    # approval-type cell, so its first numeric block starts at
                    # col 2 or col 3 — locate it rather than assume.
                    base = next((i for i in range(1, len(r))
                                 if re.fullmatch(r"[\d,]+", _cell(r[i]))), None)
                    if base is None or base + 3 * BLOCKS > len(r):
                        continue
                    tvals = [_num(_cell(r[base + 3 * b + g]))
                             for b in range(BLOCKS) for g in range(3)]
                    if not any(tvals[3:]):  # stray "Total" (no month/cumulative)
                        continue
                    total_candidates.append(
                        {sc: (tvals[3 * b], tvals[3 * b + 1],
                              tvals[3 * b] + tvals[3 * b + 1])
                         for b, sc in enumerate(SCOPES)})
                    continue
                approval_type = _approval_type(c2)
                if approval_type == "subtotal":  # per-country जम्मा (redundant)
                    continue
                if c1 and re.match(r"^[A-Za-z]", c1):
                    country = c1
                if _INT_RE.match(c0):
                    sn = c0
                if not country or approval_type not in ("institutional", "individual"):
                    continue
                for b, sc in enumerate(SCOPES):
                    # The printed Total cell is unreliable in later vintages
                    # (e.g. Finland prev 24+2 -> T=19). M/F are authoritative.
                    m, f = vals[3 * b], vals[3 * b + 1]
                    out.rows.append(HistRow(
                        country=country, scope=sc, male=m, female=f,
                        total=m + f, sn=sn, approval_type=approval_type,
                        page=pi + 1))

    seen_rows: set[tuple[str, str, str]] = set()
    deduped: list[HistRow] = []
    for r in out.rows:
        key = (r.country, r.approval_type, r.scope)
        if key in seen_rows:
            continue
        seen_rows.add(key)
        deduped.append(r)
    if len(deduped) != len(out.rows):
        out.warnings.append(
            f"{len(out.rows) - len(deduped)} duplicate "
            "country/approval_type/scope row(s) dropped")
    out.rows = deduped

    _choose_totals(out, total_candidates)
    if not meta.period_bs and out.scope_labels:
        meta.period_bs, _ = parse_report_month(out.scope_labels)
    for b0, n in sorted(skipped.items()):
        out.warnings.append(
            f"{n} table(s) with non-family layout (blocks at col {b0}) skipped")
    out.problems.extend(_validate(out))
    return out


def _detail_sums(out: HistDoc) -> dict[str, tuple[int, int, int]]:
    sums = {sc: [0, 0, 0] for sc in SCOPES}
    for r in out.rows:
        for i, g in enumerate(GENDERS):
            sums[r.scope][i] += r.value(g)
    return {sc: tuple(v) for sc, v in sums.items()}


def _choose_totals(out: HistDoc,
                   candidates: list[dict[str, tuple[int, int, int]]]) -> None:
    """Pick the grand-total candidate that reconciles with the detail rows.

    A report can carry several tables with a grand-total row (the full
    country-wise table *and* smaller summary tables). Prefer the one whose month
    and cumulative totals equal the summed detail; fall back to the first.
    """
    if not candidates:
        return
    detail = _detail_sums(out)
    for cand in candidates:
        if (cand["month"] == detail["month"]
                and cand["cumulative"] == detail["cumulative"]):
            out.totals = cand
            return
    out.totals = candidates[0]


def _validate(out: HistDoc) -> list[str]:
    problems: list[str] = []
    for r in out.rows:
        if r.male + r.female != r.total:
            problems.append(
                f"p{r.page} {r.country} [{r.scope}] M+F != T "
                f"({r.male}+{r.female}!={r.total})")
    detail = [r for r in out.rows if not r.is_total]
    for sc in ("month", "cumulative"):
        if sc not in out.totals:
            continue
        got = tuple(sum(r.value(g) for r in detail if r.scope == sc)
                    for g in GENDERS)
        if got != out.totals[sc]:
            problems.append(
                f"{sc} detail sum {got} != printed total {out.totals[sc]}")
    if "previous_cumulative" in out.totals:
        got = tuple(sum(r.value(g) for r in detail
                        if r.scope == "previous_cumulative") for g in GENDERS)
        if got != out.totals["previous_cumulative"]:
            out.warnings.append(
                "previous_cumulative detail sum "
                f"{got} != printed total {out.totals['previous_cumulative']} "
                "(source total inconsistent; month/cumulative reconcile)")
    _check_additivity(out)
    return problems


def _check_additivity(out: HistDoc) -> None:
    by_key: dict[tuple[str, str], dict[str, HistRow]] = {}
    for r in out.rows:
        by_key.setdefault((r.country, r.approval_type), {})[r.scope] = r
    bad = 0
    for scopes in by_key.values():
        p, m, c = (scopes.get(s) for s in SCOPES)
        if not (p and m and c):
            continue
        if p.total + m.total != c.total:
            bad += 1
    if bad:
        out.warnings.append(
            f"{bad} country row(s) where previous+month != cumulative")


def melt(doc: HistDoc) -> list[dict]:
    """Tidy-long rows keyed by scope (for the step-3 panel merge)."""
    base = doc.meta.as_dict()
    out = []
    for r in doc.rows:
        for gender in GENDERS:
            out.append({
                **base,
                "row_type": "total" if r.is_total else "detail",
                "section": "country",
                "name": r.country,
                "sn": r.sn,
                "approval_type": r.approval_type or "all",
                "scope": r.scope,
                "scope_class": SCOPE_CLASS.get(r.scope, ""),
                "gender": gender,
                "count": r.value(gender),
                "source_page": r.page,
            })
    return out
