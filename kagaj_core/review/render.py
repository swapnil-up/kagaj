"""Static HTML review sheet: cards, keyboard flow, persistence, import/export.

Adapters call :func:`render_review` with :class:`ReviewItem` values. The page is
a single static file: decisions live in ``localStorage`` under a key derived
from the adapter's session identifier, and export as neutral
``[{key, value, undecodable, inconsistent, note, data}]`` records.

Adapter contract:

* Scan the source, choose the key, render crops, and build the items.
* Pass a stable ``session`` string that includes the adapter and source
  identity, e.g. ``"redbook:" + pdf_path`` or
  ``"cidmap:" + pdf_path + ":" + store_path``. Different sessions never share
  persisted decisions.
* Keep ``data`` JSON-serialisable; it is copied into exports so adapters can
  recover their own identifiers.
* Convert :class:`ReviewDecision` records to the command format
  (``{cid, correct}``, ``{font, cid, decision, undecodable}``, ...).
"""

from __future__ import annotations

import hashlib
import html
import json

from .model import ReviewItem


def storage_key(session: str) -> str:
    """Return the per-session ``localStorage`` key."""

    digest = hashlib.sha256(str(session).encode("utf-8")).hexdigest()[:16]
    return f"kagaj.review.v1.{digest}"


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _script_json(value) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return (text.replace("</", "<\\/")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def _crop_html(crop) -> str:
    parts = []
    if crop.glyph:
        parts.append(f'<img class="g" src="{_esc(crop.glyph)}" alt="glyph crop"'
                     ' loading="lazy">')
    if crop.word:
        overlay = crop.overlay or {}
        keys = ("left", "top", "width", "height")
        style = "".join(f"{k}:{_esc(overlay[k])};" for k in keys
                        if k in overlay)
        box = f'<span class="gbox" style="{style}"></span>' if style else ""
        parts.append(
            f'<span class="w-wrap"><img class="w" src="{_esc(crop.word)}"'
            f' alt="word crop" loading="lazy">{box}</span>')
    if not parts:
        return ""
    caption = (f'<div class="cap">{_esc(crop.caption)}</div>'
               if crop.caption else "")
    return f'<div class="sample"><div class="croprun">{"".join(parts)}</div>{caption}</div>'


def _crops_html(item: ReviewItem) -> str:
    htmlout = "".join(_crop_html(crop) for crop in item.crops)
    return htmlout or '<span class="none">no crop</span>'


def _candidate_html(candidate, index: int) -> str:
    label = candidate.label or candidate.value
    detail = candidate.detail
    if not detail and candidate.count:
        detail = f"{int(candidate.count)} occurrence(s)"
    count = (f'<i>\u00d7{int(candidate.count)}</i>'
             if candidate.count else "")
    return (
        f'<button type="button" class="cand" data-value="{_esc(candidate.value)}"'
        f' data-index="{index}" title="{_esc(detail)}">{_esc(label)}{count}'
        f'</button>')


def _candidates_html(item: ReviewItem) -> str:
    buttons = "".join(
        _candidate_html(candidate, i)
        for i, candidate in enumerate(item.candidates, 1))
    return buttons or '<span class="none">no candidates</span>'


def _tag_id(key) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(key))


def _tag_attrs(item: ReviewItem) -> str:
    return "".join(
        f' data-tag-{_tag_id(key)}="{_esc(value)}"'
        for key, value in item.tags.items() if value)


def _card_html(item: ReviewItem) -> str:
    badges = []
    if item.group:
        badges.append(f'<span class="badge">{_esc(item.group)}</span>')
    badges.extend(f'<span class="badge tag">{_esc(value)}</span>'
                  for value in item.tags.values() if value)
    current = ""
    if item.current is not None:
        current = (f'<div class="values">current: <b>{_esc(item.current)}</b>'
                   f'</div>')
    placeholder = _esc(item.input_placeholder or item.current or "\u2014")
    search = _esc(" ".join([item.key, item.label, item.group,
                            *item.tags.values()]))
    return f"""
<div class="card" data-key="{_esc(item.key)}" data-group="{_esc(item.group)}"
     data-current="{_esc(item.current)}" data-search="{search}"{_tag_attrs(item)}
     tabindex="0">
  <div class="h"><b>{_esc(item.label)}</b>{"".join(badges)}</div>
  <div class="show">{_crops_html(item)}</div>
  <div class="ctx">{_esc(item.context)}</div>
  {current}
  <div class="cands">{_candidates_html(item)}</div>
  <div class="fill">
    <input class="value" placeholder="{placeholder}">
    <label class="undec"><input type="checkbox" class="undec-toggle"> undecodable</label>
    <label class="incon" title="Use only when the same CID prints a different glyph shape in different samples, not when it appears in different words."><input type="checkbox" class="incon-toggle"> inconsistent glyph shapes</label>
  </div>
  <input class="note" placeholder="note: how the glyph shapes differ (optional)">
</div>"""


def render_review(items, *, session: str, title: str = "Review",
                  export_name: str = "decisions.json",
                  help_text: str | None = None,
                  notice: str | None = None,
                  group_label: str = "group",
                  search_placeholder: str = "Search key",
                  tag_filters: tuple[str, ...] = ()) -> str:
    """Render review items to a self-contained HTML page.

    ``tag_filters`` names adapter tags (for example ``("verdict",)``) that get
    their own select in the filter bar and a badge on each card.
    """

    items = list(items)
    cards = "".join(_card_html(item) for item in items)
    groups = sorted({item.group for item in items if item.group})
    group_options = "".join(
        f'<option value="{_esc(group)}">{_esc(group)}</option>'
        for group in groups)
    tag_selects = []
    for key in tag_filters:
        tag_id = _tag_id(key)
        values = sorted({item.tags.get(key, "") for item in items
                         if item.tags.get(key)})
        if not values:
            continue
        options = "".join(
            f'<option value="{_esc(value)}">{_esc(value)}</option>'
            for value in values)
        tag_selects.append(
            f'<select id="filter-{_esc(tag_id)}" data-tag="{_esc(tag_id)}">'
            f'<option value="all">all {_esc(key)}s</option>{options}</select>')
    tag_filter_html = "".join(tag_selects)
    bootstrap = _script_json([
        {"key": item.key, "current": item.current or "", "data": dict(item.data)}
        for item in items
    ])
    if help_text is None:
        help_text = ("1\u20139 pick candidate \u00b7 Enter accept + next \u00b7 "
                     "K keep current \u00b7 U undecodable \u00b7 I inconsistent \u00b7 "
                     "S skip \u00b7 \u2190/\u2192 previous/next")
    empty = ""
    if not items:
        empty = '<p class="empty">No items to review.</p>'

    return (_TEMPLATE
            .replace("__TITLE__", _esc(title))
            .replace("__COUNT__", str(len(items)))
            .replace("__CARDS__", cards)
            .replace("__GROUPS__", group_options)
            .replace("__TAG_FILTERS__", tag_filter_html)
            .replace("__GROUP_LABEL__", _esc(group_label))
            .replace("__SEARCH_PLACEHOLDER__", _esc(search_placeholder))
            .replace("__BOOTSTRAP__", bootstrap)
            .replace("__STORAGE_KEY__", _script_json(storage_key(session)))
            .replace("__EXPORT_LABEL__", _esc(export_name))
            .replace("__EXPORT_NAME__", _script_json(export_name))
            .replace("__HELP__", _esc(help_text))
            .replace("__NOTICE__", _esc(notice or ""))
            .replace("__EMPTY__", empty))


_TEMPLATE = """<!DOCTYPE html><html lang="ne"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
body{font-family:sans-serif;background:#13161b;color:#e6e6e6;margin:0;padding:16px}
#toolbar,#filters{position:sticky;z-index:5;background:#13161bee;padding:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#toolbar{top:0}#filters{top:48px;border-bottom:1px solid #2c333d;margin-bottom:12px}
button,input,select{font:inherit}
button{padding:6px 10px;border:1px solid #3d4a5a;border-radius:6px;background:#1b2027;color:#e6e6e6;cursor:pointer}
button.primary{background:#2f81f7;border-color:#2f81f7;color:#fff;font-weight:700}
label.import{padding:6px 10px;border:1px solid #3d4a5a;border-radius:6px;background:#1b2027;color:#e6e6e6;cursor:pointer}
#progress{color:#9aa7b8}
.help{color:#7f8c9d;font-size:.82em;margin:0 0 12px}
.notice{color:#ffd8a8;background:#2a2113;border:1px solid #5c4318;border-radius:6px;padding:8px 10px;margin:0 0 12px}
.notice:empty{display:none}
.empty{color:#9aa7b8}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:#1b2027;border:1px solid #2c333d;border-left:4px solid #555;border-radius:8px;padding:10px 12px;outline:none}
.card:focus{box-shadow:0 0 0 2px #2f81f7}
.card[hidden]{display:none}
.card.decided{border-top:1px solid #2f9e44}
.h{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.badge{font-size:.75em;text-transform:uppercase;color:#9aa7b8}
.badge.tag{color:#c8d2e0}
.show{display:flex;flex-direction:column;gap:8px;margin:8px 0}
.sample{display:flex;flex-direction:column;gap:3px}
.cap{color:#8b98a8;font-size:.75em}
.croprun{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap}
.show img.g{border:2px solid #2f81f7;background:#fff;max-height:90px;image-rendering:pixelated}
.w-wrap{position:relative;display:inline-block;background:#fff;max-width:100%;}
.w-wrap img.w{display:block;border:1px solid #3a4350;max-height:140px;max-width:100%}
.gbox{position:absolute;border:2px solid #f85149;background:#f8514926;pointer-events:none;box-sizing:border-box}
.ctx{color:#fff;font-family:'Noto Sans Devanagari',sans-serif;font-size:1.2em;line-height:1.5;word-break:break-word}
.values{color:#c8d2e0;font-size:.9em;margin-top:4px;font-family:'Noto Sans Devanagari',sans-serif}
.cands{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.cand{font-family:'Noto Sans Devanagari',sans-serif;font-size:1.1em}
.cand i{color:#7f8c9d;font-style:normal;font-size:.7em;margin-left:4px}
.fill{display:flex;gap:8px;align-items:center;margin-top:6px}
input.value{flex:1;padding:6px 8px;font-size:1.2em;background:#0f1216;color:#fff;border:1px solid #3d4a5a;border-radius:4px;font-family:'Noto Sans Devanagari',sans-serif}
.undec,.incon{color:#8b98a8;font-size:.75em;white-space:nowrap}
.note{margin-top:6px;width:100%;box-sizing:border-box;padding:5px 7px;background:#0f1216;color:#e6e6e6;border:1px solid #2c333d;border-radius:4px}
.card.inconsistent{border-left-color:#e67700}
.card.inconsistent .note{border-color:#e67700}
.none{color:#666;font-size:.8em}
</style></head><body>
<div id="toolbar">
  <button class="primary" id="export">Export __EXPORT_LABEL__</button>
  <label class="import">Import<input id="import" type="file" accept="application/json" hidden></label>
  <button id="reset">Reset</button>
  <span id="progress"><span id="filled">0</span> / __COUNT__ decided</span>
</div>
<div id="filters">
  <select id="filter-group"><option value="all">all __GROUP_LABEL__s</option>__GROUPS__</select>
  __TAG_FILTERS__
  <input id="filter-search" type="search" placeholder="__SEARCH_PLACEHOLDER__">
  <label><input id="only-undecided" type="checkbox"> only undecided</label>
  <span id="visible"></span>
</div>
<p class="help">__HELP__</p>
<div class="notice">__NOTICE__</div>
__EMPTY__
<div class="cards">__CARDS__</div>
<script id="review-data" type="application/json">__BOOTSTRAP__</script>
<script>
const KEY=__STORAGE_KEY__;
const EXPORT_NAME=__EXPORT_NAME__;
const META=Object.fromEntries(JSON.parse(document.getElementById('review-data').textContent).map(i=>[i.key,i]));
const cards=Array.from(document.querySelectorAll('.card'));
const inputOf=c=>c.querySelector('.value');
const undecOf=c=>c.querySelector('.undec-toggle');
const inconOf=c=>c.querySelector('.incon-toggle');
const noteOf=c=>c.querySelector('.note');
const keyOf=c=>c.dataset.key;
function isDecided(c){return !!inputOf(c).value.trim()||undecOf(c).checked||inconOf(c).checked;}
function collect(){return cards.map(c=>({key:keyOf(c),value:inputOf(c).value.trim(),
  undecodable:undecOf(c).checked,inconsistent:inconOf(c).checked,
  note:noteOf(c).value.trim(),data:(META[keyOf(c)]||{}).data||{}}));}
function persist(){const o={};cards.forEach(c=>{if(isDecided(c))o[keyOf(c)]={
  value:inputOf(c).value.trim(),undecodable:undecOf(c).checked,
  inconsistent:inconOf(c).checked,note:noteOf(c).value.trim()};});
  try{localStorage.setItem(KEY,JSON.stringify(o));}catch(e){}}
function updateProgress(){let n=0;cards.forEach(c=>{const d=isDecided(c);if(d)n++;
  c.classList.toggle('decided',d);
  c.classList.toggle('inconsistent',inconOf(c).checked);});
  document.getElementById('filled').textContent=n;}
const tagFilters=Array.from(document.querySelectorAll('#filters select[data-tag]'));
function applyFilters(){const g=document.getElementById('filter-group').value;
  const q=document.getElementById('filter-search').value.trim().toLowerCase();
  const und=document.getElementById('only-undecided').checked;let shown=0;
  cards.forEach(c=>{const tagsOk=tagFilters.every(s=>s.value==='all'||
    (c.getAttribute('data-tag-'+s.dataset.tag)||'')===s.value);
    const ok=tagsOk&&(g==='all'||c.dataset.group===g)&&
    (!q||(c.dataset.search||'').toLowerCase().includes(q))&&(!und||!isDecided(c));
    c.hidden=!ok;if(ok)shown++;});
  document.getElementById('visible').textContent=shown+' shown';}
function refresh(){updateProgress();applyFilters();}
function visibleCards(){return cards.filter(c=>!c.hidden);}
function activeCard(){const el=document.activeElement;
  return el&&el.closest?el.closest('.card'):null;}
function focusCard(c){if(!c)return;c.focus({preventScroll:true});
  c.scrollIntoView({block:'center'});}
function move(dir){const v=visibleCards();if(!v.length)return;
  const cur=activeCard();let i=v.indexOf(cur);
  i=i<0?(dir>0?0:v.length-1):(i+dir+v.length)%v.length;focusCard(v[i]);}
function choose(btn){const c=btn.closest('.card');inputOf(c).value=btn.dataset.value;
  persist();refresh();focusCard(c);}
function keepCurrent(){const c=activeCard();if(!c)return;
  const v=c.dataset.current||'';if(!v)return;inputOf(c).value=v;
  undecOf(c).checked=false;inconOf(c).checked=false;persist();refresh();move(1);}
function acceptCurrent(){const c=activeCard();if(!c)return;const input=inputOf(c);
  if(!input.value.trim())input.value=c.dataset.current||'';
  if(!input.value.trim()&&!undecOf(c).checked&&!inconOf(c).checked)return;
  persist();refresh();move(1);}
function markUndecodable(){const c=activeCard();if(!c)return;
  undecOf(c).checked=true;inconOf(c).checked=false;persist();refresh();move(1);}
function markInconsistent(){const c=activeCard();if(!c)return;
  inconOf(c).checked=!inconOf(c).checked;
  if(inconOf(c).checked)undecOf(c).checked=false;
  persist();refresh();noteOf(c).focus();}
function applyMap(obj){cards.forEach(c=>{const d=obj[keyOf(c)];if(!d)return;
  inputOf(c).value=d.value||'';undecOf(c).checked=!!d.undecodable;
  inconOf(c).checked=!!d.inconsistent;noteOf(c).value=d.note||'';});refresh();}
function loadSaved(){try{applyMap(JSON.parse(localStorage.getItem(KEY)||'{}'));}
  catch(e){refresh();}}
function importFile(file){const r=new FileReader();r.onload=()=>{try{
  const data=JSON.parse(r.result);if(!Array.isArray(data))throw new Error('expected array');
  const o={};data.forEach(d=>{if(!d||typeof d.key==='undefined')return;
    o[String(d.key)]={value:(d.value||'').trim(),undecodable:!!d.undecodable,
      inconsistent:!!d.inconsistent,note:(d.note||'').trim()};});
  try{localStorage.setItem(KEY,JSON.stringify(o));}catch(e){}applyMap(o);
  }catch(e){alert('Import failed: '+e.message);}};r.readAsText(file);}
function download(){const b=new Blob([JSON.stringify(collect(),null,2)],
  {type:'application/json'});const a=document.createElement('a');
  a.href=URL.createObjectURL(b);a.download=EXPORT_NAME;a.click();}
cards.forEach(c=>{c.addEventListener('click',e=>{if(e.target.tagName!=='INPUT')focusCard(c);});
  inputOf(c).addEventListener('input',()=>{persist();refresh();});
  noteOf(c).addEventListener('input',()=>{persist();refresh();});
  undecOf(c).addEventListener('change',()=>{if(undecOf(c).checked)inconOf(c).checked=false;persist();refresh();});
  inconOf(c).addEventListener('change',()=>{if(inconOf(c).checked)undecOf(c).checked=false;persist();refresh();});
  c.querySelectorAll('.cand').forEach(b=>b.addEventListener('click',()=>choose(b)));});
document.getElementById('filter-group').addEventListener('change',applyFilters);
tagFilters.forEach(s=>s.addEventListener('change',applyFilters));
document.getElementById('filter-search').addEventListener('input',applyFilters);
document.getElementById('only-undecided').addEventListener('change',applyFilters);
document.getElementById('export').addEventListener('click',download);
document.getElementById('import').addEventListener('change',
  e=>{if(e.target.files[0])importFile(e.target.files[0]);});
document.getElementById('reset').addEventListener('click',()=>{
  if(!confirm('Clear all decisions?'))return;
  try{localStorage.removeItem(KEY);}catch(e){}
  cards.forEach(c=>{inputOf(c).value='';undecOf(c).checked=false;
    inconOf(c).checked=false;noteOf(c).value='';});refresh();});
document.addEventListener('keydown',e=>{const tag=(e.target.tagName||'').toLowerCase();
  const field=tag==='input'||tag==='textarea'||tag==='select';
  if(field){if(e.key==='Enter'&&e.target!==document.getElementById('filter-search')){
    e.preventDefault();acceptCurrent();}return;}
  const c=activeCard();if(!c)return;
  if(e.key>='1'&&e.key<='9'){const b=c.querySelectorAll('.cand')[Number(e.key)-1];
    if(b){e.preventDefault();choose(b);}return;}
  if(e.key==='Enter'){e.preventDefault();acceptCurrent();}
  else if(e.key==='k'||e.key==='K'){e.preventDefault();keepCurrent();}
  else if(e.key==='u'||e.key==='U'){e.preventDefault();markUndecodable();}
  else if(e.key==='i'||e.key==='I'){e.preventDefault();markInconsistent();}
  else if(e.key==='s'||e.key==='S'||e.key==='ArrowRight'){e.preventDefault();move(1);}
  else if(e.key==='ArrowLeft'){e.preventDefault();move(-1);}});
loadSaved();
</script></body></html>"""
