"""OCR cross-check: render pages, read the printed words at unknown-CID spots.

The text layer cannot tell us what an unknown CID *prints* as -- only the glyph
ink can. Rasterising the page and running a Devanagari OCR model gives the
ground-truth word at each unknown glyph position. Those reads feed (a) the
review sheet's candidate guesses and (b) an independent check on derive results.

PaddleOCR is heavy; every page is rasterised once and OCR'd once, and the word
boxes are matched to glyph origins inside this module. Rendering and engine
setup live in :mod:`kagaj_core.pdf` and :mod:`kagaj_core.ocr`.
"""

from __future__ import annotations

from kagaj_core import ocr as core_ocr
from kagaj_core import pdf as core_pdf

from .decode import is_unknown_glyph, glyphs, cluster_lines

RENDER_SCALE = 300 / 72.0  # 300 dpi


def _ocr_engine(**kwargs):
    return core_ocr.create_engine(**kwargs)


def render_page(page):
    return core_pdf.render_page(page, dpi=300)


def ocr_words(engine, page_array):
    """OCR a rendered page array; return [(text, x0pt, y0pt, x1pt, y1pt)]."""
    return [word.as_tuple() for word in core_ocr.ocr_array(
        engine, page_array, scale=RENDER_SCALE)]


def _text_space_bbox(page, bbox):
    """Map a rendered-page word box into unrotated text space."""
    return core_pdf.text_space_bbox(page, bbox)


def _text_space_words(page, words):
    return [(text, *_text_space_bbox(page, (x0, y0, x1, y1)))
            for text, x0, y0, x1, y1 in words]


def word_box_at(words, x_pt, y_pt):
    """Return the full OCR word tuple whose box contains (x, y) in PDF points."""
    for word in words:
        _, x0, y0, x1, y1 = word
        if x0 <= x_pt <= x1 and y0 <= y_pt <= y1:
            return word
    return None


def word_at(words, x_pt, y_pt):
    """Return the OCR word text whose box contains (x, y) in PDF points."""
    word = word_box_at(words, x_pt, y_pt)
    return word[0] if word else None


def cross_check(doc, census_result, max_pages=None, log=None) -> dict:
    """For each unknown (font_id,cid), collect the OCR words it appears in.

    Returns {font: {cid: {word: count}}} plus per-glyph reads
    {font: {cid: [{page, word, bbox, x, y}]}}; ``bbox`` is the printed word
    box in unrotated text space, not the glyph box.
    """
    engine = _ocr_engine()
    reads: dict[str, dict[int, list[dict]]] = {}
    counts: dict[str, dict[int, dict]] = {}

    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))

    for pn in pages:
        page = doc[pn]
        arr = render_page(page)
        words = _text_space_words(page, ocr_words(engine, arr))
        if log:
            log(f"  OCR p{pn + 1}: {len(words)} words")
        for line in cluster_lines(glyphs(page)):
            for g in line:
                if not is_unknown_glyph(g):
                    continue
                font = g["font_id"] or ""
                ox, oy = g["origin"][0], g["origin"][1]
                word = word_box_at(words, ox, oy)
                if not word:
                    continue
                text, x0, y0, x1, y1 = word
                reads.setdefault(font, {}).setdefault(g["cid"], []).append({
                    "page": pn + 1, "word": text, "bbox": (x0, y0, x1, y1),
                    "x": ox, "y": oy})
                cnt = counts.setdefault(font, {}).setdefault(g["cid"], {})
                cnt[text] = cnt.get(text, 0) + 1
    if log:
        nf = sum(len(v) for v in counts.values())
        log(f"  reads for {nf} (font,cid) pairs across {len(counts)} fonts")
    return {"reads": reads, "counts": counts}
