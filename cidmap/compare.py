"""Compare decoder output vs OCR output: find where the two disagree.

The decoder reads the text layer through the canonical store; OCR reads the
printed ink. When they differ it is either (a) a wrong/missing store entry
(the decoder misreads or leaves a ``⟦cid:N⟧`` marker) or (b) an OCR error.
The reviewer inspects these discrepancies to decide the true mapping.

Output is a standalone HTML report, one card per page:

  - coverage header (decoder unmapped count, OCR word count),
  - aligned line pairs (decoder on the left, OCR on the right) sorted by
    baseline y, with character-level differences highlighted,
  - lines present in only one stream flagged as extra/missing.

Alignment: lines from both streams are clustered by y and matched to their
nearest same-page partner (within ``Y_TOL`` pt); a line may also be unmatched.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import sys
from pathlib import Path

from kagaj_core.devanagari import canonical_key, normalize

from .decode import cluster_lines, glyphs
from .decoder import decode_page
from .mappings import load

Y_TOL = 6.0
AGREE_RATIO = 0.85


def _decoder_lines(page, store):
    return [(_line_y(line), _line_text(line, store))
            for line in cluster_lines(glyphs(page))]


def _line_y(line):
    return sum(g["origin"][1] for g in line) / len(line)


def _line_text(line, store):
    from .decoder import _resolve
    return normalize("".join(_resolve(g, store) for g in line))


def _ocr_lines(page_array, engine):
    from .ocr import ocr_words
    words = ocr_words(engine, page_array)
    words.sort(key=lambda w: (w[2], w[1]))
    lines = []
    for t, x0, y0, x1, y1 in words:
        if lines and abs(y0 - lines[-1]["y"]) <= Y_TOL:
            lines[-1]["text"] += " " + t
        else:
            lines.append({"y": y0, "text": t})
    return [(l["y"], l["text"]) for l in lines]


def _align(dec_lines, ocr_lines):
    """Pair decoder/OCR lines by nearest y; return (pairs, dec_only, ocr_only)."""
    pairs = []
    dec_only, ocr_only = [], []
    used = set()
    for dy, dt in dec_lines:
        best, best_d = None, None
        for i, (oy, ot) in enumerate(ocr_lines):
            if i in used:
                continue
            d = abs(dy - oy)
            if d <= Y_TOL and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            used.add(best)
            pairs.append((dt, ocr_lines[best][1]))
        else:
            dec_only.append(dt)
    for i, (oy, ot) in enumerate(ocr_lines):
        if i not in used:
            ocr_only.append(ot)
    return pairs, dec_only, ocr_only


def _diff_html(a, b):
    a = a.replace(" ", "\u2423")
    b = b.replace(" ", "\u2423")
    sm = difflib.SequenceMatcher(None, a, b)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            left.append(html.escape(a[i1:i2]))
            right.append(html.escape(b[j1:j2]))
        else:
            left.append(f'<span class="d">{html.escape(a[i1:i2])}</span>')
            right.append(f'<span class="d">{html.escape(b[j1:j2])}</span>')
    return "".join(left), "".join(right)


def _page_html(pn, dec_lines, ocr_lines, stats=None):
    pairs, dec_only, ocr_only = _align(dec_lines, ocr_lines)
    n_unk = sum(1 for y, t in dec_lines if "\u27e6cid:" in t)
    rows = ""
    for a, b in pairs:
        la, ra = _diff_html(a, b)
        agree = _agree(a, b)
        cls = ' class="ok"' if agree else ""
        rows += (f'<tr{cls}><td class="np">{la}</td>'
                 f'<td class="ocr">{ra}</td></tr>\n')
    for t in dec_only:
        rows += f'<tr><td class="np d-line">{html.escape(t)}</td><td class="m">—</td></tr>\n'
    for t in ocr_only:
        rows += f'<tr><td class="m">—</td><td class="ocr d-line">{html.escape(t)}</td></tr>\n'
    if not rows:
        rows = '<tr><td colspan="2" class="m">no text</td></tr>'
    meta = f"unmapped ⟦cid⟧: {n_unk} · OCR words: {len(ocr_lines)}"
    if stats:
        meta += f" · agree: {stats['agree']}/{stats['pairs']} ({stats['rate']:.0%})"
    return f"""
<div class="page">
<h2>Page {pn} <span class="meta">{meta}</span></h2>
<table>{rows}</table>
</div>"""


def _line_key(s: str) -> str:
    """Whitespace-free canonical key for line similarity scoring."""
    return "".join(canonical_key(s, drop_joiners=False).split())


def _agree(a: str, b: str) -> bool:
    """True when decoder/OCR agree on a line after canonicalization.

    Decoder output is visual order and OCR is reading order, so exact equality
    is rare; agreement means a difflib ratio at or above ``AGREE_RATIO``.
    ``canonical_key`` folds digits and matra variants but deliberately does not
    reorder text, so visual-order/logical-order disagreements still surface.
    """
    return difflib.SequenceMatcher(None, _line_key(a), _line_key(b)).ratio() >= AGREE_RATIO


def _page_stats(pairs, dec_only, ocr_only) -> dict:
    agree = sum(1 for a, b in pairs if _agree(a, b))
    n = len(pairs)
    return {"pairs": n, "agree": agree, "differ": n - agree,
            "rate": agree / n if n else 1.0,
            "dec_only": len(dec_only), "ocr_only": len(ocr_only)}


def compare(doc, store, engine, pages=None, log=None) -> tuple[str, list[dict]]:
    if pages is None:
        pages = range(len(doc))
    body = []
    all_stats = []
    for pn in pages:
        if log:
            log(f"  compare p{pn + 1}...")
        page = doc[pn]
        from .ocr import render_page
        arr = render_page(page)
        dec_lines = _decoder_lines(page, store)
        ocr_lines = _ocr_lines(arr, engine)
        pairs, dec_only, ocr_only = _align(dec_lines, ocr_lines)
        stats = _page_stats(pairs, dec_only, ocr_only)
        stats["page"] = pn + 1
        all_stats.append(stats)
        body.append(_page_html(pn + 1, dec_lines, ocr_lines, stats))
    return (f"""<!DOCTYPE html><html lang="ne"><head><meta charset="utf-8">
<title>Decoder vs OCR comparison</title>
<style>
body{{font-family:'Noto Sans',sans-serif;background:#101318;color:#e8e8e8;margin:0;padding:16px}}
h2{{font-size:1em;color:#fff;border-bottom:1px solid #2c333d;padding-bottom:6px;margin-top:26px}}
.meta{{color:#7f8c9d;font-weight:normal;font-size:.85em}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}
td{{padding:6px 10px;vertical-align:top;border-bottom:1px solid #1d232b;word-break:break-word;white-space:pre-wrap}}
td.np{{width:50%;color:#c8d2e0;font-family:'Noto Sans Devanagari',sans-serif;font-size:1.15em}}
td.ocr{{width:50%;color:#7ee787;font-family:'Noto Sans Devanagari',sans-serif;font-size:1.15em}}
span.d{{background:#7c1f2a;color:#ffb3b3;border-radius:3px;padding:0 1px}}
td.d-line{{background:#1f2430}}
td.m{{color:#555}}
tr.ok td.np{{color:#9fd08a}}
</style></head><body>
<h1>Decoder (text layer) vs OCR (ink)</h1>
<p style="color:#9aa7b8">Left: canonical-store decode · Right: PaddleOCR. Red spans = disagree; green rows agree.</p>
{chr(10).join(body)}
</body></html>""", all_stats)


def summarize(stats: list[dict]) -> str:
    """Render the agreement summary for a compare run."""
    if not stats:
        return "no pages compared"
    pairs = sum(s["pairs"] for s in stats)
    agree = sum(s["agree"] for s in stats)
    dec_only = sum(s["dec_only"] for s in stats)
    ocr_only = sum(s["ocr_only"] for s in stats)
    rate = agree / pairs if pairs else 1.0
    lines = [f"pages={len(stats)} pairs={pairs} agree={agree} ({rate:.0%}) "
             f"differ={pairs - agree} dec_only={dec_only} ocr_only={ocr_only}"]
    for s in stats:
        lines.append(
            f"  p{s['page']:<4} pairs={s['pairs']:<4} agree={s['agree']:<4} "
            f"({s['rate']:.0%})  differ={s['differ']:<3} "
            f"dec_only={s['dec_only']} ocr_only={s['ocr_only']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pdf")
    p.add_argument("--store", default="cidmap/data/cid_mappings.json")
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--random", type=int, default=None,
                   help="sample N random pages for a concurrence quorum")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("-o", "--output", default="output/cidmap_compare.html")
    a = p.parse_args(argv)

    import fitz  # lazy
    doc = fitz.open(a.pdf)
    store = load(a.store)

    from .ocr import _ocr_engine
    engine = _ocr_engine()

    if a.random:
        import random
        rng = random.Random(a.seed)
        pages = sorted(rng.sample(range(len(doc)), min(a.random, len(doc))))
    else:
        pages = None if a.max_pages is None else range(
            min(a.max_pages, len(doc)))

    htmlout, stats = compare(doc, store, engine, pages=pages, log=print)
    print(summarize(stats), file=sys.stderr)

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmlout, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
