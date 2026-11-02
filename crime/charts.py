"""Geometry-based extraction of the bar charts in CID monthly bulletins.

The charts are vector graphics.  Bars are filled rectangles in the content
stream and the numeric data labels sit just above them, so province groups and
series order can be recovered from coordinates even when the PDF's Devanagari
text layer is badly mangled.  Province names are read from the axis labels and
matched fuzzily; a chart may cover seven provinces (the serious-crime chart in
some editions omits Kathmandu Valley) or eight.

The numeric labels are the source of truth for values.  Bars are used to
locate the plot area, the x-axis baseline, and to verify the reconstruction.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from cidmap import legacy as cidmap_legacy
from cidmap.legacy_identify import LegacyIdentity, identify_font

from .schema import (
    OFFENSES,
    clean_label,
    match_offense_exact,
    match_province,
    parse_int,
)


@dataclass
class Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Bar:
    x0: float
    y0: float
    x1: float
    y1: float
    fill: tuple[float, float, float]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Chart:
    title_raw: str
    series_raw: list[str]
    provinces: list[str]
    values: list[list[int | None]] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    warnings: list[str] = field(default_factory=list)
    baseline: float | None = None
    scale: float | None = None

    @property
    def n_series(self) -> int:
        return len(self.series_raw)

    @property
    def province_sums(self) -> list[int]:
        return [sum(v for v in row if v is not None) for row in self.values]

    @property
    def covered_total(self) -> int:
        return sum(self.province_sums)

    @property
    def series_totals(self) -> list[int]:
        return [sum(row[j] or 0 for row in self.values) for j in range(self.n_series)]


def _is_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def _is_province_row(text: str) -> bool:
    return text.count("प्रदेश") >= 3


def page_spans(page: pymupdf.Page) -> list[Span]:
    spans: list[Span] = []
    identities: dict[str, LegacyIdentity] = {}
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                identity = identities.get(span["font"])
                if identity is None:
                    identity = identify_font(span["font"])
                    identities[span["font"]] = identity
                if identity.family and identity.supported:
                    decoded = cidmap_legacy.decode(text, identity.family)
                    if decoded is not None:
                        text = decoded
                x0, y0, x1, y1 = span["bbox"]
                spans.append(Span(text, x0, y0, x1, y1, float(span["size"])))
    return spans


def _titles(spans: list[Span]) -> list[Span]:
    candidates = [
        s
        for s in spans
        if s.size >= 12.5
        and _is_devanagari(s.text)
        and len(clean_label(s.text)) >= 3
        and parse_int(s.text) is None
        and not _is_province_row(s.text)
    ]
    candidates.sort(key=lambda s: (s.y0, s.x0))
    lines: list[Span] = []
    for span in candidates:
        if lines and abs(span.cy - lines[-1].cy) <= 7:
            prev = lines[-1]
            lines[-1] = Span(
                clean_label(prev.text + " " + span.text),
                min(prev.x0, span.x0),
                min(prev.y0, span.y0),
                max(prev.x1, span.x1),
                max(prev.y1, span.y1),
                max(prev.size, span.size),
            )
        else:
            lines.append(span)

    merged: list[Span] = []
    for line in lines:
        if merged and (line.y0 - merged[-1].y1) <= 30:
            prev = merged[-1]
            merged[-1] = Span(
                clean_label(prev.text + " " + line.text),
                min(prev.x0, line.x0),
                min(prev.y0, line.y0),
                max(prev.x1, line.x1),
                max(prev.y1, line.y1),
                max(prev.size, line.size),
            )
        else:
            merged.append(line)
    return [line for line in merged if not _is_province_row(line.text)]


def _swatch_rows(page: pymupdf.Page) -> list[tuple[float, list[tuple[float, tuple[float, float, float]]]]]:
    rows: list[tuple[float, list[tuple[float, tuple[float, float, float]]]]] = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        fill = drawing.get("fill")
        if fill is None:
            continue
        if not (4 <= rect.width <= 7 and 4 <= rect.height <= 7):
            continue
        cy = (rect.y0 + rect.y1) / 2
        color = tuple(round(float(c), 3) for c in fill)
        for i, (row_y, items) in enumerate(rows):
            if abs(cy - row_y) <= 5:
                items.append(((rect.x0 + rect.x1) / 2, color))
                rows[i] = ((row_y * len(items) + cy) / (len(items) + 1), items)
                break
        else:
            rows.append((cy, [((rect.x0 + rect.x1) / 2, color)]))
    for _, items in rows:
        items.sort()
    return rows


def _all_bar_rects(page: pymupdf.Page) -> list[Bar]:
    bars: list[Bar] = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        if fill is None:
            continue
        color = tuple(round(float(c), 3) for c in fill)
        for item in drawing.get("items", []):
            if item[0] not in ("re", "qu"):
                continue
            rect = item[1]
            if not (3 <= rect.width <= 35 and 0.5 <= rect.height <= 700):
                continue
            bars.append(Bar(rect.x0, rect.y0, rect.x1, rect.y1, color))
    return bars


def _cluster_1d(values: list[float], threshold: float) -> list[list[int]]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups: list[list[int]] = []
    for idx in order:
        if groups and values[idx] - values[groups[-1][-1]] <= threshold:
            groups[-1].append(idx)
        else:
            groups.append([idx])
    return groups


def _group_spans(spans: list[Span], threshold: float = 30.0) -> list[tuple[float, str]]:
    if not spans:
        return []
    groups = _cluster_1d([s.cx for s in spans], threshold)
    out: list[tuple[float, str]] = []
    for group in groups:
        members = sorted((spans[i] for i in group), key=lambda s: (s.y0, s.x0))
        text = clean_label(" ".join(m.text for m in members))
        center = (min(m.x0 for m in members) + max(m.x1 for m in members)) / 2
        out.append((center, text))
    return sorted(out)


def _province_row(spans: list[Span], band_top: float, band_bottom: float) -> list[tuple[float, str]]:
    candidates = [
        s
        for s in spans
        if band_top <= s.y0 <= band_bottom
        and 8.0 <= s.size <= 12.5
        and _is_devanagari(s.text)
        and parse_int(s.text) is None
    ]
    return _group_spans(candidates)


def _legend(spans: list[Span], swatch_rows, region_top: float, region_bottom: float):
    row_ys = [y for y, _ in swatch_rows if region_top <= y <= region_bottom]
    if not row_ys:
        return None, [], []
    legend_y = max(row_ys)
    entries = sorted(
        (x, color) for y, colors in swatch_rows if abs(y - legend_y) <= 5 for x, color in colors
    )
    labels: list[str] = []
    for sx, _ in entries:
        best: Span | None = None
        best_dx = 1e9
        for span in spans:
            if not _is_devanagari(span.text) or parse_int(span.text) is not None:
                continue
            if abs(span.cy - legend_y) > 9 or span.x0 < sx - 1:
                continue
            dx = span.x0 - sx
            if dx < best_dx:
                best_dx = dx
                best = span
        labels.append(clean_label(best.text) if best else "")
    return legend_y, [x for x, _ in entries], labels


def _assign(labels: list[Span], centers: list[float]) -> list[list[Span]]:
    buckets: list[list[Span]] = [[] for _ in centers]
    for span in labels:
        distances = [abs(span.cx - c) for c in centers]
        idx = min(range(len(centers)), key=lambda i: distances[i])
        buckets[idx].append(span)
    for bucket in buckets:
        bucket.sort(key=lambda s: s.cx)
    return buckets


def _tick_indices(spans: list[Span], bars: list[Bar] | None = None) -> set[int]:
    """Indices of axis-tick labels: a right-aligned column left of the plot.

    When bars are available, only columns left of the leftmost bar count, so
    that grouped charts whose series share an x position are not mistaken for
    the y-axis.
    """
    if not spans:
        return set()
    axis_edge = min(b.x0 for b in bars) - 1 if bars else None
    order = sorted(range(len(spans)), key=lambda i: spans[i].x1)
    drop: set[int] = set()
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and spans[order[j]].x1 - spans[order[j - 1]].x1 <= 2.5:
            j += 1
        group = order[i:j]
        if len(group) >= 4:
            ys = [spans[k].cy for k in group]
            if max(ys) - min(ys) > 30:
                if axis_edge is None or max(spans[k].x1 for k in group) <= axis_edge:
                    drop.update(group)
        i = j
    return drop


def extract_charts(page: pymupdf.Page, debug: bool = False) -> list[Chart]:
    spans = page_spans(page)
    titles = _titles(spans)
    swatch_rows = _swatch_rows(page)
    all_bars = _all_bar_rects(page)
    charts: list[Chart] = []

    for t_idx, title in enumerate(titles):
        region_top = title.y1 + 2
        region_bottom = titles[t_idx + 1].y0 - 2 if t_idx + 1 < len(titles) else page.rect.y1
        if region_bottom - region_top < 40:
            continue

        bars = [b for b in all_bars if region_top <= b.y1 <= region_bottom and b.height >= 1.0]
        if not bars:
            continue

        baseline = Counter(round(b.y1, 0) for b in bars).most_common(1)[0][0]
        chart_bars = [b for b in bars if abs(b.y1 - baseline) <= 1.5 and b.height >= 0.5]
        if not chart_bars:
            continue

        legend_y, legend_xs, legend_labels = _legend(spans, swatch_rows, region_top, region_bottom)

        band_top = baseline + 1
        band_bottom = min(legend_y - 8 if legend_y is not None else baseline + 55, baseline + 30)
        province_entries = _province_row(spans, band_top, band_bottom)

        warnings: list[str] = []
        data_spans = [
            s
            for s in spans
            if region_top <= s.cy < baseline - 1
            and parse_int(s.text) is not None
            and len(s.text.strip()) <= 4
        ]
        drop = _tick_indices(data_spans, chart_bars)
        data_spans = [s for i, s in enumerate(data_spans) if i not in drop]

        n_prov = len(province_entries) if len(province_entries) in (7, 8) else None
        if n_prov is None:
            for candidate in (8, 7):
                if data_spans and len(data_spans) % candidate == 0:
                    n_prov = candidate
                    break
        if n_prov is None or not data_spans:
            warnings.append(
                f"cannot determine grid (labels={len(data_spans)}, provinces={len(province_entries)})"
            )
            charts.append(Chart(title.text, legend_labels, [], [],
                                (title.x0, region_top, title.x1, region_bottom), warnings, baseline))
            continue

        if len(data_spans) % n_prov:
            warnings.append(f"{len(data_spans)} labels not divisible by {n_prov} provinces")

        ordered = sorted(data_spans, key=lambda s: s.cx)
        n_series = len(ordered) // n_prov
        if n_series == 0:
            warnings.append("no series found")
            charts.append(Chart(title.text, legend_labels, [], [],
                                (title.x0, region_top, title.x1, region_bottom), warnings, baseline))
            continue
        if len(legend_labels) != n_series:
            warnings.append(f"legend has {len(legend_labels)} entries for {n_series} series")

        if len(province_entries) != n_prov:
            province_entries = [(0.0, "") for _ in range(n_prov)]

        province_ids: list[str] = []
        for idx, (_, text) in enumerate(province_entries):
            matched = match_province(text)
            province_ids.append(matched or f"unknown_{idx}")
            if text and not matched:
                warnings.append(f"unmatched province label: {text!r}")

        matrix: list[list[int | None]] = []
        for p in range(n_prov):
            chunk = ordered[p * n_series:(p + 1) * n_series]
            matrix.append([parse_int(s.text) for s in chunk])

        series_raw = list(legend_labels[:n_series])
        series_raw += [""] * (n_series - len(series_raw))
        if n_series == 1 and not series_raw[0]:
            exact = match_offense_exact(title.text)
            if exact and OFFENSES[exact][2] == "heinous":
                series_raw[0] = OFFENSES[exact][1]
        scale = _estimate_scale(chart_bars, data_spans)

        if debug:
            print(f"  title={title.text!r} provinces={n_prov} series={n_series} "
                  f"labels={len(data_spans)} ticks={len(drop)} scale={scale}")

        charts.append(
            Chart(
                title_raw=title.text,
                series_raw=series_raw,
                provinces=province_ids,
                values=matrix,
                bbox=(title.x0, region_top, title.x1, region_bottom),
                warnings=warnings,
                baseline=baseline,
                scale=scale,
            )
        )
    return charts


def _estimate_scale(bars: list[Bar], labels: list[Span]) -> float | None:
    ratios: list[float] = []
    for bar in bars:
        span = _match_label(bar, labels)
        if span is None:
            continue
        value = parse_int(span.text)
        if value:
            ratios.append(bar.height / value)
    if not ratios:
        return None
    ratios.sort()
    return ratios[len(ratios) // 2]


def _match_label(bar: Bar, labels: list[Span]) -> Span | None:
    best: Span | None = None
    best_d = 1e9
    for span in labels:
        if not (bar.cx - 7 <= span.cx <= bar.cx + 7):
            continue
        if not (bar.y0 - 18 <= span.cy <= bar.y0 + 4):
            continue
        d = abs(span.cx - bar.cx) + abs(span.cy - (bar.y0 - 6))
        if d < best_d:
            best_d = d
            best = span
    return best


def _bar_groups(bars: list[Bar], allowed=(7, 8)) -> list[list[Bar]] | None:
    xs = [b.cx for b in bars]
    for threshold in (26, 24, 28, 22, 30, 20, 32):
        groups = _cluster_1d(xs, threshold)
        if len(groups) not in allowed:
            continue
        spans = [max(xs[i] for i in g) - min(xs[i] for i in g) for g in groups]
        if max(spans) <= 46:
            return sorted(([bars[i] for i in g] for g in groups), key=lambda g: min(b.cx for b in g))
    return None


def _parse_fy_label(text: str) -> str | None:
    from .schema import normalize_digits

    digits = normalize_digits(text)
    tokens = re.findall(r"\d{2,4}", digits)
    if len(tokens) < 2:
        return None
    first, second = tokens[0], tokens[1]
    start = int(first) if len(first) == 4 else 2000 + int(first)
    end = int(second) if len(second) == 4 else 2000 + int(second)
    if not (2070 <= start <= 2100) or end != start + 1:
        return None
    return f"{start}/{str(end)[-2:]}"


def extract_annual(page: pymupdf.Page) -> tuple[list[str], list[str], list[list[int | None]]] | None:
    """Find a multi-year total registered/disposed chart on a page.

    Returns (fiscal_years, series_names, matrix) when found.  The number of
    fiscal years and series varies by edition (some years add a pending line),
    so both are inferred from the axis labels and the count of data labels.
    """
    spans = page_spans(page)
    titles = _titles(spans)
    for t_idx, title in enumerate(titles):
        region_top = title.y1 + 2
        limit = titles[t_idx + 1].y0 - 2 if t_idx + 1 < len(titles) else page.rect.y1
        fy_candidates = [
            s for s in spans if region_top <= s.cy < limit and _parse_fy_label(s.text)
        ]
        rows: dict[int, list[Span]] = {}
        for span in fy_candidates:
            rows.setdefault(round(span.cy / 5), []).append(span)
        if not rows:
            continue
        row_key = max(
            (key for key, members in rows.items() if len({round(m.cx / 3) for m in members}) >= 3),
            default=None,
            key=lambda key: key,
        )
        if row_key is None:
            continue
        by_cx: dict[int, Span] = {}
        for span in rows[row_key]:
            by_cx.setdefault(round(span.cx / 3), span)
        fy_spans = sorted(by_cx.values(), key=lambda s: s.cx)
        if len(fy_spans) < 3:
            continue
        region_bottom = min(s.y0 for s in fy_spans) - 4
        data = [
            s
            for s in spans
            if region_top <= s.cy < region_bottom
            and parse_int(s.text) is not None
            and len(s.text.strip()) <= 5
        ]
        drop = _tick_indices(data)
        data = [s for i, s in enumerate(data) if i not in drop]
        n_fy = len(fy_spans)
        if n_fy < 3 or not data or len(data) % n_fy:
            continue
        n_series = len(data) // n_fy
        if not (2 <= n_series <= 4):
            continue
        data.sort(key=lambda s: s.cx)
        matrix = [
            [parse_int(s.text) for s in data[idx * n_series:(idx + 1) * n_series]]
            for idx in range(n_fy)
        ]
        _, _, legend = _legend(spans, _swatch_rows(page), region_top, page.rect.y1)
        names = _annual_series_names(legend, n_series)
        return [_parse_fy_label(s.text) for s in fy_spans], names, matrix
    return None


def _annual_series_names(labels: list[str], n_series: int) -> list[str]:
    names: list[str | None] = []
    for label in labels[:n_series]:
        if "दर्ता" in label or "दिा" in label:
            names.append("registered")
        elif any(k in label for k in ("बाकी", "बांकी", "बााँकी", "बाकि", "विचार", "वििार", "पेंडि")):
            names.append("pending")
        elif "फछ" in label or "फि" in label or "छयौट" in label or "छर्ौ" in label:
            names.append("disposed")
        else:
            names.append(None)
    defaults = ["registered", "disposed", "pending", "other"]
    for i in range(len(names), n_series):
        names.append(defaults[i] if i < len(defaults) else f"series_{i}")
    return [n or defaults[i] for i, n in enumerate(names)]


def extract_text_chart(
    page: pymupdf.Page, title: Span, n_series: int, n_prov: int = 8
) -> list[list[int]] | None:
    """Recover chart data labels rendered as text over a raster background."""
    words = page.get_text("words")
    province_markers = ("उपत्यका", "कोशी", "मधेश", "बागमिी", "गण्र्की",
                        "लुतम्बनी", "कणााली", "सुदुर", "प्रदेश")
    below = [w for w in words if w[1] > title.y1 + 1]
    province_words = [w for w in below if any(k in w[4] for k in province_markers)]
    if not province_words:
        return None
    province_y = min(w[1] for w in province_words)
    values: list[int] = []
    for w in below:
        if w[1] >= province_y - 2 or w[0] < 72:
            continue
        value = parse_int(w[4])
        if value is not None:
            values.append(value)
    if len(values) < n_series * n_prov:
        return None
    values = values[: n_series * n_prov]
    return [values[i * n_prov:(i + 1) * n_prov] for i in range(n_series)]
