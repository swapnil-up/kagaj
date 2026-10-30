"""Per-CID quorum: do the decoder and OCR concur on each unknown glyph?

Text-level diffs are misleading — the decoder emits visual-order Devanagari
(reph/मात्रा before their base) while OCR reads logical order, so whole-line
strings rarely match even when every glyph is right. The meaningful concurrence
check is per (font_id, cid):

  - for a sample of pages, run OCR and note the word box containing each
    unknown glyph's origin (``cross_check``),
  - ask whether that OCR word contains the canonical store value for the glyph,
  - tally concurrence / disagreement per (font_id, cid).

Output: a plain-text report + HTML. "agree" = store value appears in the OCR
read word; "disagree" = OCR read contradicts the store; "missing" = no store
value yet (decoder emits ⟦cid⟧); "no-ocr" = no OCR word at the glyph spot.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
from pathlib import Path

from kagaj_core.devanagari import canonical_key

from .decode import census
from .mappings import get_value, load


def _key(s: str) -> str:
    """Canonical key for an OCR read; folds digits and matra variants."""
    return canonical_key(s or "", drop_joiners=False)


def _read_counts(reads: dict[str, int], value: str | None) -> tuple[int, int, int]:
    """Tally (agree, disagree, evidence) occurrences for one CID's OCR reads."""
    key = _key(value or "")
    agree = disagree = evidence = 0
    for read, count in reads.items():
        read_key = _key(read)
        if not read_key:
            continue
        if not key:
            evidence += count
        elif key in read_key:
            agree += count
        else:
            disagree += count
    return agree, disagree, evidence


def quorum(doc, store, engine, pages=None, log=None):
    """Run OCR cross-check on sampled pages; return per-(font,cid) verdicts."""
    cen = census(doc, max_pages=None)

    # Restrict census to the sampled pages, then cross_check over the same set.
    page_set = set(pages)
    rows = []
    for font, cids in cen.items():
        for cid, rec in cids.items():
            rec_pages = [p for p in rec["pages"] if p in page_set]
            if not rec_pages:
                continue
            rows.append((font, cid, rec))

    # cross_check needs the pages; call with max_pages=len(doc) but then filter.
    counts = _cross_check_pages(doc, engine, pages, log)
    out = {}
    for font, cid, rec in rows:
        val = get_value(store, font, cid)
        reads = counts.get(font, {}).get(cid, {})
        agree, disagree, evidence = _read_counts(reads, val)
        no_ocr = rec["count"] - (agree + disagree + evidence)
        if not val:
            verdict = "missing"
        elif agree > disagree:
            verdict = "agree"
        elif disagree > agree:
            verdict = "disagree"
        elif no_ocr:
            verdict = "no-ocr"
        else:
            verdict = "tie"
        out[(font, cid)] = {
            "font": font, "cid": cid, "value": val or "",
            "n_occ": rec["count"], "agree": agree, "disagree": disagree,
            "evidence": evidence, "no_ocr": no_ocr,
            "reads": {w: n for w, n in reads.items()},
            "verdict": verdict, "range": rec["range"],
        }
    return out


def _cross_check_pages(doc, engine, pages, log):
    """OCR words per unknown glyph over an explicit page list."""
    from .ocr import render_page, ocr_words
    from .decode import cluster_lines, glyphs, is_unknown_glyph
    from .mappings import get_value

    counts = {}
    reads = {}
    for pn in pages:
        if log:
            log(f"  OCR p{pn}...")
        page = doc[pn - 1]
        words = ocr_words(engine, render_page(page))
        for line in cluster_lines(glyphs(page)):
            for g in line:
                if not is_unknown_glyph(g):
                    continue
                font = g["font_id"] or ""
                ox, oy = g["origin"][0], g["origin"][1]
                w = next((t for t, x0, y0, x1, y1 in words
                          if x0 <= ox <= x1 and y0 <= oy <= y1), None)
                if not w:
                    continue
                cnt = counts.setdefault(font, {}).setdefault(g["cid"], {})
                cnt[w] = cnt.get(w, 0) + 1
    return counts


def _report(out) -> str:
    lines = []
    verdicts = [r["verdict"] for r in out.values()]
    n = len(out)
    lines.append(f"(font,cid) pairs: {n}")
    if n:
        for v in ("agree", "disagree", "missing", "no-ocr", "tie"):
            lines.append(f"  {v}: {verdicts.count(v)}")
        lines.append(f"  agree-rate: {verdicts.count('agree') / n:.0%}")
    lines.append("")
    for (font, cid), r in sorted(out.items(),
                                 key=lambda kv: (kv[1]["verdict"], kv[0][0], kv[0][1])):
        reads = ", ".join(f"{w}×{k}" for w, k in
                          sorted(r["reads"].items(), key=lambda x: -x[1])[:4])
        lines.append(
            f"[{r['verdict']:<9}] cid={cid:<3} value={r['value']!r} "
            f"agree={r['agree']} disagree={r['disagree']} "
            f"evidence={r['evidence']} no-ocr={r['no_ocr']} "
            f"| OCR reads: {reads}")
    return "\n".join(lines)


def _html_report(out) -> str:
    cards = []
    for (font, cid), r in sorted(out.items()):
        badge = {"agree": "ok", "disagree": "bad", "missing": "miss",
                 "no-ocr": "none", "tie": "none"}[r["verdict"]]
        reads = "".join(
            f'<span class="rd">{html.escape(w)}<i>×{k}</i></span>'
            for w, k in sorted(r["reads"].items(), key=lambda x: -x[1])[:6])
        cards.append(f"""
<div class="card {badge}">
  <div class="h"><b>CID {cid}</b> <span class="meta">{html.escape(font)}</span></div>
  <div class="v">value: <b>{html.escape(r['value'] or '—')}</b></div>
  <div class="s">agree {r['agree']} · disagree {r['disagree']} · evidence {r['evidence']} · no-ocr {r['no_ocr']}</div>
  <div class="reads">{reads or '—'}</div>
</div>""")
    return f"""<!DOCTYPE html><html lang="ne"><head><meta charset="utf-8">
<title>CID quorum</title>
<style>
body{{font-family:'Noto Sans',sans-serif;background:#101318;color:#e8e8e8;margin:0;padding:16px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
.card{{background:#1b2027;border:1px solid #2c333d;border-radius:8px;padding:10px 12px}}
.card.ok{{border-left:4px solid #2f9e44}}.card.bad{{border-left:4px solid #c92a2a}}
.card.miss{{border-left:4px solid #e67700}}.card.none{{border-left:4px solid #555}}
.h{{display:flex;justify-content:space-between;align-items:baseline}}
.meta{{color:#7f8c9d;font-size:.8em;word-break:break-all}}
.v{{font-size:1.2em;margin-top:6px}}
.s{{color:#9aa7b8;font-size:.85em}}
.reads{{margin-top:6px;font-family:'Noto Sans Devanagari',sans-serif}}
.rd{{display:inline-block;background:#222a33;border-radius:4px;padding:2px 6px;margin:2px}}
.rd i{{color:#7f8c9d;font-style:normal;margin-left:3px}}
</style></head><body>
<div class="cards">{chr(10).join(cards)}</div>
</body></html>"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("--store", default="cidmap/data/cid_mappings.json")
    p.add_argument("--random", type=int, default=5, help="pages to sample")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--html", default=None, help="write an HTML report too")
    a = p.parse_args(argv)

    from kagaj_core import pdf as core_pdf
    doc = core_pdf.open_pdf(a.pdf)
    store = load(a.store)
    from .ocr import _ocr_engine
    engine = _ocr_engine()

    rng = random.Random(a.seed)
    pages = sorted(rng.sample(range(1, len(doc) + 1),
                              min(a.random, len(doc))))
    print(f"Sampling pages {pages}", file=sys.stderr)
    out = quorum(doc, store, engine, pages=pages, log=print)

    text = _report(out)
    print(text)
    if a.html:
        Path(a.html).write_text(_html_report(out), encoding="utf-8")
        print(f"Wrote {a.html}", file=sys.stderr)
    return 0 if all(r["verdict"] in ("agree", "missing", "no-ocr")
                    for r in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
