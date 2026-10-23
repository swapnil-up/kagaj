"""Tests for the shared, dependency-light review harness."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from kagaj_core.review import (
    ReviewCandidate,
    ReviewCrop,
    ReviewItem,
    parse_decisions,
    render_review,
    storage_key,
)

ROOT = Path(__file__).resolve().parents[1]


def _item(**overrides):
    values = dict(
        key="42",
        label="CID 42",
        group="FontA",
        context="\u0915\u27e642\u27e7",
        current="\u0915",
        candidates=(
            ReviewCandidate(value="\u0916", count=3),
            ReviewCandidate(value="\u0917", label="\u0917 (ga)", count=1,
                            detail="from OCR"),
        ),
        crops=(
            ReviewCrop(glyph="data:image/png;base64,AAAA",
                       word="data:image/png;base64,BBBB",
                       overlay={"left": "10%", "top": "20%",
                                "width": "30%", "height": "40%"}),
        ),
        data={"cid": 42},
    )
    values.update(overrides)
    return ReviewItem(**values)


def _bootstrap(html):
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        html, re.S)
    assert match
    return json.loads(match.group(1))


def test_bootstrap_carries_key_current_and_data():
    html = render_review([_item()], session="test")
    assert _bootstrap(html) == [
        {"key": "42", "current": "\u0915", "data": {"cid": 42}}
    ]


def test_candidates_are_buttons_with_values_and_counts():
    html = render_review([_item()], session="test")
    buttons = re.findall(
        r'<button type="button" class="cand" data-value="([^"]*)"'
        r' data-index="(\d+)" title="([^"]*)">(.*?)</button>', html, re.S)
    assert [b[0] for b in buttons] == ["\u0916", "\u0917"]
    assert [b[1] for b in buttons] == ["1", "2"]
    assert "\u0917 (ga)" in buttons[1][3]
    assert "\u00d73" in buttons[0][3]


def test_filters_progress_and_keyboard_help_are_present():
    html = render_review([_item()], session="test")
    for element in ("filter-group", "filter-search", "only-undecided",
                    "filled", "visible", "export", "import", "reset"):
        assert f'id="{element}"' in html
    assert "1\u20139 pick candidate" in html
    assert "ArrowRight" in html and "ArrowLeft" in html
    assert "inconsistent glyph shapes" in html
    assert "not when it appears in different words" in html


def test_tag_filters_render_options_badges_and_card_attributes():
    items = [
        _item(tags={"verdict": "disagree"}),
        _item(key="43", label="CID 43", tags={"verdict": "agree"}),
    ]
    html = render_review(items, session="test", tag_filters=("verdict",))
    assert 'id="filter-verdict"' in html
    assert 'data-tag="verdict"' in html
    assert '<option value="agree">' in html
    assert '<option value="disagree">' in html
    assert 'data-tag-verdict="disagree"' in html
    assert '<span class="badge tag">agree</span>' in html


def test_tag_filter_is_omitted_when_no_values_exist():
    html = render_review([_item()], session="test", tag_filters=("verdict",))
    assert 'id="filter-verdict"' not in html


def test_tag_filter_values_are_escaped_and_sanitised():
    item = _item(tags={"verdict": '"><script>x</script>'})
    html = render_review([item], session="test", tag_filters=("verdict",))
    assert 'data-tag-verdict="&quot;&gt;&lt;script&gt;x&lt;/script&gt;"' in html
    item = _item(tags={"bad key": "v"})
    html = render_review([item], session="test", tag_filters=("bad key",))
    assert 'id="filter-bad_key"' in html
    assert 'data-tag-bad_key="v"' in html


def test_export_name_appears_in_label_and_script():
    html = render_review([_item()], session="test", export_name="my.json")
    assert "Export my.json" in html
    assert 'const EXPORT_NAME="my.json";' in html


def test_group_options_are_rendered():
    items = [_item(), _item(key="43", label="CID 43", group="FontB")]
    html = render_review(items, session="test")
    options = re.findall(r'<option value="([^"]*)">', html)
    assert options == ["all", "FontA", "FontB"]


def test_storage_key_is_session_specific_and_stable():
    a = storage_key("redbook:/tmp/a.pdf")
    b = storage_key("redbook:/tmp/b.pdf")
    assert a == storage_key("redbook:/tmp/a.pdf")
    assert a != b
    assert storage_key("cidmap:/tmp/a.pdf") != storage_key("redbook:/tmp/a.pdf")


def test_storage_key_is_embedded_per_session():
    html_a = render_review([_item()], session="redbook:/tmp/a.pdf")
    html_b = render_review([_item()], session="redbook:/tmp/b.pdf")
    key_a = storage_key("redbook:/tmp/a.pdf")
    key_b = storage_key("redbook:/tmp/b.pdf")
    assert json.dumps(key_a) in html_a
    assert json.dumps(key_b) not in html_a
    assert json.dumps(key_b) in html_b


def test_crops_render_src_strings_and_overlay():
    html = render_review([_item()], session="test")
    assert 'src="data:image/png;base64,AAAA"' in html
    assert 'src="data:image/png;base64,BBBB"' in html
    assert 'class="gbox" style="left:10%;top:20%;width:30%;height:40%;"' in html
    assert 'loading="lazy"' in html


def test_crop_caption_and_input_placeholder_are_rendered():
    item = _item(
        input_placeholder="full printed word",
        crops=(ReviewCrop(glyph="g.png", caption="p5 \u00b7 occurrence 1/2"),),
    )
    html = render_review([item], session="test")
    assert 'class="sample"' in html
    assert 'class="cap">p5 \u00b7 occurrence 1/2</div>' in html
    assert 'placeholder="full printed word"' in html


def test_asset_paths_are_accepted_as_src():
    item = _item(crops=(ReviewCrop(glyph="crops/42.png",
                                  word="crops/42-word.png"),))
    html = render_review([item], session="test")
    assert 'src="crops/42.png"' in html
    assert 'src="crops/42-word.png"' in html


def test_values_labels_contexts_and_candidates_are_escaped():
    item = _item(
        label='CID <42> "x"',
        group="A&B",
        context="<script>alert(1)</script>",
        current='"quoted"',
        candidates=(ReviewCandidate(value='"evil<',
                                    label="<b>evil</b>&",
                                    detail='" onmouseover="x'),),
    )
    html = render_review([item], session="test")
    assert "CID &lt;42&gt; &quot;x&quot;" in html
    assert "A&amp;B" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&quot;quoted&quot;" in html
    assert 'data-value="&quot;evil&lt;"' in html
    assert "&lt;b&gt;evil&lt;/b&gt;&amp;" in html
    assert "&quot; onmouseover=&quot;x" in html


def test_bootstrap_cannot_break_out_of_script_tag():
    item = _item(data={"thing": "</script><script>alert(1)</script>"})
    html = render_review([item], session="test")
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        html, re.S)
    assert match
    assert "</script><script>alert(1)" not in match.group(1)
    assert json.loads(match.group(1))[0]["data"]["thing"] == \
        "</script><script>alert(1)</script>"


def test_all_template_placeholders_are_replaced():
    html = render_review([_item()], session="test",
                         tag_filters=("verdict",))
    for token in ("__TITLE__", "__COUNT__", "__CARDS__", "__GROUPS__",
                  "__TAG_FILTERS__", "__GROUP_LABEL__",
                  "__SEARCH_PLACEHOLDER__", "__BOOTSTRAP__",
                  "__STORAGE_KEY__", "__EXPORT_LABEL__", "__EXPORT_NAME__",
                  "__HELP__", "__NOTICE__", "__EMPTY__"):
        assert token not in html


def test_empty_review_has_empty_state():
    html = render_review([], session="test")
    assert "No items to review." in html
    assert '<span id="filled">0</span> / 0 decided' in html
    assert _bootstrap(html) == []


def test_export_supports_undecodable_and_legacy_import_conversion():
    records = parse_decisions(
        [{"key": "42", "value": "\u0915", "undecodable": False,
          "data": {"cid": 42}}])
    assert records[0].to_record() == {
        "key": "42", "value": "\u0915", "undecodable": False,
        "inconsistent": False, "note": "", "data": {"cid": 42},
    }

    def legacy(record):
        return {"key": str(record["cid"]), "value": record["correct"],
                "data": {"cid": record["cid"]}}

    converted = parse_decisions([{"cid": 7, "correct": "\u0916"}],
                                convert=legacy)
    assert converted[0].key == "7"
    assert converted[0].value == "\u0916"


def test_renderer_is_stdlib_only():
    code = (
        "import sys; import kagaj_core.review; "
        "assert 'fitz' not in sys.modules; "
        "assert 'numpy' not in sys.modules; "
        "assert 'paddleocr' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_review_item_is_immutable():
    item = _item()
    with pytest.raises(Exception):
        item.key = "new"
