"""Tests for redbook_parser.extraction — glyph pipeline + spatial line clustering.

extract_glyphs is tested against a duck-typed fake page (no PyMuPDF needed);
cluster_lines is pure logic on synthetic glyph records.
"""

from redbook_parser.extraction import cluster_lines, extract_glyphs


class FakePage:
    """Emulates the get_texttrace() shape PyMuPDF 1.28 returns."""

    def __init__(self, spans):
        self._spans = spans

    def get_texttrace(self):
        return self._spans


def span(font, chars):
    return {"font": font, "chars": chars}


def char(u, glyph, x, y):
    return (u, glyph, (x, y), (x, y, x + 5, y + 5))


class TestExtractGlyphs:
    def test_maps_texttrace_to_records(self):
        page = FakePage([span("CIDFont+F1", [char(2346, 148, 10.0, 20.0)])])
        out = extract_glyphs(page)
        assert out == [{
            "font": "CIDFont+F1", "base_font": "CIDFont+F1",
            "font_id": "CIDFont+F1", "font_xref": None,
            "font_id_scheme": "unresolved", "cid": 148, "c": "प",
            "origin": (10.0, 20.0), "bbox": (10.0, 20.0, 15.0, 25.0),
        }]

    def test_unmapped_cid_is_fffd_with_glyph_key(self):
        # U+FFFD means unmapped; the CID is the glyph id.
        page = FakePage([span("CIDFont+F1", [char(0xFFFD, 219, 1.0, 1.0)])])
        out = extract_glyphs(page)
        assert out[0]["c"] == "\ufffd"
        assert out[0]["cid"] == 219


class TestClusterLines:
    def _glyph(self, x, y, text="x"):
        return {"c": text, "cid": 0, "font": "F", "origin": (x, y),
                "bbox": (x, y, x + 5, y + 5)}

    def test_groups_by_y_gap(self):
        glyphs = [self._glyph(0, 100), self._glyph(10, 100), self._glyph(0, 140)]
        lines = cluster_lines(glyphs, y_gap=3.0)
        assert len(lines) == 2
        assert [g["origin"] for g in lines[0]] == [(0, 100), (10, 100)]

    def test_sorts_within_line_by_x(self):
        glyphs = [self._glyph(20, 100), self._glyph(5, 100), self._glyph(0, 100)]
        lines = cluster_lines(glyphs, y_gap=3.0)
        xs = [g["origin"][0] for g in lines[0]]
        assert xs == [0, 5, 20]

    def test_empty(self):
        assert cluster_lines([], y_gap=3.0) == []
