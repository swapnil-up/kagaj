"""Extraction of the migration_2020 Annex labour-approval tables.

Nepal Labour Migration Report 2020 prints the FY2017/18 and FY2018/19 labour
approvals in annexes that are **not** the live wide template: the country tables
have no S.N. column and use channel typologies specific to that report, and the
district tables are a compact name × Men/Women/Total layout (one channel each).

Output rows use the same schema as ``parser.melt`` (panel.csv).
"""

import re

from .model import GENDERS
from .parser import _to_int

# Country tables: channel keys in column order (each × Male/Female/Total).
CHANNELS_IX = [
    "recruiting_agency", "new_entry", "regularized_entry", "re_entry",
    "total_with_reentry", "total_without_reentry",
]
CHANNELS_X = [
    "recruiting_agency", "individual_new", "individual_regularization",
    "individual_renew", "total_without_renew", "total_with_renew",
]

ANNEX_COUNTRY = {
    "IX": {
        "pages": (144, 147),
        "channels": CHANNELS_IX,
        "with": "total_with_reentry",
        "without": "total_without_reentry",
        "reentry": "re_entry",
        "period_bs": "2074/75",
        "period_ad": ("2017-07-16", "2018-07-16"),
        "title": "LABOUR APPROVAL RECORD FOR FISCAL YEAR 2074.75 (2017.07.16 TO 2018.07.16)",
    },
    "X": {
        "pages": (148, 151),
        "channels": CHANNELS_X,
        "with": "total_with_renew",
        "without": "total_without_renew",
        "reentry": "individual_renew",
        "period_bs": "2074/75",
        "period_ad": ("2017-07-16", "2018-07-16"),
        "title": "LABOUR APPROVAL RECORD FOR FISCAL YEAR 2074.75 (2017.07.16 TO 2018.07.16)",
    },
}

ANNEX_DISTRICT = {
    "XI": {
        "pages": (152, 153), "channel": "recruiting_agency",
        "period_bs": "2074/75", "period_ad": ("2017-07-16", "2018-07-16"),
        "title": "LABOUR APPROVAL VIA RECRUITING AGENCY (2017/2018)",
    },
    "XII": {
        "pages": (154, 155), "channel": "individual",
        "period_bs": "2074/75", "period_ad": ("2017-07-16", "2018-07-16"),
        "title": "LABOUR APPROVAL VIA INDIVIDUAL MODE OF RECRUITMENT (NEW, RENEW & REGULARIZATION)",
    },
    "XIII": {
        "pages": (156, 157), "channel": "recruiting_agency",
        "period_bs": "2075/76", "period_ad": ("2018-07-17", "2019-07-16"),
        "title": "LABOUR APPROVAL VIA RECRUITING AGENCY (2018/2019)",
    },
}

_TOTAL_RE = re.compile(r"(?i)^(total|grand\s+total)\b")


def _base_meta(doc_id, cfg, section, report_url):
    return {
        "doc_id": doc_id,
        "period_bs": cfg["period_bs"],
        "period_ad_start": cfg["period_ad"][0],
        "period_ad_end": cfg["period_ad"][1],
        "doc_type": "annual",
        "section": section,
        "sn": "",
        "verified": True,
        "source_url": report_url,
    }


def _emit(meta, name, channel, gender, count, page):
    return {**meta, "row_type": "detail", "name": name, "channel": channel,
            "gender": gender, "count": count, "source_page": page}


def extract_country_table(rows, cfg, page, report_url, doc_id) -> tuple[list[dict], list[str]]:
    """One country × channel table (2 header rows, no S.N. column)."""
    meta = _base_meta(doc_id, cfg, "country", report_url)
    channels = cfg["channels"]
    components = [c for c in channels if not c.startswith("total")]
    out: list[dict] = []
    problems: list[str] = []
    for r in rows[2:]:
        name = " ".join(str(r[0]).split()) if r and r[0] else ""
        if not name or _TOTAL_RE.match(name):
            continue
        vals = {c: [_to_int(r[1 + i * 3 + g]) for g in range(3)]
                for i, c in enumerate(channels)}
        for c in channels:
            m, f, t = vals[c]
            if m + f != t:
                problems.append(f"{doc_id} p{page} {name} {c}: M+F={m + f} != T={t}")
        for gi in range(3):
            parts = sum(vals[c][gi] for c in components)
            if parts != vals[cfg["with"]][gi]:
                problems.append(f"{doc_id} p{page} {name} {GENDERS[gi]}: "
                                f"components={parts} != with={vals[cfg['with']][gi]}")
            if vals[cfg["with"]][gi] - vals[cfg["reentry"]][gi] != vals[cfg["without"]][gi]:
                problems.append(f"{doc_id} p{page} {name} {GENDERS[gi]}: "
                                f"without_reentry mismatch")
        for c in channels:
            for gi, gender in enumerate(GENDERS):
                out.append(_emit(meta, name, c, gender, vals[c][gi], page))
    return out, problems


def extract_district_table(rows, cfg, page, report_url, doc_id) -> tuple[list[dict], list[str]]:
    """One district × Men/Women/Total table for a single channel."""
    meta = _base_meta(doc_id, cfg, "district", report_url)
    out: list[dict] = []
    problems: list[str] = []
    for r in rows[1:]:
        name = " ".join(str(r[0]).split()) if r and r[0] else ""
        if not name or _TOTAL_RE.match(name):
            continue
        m, f, t = _to_int(r[1]), _to_int(r[2]), _to_int(r[3])
        if m + f != t:
            problems.append(f"{doc_id} p{page} {name}: M+F={m + f} != T={t}")
        for gender, v in zip(GENDERS, (m, f, t)):
            out.append(_emit(meta, name, cfg["channel"], gender, v, page))
    return out, problems


def extract_annex(path: str, report_url: str = "") -> tuple[list[dict], list[str]]:
    """Extract all Annex country + district approval tables from migration_2020."""
    from kagaj_core import pdf as core_pdf

    doc = core_pdf.open_pdf(path)
    out: list[dict] = []
    problems: list[str] = []

    for name, cfg in ANNEX_COUNTRY.items():
        doc_id = f"report2020_annex_{name}"
        p0, p1 = cfg["pages"]
        for pi in range(p0, min(p1 + 1, len(doc))):
            tables = doc[pi - 1].find_tables().tables
            if not tables:
                continue
            rows = tables[0].extract()
            if not rows or "Country" not in str(rows[0][0]):
                continue
            r, p = extract_country_table(rows, cfg, pi, report_url, doc_id)
            out.extend(r)
            problems.extend(p)

    for name, cfg in ANNEX_DISTRICT.items():
        doc_id = f"report2020_annex_{name}"
        p0, p1 = cfg["pages"]
        for pi in range(p0, min(p1 + 1, len(doc))):
            for table in doc[pi - 1].find_tables().tables:
                rows = table.extract()
                if not rows or "District" not in str(rows[0][0]):
                    continue
                r, p = extract_district_table(rows, cfg, pi, report_url, doc_id)
                out.extend(r)
                problems.extend(p)

    # Flag the whole document unverified if any invariant failed (source typos
    # included), matching the live-panel convention.
    bad = {p.split()[0] for p in problems}
    for row in out:
        if row["doc_id"] in bad:
            row["verified"] = False

    return out, problems
