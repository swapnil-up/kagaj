"""Extraction of the pre-approval (पूर्व अनुमति) and institutional (संस्थागत)
labour-approval tables.

Two shapes appear:

* **Pre-approval** documents (#030–#032) — a country summary table
  (``SN | Country | Male | Female | Total``) followed by a country × agency
  detail table (``S.N | Lot No | Country | Name | Male | Female | Total``).
  The summary goes into ``panel.csv`` (``channel="preapproval"``); the detail
  goes into the tracked ``migration/agencies.csv``.
* **Institutional** documents (#027–#028) — a single agency table
  (``S.N | Recruitment Agency | Male | Female | Total``) → ``agencies.csv``.

These PDFs are native text (ASCII tables); no OCR.
"""

import re

from .parser import _to_int

# SN LotNo Country   (detail record start)
_REC = re.compile(r"^(\d+)\s+(\d+)\s+(.+)$")
# a lone numeric SN whose next line is "LotNo Country"
_NUM = re.compile(r"^\d+$")
_LOT_COUNTRY = re.compile(r"^\d+\s+[A-Za-z].*$")
_WINDOW = re.compile(
    r"(?i)\bfrom\b.*?(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")
_TOTAL_RE = re.compile(r"(?i)^(total|grand\s+total)\b")
# institutional record start: "S.N Agency Name"
_REC_INST = re.compile(r"^(\d+)\s+(.+)$")

PREAPPROVAL = {
    "030_95": {"doc_id": "preapproval_030", "period_bs": "2075 असाढ", "doc_type": "single_month"},
    "031_93": {"doc_id": "preapproval_031", "period_bs": "2075 जेठ", "doc_type": "single_month"},
    "032_94": {"doc_id": "preapproval_032", "period_bs": "2073/74", "doc_type": "annual"},
}
INSTITUTIONAL = {
    "027_91": {"doc_id": "institutional_027", "period_bs": "2077/78", "doc_type": "annual"},
    "028_90": {"doc_id": "institutional_028", "period_bs": "2076/77", "doc_type": "annual"},
}

AGENCY_COLUMNS = [
    "measure", "doc_id", "period_bs", "period_ad_start", "period_ad_end",
    "doc_type", "sn", "lot_no", "country", "agency", "male", "female", "total",
    "source_page", "verified", "source_url",
]


def parse_window(text: str) -> tuple[str, str]:
    m = _WINDOW.search(text)
    return (m.group(1), m.group(2)) if m else ("", "")


def _find_summary(rows: list[list]) -> tuple[list[list], list[list]]:
    """Split a page-1 table into (country rows, total rows) after the header."""
    start = None
    for i, r in enumerate(rows):
        cells = [str(c).strip() if c is not None else "" for c in r]
        if len(cells) >= 2 and cells[0] in ("SN", "S.N") and cells[1] == "Country":
            start = i + 1
            break
    if start is None:
        return [], []
    detail, totals = [], []
    for r in rows[start:]:
        cells = [str(c).strip() if c is not None else "" for c in r]
        if len(cells) < 5:
            continue
        name = cells[1]
        if not name:
            continue
        (totals if _TOTAL_RE.match(name) else detail).append(cells)
    return detail, totals


def extract_summary(path: str, cfg: dict, report_url: str):
    """Country summary rows (panel schema, channel='preapproval')."""
    import fitz
    doc = fitz.open(path)
    text = doc[0].get_text()
    ad_start, ad_end = parse_window(text)
    rows, totals = _find_summary(doc[0].find_tables().tables[0].extract())
    meta = {
        "doc_id": cfg["doc_id"], "period_bs": cfg["period_bs"],
        "period_ad_start": ad_start, "period_ad_end": ad_end,
        "doc_type": cfg["doc_type"], "section": "country", "sn": "",
        "channel": "preapproval", "verified": True, "source_url": report_url,
    }
    out: list[dict] = []
    problems: list[str] = []
    sums = [0, 0, 0]
    for cells in rows:
        name, m, f, t = cells[1], _to_int(cells[2]), _to_int(cells[3]), _to_int(cells[4])
        if m + f != t:
            problems.append(f"{cfg['doc_id']} {name}: M+F={m + f} != T={t}")
        for i in range(3):
            sums[i] += (m, f, t)[i]
        for gender, v in zip(("male", "female", "total"), (m, f, t)):
            out.append({**meta, "row_type": "detail", "name": name,
                        "gender": gender, "count": v, "source_page": 1})
    if totals:
        tc = [_to_int(totals[0][2]), _to_int(totals[0][3]), _to_int(totals[0][4])]
        if sums != tc:
            problems.append(f"{cfg['doc_id']} summary total {sums} != printed {tc}")
        for gender, v in zip(("male", "female", "total"), tc):
            out.append({**meta, "row_type": "total", "name": "Total",
                        "gender": gender, "count": v, "source_page": 1})
    if problems:
        for r in out:
            r["verified"] = False
    return out, problems


def _page_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # Rejoin an SN split onto its own line from the "LotNo Country" line.
    merged: list[str] = []
    i = 0
    while i < len(lines):
        if (_NUM.match(lines[i]) and i + 1 < len(lines)
                and _LOT_COUNTRY.match(lines[i + 1])):
            merged.append(f"{lines[i]} {lines[i + 1]}")
            i += 2
        else:
            merged.append(lines[i])
            i += 1
    return merged


def extract_detail(path: str, cfg: dict, report_url: str):
    """Country × agency detail rows (agencies.csv)."""
    import fitz
    doc = fitz.open(path)
    ad_start, ad_end = parse_window(doc[0].get_text())
    recs: list[dict] = []
    for pi in range(len(doc)):
        lines = _page_lines(doc[pi].get_text())
        i = 0
        while i < len(lines):
            m = _REC.match(lines[i])
            if (m and i + 4 < len(lines)
                    and all(lines[i + 2 + k].isdigit() for k in range(3))):
                recs.append({
                    "measure": "preapproval", "doc_id": cfg["doc_id"],
                    "period_bs": cfg["period_bs"], "period_ad_start": ad_start,
                    "period_ad_end": ad_end, "doc_type": cfg["doc_type"],
                    "sn": int(m.group(1)), "lot_no": m.group(2),
                    "country": m.group(3).strip(),
                    "agency": " ".join(lines[i + 1].split()),
                    "male": int(lines[i + 2]), "female": int(lines[i + 3]),
                    "total": int(lines[i + 4]), "source_page": pi + 1,
                    "verified": True, "source_url": report_url,
                })
                i += 5
            else:
                i += 1
    problems: list[str] = []
    for r in recs:
        if r["male"] + r["female"] != r["total"]:
            problems.append(f"{r['doc_id']} sn{r['sn']}: M+F != T")
    max_sn = max((r["sn"] for r in recs), default=0)
    missing = sorted(set(range(1, max_sn + 1)) - {r["sn"] for r in recs})
    if missing:
        problems.append(
            f"{cfg['doc_id']}: {len(missing)} detail rows missing "
            f"(SN {missing[0]}..{missing[-1]}; source pages blank/outlined)")
        for r in recs:
            r["verified"] = False
    return recs, problems


def extract_institutional(path: str, cfg: dict, report_url: str):
    """Agency rows from an institutional (संस्थागत) approval statement."""
    import fitz
    doc = fitz.open(path)
    ad_start, ad_end = parse_window(doc[0].get_text())
    recs: list[dict] = []
    problems: list[str] = []
    for pi in range(len(doc)):
        lines = [ln.strip() for ln in doc[pi].get_text().split("\n") if ln.strip()]
        i = 0
        while i < len(lines):
            m = _REC_INST.match(lines[i])
            if (m and i + 3 < len(lines)
                    and all(lines[i + 1 + k].isdigit() for k in range(3))):
                m1, f1, t1 = int(lines[i + 1]), int(lines[i + 2]), int(lines[i + 3])
                recs.append({
                    "measure": "institutional", "doc_id": cfg["doc_id"],
                    "period_bs": cfg["period_bs"], "period_ad_start": ad_start,
                    "period_ad_end": ad_end, "doc_type": cfg["doc_type"],
                    "sn": int(m.group(1)), "lot_no": "", "country": "",
                    "agency": " ".join(m.group(2).split()),
                    "male": m1, "female": f1, "total": t1, "source_page": pi + 1,
                    "verified": True, "source_url": report_url,
                })
                i += 4
            else:
                i += 1
    for r in recs:
        if r["male"] + r["female"] != r["total"]:
            problems.append(f"{r['doc_id']} sn{r['sn']}: M+F != T")
    max_sn = max((r["sn"] for r in recs), default=0)
    missing = sorted(set(range(1, max_sn + 1)) - {r["sn"] for r in recs})
    if missing:
        problems.append(f"{cfg['doc_id']}: {len(missing)} rows missing "
                        f"(SN gaps: {missing[:5]}...)")
    if problems:
        for r in recs:
            r["verified"] = False
    return recs, problems

