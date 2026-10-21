"""HTML decision sheet: review conflict records, crop evidence, export decisions.

Each card is one :class:`cidmap.conflicts.Conflict`: current store/derive values,
verdict, census context, a glyph crop, and the printed-word crop with the glyph
region highlighted. OCR candidates are separate buttons, never concatenated.

Decisions persist in ``localStorage`` and export as
``[{font, cid, decision, undecodable}]``, the shape accepted by
``cidmap commit``.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

from .conflicts import Conflict, build_conflicts
from .decode import census

DPI = 300
_MARGIN = 8.0


def _render(doc, page_no, bbox, dpi=DPI):
    """Render a PDF-point region to a base64 PNG."""
    import fitz
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(bbox).normalize())
    if pix.colorspace.name not in ("RGB", fitz.csRGB.name):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return "data:image/png;base64," + base64.b64encode(
        pix.tobytes("png")).decode()


def _pad(bbox, pad):
    return (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)


def _overlay(outer, inner):
    width = max(outer[2] - outer[0], 1e-6)
    height = max(outer[3] - outer[1], 1e-6)
    left = (inner[0] - outer[0]) / width * 100
    top = (inner[1] - outer[1]) / height * 100
    right = (inner[2] - outer[0]) / width * 100
    bottom = (inner[3] - outer[1]) / height * 100
    left, right = max(0.0, min(100.0, left)), max(0.0, min(100.0, right))
    top, bottom = max(0.0, min(100.0, top)), max(0.0, min(100.0, bottom))
    return {"left": f"{left:.1f}%", "top": f"{top:.1f}%",
            "width": f"{max(0.0, right - left):.1f}%",
            "height": f"{max(0.0, bottom - top):.1f}%"}


def _crops(doc, conflict: Conflict) -> dict:
    crop = {}
    if conflict.glyph_bbox and conflict.page:
        try:
            crop["glyph"] = _render(
                doc, conflict.page, _pad(conflict.glyph_bbox, 6), dpi=400)
        except Exception:
            pass
    word_bbox = conflict.word_bbox or conflict.glyph_bbox
    if not word_bbox:
        return crop
    top = conflict.ocr_candidates[0] if conflict.ocr_candidates else {}
    word_page = (top.get("pages") or [conflict.page])[0]
    if not word_page:
        return crop
    outer = _pad(word_bbox, _MARGIN)
    try:
        crop["word"] = _render(doc, word_page, outer)
    except Exception:
        return crop
    if conflict.glyph_bbox and word_page == conflict.page:
        crop["overlay"] = _overlay(outer, conflict.glyph_bbox)
    return crop


def _h(text) -> str:
    return html.escape("" if text is None else str(text))


def _candidate_buttons(candidates: list[dict]) -> str:
    buttons = []
    for candidate in candidates:
        pages = candidate.get("pages") or []
        title = f"{candidate['count']} occurrence(s)"
        if pages:
            title += f" on p{pages[0]}\u2013p{pages[-1]}"
        buttons.append(
            f'<button type="button" class="cand" data-word="{_h(candidate["word"])}"'
            f' title="{_h(title)}">{_h(candidate["word"])}'
            f'<i>\u00d7{candidate["count"]}</i></button>')
    return "".join(buttons) or '<span class="none">no OCR candidates</span>'


def _card(conflict: Conflict, crop: dict) -> str:
    current = conflict.store_value or conflict.derive_value
    glyph = (f'<img class="g" src="{crop["glyph"]}" alt="glyph crop">'
             if crop.get("glyph") else '<span class="none">no glyph crop</span>')
    if crop.get("word"):
        overlay = crop.get("overlay")
        box = (f'<span class="gbox" style="left:{overlay["left"]};top:{overlay["top"]};'
               f'width:{overlay["width"]};height:{overlay["height"]}"></span>'
               if overlay else "")
        word = (f'<span class="w-wrap"><img class="w" src="{crop["word"]}" '
                f'alt="word crop">{box}</span>')
    else:
        word = '<span class="none">no word crop</span>'
    store = _h(conflict.store_value or "\u2014")
    derive = _h(conflict.derive_value or "\u2014")
    placeholder = _h(current or "\u2014")
    return f"""
<div class="card verdict-{_h(conflict.verdict)}" data-font="{_h(conflict.font)}"
     data-cid="{conflict.cid}" data-verdict="{_h(conflict.verdict)}"
     data-store="{_h(current)}" tabindex="0">
  <div class="h"><b>CID {conflict.cid}</b>
    <span class="badge">{_h(conflict.verdict)}</span></div>
  <div class="meta">{_h(conflict.font or "(no font)")} \u00b7 n={conflict.n_occ}
    \u00b7 {_h(conflict.page_range)} \u00b7 p{_h(conflict.page)}</div>
  <div class="show">{glyph}{word}</div>
  <div class="ctx">{_h(conflict.context)}</div>
  <div class="values">store: <b>{store}</b> \u00b7 derive: <b>{derive}</b></div>
  <div class="cands">{_candidate_buttons(conflict.ocr_candidates)}</div>
  <div class="fill">
    <input class="value" placeholder="{placeholder}">
    <label class="undec"><input type="checkbox" class="undec-toggle"> undecodable</label>
  </div>
  <div class="stats">agree {conflict.agreement['agree']} \u00b7
    disagree {conflict.agreement['disagree']} \u00b7
    evidence {conflict.agreement['evidence']} \u00b7
    no-ocr {conflict.agreement['no_ocr']}</div>
</div>"""


def build_conflicts_html(conflicts: list[Conflict], crops: dict | None = None) -> str:
    """Render conflict records to the workbench HTML (no PDF/OCR needed)."""
    crops = crops or {}
    cards = "".join(_card(c, crops.get((c.font, c.cid), {}))
                    for c in conflicts)
    fonts = sorted({c.font for c in conflicts})
    font_options = "".join(
        f'<option value="{_h(font)}">{_h(font or "(no font)")}</option>'
        for font in fonts)
    bootstrap = json.dumps(
        [{"font": c.font, "cid": c.cid, "decision": "", "undecodable": False}
         for c in conflicts], ensure_ascii=False).replace("</", "<\\/")

    return (_TEMPLATE
            .replace("__CARDS__", cards)
            .replace("__BOOTSTRAP__", bootstrap)
            .replace("__FONT_OPTIONS__", font_options)
            .replace("__TOTAL__", str(len(conflicts))))


def build_review_html(doc, store, ocr_data, only_font=None, max_samples=2,
                      max_pages=None, *, conflicts=None,
                      census_result=None) -> str:
    if conflicts is None:
        if census_result is None and doc is not None:
            census_result = census(doc, max_pages=max_pages)
        conflicts = build_conflicts(
            doc, store, ocr_data, census_result=census_result)
    if only_font:
        conflicts = [c for c in conflicts if c.font == only_font]
    crops = {}
    if doc is not None:
        for conflict in conflicts:
            try:
                crops[(conflict.font, conflict.cid)] = _crops(doc, conflict)
            except Exception:
                crops[(conflict.font, conflict.cid)] = {}
    return build_conflicts_html(conflicts, crops)


_TEMPLATE = """<!DOCTYPE html><html lang="ne"><head><meta charset="utf-8">
<title>CID mapping review</title>
<style>
body{font-family:sans-serif;background:#13161b;color:#e6e6e6;margin:0;padding:16px}
#toolbar,#filters{position:sticky;top:0;z-index:5;background:#13161bee;padding:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#toolbar{top:0}#filters{top:48px;border-bottom:1px solid #2c333d;margin-bottom:12px}
button,input,select{font:inherit}
button{padding:6px 10px;border:1px solid #3d4a5a;border-radius:6px;background:#1b2027;color:#e6e6e6;cursor:pointer}
button.primary{background:#2f81f7;border-color:#2f81f7;color:#fff;font-weight:700}
label.import{padding:6px 10px;border:1px solid #3d4a5a;border-radius:6px;background:#1b2027;color:#e6e6e6;cursor:pointer}
#progress{color:#9aa7b8}
.help{color:#7f8c9d;font-size:.82em;margin:0 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:#1b2027;border:1px solid #2c333d;border-left:4px solid #555;border-radius:8px;padding:10px 12px;outline:none}
.card:focus{box-shadow:0 0 0 2px #2f81f7}
.card[hidden]{display:none}
.card.decided{border-top:1px solid #2f9e44}
.card.verdict-agree{border-left-color:#2f9e44}.card.verdict-disagree{border-left-color:#c92a2a}
.card.verdict-missing{border-left-color:#e67700}.card.verdict-no-ocr{border-left-color:#777}
.card.verdict-tie{border-left-color:#b78e3b}
.h{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.badge{font-size:.75em;text-transform:uppercase;color:#9aa7b8}
.meta{color:#7f8c9d;font-size:.8em;margin-top:2px;word-break:break-all}
.show{display:flex;gap:8px;margin:8px 0;align-items:flex-start;flex-wrap:wrap}
.show img.g{border:2px solid #2f81f7;background:#fff;max-height:90px}
.w-wrap{position:relative;display:inline-block;background:#fff}
.w-wrap img.w{display:block;border:1px solid #3a4350;max-height:140px}
.gbox{position:absolute;border:2px solid #f85149;background:#f8514926;pointer-events:none;box-sizing:border-box}
.ctx{color:#fff;font-family:'Noto Sans Devanagari',sans-serif;font-size:1.2em;line-height:1.5;word-break:break-word}
.values{color:#c8d2e0;font-size:.9em;margin-top:4px;font-family:'Noto Sans Devanagari',sans-serif}
.cands{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.cand{font-family:'Noto Sans Devanagari',sans-serif;font-size:1.1em}
.cand i{color:#7f8c9d;font-style:normal;font-size:.7em;margin-left:4px}
.fill{display:flex;gap:8px;align-items:center;margin-top:6px}
input.value{flex:1;padding:6px 8px;font-size:1.2em;background:#0f1216;color:#fff;border:1px solid #3d4a5a;border-radius:4px;font-family:'Noto Sans Devanagari',sans-serif}
.undec{color:#8b98a8;font-size:.75em;white-space:nowrap}
.stats{color:#7f8c9d;font-size:.75em;margin-top:6px}
.none{color:#666;font-size:.8em}
</style></head><body>
<div id="toolbar">
  <button class="primary" id="export">Export decisions.json</button>
  <label class="import">Import<input id="import" type="file" accept="application/json" hidden></label>
  <button id="reset">Reset</button>
  <span id="progress"><span id="filled">0</span> / __TOTAL__ decided</span>
</div>
<div id="filters">
  <select id="filter-verdict">
    <option value="all">all verdicts</option>
    <option value="missing">missing</option>
    <option value="disagree">disagree</option>
    <option value="agree">agree</option>
    <option value="no-ocr">no-ocr</option>
    <option value="tie">tie</option>
  </select>
  <select id="filter-font"><option value="all">all fonts</option>__FONT_OPTIONS__</select>
  <input id="filter-cid" type="search" placeholder="CID search">
  <label><input id="only-undecided" type="checkbox"> only undecided</label>
  <span id="visible"></span>
</div>
<p class="help">Keys: 1\u20139 pick candidate \u00b7 Enter accept + next \u00b7 K keep store \u00b7 U undecodable \u00b7 S skip \u00b7 \u2190/\u2192 previous/next</p>
<div class="cards">__CARDS__</div>
<script id="cards-data" type="application/json">__BOOTSTRAP__</script>
<script>
const KEY='kagaj.cidmap.decisions.v1';
const cards=Array.from(document.querySelectorAll('.card'));
const inputOf=c=>c.querySelector('.value');
const undecOf=c=>c.querySelector('.undec-toggle');
const keyOf=c=>c.dataset.font+'\u2571'+c.dataset.cid;
function isDecided(c){return !!inputOf(c).value.trim()||undecOf(c).checked;}
function collect(){return cards.map(c=>({font:c.dataset.font,cid:Number(c.dataset.cid),
  decision:inputOf(c).value.trim(),undecodable:undecOf(c).checked}));}
function persist(){const o={};collect().forEach(d=>{if(d.decision||d.undecodable)o[d.font+'\u2571'+d.cid]=d;});
  try{localStorage.setItem(KEY,JSON.stringify(o));}catch(e){}}
function updateProgress(){let n=0;cards.forEach(c=>{if(isDecided(c))n++;c.classList.toggle('decided',isDecided(c));});
  document.getElementById('filled').textContent=n;}
function applyFilters(){const v=document.getElementById('filter-verdict').value;
  const f=document.getElementById('filter-font').value;
  const q=document.getElementById('filter-cid').value.trim();
  const und=document.getElementById('only-undecided').checked;let shown=0;
  cards.forEach(c=>{const ok=(v==='all'||c.dataset.verdict===v)&&(f==='all'||c.dataset.font===f)&&
    (!q||c.dataset.cid.includes(q))&&(!und||!isDecided(c));c.hidden=!ok;if(ok)shown++;});
  document.getElementById('visible').textContent=shown+' shown';}
function refresh(){updateProgress();applyFilters();}
function visibleCards(){return cards.filter(c=>!c.hidden);}
function activeCard(){const el=document.activeElement;return el&&el.closest?el.closest('.card'):null;}
function focusCard(c){if(!c)return;c.focus({preventScroll:true});c.scrollIntoView({block:'center'});}
function move(dir){const v=visibleCards();if(!v.length)return;const cur=activeCard();let i=v.indexOf(cur);
  i=i<0?(dir>0?0:v.length-1):(i+dir+v.length)%v.length;focusCard(v[i]);}
function choose(btn){const c=btn.closest('.card');inputOf(c).value=btn.dataset.word;persist();refresh();focusCard(c);}
function keepStore(){const c=activeCard();if(!c)return;const v=c.dataset.store||'';if(!v)return;
  inputOf(c).value=v;undecOf(c).checked=false;persist();refresh();move(1);}
function acceptCurrent(){const c=activeCard();if(!c)return;const input=inputOf(c);
  if(!input.value.trim())input.value=c.dataset.store||'';if(!input.value.trim()&&!undecOf(c).checked)return;
  persist();refresh();move(1);}
function markUndecodable(){const c=activeCard();if(!c)return;undecOf(c).checked=true;persist();refresh();move(1);}
function applyMap(obj){cards.forEach(c=>{const d=obj[keyOf(c)];if(!d)return;
  inputOf(c).value=d.decision||'';undecOf(c).checked=!!d.undecodable;});refresh();}
function loadSaved(){try{applyMap(JSON.parse(localStorage.getItem(KEY)||'{}'));}catch(e){refresh();}}
function importFile(file){const r=new FileReader();r.onload=()=>{try{const data=JSON.parse(r.result);
  if(!Array.isArray(data))throw new Error('expected array');const o={};data.forEach(d=>{
    const rec={font:d.font||'',cid:Number(d.cid),decision:(d.decision||'').trim(),undecodable:!!d.undecodable};
    o[rec.font+'\u2571'+rec.cid]=rec;});localStorage.setItem(KEY,JSON.stringify(o));applyMap(o);
  }catch(e){alert('Import failed: '+e.message);}};r.readAsText(file);}
function download(){const b=new Blob([JSON.stringify(collect(),null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='decisions.json';a.click();}
cards.forEach(c=>{c.addEventListener('click',e=>{if(e.target.tagName!=='INPUT')focusCard(c);});
  inputOf(c).addEventListener('input',()=>{persist();refresh();});
  undecOf(c).addEventListener('change',()=>{persist();refresh();});
  c.querySelectorAll('.cand').forEach(b=>b.addEventListener('click',()=>choose(b)));});
document.getElementById('filter-verdict').addEventListener('change',applyFilters);
document.getElementById('filter-font').addEventListener('change',applyFilters);
document.getElementById('filter-cid').addEventListener('input',applyFilters);
document.getElementById('only-undecided').addEventListener('change',applyFilters);
document.getElementById('export').addEventListener('click',download);
document.getElementById('import').addEventListener('change',e=>{if(e.target.files[0])importFile(e.target.files[0]);});
document.getElementById('reset').addEventListener('click',()=>{if(!confirm('Clear all decisions?'))return;
  try{localStorage.removeItem(KEY);}catch(e){}cards.forEach(c=>{inputOf(c).value='';undecOf(c).checked=false;});refresh();});
document.addEventListener('keydown',e=>{const tag=(e.target.tagName||'').toLowerCase();
  if(tag==='button'&&(e.key==='Enter'||e.key===' '))return;
  const field=tag==='input'||tag==='textarea'||tag==='select';
  if(field){if(e.key==='Enter'){e.preventDefault();acceptCurrent();}return;}
  const c=activeCard();if(!c)return;
  if(e.key>='1'&&e.key<='9'){const b=c.querySelectorAll('.cand')[Number(e.key)-1];
    if(b){e.preventDefault();choose(b);}return;}
  if(e.key==='Enter'){e.preventDefault();acceptCurrent();}
  else if(e.key==='k'||e.key==='K'){e.preventDefault();keepStore();}
  else if(e.key==='u'||e.key==='U'){e.preventDefault();markUndecodable();}
  else if(e.key==='s'||e.key==='S'||e.key==='ArrowRight'){e.preventDefault();move(1);}
  else if(e.key==='ArrowLeft'){e.preventDefault();move(-1);}});
loadSaved();
</script></body></html>"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("--store", default="cidmap/data/cid_mappings.json")
    p.add_argument("--ocr", default=None, help="optional cross_check JSON")
    p.add_argument("--font", default=None)
    p.add_argument("-o", "--output", default="output/cidmap_review.html")
    a = p.parse_args(argv)

    import fitz
    doc = fitz.open(a.pdf)
    store = json.loads(Path(a.store).read_text()) if Path(a.store).exists() else {}
    ocr = json.loads(Path(a.ocr).read_text()) if a.ocr else {}
    htmlout = build_review_html(doc, store, ocr, only_font=a.font)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmlout, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
