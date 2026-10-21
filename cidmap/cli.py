"""CLI: cidmap scan <pdf> | cidmap commit <decisions.json> | cidmap seed <derive.json>

``scan``  decode -> (optional OCR) -> HTML decision sheet (+ census JSON),
``commit``  fold a decisions.json exported from the sheet into the canonical
            store, ``seed``  fold a derive output into the store as fallbacks.

Default store: ``cidmap/data/cid_mappings.json`` (tracked, the consumable map).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .decode import census, flatten
from .mappings import (
    load, save, set_value, mark_undecodable, merge_derive_results,
)
from .review import build_review_html

DEFAULT_STORE = "cidmap/data/cid_mappings.json"


def _doc(args):
    import fitz  # lazy
    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return None
    return fitz.open(args.pdf)


def cmd_scan(args) -> int:
    doc = _doc(args)
    if doc is None:
        return 1

    cen = census(doc, max_pages=args.max_pages)
    store = load(args.store)

    ocr_path = None
    if args.ocr and not args.offline:
        from .ocr import cross_check
        print("OCR cross-check (slow)...", file=sys.stderr)
        res = cross_check(doc, cen, max_pages=args.max_pages, log=print)
        ocr_path = args.ocr
        os.makedirs(os.path.dirname(ocr_path) or ".", exist_ok=True)
        with open(ocr_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        ocr_data = res
        print(f"Wrote {ocr_path}", file=sys.stderr)
    else:
        ocr_data = {}
        if args.ocr and os.path.exists(args.ocr):
            with open(args.ocr, encoding="utf-8") as f:
                ocr_data = json.load(f)

    out = args.output
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    htmlout = build_review_html(doc, store, ocr_data, only_font=args.font,
                                max_pages=args.max_pages, census_result=cen)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)", file=sys.stderr)

    if args.census:
        rows = flatten(cen)
        with open(args.census, "w", encoding="utf-8") as f:
            json.dump({"census": rows}, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(rows)} (font,cid) rows to {args.census}",
              file=sys.stderr)
    return 0


def cmd_commit(args) -> int:
    if not os.path.exists(args.decisions):
        print(f"Error: {args.decisions} not found", file=sys.stderr)
        return 1
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)

    store = load(args.store)
    n_val, n_undec = 0, 0
    for d in decisions:
        font = d.get("font") or ""
        cid = int(d["cid"])
        if d.get("undecodable"):
            mark_undecodable(store, font, cid)
            n_undec += 1
            continue
        val = (d.get("decision") or "").strip()
        if not val:
            continue
        set_value(store, font, cid, val, {"source": "review"})
        n_val += 1

    save(store, args.store)
    print(f"Committed {n_val} values, {n_undec} undecodable -> {args.store}",
          file=sys.stderr)
    return 0


def cmd_seed(args) -> int:
    if not os.path.exists(args.derive):
        print(f"Error: {args.derive} not found", file=sys.stderr)
        return 1
    with open(args.derive, encoding="utf-8") as f:
        derive_results = json.load(f)

    store = load(args.store)
    n = merge_derive_results(store, derive_results, source="derive")
    save(store, args.store)
    print(f"Seeded {n} CID fallbacks into {args.store}", file=sys.stderr)
    return 0


def cmd_compare(args) -> int:
    import fitz  # lazy
    doc = _doc(args)
    if doc is None:
        return 1
    from .compare import compare, summarize
    from .mappings import load
    from .ocr import _ocr_engine

    store = load(args.store)
    engine = _ocr_engine()
    print("OCR + decode compare (slow)...", file=sys.stderr)

    if args.random:
        import random
        rng = random.Random(args.seed)
        pages = sorted(rng.sample(range(len(doc)), min(args.random, len(doc))))
    else:
        pages = None if args.max_pages is None else range(
            min(args.max_pages, len(doc)))

    htmlout, stats = compare(doc, store, engine, pages=pages, log=print)
    print(summarize(stats), file=sys.stderr)

    out = args.output
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)", file=sys.stderr)
    return 0


def cmd_quorum(args) -> int:
    import fitz  # lazy
    doc = _doc(args)
    if doc is None:
        return 1
    from .mappings import load
    from .ocr import _ocr_engine
    from .quorum import quorum, _report, _html_report

    store = load(args.store)
    engine = _ocr_engine()
    print("Per-CID quorum (slow)...", file=sys.stderr)

    import random
    rng = random.Random(args.seed)
    pages = sorted(rng.sample(range(1, len(doc) + 1),
                              min(args.random, len(doc))))
    print(f"Sampling pages {pages}", file=sys.stderr)
    out = quorum(doc, store, engine, pages=pages, log=print)

    print(_report(out))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(_html_report(out))
        print(f"Wrote {args.html}", file=sys.stderr)
    bad = any(r["verdict"] == "disagree" for r in out.values())
    return 1 if bad else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan", help="decode + OCR -> review HTML")
    sc.add_argument("pdf")
    sc.add_argument("--store", default=DEFAULT_STORE)
    sc.add_argument("--ocr", default="output/cidmap_ocr.json",
                    help="path for OCR reads; with --offline this is instead read")
    sc.add_argument("--offline", action="store_true",
                    help="skip OCR; reuse the --ocr JSON if present")
    sc.add_argument("--font", default=None, help="restrict to one font subset")
    sc.add_argument("--max-pages", type=int, default=None)
    sc.add_argument("-o", "--output", default="output/cidmap_review.html")
    sc.add_argument("--census", default=None, help="also dump census JSON")
    sc.set_defaults(fn=cmd_scan)

    cm = sub.add_parser("commit", help="fold decisions.json into the store")
    cm.add_argument("decisions")
    cm.add_argument("--store", default=DEFAULT_STORE)
    cm.set_defaults(fn=cmd_commit)

    sd = sub.add_parser("seed", help="fold a derive output in as fallbacks")
    sd.add_argument("derive", help="derive output JSON")
    sd.add_argument("--store", default=DEFAULT_STORE)
    sd.set_defaults(fn=cmd_seed)

    cp = sub.add_parser("compare",
                        help="HTML: decoder text vs OCR text, aligned diff")
    cp.add_argument("pdf")
    cp.add_argument("--store", default=DEFAULT_STORE)
    cp.add_argument("--max-pages", type=int, default=None)
    cp.add_argument("--random", type=int, default=None,
                    help="sample N random pages for a concurrence quorum")
    cp.add_argument("--seed", type=int, default=None)
    cp.add_argument("-o", "--output", default="output/cidmap_compare.html")
    cp.set_defaults(fn=cmd_compare)

    qu = sub.add_parser("quorum",
                        help="per-CID concurrence: decoder store vs OCR reads")
    qu.add_argument("pdf")
    qu.add_argument("--store", default=DEFAULT_STORE)
    qu.add_argument("--random", type=int, default=5,
                    help="pages to sample for the quorum")
    qu.add_argument("--seed", type=int, default=None)
    qu.add_argument("--html", default=None, help="write an HTML report too")
    qu.set_defaults(fn=cmd_quorum)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
