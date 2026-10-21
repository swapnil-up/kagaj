import json
import re
from types import SimpleNamespace

from cidmap import cli, review
from cidmap.conflicts import Conflict
from cidmap.review import build_conflicts_html, build_review_html

FONT = "ABCDEF+Kalimati-1"


def _conflict(cid=2, verdict="disagree", font=FONT):
    return Conflict(
        font=font,
        cid=cid,
        store_value="\u0935\u094d\u092f\u092f",
        derive_value="\u0935\u094d\u092f\u092f",
        ocr_candidates=[
            {"word": "\u0935\u094d\u092f\u092a", "count": 2, "pages": [1],
             "bbox": (111, 211, 151, 231)},
            {"word": "\u0935\u094d\u092f\u092f", "count": 1, "pages": [1],
             "bbox": (110, 210, 150, 230)},
        ],
        glyph_bbox=(10, 20, 18, 30),
        word_bbox=(111, 211, 151, 231),
        page=1,
        context="\u27e62\u27e7",
        n_occ=3,
        page_range="p1\u2013p1",
        verdict=verdict,
        agreement={"agree": 1, "disagree": 2, "evidence": 0, "no_ocr": 0},
    )


def test_candidates_are_separate_buttons():
    html = build_conflicts_html([_conflict()])
    words = re.findall(r'class="cand" data-word="([^"]*)"', html)
    assert words == ["\u0935\u094d\u092f\u092a", "\u0935\u094d\u092f\u092f"]
    assert html.count('class="cand"') == 2


def test_export_bootstrap_has_commit_shape():
    html = build_conflicts_html([_conflict()])
    match = re.search(
        r'<script id="cards-data" type="application/json">(.*?)</script>',
        html, re.S)
    assert match
    assert json.loads(match.group(1)) == [
        {"font": FONT, "cid": 2, "decision": "", "undecodable": False}
    ]


def test_workbench_has_filters_progress_and_shortcuts():
    html = build_conflicts_html([_conflict()])
    for element in ("filter-verdict", "filter-font", "filter-cid",
                    "only-undecided", "filled", "export", "import", "reset"):
        assert f'id="{element}"' in html
    assert "1\u20139 pick candidate" in html
    assert "ArrowRight" in html and "ArrowLeft" in html


def test_word_crop_highlights_the_glyph_region():
    crops = {(FONT, 2): {
        "glyph": "data:image/png;base64,AAAA",
        "word": "data:image/png;base64,BBBB",
        "overlay": {"left": "10.0%", "top": "20.0%",
                    "width": "30.0%", "height": "40.0%"},
    }}
    html = build_conflicts_html([_conflict()], crops)
    assert html.count("<img") == 2
    assert 'class="gbox"' in html
    assert "left:10.0%;top:20.0%;width:30.0%;height:40.0%" in html


def test_render_without_pdf_uses_supplied_conflicts():
    conflict = _conflict()
    assert build_review_html(None, {}, {}, conflicts=[conflict]) == \
        build_conflicts_html([conflict])


def test_only_font_filters_cards():
    other = _conflict(cid=3, font="OTHER+Font")
    html = build_review_html(None, {}, {}, conflicts=[_conflict(), other],
                             only_font=FONT)
    assert 'data-cid="2"' in html
    assert 'data-cid="3"' not in html


def test_candidate_words_are_html_escaped():
    conflict = _conflict()
    conflict.ocr_candidates = [{"word": '"\u0915<', "count": 1,
                                "pages": [], "bbox": None}]
    html = build_conflicts_html([conflict])
    assert "data-word=\"&quot;\u0915&lt;\"" in html


def test_build_review_html_renders_crops_without_fitz(monkeypatch):
    calls = []

    def fake_render(doc, page_no, bbox, dpi=review.DPI):
        calls.append((page_no, bbox, dpi))
        return "data:image/png;base64,AAAA"

    monkeypatch.setattr(review, "_render", fake_render)
    html = build_review_html(object(), {}, {},
                             conflicts=[_conflict()])
    assert len(calls) == 2
    assert calls[0] == (1, (4.0, 14.0, 24.0, 36.0), 400)
    assert calls[1] == (1, (103.0, 203.0, 159.0, 239.0), review.DPI)
    assert 'class="gbox"' in html


def test_exported_records_are_accepted_by_commit(tmp_path):
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([
        {"font": FONT, "cid": 2,
         "decision": "व्यय", "undecodable": False},
        {"font": FONT, "cid": 3, "decision": "", "undecodable": True},
    ]), encoding="utf-8")
    store = tmp_path / "store.json"

    assert cli.cmd_commit(SimpleNamespace(
        decisions=str(decisions), store=str(store))) == 0

    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["fonts"][FONT]["2"] == "व्यय"
    assert f"{FONT}\u25713" in saved["undecodable"]


def test_cmd_scan_wires_full_ocr_data_and_census(monkeypatch, tmp_path):
    ocr_path = tmp_path / "ocr.json"
    ocr_path.write_text(json.dumps({"reads": {}, "counts": {}}),
                        encoding="utf-8")
    captured = {}

    def fake_review(doc, store, ocr_data, only_font=None, max_pages=None,
                    census_result=None):
        captured.update(ocr=ocr_data, census=census_result, font=only_font)
        return "<html></html>"

    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(cli, "census", lambda doc, max_pages=None: {})
    monkeypatch.setattr(cli, "build_review_html", fake_review)

    args = SimpleNamespace(
        pdf="fake.pdf", store=str(tmp_path / "store.json"),
        ocr=str(ocr_path), offline=True, font=None, max_pages=None,
        output=str(tmp_path / "review.html"), census=None)
    assert cli.cmd_scan(args) == 0
    assert captured["ocr"] == {"reads": {}, "counts": {}}
    assert captured["census"] == {}
    assert (tmp_path / "review.html").read_text(encoding="utf-8") == \
        "<html></html>"
