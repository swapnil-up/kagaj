"""Metric-series extraction for DoFE narrative/status reports.

The historical reports (Status 2013/14–2015/17, Country Profile 2019, Nepal
Labour Migration Report 2020) print many "name × fiscal-year" matrices, e.g.::

    Country/Year | 2008/09 | 2009/10 | ... | 2013/14 | Total
    Malaysia     |      15 |     105 | ... |     292 | 1,121

Each matrix measures a **metric** (labour approvals, deaths, disability
compensation, complaints, …) that is named in the table caption, not the data.
This module turns those matrices into long rows tagged with a metric.

Output schema (``datasets/labour-migration/series.csv``) is a superset of ``panel.csv``:
``series_key, report, source_page, caption, metric, dimension, name,
fiscal_year, unit, year_basis, gender, count, note``.
"""

import re

from kagaj_core import tables

from .parser import _to_int

# Fields that identify one additive series block: rows sharing a ``series_key``
# differ only in ``name``/``fiscal_year`` and may be summed safely. Every field
# here is constant within a key by construction, so summing across keys would mix
# incompatible measures (count vs percent vs usd, fiscal vs calendar, total vs
# male+female). ``note`` is keyed because it carries the sub-measure that a page
# can print as sibling tables under one caption (e.g. DATASET 7 prints one
# cause-of-death table per cause: "natural cause", "workplace accident", …) —
# without it those tables collide on ``(name, fiscal_year, gender)`` and a naive
# in-key sum double-counts.
SERIES_KEY_FIELDS = (
    "report", "source_page", "caption", "metric", "dimension",
    "unit", "year_basis", "gender", "note",
)


def series_key(row: dict) -> str:
    """Stable summation-safe key for a ``series.csv`` row."""
    return "|".join(str(row.get(f, "")) for f in SERIES_KEY_FIELDS)

_YEAR = re.compile(r"^\s*(\d{4})\s*[/\-]\s*(\d{2,4})\s*$")

_CAPTION_RE = re.compile(r"(?i)^(table|dataset|annex|box|figure|map)\b")

# General country-context tables and paired layouts that do not fit the
# name × year shape (2024 T3.2 = province × top-5 countries → value columns
# are interleaved with name columns).
_SKIP_CAPTION_RE = re.compile(
    r"(?i)key statistics|key indicators|table 3\.2:\s*new labour approvals")

# Death tables broken down by cause are subsets of the all-cause tables.
_CAUSE_RE = re.compile(
    r"(?i)(suicide|workplace accident|traffic accident|cardiac|heart attack|"
    r"natural cause|murder)")


def find_caption(page, table_bbox) -> str:
    """Nearest caption-like ("Table/DATASET/Annex/…") block above the table.

    Deliberately conservative: prose/heading fallbacks are skipped because data
    rows and sex-header fragments are easily mistaken for captions. Continued
    tables on later pages inherit the previous caption (see ``extract_series``).
    """
    blocks = page.get_text("blocks")
    top = table_bbox[1]
    caps = [b for b in blocks
            if b[3] <= top + 3 and b[4].strip()
            and _CAPTION_RE.match(b[4].strip())]
    return " ".join(max(caps, key=lambda b: b[3])[4].split()) if caps else ""

# Caption → metric, first match wins.
_METRIC_RULES = (
    ("deaths", r"death|suicide|fatal|workplace accident|traffic accident|"
               r"natural cause|cardiac"),
    ("detention", r"jail|detention"),
    ("hospitalisation", r"hospital|shelter"),
    ("disability_compensation", r"disabilit|compensation"),
    ("complaints", r"complaint"),
    ("assistance", r"assistance|welfare|rescue"),
    ("no_objection_letters", r"no objection|no-objection"),
    ("training", r"trainees trained|skill training"),
    ("labour_approval", r"labour permit|labor permit|labour approval|"
                        r"labour migration|labour migrant|migrant worker|"
                        r"recruiting agency|permit|"
                        r"data ?set of \d+ districts"),
    ("migration_stock", r"foreign.?born|census|absentee|population|resident"),
)


def norm_year(cell) -> str:
    """Normalise a fiscal-year token, e.g. '2008/09' or '2008-2009' → '2008/09'."""
    m = _YEAR.match(str(cell or ""))
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    return f"{a}/{b[2:]}" if len(b) == 4 else f"{a}/{b}"


_CAL_YEAR = re.compile(r"^\s*(1[89]\d{2}|20\d{2})\s*$")


def norm_cal_year(cell) -> str:
    """Normalise a bare calendar year, e.g. '2013' → '2013' (else '')."""
    m = _CAL_YEAR.match(str(cell or ""))
    return m.group(1) if m else ""


def classify_metric(caption: str) -> str:
    low = (caption or "").lower()
    for metric, pat in _METRIC_RULES:
        if re.search(pat, low):
            return metric
    return "unknown"


def classify_dimension(name_header: str, caption: str) -> str:
    t = f"{name_header} {caption}".lower()
    if "district" in t:
        return "district"
    if "country" in t or "destination" in t:
        return "country"
    return "unknown"


def _clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    n = re.sub(r"(?i)\s+total$", "", n).strip()
    return n


_FLOAT_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")


def _scalar(cell, unit: str):
    """Parse a cell. Percent tables keep their decimal (25.6 / "1.08 %")."""
    if unit == "percent":
        s = str(cell or "").replace(",", "").replace("%", "").strip()
        if _FLOAT_RE.match(s):
            return float(s)
    return _to_int(cell)


# A data cell that is purely numeric (optional thousands comma / decimal part).
_NUM_CELL = re.compile(r"^\s*\d[\d,]*(?:\.\d+)?\s*$")
_PERCENT_WORD = re.compile(r"(?i)%|\bpercent(?:age)?\b|\bshare\b|\brate\b")


def _detect_unit(header, name_hdr, caption, data_rows) -> str:
    """Classify a year-matrix as ``percent`` or ``count``.

    The old heuristic flipped a whole table to ``percent`` if *any* cell
    contained a period — which mislabelled death/approval counts whenever a row
    label did (e.g. ``Rep. of Korea``). Detect instead from (a) an explicit
    percent marker in the caption/header, or (b) a majority of *numeric* data
    cells carrying a decimal fraction.
    """
    if _PERCENT_WORD.search(f"{name_hdr} {caption} {' '.join(str(c) for c in header)}"):
        return "percent"
    nums = [str(c).strip() for r in data_rows for c in r if _NUM_CELL.match(str(c or ""))]
    if nums and sum("." in c for c in nums) >= 0.6 * len(nums):
        return "percent"
    return "count"


# Undated country-count snapshots (2024 T4.5 jail/detention, T4.6 hospital/shelter).
_COUNTRY_SNAPSHOT_RE = re.compile(
    r"(?i)jail and detention|hospitalised or in shelters")


def extract_country_snapshot(rows, caption: str, page: int, report: str) -> list[dict]:
    """Country → count snapshot, single-column (T4.6) or paired (T4.5).

    T4.5 prints two ``Country | Number`` column-pairs side by side; T4.6 is a
    single pair with section sub-headers ("Hospitalised…" / "…in Shelters").
    Rows are tagged ``year_basis=snapshot`` with a blank ``fiscal_year``.
    """
    if not _COUNTRY_SNAPSHOT_RE.search(caption):
        return []
    metric = classify_metric(caption)
    h = None
    for i, r in enumerate(rows[:3]):
        if r and re.match(r"(?i)^country\b", str(r[0]).strip()):
            h = i
            break
    if h is None:
        return []
    header = rows[h]
    name_cols = [j for j, c in enumerate(header)
                 if str(c or "").strip() and not _NUM_CELL.match(str(c or ""))
                 and not re.match(r"(?i)^number\b", str(c or "").strip())]
    name_cols = [j for j in name_cols if j + 1 < len(header)]
    if not name_cols:
        return []
    out: list[dict] = []
    section = ""
    for r in rows[h + 1:]:
        for j in name_cols:
            raw = str(r[j] or "").strip() if j < len(r) else ""
            if not raw or re.match(r"(?i)^(total|grand\s+total|sub.?total)\b", raw):
                continue
            val = r[j + 1] if j + 1 < len(r) else ""
            if not str(val or "").strip() and len(name_cols) == 1:
                section = raw  # T4.6 sub-header
                continue
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": metric, "dimension": "country", "unit": "count",
                "name": _clean_name(raw), "fiscal_year": "", "gender": "",
                "count": _to_int(val), "note": section, "year_basis": "snapshot",
            })
    return out if len(out) >= 3 else []


_MRRC_RE = re.compile(r"(?i)cases registered at migrant resource centres")
_REMITTANCE_HH_RE = re.compile(r"(?i)remittance receiving households by provinces")
_REMITTANCE_USE_RE = re.compile(r"(?i)use of remittances")


def extract_mrrc_cases(rows, caption: str, page: int, report: str) -> list[dict]:
    """MRRC registered cases by type × sex, 2022/23–2023/24 (2024 T4.7).

    Case rows are shares (``Total %``); the final ``Total N`` row is the only
    count and is kept as ``name='all cases'``.
    """
    if not _MRRC_RE.search(caption):
        return []
    h = None
    for i, r in enumerate(rows[:4]):
        if sum(1 for c in r if _gender_of(c)) >= 2:
            h = i
            break
    if h is None:
        return []
    hdr = rows[h]
    gcols = [(j, _gender_of(hdr[j])) for j in range(len(hdr)) if _gender_of(hdr[j])]
    out: list[dict] = []
    for r in rows[h + 1:]:
        raw = str(r[0] or "").strip()
        if not raw or re.match(r"(?i)^total\s*%", raw):
            continue
        is_count = bool(re.match(r"(?i)^total\s*n", raw))
        name = "all cases" if is_count else _clean_name(raw)
        for j, g in gcols:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "mrrc_cases", "dimension": "case_type",
                "unit": "count" if is_count else "percent",
                "name": name, "fiscal_year": "", "gender": g,
                "count": _scalar(r[j], "count" if is_count else "percent")
                if j < len(r) else 0,
                "note": "2022/23-2023/24", "year_basis": "snapshot",
            })
    return out if len(out) >= 4 else []


def extract_remittance_households(rows, caption: str, page: int, report: str) -> list[dict]:
    """Remittance-receiving households by province (2024 T4.8).

    Two measures per province: share of households (%) and mean amount received
    (NPR). ``unit`` distinguishes them (``percent`` / ``npr``).
    """
    if not _REMITTANCE_HH_RE.search(caption):
        return []
    header = rows[0]
    val_cols = [(j, str(header[j] or "")) for j in range(1, len(header))]
    out: list[dict] = []
    for r in rows[1:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j, htxt in val_cols:
            unit = "percent" if re.search(r"(?i)%|per cent", htxt) else "npr"
            note = "" if unit == "percent" else "amount per remitter (NPR)"
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "remittance_receiving", "dimension": "province",
                "unit": unit, "name": name, "fiscal_year": "", "gender": "",
                "count": _scalar(r[j], unit) if j < len(r) else 0,
                "note": note, "year_basis": "snapshot",
            })
    return out if len(out) >= 4 else []


def extract_remittance_use(rows, caption: str, page: int, report: str) -> list[dict]:
    """Use of remittances by priority and year 2011/2023 (2024 T4.9).

    Two-level header: priority (First/Second) over 2011/2023. Emitted as
    ``dimension=remittance_use``, ``year_basis=calendar``, ``note`` = priority.
    """
    if not _REMITTANCE_USE_RE.search(caption):
        return []
    h0 = h1 = None
    for i, r in enumerate(rows[:4]):
        if len([j for j, c in enumerate(r) if norm_cal_year(c)]) >= 2:
            h0, h1 = i - 1, i
            break
    if h0 is None or h0 < 0:
        return []
    pri_row, yr_row = rows[h0], rows[h1]
    cols: list[tuple[int, str, str]] = []
    pri = ""
    for j in range(len(yr_row)):
        if j < len(pri_row) and str(pri_row[j] or "").strip():
            pri = str(pri_row[j]).strip()
        yr = norm_cal_year(yr_row[j])
        if yr:
            cols.append((j, yr, pri.lower()))
    out: list[dict] = []
    for r in rows[h1 + 1:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j, yr, p in cols:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "remittance_use", "dimension": "remittance_use",
                "unit": "percent", "name": name, "fiscal_year": yr, "gender": "",
                "count": _scalar(r[j], "percent") if j < len(r) else 0,
                "note": p if p else "", "year_basis": "calendar",
            })
    return out if len(out) >= 4 else []


_APPROVAL_RANGE_RE = re.compile(r"(?i)new labour approvals,\s*2022/23")


def _category_dimension(hdr: str) -> str:
    h = (hdr or "").lower()
    if "occupation" in h:
        return "occupation"
    if "destination" in h or "country" in h:
        return "country"
    if "skill" in h:
        return "skill"
    return "category"


def extract_measure_crosstab(rows, caption: str, page: int, report: str) -> list[dict]:
    """Year (col 0) × category (col 1) × several measure columns (2022/23–2023/24).

    Handles 2024 T3.7 (skill × mode), T3.10 (destination × skill, plus a
    ``Total N`` count column) and T3.13 (occupation × mode × sex). Header may be
    one or two rows; the last header cell of a column is its measure label, the
    one above (if any) is the mode group. Percent shares keep decimals; a
    ``Total N``/number column is a count.
    """
    if not _APPROVAL_RANGE_RE.search(caption):
        return []
    data_start = None
    for i, r in enumerate(rows):
        if len(r) >= 3 and norm_year(r[0]) and str(r[1] or "").strip():
            data_start = i
            break
    if data_start is None or data_start < 1:
        return []
    header_rows = rows[:data_start]
    cat_hdr = ""
    for hr in header_rows:
        if len(hr) > 1 and str(hr[1] or "").strip():
            cat_hdr = str(hr[1]).strip()
    dimension = _category_dimension(cat_hdr)
    if dimension not in ("skill", "country", "occupation"):
        return []  # not one of the T3.7/T3.10/T3.13 category cross-tabs

    cols: list[tuple[int, str, str, str]] = []  # (col, unit, gender, note)
    carry = ""
    for j in range(2, len(rows[0])):
        cells = [re.sub(r"\s+", " ", str(hr[j])).strip() for hr in header_rows
                 if j < len(hr) and str(hr[j] or "").strip()]
        if not cells:
            continue
        last = cells[-1]
        unit = "count" if re.search(r"(?i)\btotal\s*n\b|\bnumber\b", last) else "percent"
        gender = _gender_of(last)
        if gender:
            if len(cells) >= 2:
                carry = cells[-2]
            note = carry
        else:
            note = last
        cols.append((j, unit, gender, note))
    if len(cols) < 2:
        return []

    out: list[dict] = []
    year = ""
    for r in rows[data_start:]:
        y = norm_year(r[0]) if r else ""
        if y:
            year = y
        name = _clean_name(r[1]) if len(r) > 1 else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j, unit, gender, note in cols:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "labour_approval", "dimension": dimension, "unit": unit,
                "name": name, "fiscal_year": year, "gender": gender,
                "count": _scalar(r[j], unit) if j < len(r) else 0,
                "note": note, "year_basis": "fiscal",
            })
    return out if len(out) >= 4 else []


def extract_destination_gender_crosstab(rows, caption: str, page: int, report: str) -> list[dict]:
    """Destination × sex counts + shares for one year (Country Profile 2019 Table 8).

    Header is two rows: sex groups (Male/Female/Total) over ``No.`` / ``%``.
    Only ``No.`` columns are counts; ``%`` columns are shares.
    """
    if not re.search(r"(?i)permits issued by place of destination and sex", caption):
        return []
    m = re.search(r"(\d{4}\s*/\s*\d{2,4})", caption)
    year = norm_year(m.group(1)) if m else ""
    hdr = rows[0]
    sub = rows[1] if len(rows) > 1 else []
    specs: list[tuple[int, str, str]] = []
    carry = ""
    for j in range(1, len(hdr)):
        g = _gender_of(hdr[j])
        if g:
            carry = g
        lbl = str(sub[j] or "").strip().lower() if j < len(sub) else ""
        if lbl.startswith("no"):
            specs.append((j, carry, "count"))
        elif "%" in lbl:
            specs.append((j, carry, "percent"))
    if not specs or not year:
        return []
    out: list[dict] = []
    for r in rows[2:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j, g, unit in specs:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "labour_approval", "dimension": "country", "unit": unit,
                "name": name, "fiscal_year": year, "gender": g,
                "count": _scalar(r[j], unit) if j < len(r) else 0,
                "note": "", "year_basis": "fiscal",
            })
    return out if len(out) >= 4 else []


def extract_cause_country(rows, caption: str, page: int, report: str) -> list[dict]:
    """Cause of death by destination country (Nepal Labour Migration Report 2020 T17)."""
    if not re.search(r"(?i)cause of death by country", caption):
        return []
    causes = rows[1] if len(rows) > 1 else []
    out: list[dict] = []
    for r in rows[2:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j in range(1, len(causes)):
            cause = str(causes[j] or "").strip()
            if not cause or j >= len(r):
                continue
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "deaths_by_cause", "dimension": "country", "unit": "count",
                "name": name, "fiscal_year": "", "gender": "", "count": _to_int(r[j]),
                "note": cause.lower(), "year_basis": "snapshot",
            })
    return out if len(out) >= 4 else []


_CAUSE_COUNTRY_YEAR_RE = re.compile(
    r"(?i)by cause of death,\s*destination country")


def _sex_single(cell) -> str:
    """Map the single-letter sex tokens (``M``/``F``) these tables print."""
    return {"m": "male", "f": "female"}.get(str(cell or "").strip().lower(), "")


def extract_cause_country_year(rows, caption: str, page: int, report: str) -> list[dict]:
    """Cause × destination country × fiscal year × sex (status-report DATASET 7).

    The status reports print **one table per cause** ("Other or unidentified
    causes", "Natural cause", "Workplace accident", "Cardiac arrest", …), each
    with a two-level header: fiscal years across the top and ``M``/``F`` beneath
    each year (the year label sits on the ``M`` column, so it is forward-filled
    to the ``F`` column). The cause is the first non-name header cell.

    This is kept as ``deaths_by_cause`` with the cause in ``note`` and the sex in
    ``gender`` — without the cause, the per-cause tables collide on
    ``(name, fiscal_year, gender)`` under the shared caption and in-key summing
    double-counts.
    """
    if not _CAUSE_COUNTRY_YEAR_RE.search(caption):
        return []
    cause = ""
    for cell in (rows[0][1:] if rows else []):
        if str(cell or "").strip():
            cause = str(cell).strip().lower()
            break
    if not cause:
        return []
    h = None
    for i in range(min(4, len(rows) - 1)):
        yr = [j for j, c in enumerate(rows[i]) if _year_token(c)]
        gm = [j for j, c in enumerate(rows[i + 1]) if _sex_single(c)]
        if len(yr) >= 2 and yr[0] == 1 and len(gm) >= 2:
            h = i
            break
    if h is None:
        return []
    yrow, grow = rows[h], rows[h + 1]
    cols: list[tuple[int, str, str]] = []
    year = ""
    for j in range(1, len(yrow)):
        y = _year_token(yrow[j])
        if y:
            year = y
        g = _sex_single(grow[j]) if j < len(grow) else ""
        if year and g:
            cols.append((j, year, g))
    if len(cols) < 2:
        return []
    out: list[dict] = []
    for r in rows[h + 2:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j, fy, g in cols:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "deaths_by_cause", "dimension": "country",
                "unit": "count", "name": name, "fiscal_year": fy, "gender": g,
                "count": _to_int(r[j]) if j < len(r) else 0, "note": cause,
            })
    return out if len(out) >= 4 else []


def extract_remittance_cost(rows, caption: str, page: int, report: str) -> list[dict]:
    """Remittance transfer costs by destination (2020 T19): % of amount sent."""
    if not re.search(r"(?i)remittance transfer costs", caption):
        return []
    tiers = rows[0]
    out: list[dict] = []
    for r in rows[1:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j in range(1, len(tiers)):
            tier = str(tiers[j] or "").strip()
            if not tier or j >= len(r):
                continue
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "remittance_cost", "dimension": "country", "unit": "percent",
                "name": name, "fiscal_year": "", "gender": "",
                "count": _scalar(r[j], "percent"), "note": tier, "year_basis": "snapshot",
            })
    return out if len(out) >= 4 else []


def extract_migration_cost(rows, caption: str, page: int, report: str) -> list[dict]:
    """Cost of migration vs average earnings by destination (2019 T12), USD."""
    if not re.search(r"(?i)cost of migration versus average earnings", caption):
        return []
    measures = rows[0]
    out: list[dict] = []
    for r in rows[1:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j in range(1, len(measures)):
            note = re.sub(r"\s+", " ", str(measures[j] or "")).strip()
            if not note or j >= len(r):
                continue
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "migration_cost", "dimension": "country", "unit": "usd",
                "name": name, "fiscal_year": "", "gender": "", "count": _to_int(r[j]),
                "note": note, "year_basis": "snapshot",
            })
    return out if len(out) >= 4 else []


def extract_calendar_year_matrix(rows, caption: str, page: int, report: str) -> list[dict]:
    """Extract a name × **calendar-year** matrix (e.g. 2024 Table 3.19).

    Identical in shape to ``extract_year_matrix`` but the header holds bare
    calendar years (2013, 2014, …). Rows are tagged ``year_basis=calendar`` so
    they are never summed with the fiscal-year series.
    """
    header_idx = None
    year_cols: list[int] = []
    for i, r in enumerate(rows[:5]):
        cols = [j for j, c in enumerate(r) if norm_cal_year(c)]
        if len(cols) >= 2:
            header_idx, year_cols = i, cols
            break
    if header_idx is None or year_cols[0] != 1:
        return []

    header = rows[header_idx]
    name_hdr = str(header[0]) if header else ""
    metric = classify_metric(caption)
    if metric in ("unknown", ""):
        metric = "migration_stock"
    if re.search(r"(?i)status of residence", name_hdr):
        dimension = "residence_status"
    else:
        dimension = classify_dimension(name_hdr, caption)
        if dimension in ("unknown", ""):
            dimension = "category"
    unit = _detect_unit(header, name_hdr, caption, rows[header_idx + 1:])

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in rows[header_idx + 1:]:
        name = _clean_name(r[0]) if r else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j in year_cols:
            key = (name.lower(), norm_cal_year(header[j]))
            if key in seen:
                return []  # cross-tab, not a series
            seen.add(key)
            out.append({
                "report": report,
                "source_page": page,
                "caption": caption,
                "metric": metric,
                "dimension": dimension,
                "unit": unit,
                "name": name,
                "fiscal_year": norm_cal_year(header[j]),
                "gender": "",
                "count": _scalar(r[j], unit) if j < len(r) else 0,
                "note": "",
                "year_basis": "calendar",
            })
    return out


def extract_year_matrix(rows, caption: str, page: int, report: str) -> list[dict]:
    """Extract one name × fiscal-year matrix into long rows."""
    header_idx = None
    year_cols: list[int] = []
    for i, r in enumerate(rows[:5]):
        cols = [j for j, c in enumerate(r) if norm_year(c)]
        if len(cols) >= 2:
            header_idx, year_cols = i, cols
            break
    if header_idx is None or year_cols[0] != 1:
        return []

    name_col = 0
    header = rows[header_idx]
    name_hdr = str(header[name_col]) if name_col < len(header) else ""
    metric = classify_metric(caption)
    note = ""
    if metric == "deaths":
        cm = _CAUSE_RE.search(caption)
        if cm:
            metric, note = "deaths_by_cause", cm.group(1).lower()
    dimension = classify_dimension(name_hdr, caption)
    unit = _detect_unit(header, name_hdr, caption, rows[header_idx + 1:])

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in rows[header_idx + 1:]:
        name = _clean_name(r[name_col]) if name_col < len(r) else ""
        if not name:
            continue
        if re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        for j in year_cols:
            key = (name.lower(), norm_year(header[j]))
            if key in seen:
                # A real matrix has one row per name×year; duplicates mean this
                # is a cross-tab (e.g. country × cause × year) — not a series.
                return []
            seen.add(key)
            out.append({
                "report": report,
                "source_page": page,
                "caption": caption,
                "metric": metric,
                "dimension": dimension,
                "unit": unit,
                "name": name,
                "fiscal_year": norm_year(header[j]),
                "gender": "",
                "count": _scalar(r[j], unit) if j < len(r) else 0,
                "note": note,
            })
    return out


# The two "cause of death × year" prints, each with fiscal years down column 0.
# Deliberately narrow: other cause tables (status-report "…by sex", country
# cross-tabs) either double-count sexes or are not year-rows.
_MF_YEAR_RE = re.compile(r"(?i)cause\s+of\s+death\s+by\s+year")          # 2020: printed M/F
_SUM_YEAR_RE = re.compile(r"(?i)cause\s+of\s+death,\s*2008/09")          # 2024: causes only


def extract_cause_of_death_year(rows, caption: str, page: int, report: str) -> list[dict]:
    """All-cause deaths per year from a transposed cause × year cross-tab.

    The Nepal Labour Migration Report 2020 ("TABLE 16: Cause of Death by Year")
    and the 2024 report ("Table 4.1: Cause of Death, 2008/09–2023/24") both
    print fiscal years running *down* column 0 with the causes as columns. The
    generic year-across-columns extractor rejects these (they are cross-tabs),
    so this reads the all-cause total per row — the printed ``Total`` M/F pair
    where present (2020), otherwise the sum of the cause cells (2024, whose row
    sums equal the independently printed death totals). Extends the all-cause
    death series through FY2023/24.
    """
    mf = _MF_YEAR_RE.search(caption)
    if not mf and not _SUM_YEAR_RE.search(caption):
        return []
    hdr = None
    if mf:
        hdr = next((h for h, r in enumerate(rows[:6])
                    if len(r) >= 2
                    and str(r[-2]).strip().upper() == "M"
                    and str(r[-1]).strip().upper() == "F"), None)
        if hdr is None:
            return []
    data = rows[hdr + 1:] if hdr is not None else rows
    out: list[dict] = []
    years = 0
    for r in data:
        fy = norm_year(r[0]) if r else ""
        if not fy:
            continue
        if hdr is not None:
            m, f = _to_int(r[-2]), _to_int(r[-1])
            total = m + f
        else:
            cells = [str(c) for c in r[1:] if _NUM_CELL.match(str(c or ""))]
            m = f = None
            total = sum(_to_int(c) for c in cells)
        base = {
            "report": report, "source_page": page, "caption": caption,
            "metric": "deaths", "dimension": "country",
            "name": "All destinations", "fiscal_year": fy, "note": "",
        }
        if m is not None:
            out.append({**base, "unit": "count", "gender": "male", "count": m})
            out.append({**base, "unit": "count", "gender": "female", "count": f})
        out.append({**base, "unit": "count", "gender": "total", "count": total})
        years += 1
    return out if years >= 2 else []


_GENDER = {"female": "female", "women": "female", "male": "male", "total": "total"}


def _year_token(cell) -> str:
    """Fiscal-year token, tolerating labels like ``2022/23 (2079/80)``."""
    y = norm_year(cell)
    if y:
        return y
    m = re.search(r"\d{4}\s*[/\-]\s*\d{2,4}", str(cell or ""))
    return norm_year(m.group(0)) if m else ""

# Narrative-report cross-tabs of the shape
#   [name | Female Male Total | (name) Female Male Total | ...]
#   [  ... year labels spanning the sex blocks ...]
# keyed by caption → (metric, dimension). Each sex column is assigned to the
# nearest year label; a repeated name column to the left of a block is honoured
# (e.g. 2024 T4.2 lists two differently-ordered destination rankings side by
# side).
_BLOCK_RULES = (
    (re.compile(r"(?i)deceased migrant workers.? sex and country"), "deaths", "country"),
    (re.compile(r"(?i)migrant workers.? deaths,\s*20\d\d"), "deaths", "province"),
    (re.compile(r"(?i)annex 1[23]:\s*number of returnee"), "return_migration", ""),
)


def _block_dimension(caption: str, dim: str) -> str:
    if dim:
        return dim
    return "district" if re.search(r"(?i)annex 13", caption) else "country"


def _gender_of(cell) -> str:
    return _GENDER.get(str(cell or "").strip().lower(), "")


def extract_year_gender_blocks(rows, caption: str, page: int, report: str,
                               metric: str, dimension: str) -> list[dict]:
    """Extract a two-row header table with year-labelled sex blocks."""
    h0 = None
    for i in range(min(4, len(rows) - 1)):
        yr = [j for j, c in enumerate(rows[i]) if _year_token(c)]
        gm = [j for j, c in enumerate(rows[i + 1]) if _gender_of(c)]
        if len(yr) >= 2 and len(gm) >= 2:
            h0 = i
            break
    if h0 is None:
        return []
    yrow, grow = rows[h0], rows[h0 + 1]
    ytoks = []
    for j in range(len(yrow)):
        y = _year_token(yrow[j])
        if y:
            ytoks.append((j, y))
        elif str(yrow[j] or "").strip().lower() == "total":
            ytoks.append((j, "total"))  # combined both-years block → skip

    # Split the sex columns into blocks. A block starts wherever the sex
    # sequence restarts (after a "Total" marker or a column gap), which is
    # robust to whether the year label sits at the block start (Annex 12/13) or
    # mid-block (Tables 4.2/4.4).
    gcols = [(j, _gender_of(grow[j])) for j in range(len(grow)) if _gender_of(grow[j])]
    blocks: list[list[tuple[int, str]]] = []
    prev_j = prev_g = None
    for j, g in gcols:
        if not blocks or prev_g == "total" or j != prev_j + 1:
            blocks.append([])
        blocks[-1].append((j, g))
        prev_j, prev_g = j, g

    assigned = []
    first_name: int | None = None
    for blk in blocks:
        year = min(ytoks, key=lambda t: abs(t[0] - min(c for c, _ in blk)))[1]
        if year == "total":
            continue
        nc = min(c for c, _ in blk) - 1
        if not (nc >= 0 and str(yrow[nc]).strip() and not _year_token(yrow[nc])
                and not _gender_of(grow[nc])):
            nc = first_name if first_name is not None else 0
        if first_name is None:
            first_name = nc
        for j, g in blk:
            assigned.append((j, g, year, nc))

    out: list[dict] = []
    for r in rows[h0 + 2:]:
        if not any(str(c).strip() for c in r):
            continue
        for j, g, year, nc in assigned:
            raw = str(r[nc]).strip() if nc < len(r) else ""
            if not raw or re.match(r"(?i)^(total|grand\s+total)\b", raw):
                continue
            nm = _clean_name(raw)
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": metric, "dimension": dimension, "unit": "count",
                "name": nm, "fiscal_year": year, "gender": g,
                "count": _to_int(r[j]) if j < len(r) else 0, "note": "",
            })
    return out if len(out) >= 4 else []


_OCC_PROFILE_RE = re.compile(
    r"(?i)occupation profile:\s*([^,]+?)\s*,\s*(\d{4}\s*[/\-]\s*\d{2,4})")


def extract_occupation_profile(rows, caption: str, page: int, report: str) -> list[dict]:
    """Occupation × sex counts for one destination-year (status-report T25–T31).

    Shape: ``Occupation | Male Female Total | Percentage | M F T`` — only the
    first Male/Female/Total block is a count; the single-letter block is the
    percentage. Destination and fiscal year come from the caption.
    """
    m = _OCC_PROFILE_RE.search(caption)
    if not m:
        return []
    dest = re.sub(r"\s*\(.*", "", m.group(1)).strip()
    year = norm_year(m.group(2))
    h = None
    for i, r in enumerate(rows[:4]):
        if sum(1 for c in r if _gender_of(c)) >= 2:
            h = i
            break
    if h is None or not year:
        return []
    hdr = rows[h]
    gcols = [(j, _gender_of(hdr[j])) for j in range(len(hdr)) if _gender_of(hdr[j])]
    out: list[dict] = []
    for r in rows[h + 1:]:
        raw = str(r[0]).strip() if r else ""
        if not raw or re.match(r"(?i)^(total|grand\s+total)\b", raw):
            continue
        for j, g in gcols:
            out.append({
                "report": report, "source_page": page, "caption": caption,
                "metric": "labour_approval", "dimension": "occupation",
                "unit": "count", "name": _clean_name(raw), "fiscal_year": year,
                "gender": g, "count": _to_int(r[j]) if j < len(r) else 0,
                "note": dest,
            })
    return out if len(out) >= 4 else []


def extract_cross_tab(rows, caption: str, page: int, report: str) -> list[dict]:
    """Dispatch a cross-tab table to its extractor by caption rule."""
    for pat, metric, dimension in _BLOCK_RULES:
        if pat.search(caption):
            return extract_year_gender_blocks(
                rows, caption, page, report, metric,
                _block_dimension(caption, dimension))
    return []


def _verify_matrix(rows, header_idx, year_cols, name_col) -> list[str]:
    """Check printed row totals (Σ years) where a "Total" column is present.

    Column totals are deliberately not checked: continued tables print a single
    cumulative Total row that spans pages, so per-page column sums never match.
    """
    header = rows[header_idx]
    total_col = year_cols[-1] + 1
    has_total_col = (total_col < len(header)
                     and str(header[total_col] or "").strip().lower().startswith("total"))
    if not has_total_col:
        return []
    value_columns = [f"y{j}" for j in year_cols]
    records: list[dict] = []
    for r in rows[header_idx + 1:]:
        name = _clean_name(r[name_col]) if name_col < len(r) else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        stated = _to_int(r[total_col]) if total_col < len(r) else 0
        if not stated:
            continue
        record = {"name": name, "total": stated}
        for j in year_cols:
            record[f"y{j}"] = _to_int(r[j]) if j < len(r) else 0
        records.append(record)
    violations = tables.row_sums_equal(
        value_columns=value_columns, total_column="total")(records)
    checks: list[str] = []
    for violation in violations:
        record = records[violation.row]
        computed = sum(record[column] for column in value_columns)
        checks.append(
            f"row_total {record['name']!r} computed={computed} "
            f"stated={record['total']}")
    return checks


def extract_series(path: str, report: str = "") -> tuple[list[dict], list[str]]:
    """Extract every name × fiscal-year matrix from one report PDF.

    Captions are propagated across pages so multi-page (continued) tables keep
    the metric/dimension of their header page. Returns ``(rows, problems)``
    where problems are row/column-total mismatches.
    """
    from kagaj_core import pdf as core_pdf

    doc = core_pdf.open_pdf(path)
    out: list[dict] = []
    problems: list[str] = []
    last_caption = ""
    for pi in range(len(doc)):
        page = doc[pi]
        for table in page.find_tables().tables:
            rows = table.extract()
            if len(rows) < 3:
                continue
            found = find_caption(page, table.bbox)
            if found:
                last_caption = found
            caption = found or last_caption
            if _SKIP_CAPTION_RE.search(caption):
                continue

            header_idx = None
            year_cols: list[int] = []
            for i, r in enumerate(rows[:5]):
                cols = [j for j, c in enumerate(r) if norm_year(c)]
                if len(cols) >= 2 and cols[0] == 1:
                    header_idx, year_cols = i, cols
                    break
            rows_out = (extract_cause_of_death_year(rows, caption, pi + 1, report)
                        or extract_cross_tab(rows, caption, pi + 1, report)
                        or extract_occupation_profile(rows, caption, pi + 1, report)
                        or extract_country_snapshot(rows, caption, pi + 1, report)
                        or extract_measure_crosstab(rows, caption, pi + 1, report)
                        or extract_mrrc_cases(rows, caption, pi + 1, report)
                        or extract_remittance_households(rows, caption, pi + 1, report)
                        or extract_remittance_use(rows, caption, pi + 1, report)
                        or extract_destination_gender_crosstab(rows, caption, pi + 1, report)
                        or extract_cause_country(rows, caption, pi + 1, report)
                        or extract_cause_country_year(rows, caption, pi + 1, report)
                        or extract_remittance_cost(rows, caption, pi + 1, report)
                        or extract_migration_cost(rows, caption, pi + 1, report)
                        or extract_year_matrix(rows, caption, pi + 1, report)
                        or extract_calendar_year_matrix(rows, caption, pi + 1, report))
            for row in rows_out:
                row.setdefault("year_basis", "fiscal")
            if rows_out and header_idx is not None and rows_out[0]["unit"] == "count":
                problems.extend(
                    f"{report} p{pi + 1} [{caption[:40]}]: {c}"
                    for c in _verify_matrix(rows, header_idx, year_cols, 0))
            out.extend(rows_out)
    return out, problems
