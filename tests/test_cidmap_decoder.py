from cidmap import legacy
from cidmap.decode import layout_lines
from cidmap.decoder import decode_page
from cidmap.legacy_tables import Row, build_table, save_table


class FakePage:
    parent = None

    def __init__(self, spans):
        self._spans = spans

    def get_texttrace(self):
        return self._spans


def _span(font, text, start=0.0, y=10.0):
    return _span_cids(font, text, [100 + index for index in range(len(text))],
                      start=start, y=y)


def _span_cids(font, text, cids, start=0.0, y=10.0):
    chars = []
    x = start
    for char, cid in zip(text, cids):
        chars.append((ord(char), cid, (x, y),
                      (x, y - 10, x + 5, y)))
        x += 5
    return {"font": font, "text": text, "chars": chars,
            "bbox": (start, y - 10, x, y)}


def _glyph(x, y, cid=0):
    return {"c": "x", "cid": cid, "font": "F", "origin": (x, y),
            "bbox": (x, y, x + 1, y + 1)}


def test_layout_lines_reads_columns_by_column():
    lines = [
        [_glyph(0, 0, 1), _glyph(5, 0, 2), _glyph(20, 0, 3)],
        [_glyph(0, 10, 4), _glyph(5, 10, 5),
         _glyph(100, 10, 6), _glyph(105, 10, 7)],
        [_glyph(0, 20, 8), _glyph(5, 20, 9),
         _glyph(100, 20, 10), _glyph(105, 20, 11)],
        [_glyph(100, 30, 12), _glyph(105, 30, 13)],
    ]
    out = layout_lines(lines)
    assert [[glyph["cid"] for glyph in line] for line in out] == [
        [1, 2, 3],
        [4, 5],
        [8, 9],
        [6, 7],
        [10, 11],
        [12, 13],
    ]


def test_preeti_span_is_decoded_by_default():
    page = FakePage([_span("ABCDEE+Preeti", "g]kfn ;/sf/")])
    assert decode_page(page, {}) == "नेपाल सरकार"


def test_legacy_decoding_can_be_disabled():
    page = FakePage([_span("ABCDEE+Preeti", "g]kfn")])
    assert decode_page(page, {}, legacy=False) == "g]kfn"


def test_unsupported_legacy_font_is_left_visible():
    page = FakePage([_span("ABCDEE+Kantipur", "g]kfn")])
    assert decode_page(page, {}) == "g]kfn"


def test_legacy_run_keeps_zero_width_marks_in_source_order():
    page = FakePage([_span("ABCDEE+Preeti", "dxfn]vf")])
    assert decode_page(page, {}) == "महालेखा"


def test_store_mapping_still_resolves_non_legacy_glyphs():
    page = FakePage([
        _span("ABCDEE+Preeti", "g]kfn", start=0),
        _span("Kalimati", "\ufffd", start=50),
    ])
    store = {"fonts": {"Kalimati": {100: "क"}}}
    text = decode_page(page, store)
    assert text.startswith("नेपाल")
    assert text.endswith("क")


def test_external_legacy_table_decodes_by_cid(tmp_path):
    rows = [
        Row("gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क", "test", 2),
        Row("gen-test", "ABCDEF+Gen_Test", 3, "MT3", "्", "test", 3),
        Row("gen-test", "ABCDEF+Gen_Test", 4, "MT4", "", "test", 4),
    ]
    path = tmp_path / "legacy_fonts.json"
    save_table(build_table(rows), path)
    try:
        legacy.reload_table(path)
        page = FakePage([
            _span_cids("ABCDEF+Gen_Test", "abc", [2, 3, 4]),
        ])
        assert decode_page(page, {}) == "क्"
    finally:
        legacy.reload_table()
