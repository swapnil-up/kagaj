"""Table specs, adapters, and optional verification hooks.

A :class:`TableSpec` describes *where* columns live and, optionally, *what must
be true* about the extracted rows. Detection is deliberately not generic: the
caller supplies measured column bands (or grid order), and the adapter turns a
source into row dictionaries. Adapters cover PyMuPDF vector tables, text/OCR
word boxes, and spreadsheet grids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from .devanagari import DEVANAGARI_DIGITS


@dataclass(frozen=True)
class Column:
    """One named horizontal band in PDF points (half-open ``[x0, x1)``)."""

    name: str
    x0: float
    x1: float

    def __post_init__(self):
        if self.x1 <= self.x0:
            raise ValueError(f"column {self.name!r}: x1 must be > x0")

    def contains(self, x: float) -> bool:
        return self.x0 <= x < self.x1


@dataclass(frozen=True)
class Violation:
    """One failed table invariant."""

    kind: str
    message: str
    column: str = ""
    row: int | None = None

    def __str__(self) -> str:
        where = f" row {self.row}" if self.row is not None else ""
        col = f" [{self.column}]" if self.column else ""
        return f"{self.kind}{where}{col}: {self.message}"


@dataclass
class VerificationReport:
    """The result of running a spec's verifier over extracted rows."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        if self.ok:
            return "table verification: ok"
        return f"table verification: {len(self.violations)} violation(s)"


@dataclass(frozen=True)
class TableSpec:
    """Measured column layout plus an optional verifier for extracted rows."""

    name: str
    columns: tuple[Column, ...]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    header_rows: int = 1
    verifier: Callable[[list[dict]], list[Violation]] | None = None

    def __post_init__(self):
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"table {self.name!r}: duplicate column names")
        ordered = sorted(self.columns, key=lambda c: c.x0)
        for previous, column in zip(ordered, ordered[1:]):
            if column.x0 < previous.x1:
                raise ValueError(
                    f"table {self.name!r}: columns {previous.name!r} and "
                    f"{column.name!r} overlap")
        object.__setattr__(self, "columns", tuple(ordered))

    @classmethod
    def from_bands(cls, name: str, bands: Mapping[str, tuple[float, float]] |
                   Iterable[tuple[str, tuple[float, float]]], **kwargs):
        """Build a spec from ``{name: (x0, x1)}`` pairs."""
        items = bands.items() if isinstance(bands, Mapping) else bands
        columns = tuple(Column(label, bounds[0], bounds[1])
                        for label, bounds in items)
        return cls(name=name, columns=columns, **kwargs)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def column_at(self, x: float) -> Column | None:
        for column in self.columns:
            if column.contains(x):
                return column
        return None

    def verify(self, rows: list[dict]) -> VerificationReport:
        if self.verifier is None:
            return VerificationReport()
        return VerificationReport(self.verifier(rows))


def coerce_word(word: Any) -> tuple[str, tuple[float, float, float, float], int | None]:
    """Normalise an OCR word, dict, or tuple into ``(text, bbox, page)``."""
    if hasattr(word, "text") and hasattr(word, "bbox"):
        return word.text, tuple(word.bbox), getattr(word, "page", None)
    if isinstance(word, Mapping):
        return str(word.get("text", "")), tuple(word["bbox"]), word.get("page")
    if isinstance(word, Sequence) and len(word) == 5:
        text, x0, y0, x1, y1 = word
        return str(text), (float(x0), float(y0), float(x1), float(y1)), None
    raise TypeError(f"unsupported word record: {word!r}")


def extract_words(words: Iterable[Any], spec: TableSpec, *,
                  y_tolerance: float = 4.0) -> list[dict]:
    """Group word boxes into rows and assign each word to a column by x."""
    records = [(text, bbox, page) for text, bbox, page in
               (coerce_word(word) for word in words) if text.strip()]
    records.sort(key=lambda r: (r[2] or 0, r[1][1], r[1][0]))

    lines: list[list[tuple[str, tuple[float, float, float, float], int | None]]] = []
    for record in records:
        if not lines:
            lines.append([record])
            continue
        previous = lines[-1][-1]
        same_page = record[2] == previous[2]
        close = abs(record[1][1] - previous[1][1]) <= y_tolerance
        if same_page and close:
            lines[-1].append(record)
        else:
            lines.append([record])

    rows: list[dict] = []
    for line in lines:
        values: dict[str, list[str]] = {name: [] for name in spec.column_names}
        for text, bbox, _ in sorted(line, key=lambda r: r[1][0]):
            column = spec.column_at((bbox[0] + bbox[2]) / 2)
            if column is not None:
                values[column.name].append(text)
        rows.append({name: " ".join(parts).strip()
                     for name, parts in values.items()})
    return rows


def extract_vector(page, spec: TableSpec, *, include_header: bool = False) -> list[dict]:
    """Extract a PyMuPDF vector table whose cells fall inside *spec*'s bands."""
    fitz = _fitz()
    clip = fitz.Rect(spec.bbox) if spec.bbox else None
    found = page.find_tables(clip=clip).tables if clip else page.find_tables().tables
    if not found:
        raise ValueError(f"table {spec.name!r}: no vector table found")
    table = max(found, key=lambda t: _area(t.bbox))
    rows = table.rows
    if not include_header and spec.header_rows:
        rows = rows[spec.header_rows:]
    out: list[dict] = []
    for row in rows:
        values: dict[str, list[str]] = {name: [] for name in spec.column_names}
        for cell in row.cells:
            if cell is None:
                continue
            rect = fitz.Rect(cell)
            text = page.get_textbox(rect).strip()
            if not text:
                continue
            column = spec.column_at((rect.x0 + rect.x1) / 2)
            if column is not None:
                values[column.name].append(text)
        out.append({name: " ".join(parts).strip()
                    for name, parts in values.items()})
    return out


def extract_grid(rows: Iterable[Sequence[Any]], spec: TableSpec, *,
                 include_header: bool = False) -> list[dict]:
    """Map spreadsheet/list rows onto ``spec.column_names`` by position."""
    values = list(rows)
    if not include_header and spec.header_rows:
        values = values[spec.header_rows:]
    out: list[dict] = []
    for row in values:
        item = {}
        for index, name in enumerate(spec.column_names):
            value = row[index] if index < len(row) else ""
            item[name] = "" if value is None else str(value).strip()
        out.append(item)
    return out


def extract_spreadsheet(path, spec: TableSpec, *, sheet: str | None = None,
                        include_header: bool = False) -> list[dict]:
    """Read an ``.xlsx`` sheet with openpyxl and map rows by position."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet] if sheet else workbook.active
        return extract_grid(worksheet.iter_rows(values_only=True), spec,
                            include_header=include_header)
    finally:
        workbook.close()


ADAPTERS: dict[str, Callable[..., list[dict]]] = {
    "vector": extract_vector,
    "words": extract_words,
    "ocr": extract_words,
    "grid": extract_grid,
    "spreadsheet": extract_spreadsheet,
}


def adapter(kind: str) -> Callable[..., list[dict]]:
    """Return a registered adapter by name."""
    try:
        return ADAPTERS[kind]
    except KeyError as error:
        raise ValueError(
            f"unknown table adapter {kind!r}; choose from {sorted(ADAPTERS)}"
        ) from error


def extract(source, spec: TableSpec, *, kind: str = "words", **kwargs) -> list[dict]:
    """Extract rows with the named adapter."""
    return adapter(kind)(source, spec, **kwargs)


def verify(rows: list[dict], spec: TableSpec) -> VerificationReport:
    """Run the spec's verifier over *rows*."""
    return spec.verify(rows)


def sum_to_total(*, value_columns: Sequence[str], total_column: str,
                 label_column: str | None = None,
                 total_labels: Sequence[str] = ("total", "grand total", "जम्मा", "कुल"),
                 tolerance: float = 0.5) -> Callable[[list[dict]], list[Violation]]:
    """Build a verifier checking that detail columns sum to one printed total."""

    def check(rows: list[dict]) -> list[Violation]:
        totals = [i for i, row in enumerate(rows) if _is_total(row, label_column,
                                                               total_labels)]
        if not totals:
            return [Violation("missing-total",
                              f"no row labelled {list(total_labels)!r}")]
        if len(totals) > 1:
            return [Violation("multiple-totals",
                              f"{len(totals)} total rows found")]
        total_index = totals[0]
        detail = [row for i, row in enumerate(rows) if i != total_index]
        computed = sum(_number(row.get(column))
                       for row in detail for column in value_columns)
        stated = _number(rows[total_index].get(total_column))
        if abs(computed - stated) <= tolerance:
            return []
        return [Violation(
            "sum-mismatch",
            f"computed={computed:g} stated={stated:g}",
            column=total_column,
            row=total_index,
        )]

    return check


def row_sums_equal(*, value_columns: Sequence[str], total_column: str,
                   tolerance: float = 0.5,
                   skip_labels: Sequence[str] = ("total", "grand total",
                                                  "जम्मा", "कुल")
                   ) -> Callable[[list[dict]], list[Violation]]:
    """Build a verifier checking each non-total row's columns sum to its total."""

    def check(rows: list[dict]) -> list[Violation]:
        violations: list[Violation] = []
        for index, row in enumerate(rows):
            label = str(row.get(value_columns[0], "")).strip().lower()
            if any(label.startswith(word) for word in skip_labels):
                continue
            computed = sum(_number(row.get(column)) for column in value_columns)
            stated = _number(row.get(total_column))
            if stated == 0 and computed == 0:
                continue
            if abs(computed - stated) > tolerance:
                violations.append(Violation(
                    "row-sum",
                    f"computed={computed:g} stated={stated:g}",
                    column=total_column,
                    row=index,
                ))
        return violations

    return check


def _is_total(row: dict, label_column: str | None,
              labels: Sequence[str]) -> bool:
    if label_column:
        label = str(row.get(label_column, "")).strip().lower()
        return any(label == word or label.startswith(word + " ") for word in labels)
    return False


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().translate(DEVANAGARI_DIGITS)
    text = text.replace(",", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _area(bbox) -> float:
    rect = tuple(bbox)
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    return fitz
