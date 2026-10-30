"""Tests for the PyMuPDF helper layer, using fakes instead of real PDFs."""

from kagaj_core.pdf import iter_pages, open_pdf, text_space_bbox


class FakePage:
    number = 0
    rotation = 0


class FakeDoc:
    page_count = 3

    def __init__(self):
        self.loaded = []

    def load_page(self, number):
        self.loaded.append(number)
        return FakePage()


def test_open_pdf_passes_through_an_open_document():
    doc = FakeDoc()
    assert open_pdf(doc) is doc


def test_iter_pages_honours_max_pages():
    doc = FakeDoc()
    pages = list(iter_pages(doc, max_pages=2))
    assert len(pages) == 2
    assert doc.loaded == [0, 1]


def test_text_space_bbox_is_identity_without_rotation():
    assert text_space_bbox(FakePage(), (1, 2, 3, 4)) == (1.0, 2.0, 3.0, 4.0)


def test_normalize_bbox_orders_coordinates():
    from kagaj_core.pdf import normalize_bbox

    assert normalize_bbox((3, 4, 1, 2)) == (1.0, 2.0, 3.0, 4.0)
