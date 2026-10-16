"""Metric-series extraction for DoFE narrative/status reports.

The historical reports (Status 2013/14–2015/17, Country Profile 2019, Nepal
Labour Migration Report 2020) print many "name × fiscal-year" matrices, e.g.::

    Country/Year | 2008/09 | 2009/10 | ... | 2013/14 | Total
    Malaysia     |      15 |     105 | ... |     292 | 1,121

Each matrix measures a **metric** (labour approvals, deaths, disability
compensation, complaints, …) that is named in the table caption, not the data.
This module turns those matrices into long rows tagged with a metric.

Output schema (``migration/series.csv``) is a superset of ``panel.csv``:
``report, source_page, caption, metric, dimension, name, fiscal_year,
gender, count, note``.
"""

import re

from .parser import _to_int

_YEAR = re.compile(r"^\s*(\d{4})\s*[/\-]\s*(\d{2,4})\s*$")

_CAPTION_RE = re.compile(r"(?i)^(table|dataset|annex|box|figure|map)\b")

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
    ("disability_compensation", r"disabilit|compensation"),
    ("complaints", r"complaint"),
    ("assistance", r"assistance|welfare|rescue"),
    ("no_objection_letters", r"no objection|no-objection"),
    ("labour_approval", r"labour permit|labor permit|labour approval|"
                        r"labour migration|labour migrant|migrant worker|"
                        r"recruiting agency|permit|"
                        r"data ?set of \d+ districts"),
    ("migration_stock", r"foreign.?born|census|absentee|population"),
)


def norm_year(cell) -> str:
    """Normalise a fiscal-year token, e.g. '2008/09' or '2008-2009' → '2008/09'."""
    m = _YEAR.match(str(cell or ""))
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    return f"{a}/{b[2:]}" if len(b) == 4 else f"{a}/{b}"


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
    n = str(name or "").strip()
    n = re.sub(r"(?i)\s+total$", "", n).strip()
    return n


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
    unit = "percent" if any(
        "." in str(c) for r in rows[header_idx + 1:] for c in r) else "count"

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
                "count": _to_int(r[j]) if j < len(r) else 0,
                "note": note,
            })
    return out


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
    checks: list[str] = []
    for r in rows[header_idx + 1:]:
        name = _clean_name(r[name_col]) if name_col < len(r) else ""
        if not name or re.match(r"(?i)^(total|grand\s+total)\b", name):
            continue
        vals = sum(_to_int(r[j]) for j in year_cols if j < len(r))
        stated = _to_int(r[total_col]) if total_col < len(r) else 0
        if stated and vals != stated:
            checks.append(f"row_total {name!r} computed={vals} stated={stated}")
    return checks


def extract_series(path: str, report: str = "") -> tuple[list[dict], list[str]]:
    """Extract every name × fiscal-year matrix from one report PDF.

    Captions are propagated across pages so multi-page (continued) tables keep
    the metric/dimension of their header page. Returns ``(rows, problems)``
    where problems are row/column-total mismatches.
    """
    import fitz

    doc = fitz.open(path)
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

            header_idx = None
            year_cols: list[int] = []
            for i, r in enumerate(rows[:5]):
                cols = [j for j, c in enumerate(r) if norm_year(c)]
                if len(cols) >= 2 and cols[0] == 1:
                    header_idx, year_cols = i, cols
                    break
            rows_out = extract_year_matrix(rows, caption, pi + 1, report)
            if rows_out and header_idx is not None and rows_out[0]["unit"] == "count":
                problems.extend(
                    f"{report} p{pi + 1} [{caption[:40]}]: {c}"
                    for c in _verify_matrix(rows, header_idx, year_cols, 0))
            out.extend(rows_out)
    return out, problems
