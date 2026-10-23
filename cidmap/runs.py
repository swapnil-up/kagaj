"""Group decoded PDF glyphs into visual-order word runs.

The text layer exposes glyphs individually. Shape-run inference needs the
contiguous run a glyph was drawn in, because Devanagari reorders matras, reph,
and ligatures. Runs are kept in visual order; callers compare them with
HarfBuzz output, which is also visual order but carries cluster indices back to
the input text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decode import cluster_lines, is_unknown

_PUNCTUATION = frozenset("()[]{}<>.,;:!?\"'\u201c\u201d\u2018\u2019|/\\")


@dataclass(frozen=True)
class WordRun:
    page: int
    font_id: str
    font_xref: int | None
    glyphs: tuple[dict, ...]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [glyph["bbox"] for glyph in self.glyphs if glyph.get("bbox")]
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    @property
    def has_unknown(self) -> bool:
        return any(is_unknown(glyph.get("c") or "")
                   for glyph in self.glyphs)

    @property
    def unknown_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index, glyph in enumerate(self.glyphs)
            if is_unknown(glyph.get("c") or "")
        )


def _dedup_visual(glyphs, tolerance=1.0):
    out = []
    for glyph in glyphs:
        duplicate = False
        for previous in reversed(out):
            if previous.get("cid") != glyph.get("cid"):
                continue
            px = previous.get("origin", (0.0, 0.0))[0]
            py = previous.get("origin", (0.0, 0.0))[1]
            gx = glyph.get("origin", (0.0, 0.0))[0]
            gy = glyph.get("origin", (0.0, 0.0))[1]
            if abs(px - gx) <= tolerance and abs(py - gy) <= tolerance:
                duplicate = True
                break
        if not duplicate:
            out.append(glyph)
    return out


def _x_span(glyph):
    bbox = glyph.get("bbox") or (0.0, 0.0, 0.0, 0.0)
    return (bbox[0], bbox[2])


def _split_run(line, gap):
    runs = []
    current = []
    previous = None
    for glyph in line:
        if current:
            font = current[-1].get("font_id") or current[-1].get("font")
            same_font = font == (glyph.get("font_id") or glyph.get("font"))
            _, previous_x1 = _x_span(previous)
            current_x0, _ = _x_span(glyph)
            if not same_font or current_x0 - previous_x1 > gap:
                runs.append(current)
                current = []
        current.append(glyph)
        previous = glyph
    if current:
        runs.append(current)
    return runs


def _split_words(glyphs):
    words = []
    current = []
    for glyph in glyphs:
        char = glyph.get("c") or ""
        if char.isspace() or (char in _PUNCTUATION and not is_unknown(char)):
            if current:
                words.append(current)
                current = []
            continue
        current.append(glyph)
    if current:
        words.append(current)
    return words


def word_runs(page_glyphs, *, page=0, y_tol=3.0, gap=2.0) -> list[WordRun]:
    """Return whitespace-delimited visual-order word runs."""
    glyphs = _dedup_visual(page_glyphs)
    out = []
    for line in cluster_lines(glyphs, y_gap=y_tol):
        line = sorted(line, key=lambda glyph: glyph["origin"][0])
        for run in _split_run(line, gap):
            for word in _split_words(run):
                if not word:
                    continue
                first = word[0]
                out.append(WordRun(
                    page=page,
                    font_id=(first.get("font_id") or first.get("font")
                             or "default"),
                    font_xref=first.get("font_xref"),
                    glyphs=tuple(word),
                ))
    return out


def runs_with_unknown(runs) -> list[WordRun]:
    return [run for run in runs if run.has_unknown]
