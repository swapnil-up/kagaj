"""Extract violent-crime and total-case series from a CID bulletin PDF."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

from .charts import extract_annual, extract_charts, extract_text_chart
from .normalize import HEINOUS_ORDER, SERIOUS_FULL_ORDER, SERIOUS_MODERN_ORDER, resolve_series, title_kind
from .schema import PROVINCES, Issue, add_months, fiscal_year, month_key, normalize_digits, parse_int


@dataclass
class ViolentRecord:
    month: str
    fy: str
    offense: str
    chart_kind: str
    province: str
    value: int
    basis: str
    window: str
    method: str
    confidence: str
    issue_no: int | None
    page: int
    source_url: str


@dataclass
class MonthlyTotalRecord:
    month: str
    fy: str
    province: str
    value: int
    as_of: str
    issue_no: int | None
    page: int
    source_url: str


@dataclass
class NationalTotalRecord:
    month: str
    fy: str
    value: int
    as_of: str
    method: str
    issue_no: int | None
    page: int
    source_url: str


@dataclass
class AnnualRecord:
    fy: str
    series: str
    value: int | None
    as_of: str
    n_series: int
    issue_no: int | None
    page: int
    source_url: str


@dataclass
class BulletinData:
    issue: Issue
    source_url: str
    pdf: str
    violent: list[ViolentRecord] = field(default_factory=list)
    monthly_totals: list[MonthlyTotalRecord] = field(default_factory=list)
    national_totals: list[NationalTotalRecord] = field(default_factory=list)
    annual: list[AnnualRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "issue": asdict(self.issue),
            "source_url": self.source_url,
            "pdf": self.pdf,
            "violent": [asdict(r) for r in self.violent],
            "monthly_totals": [asdict(r) for r in self.monthly_totals],
            "national_totals": [asdict(r) for r in self.national_totals],
            "annual": [asdict(r) for r in self.annual],
            "warnings": self.warnings,
        }


def _window_key(title: str) -> str:
    match = re.search(r"(20\d\d)\s*[/।.\-]\s*(\d{2,3})", normalize_digits(title))
    if not match:
        return ""
    start = int(match.group(1))
    end = int(match.group(2))
    if end < 100:
        end += 2000
    return f"{start}/{end % 100:02d}"


def _is_violent_chart(title: str, provinces: list[str], kind: str | None, n_series: int) -> bool:
    if kind is None or not provinces or len(provinces) not in (7, 8):
        return False
    if n_series not in (1, 3, 4, 5, 6):
        return False
    if any(k in title for k in ("शीर्षकगत", "सामान्य", "सम्पत्ती", "शुद्धीकरण", "सुवि")):
        return False
    return True


def analyze_pdf(path: str | Path, issue: Issue, source_url: str = "") -> BulletinData:
    doc = pymupdf.open(path)
    data = BulletinData(issue=issue, source_url=source_url, pdf=str(path))
    from .charts import _titles, page_spans

    quarter_covered: set[str] = set()
    for page_no, page in enumerate(doc, start=1):
        page_titles = _titles(page_spans(page))
        quarter_titles = [t for t in page_titles if "त्रैम" in t.text]
        seen_kinds: set[str] = set()
        for chart in extract_charts(page):
            provinces = chart.provinces
            if provinces and any(p.startswith("unknown_") for p in provinces):
                if len(provinces) == 8:
                    provinces = list(PROVINCES)
                elif len(provinces) == 7:
                    provinces = list(PROVINCES[1:])
            canonical, kind, warnings = resolve_series(chart.series_raw, chart.title_raw)
            data.warnings.extend(f"p{page_no}: {w}" for w in warnings)
            n_series = len(canonical)

            title_text = chart.title_raw
            cumulative = (
                "२०७८/०७९" in title_text
                or (
                    ("देख" in title_text or "देतख" in title_text)
                    and ("सम्म" in title_text or "म्म" in title_text)
                )
            )
            if (
                title_kind(chart.title_raw) == kind
                and _is_violent_chart(chart.title_raw, provinces, kind, n_series)
            ):
                seen_kinds.add(kind)
                if len(chart.values) != len(provinces):
                    continue
                for province, row in zip(provinces, chart.values):
                    for offense, value in zip(canonical, row):
                        if offense is None or value is None:
                            continue
                        data.violent.append(
                            ViolentRecord(
                                month=issue.month_key,
                                fy=issue.fy,
                                offense=offense,
                                chart_kind=kind,
                                province=province,
                                value=value,
                                basis="cumulative" if cumulative else "monthly",
                                window=_window_key(title_text) if cumulative else "",
                                method="chart_labels",
                                confidence="high",
                                issue_no=issue.issue_no,
                                page=page_no,
                                source_url=source_url,
                            )
                        )
                continue

            near_quarter = any(
                0 <= chart.bbox[1] - t.y1 < 900 for t in quarter_titles
            )
            if (
                kind is None
                and near_quarter
                and len(provinces) == 8
                and len(chart.values) == 8
                and n_series == 3
            ):
                slots = [add_months(issue.bs_year, issue.bs_month, delta) for delta in (-2, -1, 0)]
                quarter_covered.add(issue.month_key)
                for province, row in zip(provinces, chart.values):
                    for (year, month), value in zip(slots, row):
                        if value is None:
                            continue
                        data.monthly_totals.append(
                            MonthlyTotalRecord(
                                month=month_key(year, month),
                                fy=fiscal_year(year, month),
                                province=province,
                                value=value,
                                as_of=issue.month_key,
                                issue_no=issue.issue_no,
                                page=page_no,
                                source_url=source_url,
                            )
                        )
                continue

            title = chart.title_raw
            total_title = any(
                k in title for k in ("कुल मुद्दा", "कुल मुद्धा", "कुल मुद्धव", "अपराध", "अपराि", "अपरवध")
            ) or (
                any(k in title for k in ("मासिक", "मावसक"))
                and any(k in title for k in ("मुद्दा", "मुद्ध"))
            )
            other_title = any(
                k in title
                for k in ("बैं", "साइबर", "साईबर", "आत्महत", "सम्पत्ती", "सम्पवि", "सम्पति",
                          "शुद्ध", "शुवि", "शुद्दी", "शीर्षक", "लागू", "सवारी")
            )
            if (
                kind is None
                and issue.month_key not in quarter_covered
                and len(provinces) == 8
                and len(chart.values) == 8
                and n_series == 1
                and total_title
                and not other_title
            ):
                for province, row in zip(provinces, chart.values):
                    value = row[0]
                    if value is None:
                        continue
                    data.monthly_totals.append(
                        MonthlyTotalRecord(
                            month=issue.month_key,
                            fy=issue.fy,
                            province=province,
                            value=value,
                            as_of=issue.month_key,
                            issue_no=issue.issue_no,
                            page=page_no,
                            source_url=source_url,
                        )
                    )

        for title in page_titles:
            kind = title_kind(title.text)
            if kind != "heinous" or kind in seen_kinds:
                continue
            matrix = extract_text_chart(page, title, len(HEINOUS_ORDER))
            if matrix is None:
                continue
            seen_kinds.add(kind)
            data.warnings.append(
                f"p{page_no}: heinous labels read from text layer (raster chart background)"
            )
            for idx, province in enumerate(PROVINCES):
                for offense, values in zip(HEINOUS_ORDER, matrix):
                    data.violent.append(
                        ViolentRecord(
                            month=issue.month_key,
                            fy=issue.fy,
                            offense=offense,
                            chart_kind=kind,
                            province=province,
                            value=values[idx],
                            basis="monthly",
                            window="",
                            method="text_labels",
                            confidence="high",
                            issue_no=issue.issue_no,
                            page=page_no,
                            source_url=source_url,
                        )
                    )

        for title in page_titles:
            text = title.text
            if not any(k in text for k in ("मुद्धा", "मुिा", "मनद्धा", "मुद्दा")):
                continue
            if any(k in text for k in ("उपत्यका", "प्रदेशगत", "प्रदेिगत", "प्रदेश")):
                continue
            if not any(k in text for k in ("दर्ता", "दताय", "दताि", "दताा", "दिाा", "दतान", "दताम", "दताण", "दिाय", "दिाा")):
                continue
            if "(" not in text and ")" not in text:
                continue
            candidates = []
            for word in page.get_text("words"):
                x0, y0, y1, token = word[0], word[1], word[3], word[4]
                if x0 < 120 or (y0 + y1) / 2 < 80:
                    continue
                value = parse_int(token)
                if value is None or not 500 <= value <= 20000:
                    continue
                candidates.append(((y0 + y1) / 2, x0, value))
            candidates.sort()
            if len(candidates) < 3:
                continue
            top = sorted(candidates[:3], key=lambda item: item[1])
            months = []
            for delta in (-2, -1, 0):
                year, month = add_months(issue.bs_year, issue.bs_month, delta)
                months.append((year, month))
            for (year, month), (_, _, value) in zip(months, top):
                data.national_totals.append(
                    NationalTotalRecord(
                        month=month_key(year, month),
                        fy=fiscal_year(year, month),
                        value=value,
                        as_of=issue.month_key,
                        method="line_labels",
                        issue_no=issue.issue_no,
                        page=page_no,
                        source_url=source_url,
                    )
                )

        annual = extract_annual(page)
        if annual and not data.annual:
            years, series_names, matrix = annual
            for idx, fy in enumerate(years):
                for series_name, value in zip(series_names, matrix[idx]):
                    data.annual.append(
                        AnnualRecord(
                            fy=fy,
                            series=series_name,
                            value=value,
                            as_of=issue.month_key,
                            n_series=len(series_names),
                            issue_no=issue.issue_no,
                            page=page_no,
                            source_url=source_url,
                        )
                    )
    dedup: dict[tuple[str, str], MonthlyTotalRecord] = {}
    for record in data.monthly_totals:
        dedup[(record.month, record.province)] = record
    data.monthly_totals = list(dedup.values())
    national_dedup: dict[str, NationalTotalRecord] = {}
    for record in data.national_totals:
        national_dedup[record.month] = record
    data.national_totals = list(national_dedup.values())
    return data


def write_json(data: BulletinData, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{data.issue.month_key}.json"
    path.write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
