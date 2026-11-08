import shutil
import sys
from pathlib import Path

import pytest

PARLIAMENT = Path(__file__).resolve().parents[1] / "parliament"
sys.path.insert(0, str(PARLIAMENT))

import pdf_to_text as p2t  # noqa: E402


class _FakeImage:
    def __init__(self, index):
        self.index = index


def test_iter_page_images_batches_without_holding_all_pages(monkeypatch):
    calls = []

    monkeypatch.setattr(p2t, "pdfinfo_from_path", lambda path: {"Pages": 25})

    def fake_convert(pdf_path, dpi=200, first_page=None, last_page=None, **kwargs):
        calls.append((first_page, last_page))
        return [_FakeImage(i) for i in range(first_page, last_page + 1)]

    monkeypatch.setattr(p2t, "convert_from_path", fake_convert)

    pages = list(p2t.iter_page_images("doc.pdf", dpi=300, batch_size=10))

    assert [index for index, _ in pages] == list(range(25))
    assert calls == [(1, 10), (11, 20), (21, 25)]
    assert all(last - first + 1 <= 10 for first, last in calls)


@pytest.mark.skipif(shutil.which("pdftoppm") is None,
                    reason="poppler (pdftoppm) not installed")
def test_iter_page_images_real_pdf(monkeypatch, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")

    pdf_path = tmp_path / "ten-pages.pdf"
    doc = pymupdf.open()
    for _ in range(10):
        doc.new_page()
    doc.save(pdf_path)
    doc.close()

    real_convert = p2t.convert_from_path
    calls = []

    def spy(pdf_path, **kwargs):
        calls.append((kwargs.get("first_page"), kwargs.get("last_page")))
        return real_convert(pdf_path, **kwargs)

    monkeypatch.setattr(p2t, "convert_from_path", spy)

    pages = list(p2t.iter_page_images(str(pdf_path), dpi=72, batch_size=4))

    assert [index for index, _ in pages] == list(range(10))
    assert calls == [(1, 4), (5, 8), (9, 10)]


def test_extract_lines_preserves_supplied_page_indices(monkeypatch):
    class _Word:
        score = 0.99

        def __init__(self, text):
            self.text = text
            self.bbox = (10, 20, 30, 40)

    monkeypatch.setattr(p2t.core_ocr, "create_engine", lambda **kwargs: object())
    monkeypatch.setattr(p2t.core_ocr, "ocr_array",
                        lambda engine, arr: [_Word("क")])

    lines = p2t.extract_lines([(5, object()), (7, object())])

    assert [line["page"] for line in lines] == [5, 7]
