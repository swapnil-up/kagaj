"""PaddleOCR adapter with optional confidence and Devanagari filtering.

PaddleOCR is imported on first use, so importing this module is cheap and does
not require the ``ocr`` extra. All public functions return :class:`Word`
objects whose ``bbox`` is in PDF points (unrotated text space) when the input
is a PyMuPDF page, or in image pixels when the input is an array/image.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from . import pdf

RECOGNITION_MODEL = "devanagari_PP-OCRv5_mobile_rec"
DETECTION_MODEL = "PP-OCRv5_mobile_det"
DEFAULT_MIN_SCORE = 0.0

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


@dataclass(frozen=True)
class Word:
    """One OCR box: Unicode text, page-space bbox, and recognition score."""

    text: str
    bbox: tuple[float, float, float, float]
    score: float = 1.0
    page: int | None = None

    def as_tuple(self) -> tuple:
        return (self.text, *self.bbox)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "bbox": list(self.bbox),
            "score": self.score,
            "page": self.page,
        }


def create_engine(**kwargs):
    """Create a PaddleOCR engine configured for Devanagari page OCR."""
    from paddleocr import PaddleOCR

    options = {
        "text_recognition_model_name": RECOGNITION_MODEL,
        "text_detection_model_name": DETECTION_MODEL,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    options.update(kwargs)
    return PaddleOCR(**options)


def devanagari_ratio(text: str) -> float:
    """Fraction of non-whitespace characters that are Devanagari."""
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(_DEVANAGARI_RE.findall(stripped)) / len(stripped)


def is_devanagari(text: str, min_ratio: float = 0.4) -> bool:
    """True when *text* is predominantly Devanagari."""
    return devanagari_ratio(text) >= min_ratio


def ocr_array(engine, image, *, scale: float = 1.0,
              min_score: float = DEFAULT_MIN_SCORE,
              page: int | None = None) -> list[Word]:
    """OCR a rendered image array.

    *scale* converts engine pixel coordinates into the caller's coordinate
    system (use ``dpi / 72`` for a PDF page rendered at *dpi*).
    """
    result = engine.predict(image)
    words: list[Word] = []
    for record in result or []:
        texts = record["rec_texts"]
        scores = record.get("rec_scores")
        boxes = record["rec_boxes"]
        for i, raw in enumerate(texts):
            text = (raw or "").strip()
            score = float(scores[i]) if scores is not None else 1.0
            if not text or score < min_score:
                continue
            box = boxes[i]
            bbox = tuple(float(box[j]) / scale for j in range(4))
            words.append(Word(text=text, bbox=bbox, score=score, page=page))
    return words


def ocr_image(engine, image_path, *, scale: float = 1.0,
              min_score: float = DEFAULT_MIN_SCORE,
              page: int | None = None) -> list[Word]:
    """OCR an image file (PNG/JPEG) and return words in pixel coordinates."""
    from PIL import Image

    import numpy as np

    with Image.open(image_path) as img:
        return ocr_array(engine, np.array(img), scale=scale,
                         min_score=min_score, page=page)


def ocr_page(engine, page, *, dpi: int = pdf.DEFAULT_DPI,
             min_score: float = DEFAULT_MIN_SCORE) -> list[Word]:
    """Render and OCR one PyMuPDF page; bboxes are in unrotated text space."""
    scale = dpi / 72.0
    array = pdf.render_page(page, dpi=dpi)
    number = getattr(page, "number", None)
    words = ocr_array(engine, array, scale=scale, min_score=min_score,
                      page=number)
    return [
        Word(
            text=word.text,
            bbox=pdf.text_space_bbox(page, word.bbox),
            score=word.score,
            page=word.page,
        )
        for word in words
    ]


def words_in_box(words: Iterable[Word], x: float, y: float) -> Word | None:
    """Return the first word whose bbox contains ``(x, y)``."""
    for word in words:
        x0, y0, x1, y1 = word.bbox
        if x0 <= x <= x1 and y0 <= y <= y1:
            return word
    return None


def format_lines(words: Iterable[Word], *, y_gap: float = 4.0) -> list[str]:
    """Join OCR words into reading-order lines (top-to-bottom, left-to-right)."""
    ordered = sorted(words, key=lambda w: (w.page or 0, w.bbox[1], w.bbox[0]))
    lines: list[list[Word]] = []
    for word in ordered:
        if not lines:
            lines.append([word])
            continue
        previous = lines[-1][-1]
        same_page = word.page == previous.page
        close = abs(word.bbox[1] - previous.bbox[1]) <= y_gap
        if same_page and close:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [" ".join(w.text for w in sorted(line, key=lambda w: w.bbox[0]))
            for line in lines]


def engine_from_env(env: dict[str, Any] | None = None):
    """Create an engine, allowing model names to be overridden by environment."""
    import os

    values = os.environ if env is None else env
    kwargs = {}
    rec = values.get("KAGAJ_OCR_REC_MODEL")
    det = values.get("KAGAJ_OCR_DET_MODEL")
    if rec:
        kwargs["text_recognition_model_name"] = rec
    if det:
        kwargs["text_detection_model_name"] = det
    return create_engine(**kwargs)
