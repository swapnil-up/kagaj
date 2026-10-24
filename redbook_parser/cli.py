"""CLI: redbook extract <pdf> | redbook verify <db> | redbook census <pdf>"""

import argparse
import json
import os
import sys

from cidmap.reference_fonts import reference_font_arg

from .census import build_unknown_census, census_to_rows
from .db import read_rows, write_db
from .review import build_review_html
from .extraction import extract_page_text
from .legacy import fix_text
from .pipeline import extract_pdf
from .verify import BudgetVerificationEngine


def cmd_extract(args) -> int:
    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return 1

    output_path = args.output
    if not output_path and args.sqlite:
        base = os.path.splitext(os.path.basename(args.pdf))[0]
        output_path = f"output/{base}.db"

    # Load store-backed CID map if requested.
    cid_map = None
    if args.cid_map:
        from .loader import load_store
        approved, rejections = load_store(args.cid_map)
        cid_map = approved
        for reason, entries in rejections.items():
            for e in entries:
                print(f"  reject cid={e['cid']:<3} value={e['value']!r} "
                      f"reason={reason}", file=sys.stderr)
        print(f"Loaded {len(approved)} CID mappings from {args.cid_map}",
              file=sys.stderr)

    rows = extract_pdf(args.pdf, max_pages=args.max_pages,
                       start_page=args.start_page, cid_map=cid_map,
                       verify=args.verify)
    if args.verify:
        rows, report = rows
        print(report.summary(), file=sys.stderr)
        for c in report.failures:
            print(f"  FAIL  {c}", file=sys.stderr)
        for c in report.need_review:
            print(f"  REVIEW {c}", file=sys.stderr)
        for c in report.cross_failures:
            print(f"  XFAIL {c}", file=sys.stderr)
    if args.sqlite and output_path:
        import fitz  # lazy
        doc = fitz.open(args.pdf)
        page_texts = [fix_text(extract_page_text(doc, p)) for p in range(len(doc))]
        write_db(rows, page_texts, output_path)
        print(f"Wrote {len(rows)} rows to {output_path}", file=sys.stderr)
    return 0


def cmd_verify(args) -> int:
    rows = read_rows(args.db)
    report = BudgetVerificationEngine().verify_rows(rows)
    print(report.summary())
    for c in report.failures:
        print(f"  FAIL  {c}")
    for c in report.need_review:
        print(f"  REVIEW {c}")
    for c in report.checks:
        if c.ok:
            print(f"  ok    {c}")
    return 1 if report.failures else 0


def cmd_census(args) -> int:
    import fitz  # lazy

    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return 1
    doc = fitz.open(args.pdf)
    unknown = build_unknown_census(doc)
    payload = {
        "pdf": args.pdf,
        "pages": len(doc),
        "unknown_cid_count": len(unknown),
        "note": (
            "Each row is a CID that decodes to U+FFFD (missing from a page "
            "font-object's ToUnicode CMap). Fill 'correct' with the intended "
            "Devanagari; contexts give the surrounding word so the glyph is "
            "decidable."),
        "rows": census_to_rows(unknown),
    }
    out = args.output or "output/cid_census.json"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(payload['rows'])} unknown CIDs to {out}", file=sys.stderr)
    return 0


def cmd_review(args) -> int:
    import fitz  # lazy

    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return 1
    if args.reference_font and not os.path.exists(args.reference_font):
        print(f"Error: {args.reference_font} not found", file=sys.stderr)
        return 1
    if args.shape_runs and not args.reference_font:
        print("Error: --shape-runs requires --reference-font",
              file=sys.stderr)
        return 1
    doc = fitz.open(args.pdf)
    out = args.output or "output/cid_review.html"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    registry = None
    if getattr(args, "registry", None):
        from cidmap import registry as registry_mod
        registry = registry_mod.load(args.registry)
    htmlout = build_review_html(
        doc, args.crop, only=args.cids,
        session=f"redbook:{os.path.abspath(args.pdf)}",
        reference_font=args.reference_font, shape_runs=args.shape_runs,
        registry=registry)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)", file=sys.stderr)
    return 0


def cmd_derive(args) -> int:
    from .derive import derive, load_corrections
    import fitz  # lazy

    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return 1
    if not os.path.exists(args.corrections):
        print(f"Error: {args.corrections} not found", file=sys.stderr)
        return 1

    with open(args.corrections, encoding="utf-8") as f:
        recs = json.load(f)
    corrections = load_corrections(recs)
    if not corrections:
        print("No non-empty corrections found in the file", file=sys.stderr)
        return 1

    doc = fitz.open(args.pdf)
    results = derive(doc, corrections, max_span_evidence=200,
                     max_pages=args.max_pages)

    out = args.output or "output/cid_mappings.json"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    flags = {"ok": "OK", "partial": "PARTIAL", "ambiguous": "AMBIG",
             "no-solution": "NONE", "no-windows": "NOWIN"}
    for cid, r in sorted(results.items(), key=lambda kv: int(kv[0])):
        print(f"  [{flags[r['mode']]}] cid={cid:<3} -> {r['mapping']!r} "
              f"cands={r['candidates']} sol={r['windows_solved']}/{r['windows_total']}")
    n_ok = sum(r["mode"] in ("ok", "partial") for r in results.values())
    print(f"{n_ok}/{len(results)} CIDs resolved", file=sys.stderr)
    return 0 if n_ok == len(results) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="redbook",
                                     description="Spatial-first redbook budget extraction")
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="Extract budget rows from a PDF to SQLite")
    ex.add_argument("pdf")
    ex.add_argument("--start-page", type=int, default=1)
    ex.add_argument("--max-pages", type=int)
    ex.add_argument("--sqlite", action="store_true")
    ex.add_argument("--output", "-o")
    ex.add_argument("--cid-map", type=str, default=None,
                    help="Path to cidmap store JSON (default: cidmap/data/cid_mappings.json). "
                         "When set, font-scoped decode replaces legacy fix_text.")
    ex.add_argument("--verify", action="store_true",
                    help="Run math audit after extraction and report results.")
    ex.set_defaults(fn=cmd_extract)

    ve = sub.add_parser("verify", help="Run the math audit against a DB")
    ve.add_argument("db")
    ve.set_defaults(fn=cmd_verify)

    ce = sub.add_parser("census", help="List unknown-CID glyphs needing a Devanagari mapping")
    ce.add_argument("pdf")
    ce.add_argument("--output", "-o", help="JSON output path (default output/cid-unknown.json)")
    ce.set_defaults(fn=cmd_census)

    rv = sub.add_parser("review", help="HTML sheet with PDF crops for each unknown CID to fill in")
    rv.add_argument("pdf")
    rv.add_argument("--output", "-o", default="output/cid_review.html")
    rv.add_argument("--crop", type=int, default=3, help="render samples per CID")
    rv.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                    default=None, help="restrict to these CIDs (comma-separated)")
    rv.add_argument("--reference-font", default=None, type=reference_font_arg,
                    help="original TTF/OTF used to suggest glyph values")
    rv.add_argument("--shape-runs", action="store_true",
                    help="add shape-run candidates (requires --reference-font)")
    rv.add_argument("--registry", default=None,
                    help="cross-document glyph registry for candidates")
    rv.set_defaults(fn=cmd_review)

    dr = sub.add_parser("derive",
                        help="Turn typed word corrections into per-CID Devanagari mappings")
    dr.add_argument("pdf")
    dr.add_argument("corrections",
                    help="JSON list exported from the review sheet (neutral or {cid, correct})")
    dr.add_argument("--output", "-o", default="output/cid_mappings.json")
    dr.add_argument("--max-pages", type=int, default=None)
    dr.set_defaults(fn=cmd_derive)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
