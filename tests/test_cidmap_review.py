import json
import logging
import re
import sys
from types import SimpleNamespace

from kagaj_core.review import ReviewCrop
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
    words = re.findall(r'class="cand" data-value="([^"]*)"', html)
    assert words == ["\u0935\u094d\u092f\u092a", "\u0935\u094d\u092f\u092f"]
    assert html.count('class="cand"') == 2


def test_bootstrap_has_neutral_item_shape():
    html = build_conflicts_html([_conflict()])
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        html, re.S)
    assert match
    assert json.loads(match.group(1)) == [{
        "key": f"{FONT}\u25712", "current": "\u0935\u094d\u092f\u092f",
        "data": {"font": FONT, "font_id": FONT, "cid": 2},
    }]


def test_verdict_is_a_tag_filter():
    html = build_conflicts_html([_conflict()])
    assert 'id="filter-verdict"' in html
    assert 'data-tag="verdict"' in html
    assert 'data-tag-verdict="disagree"' in html
    assert '<span class="badge tag">disagree</span>' in html


def test_workbench_has_filters_progress_and_shortcuts():
    html = build_conflicts_html([_conflict()])
    for element in ("filter-verdict", "filter-group", "filter-search",
                    "only-undecided", "filled", "export", "import", "reset"):
        assert f'id="{element}"' in html
    assert "1\u20139 pick candidate" in html
    assert "ArrowRight" in html and "ArrowLeft" in html


def test_word_crop_highlights_the_glyph_region():
    crops = {(FONT, 2): ReviewCrop(
        glyph="data:image/png;base64,AAAA",
        word="data:image/png;base64,BBBB",
        overlay={"left": "10.0%", "top": "20.0%",
                 "width": "30.0%", "height": "40.0%"},
    )}
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
    assert f'data-key="{FONT}\u25712"' in html
    assert f'data-key="{FONT}\u25713"' not in html


def test_candidate_words_are_html_escaped():
    conflict = _conflict()
    conflict.ocr_candidates = [{"word": '"\u0915<', "count": 1,
                                "pages": [], "bbox": None}]
    html = build_conflicts_html([conflict])
    assert "data-value=\"&quot;\u0915&lt;\"" in html


def test_build_review_html_renders_crops_without_fitz(monkeypatch):
    calls = []

    def fake_crop(doc, *, word=None, glyph=None, **kwargs):
        calls.append((word, glyph))
        return ReviewCrop(
            glyph="data:image/png;base64,AAAA",
            word="data:image/png;base64,BBBB",
            overlay={"left": "10.0%", "top": "20.0%",
                     "width": "30.0%", "height": "40.0%"},
        )

    monkeypatch.setattr(review, "render_review_crop", fake_crop)
    html = build_review_html(object(), {}, {},
                             conflicts=[_conflict()])
    assert calls == [((1, (111, 211, 151, 231)), (1, (10, 20, 18, 30)))]
    assert 'class="gbox"' in html


def test_legacy_records_are_rejected_by_commit(tmp_path):
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([
        {"font": FONT, "cid": 2,
         "decision": "व्यय", "undecodable": False},
    ]), encoding="utf-8")
    store = tmp_path / "store.json"

    assert cli.cmd_commit(SimpleNamespace(
        decisions=str(decisions), store=str(store))) == 1
    assert not store.exists()


def test_neutral_records_are_accepted_by_commit(tmp_path):
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps([
        {"key": f"{FONT}\u25712", "value": "व्यय", "undecodable": False,
         "data": {"font": FONT, "cid": 2}},
        {"key": f"{FONT}\u25713", "value": "", "undecodable": True,
         "data": {"font": FONT, "cid": 3}},
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
                    census_result=None, **kwargs):
        captured.update(ocr=ocr_data, census=census_result, font=only_font,
                        session=kwargs.get("session"))
        return "<html></html>"

    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(
        cli, "census",
        lambda doc, max_pages=None, issues=None: issues or {})
    monkeypatch.setattr(cli, "build_review_html", fake_review)

    args = SimpleNamespace(
        pdf="fake.pdf", store=str(tmp_path / "store.json"),
        ocr=str(ocr_path), offline=True, font=None, max_pages=None,
        output=str(tmp_path / "review.html"), census=None)
    assert cli.cmd_scan(args) == 0
    assert captured["ocr"] == {"reads": {}, "counts": {}}
    assert captured["census"] == {}
    assert captured["session"].startswith("cidmap:")
    assert (tmp_path / "review.html").read_text(encoding="utf-8") == \
        "<html></html>"


def test_word_crop_uses_first_candidate_with_a_bbox(monkeypatch):
    conflict = _conflict()
    conflict.ocr_candidates[0]["bbox"] = None
    calls = []

    def fake_crop(doc, *, word=None, glyph=None, **kwargs):
        calls.append((word, glyph))
        return ReviewCrop(glyph="g", word="w")

    monkeypatch.setattr(review, "render_review_crop", fake_crop)
    crop = review._crops(object(), conflict)

    assert crop.word == "w"
    assert calls == [((1, (110, 210, 150, 230)), (1, (10, 20, 18, 30)))]


def test_crop_failures_are_logged(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("bad page")

    monkeypatch.setattr(review, "render_review_crop", boom)
    with caplog.at_level(logging.WARNING):
        crop = review._crops(object(), _conflict())

    assert crop is None
    assert "crops failed" in caplog.text


def test_review_main_loads_store_through_mappings(monkeypatch, tmp_path):
    captured = {}
    from kagaj_core import pdf as core_pdf
    monkeypatch.setattr(core_pdf, "open_pdf", lambda p: object())
    monkeypatch.setattr(review, "load_store", lambda path: {"loaded": path})

    def fake_review(doc, store, ocr, **kwargs):
        captured["store"] = store
        return "<html></html>"

    monkeypatch.setattr(review, "build_review_html", fake_review)
    out = tmp_path / "review.html"

    assert review.main(["fake.pdf", "--store", "store.json",
                        "-o", str(out)]) == 0
    assert captured["store"] == {"loaded": "store.json"}
    assert out.read_text(encoding="utf-8") == "<html></html>"
