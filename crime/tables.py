"""Read the national offence table printed in some CID bulletins."""

from __future__ import annotations

import pymupdf

from .charts import Span, page_spans
from .schema import OFFENSES, Issue, clean_label, match_offense_exact, parse_int


def _cell_text(spans: list[Span], bbox: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bbox
    parts = [
        span for span in spans
        if x0 <= span.cx <= x1 and y0 <= span.cy <= y1
    ]
    parts.sort(key=lambda span: (round(span.cy / 5), span.x0))
    return clean_label(" ".join(span.text for span in parts))


def _header_pairs(cells: list[str | None]) -> list[tuple[int, int]] | None:
    pairs = []
    for index in range(1, len(cells) - 1):
        if cells[index] == "शीर्षक" and cells[index + 1] == "जम्मा":
            pairs.append((index, index + 1))
    return pairs or None


def _records_from_table(
    table: pymupdf.table.Table,
    spans: list[Span],
    issue: Issue,
    page_no: int,
    source_url: str,
) -> list[dict]:
    rows: list[list[str | None]] = []
    for row in table.rows:
        rows.append([
            None if cell is None else _cell_text(spans, cell)
            for cell in row.cells
        ])

    header_index = None
    columns: list[tuple[int, int]] | None = None
    for index, cells in enumerate(rows):
        pairs = _header_pairs(cells)
        if pairs is not None:
            header_index = index
            columns = pairs
            break
    if header_index is None or columns is None:
        return []

    title = clean_label(" ".join(
        cell for row in rows[:header_index] for cell in row if cell
    ))
    if "मासिक" not in title:
        return []
    if any(marker in title for marker in ("देख", "सम्म", "अवधि")):
        return []

    records = []
    seen: set[str] = set()
    for cells in rows[header_index + 1:]:
        for label_index, value_index in columns:
            if label_index >= len(cells) or value_index >= len(cells):
                continue
            label = cells[label_index]
            if not label:
                continue
            offense = match_offense_exact(label)
            if offense is None or offense in seen:
                continue
            value = parse_int(cells[value_index] or "")
            if value is None:
                continue
            seen.add(offense)
            records.append({
                "month": issue.month_key,
                "fy": issue.fy,
                "offense": offense,
                "chart_kind": OFFENSES[offense][2],
                "value": value,
                "basis": "monthly",
                "window": "",
                "method": "table_labels",
                "confidence": "high",
                "issue_no": issue.issue_no,
                "page": page_no,
                "source_url": source_url,
            })
    return records


def extract_national_offense_table(
    page: pymupdf.Page,
    issue: Issue,
    page_no: int,
    source_url: str,
) -> list[dict]:
    """Return canonical national offence totals from a monthly table page."""
    try:
        tables = page.find_tables()
    except Exception:
        return []
    spans = page_spans(page)
    for table in tables.tables:
        records = _records_from_table(table, spans, issue, page_no, source_url)
        if records:
            return records
    return []
