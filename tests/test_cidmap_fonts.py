"""Tests for font identity resolution in cidmap."""

import pytest

from cidmap.fonts import (
    FontAmbiguity,
    cmap_mapping,
    lookup_identity,
    page_fonts,
    source_hash,
)
from cidmap.decode import glyphs
from cidmap.decoder import decode_page


CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
2 beginbfrange
<0001> <0002> [<0935> <093f>]
<0004> <0004> <0930>
endbfrange
endcmap
"""

CMAP_RANGE = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0005> <0007> <0930>
endbfrange
endcmap
"""

CMAP_MULTI = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfchar
<0001> <0930094D>
endbfchar
endcmap
"""

CMAP_UTF16 = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
2 beginbfchar
<0001> <D83DDE00>
<0002> <00610062>
endbfchar
endcmap
"""


class FakePage:
    def __init__(self, doc, xref=10, contents=(11,), spans=None, rotation=0):
        self.parent = doc
        self.xref = xref
        self._contents = list(contents)
        self._spans = spans or []
        self.rotation = rotation

    def get_contents(self):
        return self._contents

    def get_texttrace(self):
        return self._spans


class FakeDoc:
    name = "/definitely/not/a/real.pdf"

    def __init__(self, resources, fonts, streams):
        self.resources = resources
        self.fonts = fonts
        self.streams = streams

    def xref_get_key(self, xref, key):
        if xref in self.resources:
            return self.resources[xref].get(key, ("null", "null"))
        return self.fonts.get(xref, {}).get(key, ("null", "null"))

    def xref_stream(self, xref):
        return self.streams.get(xref, b"")

    def tobytes(self):
        return b"fake-pdf"


def _doc(font_entries, font_props, streams=None):
    resources = {10: {"Resources/Font": (
        "dict", "<< " + " ".join(f"/{name} {xref} 0 R"
                                 for name, xref in font_entries) + " >>")}}
    fonts = {xref: props for xref, props in font_props.items()}
    return FakeDoc(resources, fonts, streams or {})


def test_cmap_hash_is_preferred_and_stable():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP},
    )
    fonts = page_fonts(FakePage(doc), wanted={"Kalimati"})
    identity = fonts["Kalimati"]
    assert identity.font_id_scheme == "cmap-hash"
    assert identity.font_id.startswith("Kalimati@cmap:")
    assert identity.font_xref == 20
    assert lookup_identity(fonts, "KLMNGO+Kalimati") == identity


def test_cmap_mapping_exposes_raw_entries():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP},
    )
    mapping = cmap_mapping(doc, 20)
    assert mapping[1] == (0x0935,)
    assert mapping[2] == (0x093F,)
    assert mapping[4] == (0x0930,)


def test_cmap_multi_codepoint_values_use_utf16_units():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP_MULTI},
    )
    assert cmap_mapping(doc, 20)[1] == (0x0930, 0x094D)


def test_cmap_utf16_surrogate_pairs_and_multi_chars():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP_UTF16},
    )
    mapping = cmap_mapping(doc, 20)
    assert mapping[1] == (0x1F600,)
    assert mapping[2] == (0x61, 0x62)


def test_cmap_bfrange_expands_continuous_unicode():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP_RANGE},
    )
    mapping = cmap_mapping(doc, 20)
    assert mapping[5] == (0x0930,)
    assert mapping[6] == (0x0931,)
    assert mapping[7] == (0x0932,)


def test_missing_cmap_uses_pdf_local_fallback():
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati")}},
    )
    identity = page_fonts(FakePage(doc), wanted={"Kalimati"})["Kalimati"]
    assert identity.font_id_scheme == "pdf-local"
    assert identity.font_id.startswith("Kalimati@src:")
    assert identity.font_id.endswith(":xref20")
    assert len(source_hash(doc)) == 64


def test_two_resources_with_one_base_font_fail_loudly():
    doc = _doc(
        [("F1", 20), ("F2", 21)],
        {20: {"BaseFont": ("name", "/Kalimati")},
         21: {"BaseFont": ("name", "/Kalimati")}},
    )
    with pytest.raises(FontAmbiguity) as exc:
        page_fonts(FakePage(doc), wanted={"Kalimati"})
    assert exc.value.xrefs == [20, 21]


def test_page_fonts_can_skip_ambiguous_fonts():
    doc = _doc(
        [("F1", 20), ("F2", 21), ("F3", 22)],
        {20: {"BaseFont": ("name", "/Kalimati")},
         21: {"BaseFont": ("name", "/Kalimati")},
         22: {"BaseFont": ("name", "/Helvetica")}},
    )
    ambiguous = {}
    fonts = page_fonts(
        FakePage(doc), wanted={"Kalimati", "Helvetica"},
        skip_ambiguous=True, ambiguous=ambiguous)
    assert set(fonts) == {"Helvetica"}
    assert ambiguous == {"Kalimati": [20, 21]}


def test_glyphs_skip_ambiguous_spans_when_allowed():
    spans = [
        {"font": "Kalimati",
         "chars": [(2348, 1, (10.0, 20.0), (10.0, 20.0, 18.0, 32.0))]},
        {"font": "Helvetica",
         "chars": [(65, 2, (20.0, 20.0), (20.0, 20.0, 28.0, 32.0))]},
    ]
    doc = _doc(
        [("F1", 20), ("F2", 21), ("F3", 22)],
        {20: {"BaseFont": ("name", "/Kalimati")},
         21: {"BaseFont": ("name", "/Kalimati")},
         22: {"BaseFont": ("name", "/Helvetica")}},
    )
    issues = []
    out = glyphs(
        FakePage(doc, spans=spans), allow_ambiguous=True, issues=issues)
    assert [glyph["base_font"] for glyph in out] == ["Helvetica"]
    assert issues[0]["kind"] == "FontAmbiguity"
    assert "Kalimati" in issues[0]["message"]


def test_unwanted_ambiguous_fonts_do_not_block_the_page():
    doc = _doc(
        [("F1", 20), ("F2", 21), ("F3", 22)],
        {20: {"BaseFont": ("name", "/Helvetica")},
         21: {"BaseFont": ("name", "/Helvetica")},
         22: {"BaseFont": ("name", "/Kalimati")}},
    )
    fonts = page_fonts(FakePage(doc), wanted={"Kalimati"})
    assert set(fonts) == {"Kalimati"}


def test_glyphs_carry_scoped_font_identity():
    span = {"font": "Kalimati",
            "chars": [(2348, 1, (10.0, 20.0), (10.0, 20.0, 18.0, 32.0))]}
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP},
    )
    out = glyphs(FakePage(doc, spans=[span]))
    assert out[0]["font_id"].startswith("Kalimati@cmap:")
    assert out[0]["base_font"] == "Kalimati"
    assert out[0]["font_xref"] == 20
    assert out[0]["font_id_scheme"] == "cmap-hash"

CMAP_PUNCT = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfchar
<000E> <002C>
endbfchar
endcmap
"""


def test_glyphs_mark_valid_cmap_punctuation_as_mapped():
    span = {"font": "Kalimati",
            "chars": [(44, 14, (10.0, 20.0), (10.0, 20.0, 18.0, 32.0)),
                      (44, 99, (20.0, 20.0), (20.0, 20.0, 28.0, 32.0)),
                      (58, 14, (30.0, 20.0), (30.0, 20.0, 38.0, 32.0))]}
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Kalimati"),
              "ToUnicode": ("xref", "40 0 R")}},
        {40: CMAP_PUNCT},
    )
    page = FakePage(doc, spans=[span])
    out = glyphs(page)
    assert out[0]["c"] == ","
    assert out[0]["mapped"] is True
    assert out[1]["c"] == ","
    assert out[1]["mapped"] is False
    assert out[2]["c"] == ":"
    assert out[2]["mapped"] is False
    assert decode_page(page, {}) == ",\u27e6cid:99\u27e7\u27e6cid:14\u27e7"


def test_simple_font_ascii_artifacts_are_trusted():
    span = {"font": "Arial",
            "chars": [(44, 44, (10.0, 20.0), (10.0, 20.0, 18.0, 32.0))]}
    doc = _doc(
        [("F1", 20)],
        {20: {"BaseFont": ("name", "/Arial"),
              "Subtype": ("name", "/TrueType"),
              "Encoding": ("name", "/WinAnsiEncoding")}},
    )
    page = FakePage(doc, spans=[span])
    out = glyphs(page)
    assert out[0]["mapped"] is False
    assert out[0]["simple_font"] is True
    assert decode_page(page, {}) == ","
