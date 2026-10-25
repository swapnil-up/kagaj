"""CLI: cidmap scan <pdf> | cidmap review <pdf> | cidmap probe <pdf>
       cidmap registry ingest <pdf> | cidmap promote <pdf>
       cidmap autoscope <pdf> | cidmap repair <pdf>
       cidmap commit <decisions.json>

``scan``     decode -> (optional OCR) -> conflict decision sheet (+ census JSON),
``review``   unknown-CID PDF crops -> neutral review sheet for human mapping,
``probe``    read-only font coverage, hybrid classes, and fingerprint report,
``infer``    read-only shape-run candidates for unknown CIDs,
``registry`` record or query cross-document glyph evidence,
``promote``  dry-run or apply registry-backed mappings to the canonical store,
``autoscope`` bootstrap exact reference-outline matches into font-scoped store
             mappings (dry-run by default),
``repair``   write a copy with store-backed ToUnicode CMap additions,
``commit``   fold a neutral decisions.json into the canonical store (font-scoped
             only), ``seed`` fold a derive output into the store as fallbacks.
``legacy-import`` validate externally labelled legacy glyph CSVs and optionally
             merge them into the legacy font table.
``quorum``   OCR cross-check per unknown CID.

Default store: ``cidmap/data/cid_mappings.json`` (tracked, the consumable map).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .decisions import apply_decisions
from .legacy_tables import DEFAULT_TABLE
from .decode import census, flatten, glyphs as extract_glyphs
from .mappings import load, save, merge_derive_results
from .reference_fonts import reference_font_arg
from .registry import DEFAULT_REGISTRY
from .review import build_review_html

DEFAULT_STORE = "cidmap/data/cid_mappings.json"


def _doc(args):
    import fitz  # lazy
    if not os.path.exists(args.pdf):
        print(f"Error: {args.pdf} not found", file=sys.stderr)
        return None
    return fitz.open(args.pdf)


def _reference_fonts_arg(values):
    from .reference_fonts import ReferenceFontError, resolve_reference_fonts

    paths = []
    for value in values or []:
        for item in str(value).split(","):
            if not item.strip():
                continue
            try:
                paths.extend(resolve_reference_fonts(item.strip()))
            except ReferenceFontError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return None
    return [str(path) for path in dict.fromkeys(paths)]


def cmd_scan(args) -> int:
    doc = _doc(args)
    if doc is None:
        return 1

    issues: list[dict] = []
    cen = census(doc, max_pages=args.max_pages, issues=issues)
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
    htmlout = build_review_html(
        doc, store, ocr_data, only_font=args.font,
        max_pages=args.max_pages, census_result=cen, issues=issues,
        session=f"cidmap:{os.path.abspath(args.pdf)}:"
                f"{os.path.abspath(args.store)}")
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


def cmd_glyph_review(args) -> int:
    from .glyph_review import build_review_html as build_glyph_review_html

    doc = _doc(args)
    if doc is None:
        return 1
    if args.reference_font and not os.path.exists(args.reference_font):
        print(f"Error: {args.reference_font} not found", file=sys.stderr)
        return 1
    out = args.output
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if args.shape_runs and not args.reference_font:
        print("Error: --shape-runs requires --reference-font",
              file=sys.stderr)
        return 1
    registry = None
    if getattr(args, "registry", None):
        from . import registry as registry_mod
        registry = registry_mod.load(args.registry)
    htmlout = build_glyph_review_html(
        doc, args.crop, only=args.cids,
        reference_font=args.reference_font,
        shape_runs=args.shape_runs,
        registry=registry,
        session=f"cidmap:{os.path.abspath(args.pdf)}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)", file=sys.stderr)
    return 0


def cmd_probe(args) -> int:
    from .probe import format_probe, probe_document

    doc = _doc(args)
    if doc is None:
        return 1
    reference_fonts = _reference_fonts_arg(
        getattr(args, "reference_fonts", None))
    if reference_fonts is None:
        return 1
    if args.reference_font and not os.path.exists(args.reference_font):
        print(f"Error: {args.reference_font} not found", file=sys.stderr)
        return 1
    kwargs = {
        "max_pages": args.max_pages,
        "reference_font": args.reference_font,
        "reference_fonts": reference_fonts or None,
    }
    registry_path = getattr(args, "registry", None)
    if registry_path:
        from . import registry as registry_mod
        kwargs["registry"] = registry_mod.load(registry_path)
    try:
        result = probe_document(doc, **kwargs)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(format_probe(result))
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
    return 0


def cmd_infer(args) -> int:
    from .infer import (
        aggregate_cids, format_inference, infer_runs, inference_payload,
    )

    doc = _doc(args)
    if doc is None:
        return 1
    if not args.reference_font:
        print("Error: --reference-font is required", file=sys.stderr)
        return 1
    if not os.path.exists(args.reference_font):
        print(f"Error: {args.reference_font} not found", file=sys.stderr)
        return 1
    try:
        inferences = infer_runs(
            doc,
            reference_font=args.reference_font,
            lexicon=args.lexicon,
            max_pages=args.max_pages,
            max_candidates=args.max_candidates,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    cids = args.cids
    if cids is not None:
        inferences = [
            inference for inference in inferences
            if any(
                assignment.cid in cids
                for candidate in inference.candidates
                for assignment in candidate.assignments
            )
        ]
    print(format_inference(inferences))
    if args.json:
        payload = inference_payload(inferences, cids=cids)
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
        for item in aggregate_cids(inferences):
            if cids is None or item.cid in cids:
                print(f"CID {item.cid}: {item.value} ({item.score:.1f})",
                      file=sys.stderr)
    return 0


def _registry_matches(doc, cid: int, only_font: str | None = None,
                     max_pages=None, issues=None):
    from .fonts import FontResolutionError

    seen = set()
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    for pn in pages:
        try:
            page_glyphs = extract_glyphs(doc[pn], dedup=True)
        except FontResolutionError as exc:
            if issues is not None:
                issues.append({
                    "page": pn + 1,
                    "kind": type(exc).__name__,
                    "message": str(exc),
                })
            continue
        for glyph in page_glyphs:
            if glyph.get("cid") != cid:
                continue
            font_id = glyph.get("font_id") or ""
            if only_font and font_id != only_font:
                continue
            identity = (font_id, glyph.get("font_xref"))
            if identity in seen:
                continue
            seen.add(identity)
            yield glyph


def cmd_registry(args) -> int:
    from . import registry as registry_mod

    doc = _doc(args)
    if doc is None:
        return 1
    store = load(args.store)
    registry = registry_mod.load(args.registry)

    if args.action == "ingest":
        issues = []
        added = registry_mod.ingest_document(
            doc, store, registry=registry, max_pages=args.max_pages,
            issues=issues)
        registry_mod.save(registry, args.registry)
        observations = sum(
            len(entry.get("observations") or [])
            for entry in registry.get("glyphs", {}).values())
        print(f"Added {added} observation(s); registry has {observations} "
              f"across {len(registry.get('glyphs', {}))} glyph(s) -> "
              f"{args.registry}", file=sys.stderr)
        if issues:
            print(f"Skipped {len(issues)} page(s) with ambiguous fonts",
                  file=sys.stderr)
        return 0

    if args.cid is None:
        print("Error: registry query requires --cid", file=sys.stderr)
        return 1
    from .embedded import EmbeddedFontCache

    embedded = EmbeddedFontCache(doc)
    rows = []
    issues = []
    for glyph in _registry_matches(
            doc, args.cid, args.font, args.max_pages, issues=issues):
        bundle = registry_mod.resolve_glyph(
            registry, embedded, glyph.get("font_xref"), args.cid,
            glyph.get("base_font") or "")
        rows.append({
            "font_id": glyph.get("font_id") or "",
            "font_xref": glyph.get("font_xref"),
            "cid": args.cid,
            "entry": bundle.get("entry") if bundle else None,
            "family_hash": bundle.get("family_hash") if bundle else None,
            "outline_hash": bundle.get("outline_hash") if bundle else None,
        })
    if issues:
        print(f"Skipped {len(issues)} page(s) with ambiguous fonts",
              file=sys.stderr)
    if args.json:
        path = args.json
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cid": args.cid, "matches": rows}, f,
                      ensure_ascii=False, indent=2)
        print(f"Wrote {path}", file=sys.stderr)
    if not rows:
        print(f"No observed glyph for CID {args.cid}", file=sys.stderr)
        return 0
    for row in rows:
        print(f"[{row['font_id']}] xref {row['font_xref']}")
        print(registry_mod.format_entry(row["entry"]))
    return 0


def cmd_promote(args) -> int:
    from . import registry as registry_mod
    from .confidence import format_candidates, promote_document

    doc = _doc(args)
    if doc is None:
        return 1
    store = load(args.store)
    registry = registry_mod.load(args.registry)
    issues = []
    candidates = promote_document(
        doc, store, registry,
        reference_font=args.reference_font,
        lexicon=args.lexicon,
        max_pages=args.max_pages,
        cids=args.cids,
        issues=issues,
    )
    print(format_candidates(candidates))
    if issues:
        print(f"Skipped {len(issues)} page(s) with ambiguous fonts",
              file=sys.stderr)

    promotable = [candidate for candidate in candidates if candidate.promotable]
    promoted = []
    if args.apply and promotable:
        result = apply_decisions(store, [c.decision() for c in promotable])
        if not result.ok:
            for message in result.errors:
                print(f"Error: {message}", file=sys.stderr)
            print("No changes written; resolve the conflicts above.",
                  file=sys.stderr)
            return 1
        save(store, args.store)
        promoted = [candidate.to_dict() for candidate in promotable]
        print(f"Promoted {result.values} mapping(s) -> {args.store}",
              file=sys.stderr)
    elif args.apply:
        print("Nothing to promote.", file=sys.stderr)

    if args.json:
        path = args.json
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "candidates": [candidate.to_dict() for candidate in candidates],
            "promoted": promoted,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {path}", file=sys.stderr)
    return 0




def cmd_autoscope(args) -> int:
    from .autoscope import (
        apply_scope_plan,
        build_scope_plan,
        format_plan,
        rejected_jsonl,
    )

    doc = _doc(args)
    if doc is None:
        return 1
    reference_fonts = _reference_fonts_arg(
        getattr(args, "reference_fonts", None))
    if reference_fonts is None:
        return 1
    if args.reference_font and not os.path.exists(args.reference_font):
        print(f"Error: {args.reference_font} not found", file=sys.stderr)
        return 1
    if not args.reference_font and not reference_fonts:
        print("Error: pass --reference-font or --reference-fonts", file=sys.stderr)
        return 1
    store = load(args.store)
    plan = build_scope_plan(
        doc, store,
        reference_font=args.reference_font,
        reference_fonts=reference_fonts or None,
        max_pages=args.max_pages,
        max_score=args.max_score,
        min_margin=args.min_margin,
        lexicon=None if args.lexicon is True else args.lexicon,
    )
    print(format_plan(plan))
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
    if args.rejected_out:
        os.makedirs(os.path.dirname(args.rejected_out) or ".", exist_ok=True)
        with open(args.rejected_out, "w", encoding="utf-8") as f:
            f.write(rejected_jsonl(plan))
        print(f"Wrote {args.rejected_out}", file=sys.stderr)
    if not args.apply:
        return 0
    if not plan.mappings:
        print("Nothing to add.", file=sys.stderr)
        return 0
    count = apply_scope_plan(store, plan)
    save(store, args.store)
    print(f"Added {count} font-scoped mapping(s) -> {args.store}",
          file=sys.stderr)
    return 0


def cmd_repair(args) -> int:
    from .repair import build_repair_plan, format_plan, write_repair

    doc = _doc(args)
    if doc is None:
        return 1
    output = getattr(args, "output", None)
    if output:
        source = os.path.abspath(args.pdf)
        target = os.path.abspath(output)
        if source == target:
            print("Error: output must differ from the source PDF",
                  file=sys.stderr)
            return 1
        if os.path.exists(target) and not args.force:
            print(f"Error: {output} exists (use --force to overwrite)",
                  file=sys.stderr)
            return 1
    store = load(args.store)
    plan = build_repair_plan(
        doc, store,
        replace_conflicts=args.replace_conflicts,
        max_pages=args.max_pages,
    )
    print(format_plan(plan))
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
    if not output:
        return 0
    if not plan.changed:
        print("No changes; no output written.", file=sys.stderr)
        return 0
    try:
        count = write_repair(doc, plan, output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output} ({count} font(s) repaired)", file=sys.stderr)
    return 0


def cmd_legacy_import(args) -> int:
    from .legacy_tables import (
        build_table, load_table, read_rows, save_table, validate_rows,
    )

    rows = []
    for path in args.csv:
        try:
            rows.extend(read_rows(path))
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    catalog = None
    if args.catalog:
        try:
            catalog = read_rows(args.catalog)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    problems = validate_rows(rows, catalog)
    if problems:
        for problem in problems[:100]:
            print(f"{problem.source}:{problem.line}: {problem.message}",
                  file=sys.stderr)
        if len(problems) > 100:
            print(f"... {len(problems) - 100} more problem(s)",
                  file=sys.stderr)
        print(f"{len(problems)} validation problem(s)", file=sys.stderr)
        return 1

    existing = load_table(args.table) if args.apply else None
    table = build_table(rows, existing=existing)
    families = sorted(table.get("families", {}))
    filled = sum(1 for row in rows if row.unicode)
    if not filled:
        print("Error: no Unicode labels found in the returned CSV",
              file=sys.stderr)
        return 1
    print(f"{len(rows)} row(s), {filled} filled, "
          f"{len(rows) - filled} blank, {len(families)} family/families")
    print("families: " + ", ".join(families))
    if args.json:
        payload = {
            "rows": len(rows),
            "filled": filled,
            "blank": len(rows) - filled,
            "families": families,
            "applied": bool(args.apply),
            "table": table,
        }
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
    if args.apply:
        save_table(table, args.table)
        print(f"Wrote {args.table}", file=sys.stderr)
    else:
        print("Dry run; pass --apply to write the table.", file=sys.stderr)
    return 0


def cmd_commit(args) -> int:
    if not os.path.exists(args.decisions):
        print(f"Error: {args.decisions} not found", file=sys.stderr)
        return 1
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)
    if not isinstance(decisions, list):
        print("Error: decisions file must contain a JSON list", file=sys.stderr)
        return 1

    store = load(args.store)
    result = apply_decisions(store, decisions)
    if not result.ok:
        for message in result.errors:
            print(f"Error: {message}", file=sys.stderr)
        print("No changes written; resolve the conflicts above.",
              file=sys.stderr)
        return 1

    save(store, args.store)
    print(f"Committed {result.values} values, {result.undecodable} undecodable, "
          f"{result.unchanged} unchanged -> {args.store}", file=sys.stderr)
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
    sc.add_argument("--font", default=None, help="restrict to one font_id")
    sc.add_argument("--max-pages", type=int, default=None)
    sc.add_argument("-o", "--output", default="output/cidmap_review.html")
    sc.add_argument("--census", default=None, help="also dump census JSON")
    sc.set_defaults(fn=cmd_scan)

    gr = sub.add_parser("review", help="unknown-CID PDF crops -> review HTML")
    gr.add_argument("pdf")
    gr.add_argument("--output", "-o", default="output/cid_review.html")
    gr.add_argument("--crop", type=int, default=3,
                    help="render samples per (font, CID) pair")
    gr.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                    default=None, help="restrict to these CIDs (comma-separated)")
    gr.add_argument("--reference-font", default=None, type=reference_font_arg,
                    help="original TTF/OTF used to suggest glyph values")
    gr.add_argument("--shape-runs", action="store_true",
                    help="add shape-run candidates (requires --reference-font)")
    gr.add_argument("--registry", default=None,
                    help="cross-document glyph registry for candidates")
    gr.set_defaults(fn=cmd_glyph_review)

    pr = sub.add_parser("probe",
                        help="read-only font coverage/fingerprint report")
    pr.add_argument("pdf")
    pr.add_argument("--max-pages", type=int, default=None)
    pr.add_argument("--reference-font", default=None, type=reference_font_arg,
                    help="original TTF/OTF used to suggest unknown glyph values")
    pr.add_argument("--reference-fonts", nargs="+", default=None,
                    help="family aliases/paths; exact requires agreement")
    pr.add_argument("--registry", default=None,
                    help="annotate unknown CIDs with cross-document evidence")
    pr.add_argument("--json", default=None,
                    help="write the full report as JSON")
    pr.set_defaults(fn=cmd_probe)

    inf = sub.add_parser(
        "infer", help="read-only shape-run candidates for unknown CIDs")
    inf.add_argument("pdf")
    inf.add_argument("--reference-font", required=True, type=reference_font_arg,
                     help="original TTF/OTF used to shape candidate words")
    inf.add_argument("--lexicon", default=None,
                     help="lexicon text/gzip/SQLite (default: local or committed)")
    inf.add_argument("--max-pages", type=int, default=None)
    inf.add_argument("--max-candidates", type=int, default=5)
    inf.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                     default=None, help="restrict output to these CIDs")
    inf.add_argument("--json", default=None,
                     help="write run and CID candidates as JSON")
    inf.set_defaults(fn=cmd_infer)

    rg = sub.add_parser("registry",
                        help="record or query cross-document glyph evidence")
    rg.add_argument("action", choices=("ingest", "query"))
    rg.add_argument("pdf")
    rg.add_argument("--store", default=DEFAULT_STORE)
    rg.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    rg.add_argument("--cid", type=int, default=None)
    rg.add_argument("--font", default=None)
    rg.add_argument("--max-pages", type=int, default=None)
    rg.add_argument("--json", default=None)
    rg.set_defaults(fn=cmd_registry)

    pm = sub.add_parser(
        "promote", help="dry-run or apply registry-backed mappings")
    pm.add_argument("pdf")
    pm.add_argument("--store", default=DEFAULT_STORE)
    pm.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    pm.add_argument("--reference-font", default=None, type=reference_font_arg,
                    help="original TTF/OTF used to confirm shape runs")
    pm.add_argument("--lexicon", default=None,
                    help="lexicon text/gzip/SQLite for shape-run evidence")
    pm.add_argument("--max-pages", type=int, default=None)
    pm.add_argument("--cids", type=lambda s: {int(x) for x in s.split(",")},
                    default=None, help="restrict to these CIDs (comma-separated)")
    mode = pm.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="write promotable mappings")
    mode.add_argument("--dry-run", action="store_true",
                      help="report candidates without writing (default)")
    pm.add_argument("--json", default=None,
                    help="write the full candidate report as JSON")
    pm.set_defaults(fn=cmd_promote)



    au = sub.add_parser(
        "autoscope",
        help="bootstrap exact reference-outline matches into font-scoped mappings")
    au.add_argument("pdf")
    au.add_argument("--reference-font", default=None, type=reference_font_arg)
    au.add_argument("--reference-fonts", nargs="+", default=None,
                    help="family aliases/paths; exact requires agreement")
    au.add_argument("--store", default=DEFAULT_STORE)
    au.add_argument("--max-pages", type=int, default=None)
    au.add_argument("--max-score", type=float, default=0.75,
                    help="maximum outline distance for a near match")
    au.add_argument("--min-margin", type=float, default=1.0,
                    help="minimum score gap to the next candidate value")
    au.add_argument("--lexicon", nargs="?", const=True, default=False,
                    help="enable lexicon/shape-run context for near and "
                         "ambiguous exact matches (optional lexicon path)")
    mode = au.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="write mappings to the store")
    mode.add_argument("--dry-run", action="store_true",
                      help="report without writing (default)")
    au.add_argument("--json", default=None)
    au.add_argument("--rejected-out", default=None,
                    help="write rejected candidates as JSONL for review triage")
    au.set_defaults(fn=cmd_autoscope)

    rp = sub.add_parser(
        "repair", help="write a copy with store-backed ToUnicode entries")
    rp.add_argument("pdf")
    rp.add_argument("--store", default=DEFAULT_STORE)
    rp.add_argument("-o", "--output", default=None,
                    help="write the repaired PDF here (default: dry-run)")
    rp.add_argument("--replace-conflicts", action="store_true",
                    help="replace existing CMap values that disagree with the store")
    rp.add_argument("--max-pages", type=int, default=None)
    rp.add_argument("--force", action="store_true",
                    help="overwrite an existing output file")
    rp.add_argument("--json", default=None,
                    help="write the repair plan as JSON")
    rp.set_defaults(fn=cmd_repair)

    cm = sub.add_parser("commit", help="fold decisions.json into the store")
    cm.add_argument("decisions")
    cm.add_argument("--store", default=DEFAULT_STORE)
    cm.set_defaults(fn=cmd_commit)

    sd = sub.add_parser("seed", help="fold a derive output in as fallbacks")
    sd.add_argument("derive", help="derive output JSON")
    sd.add_argument("--store", default=DEFAULT_STORE)
    sd.set_defaults(fn=cmd_seed)

    li = sub.add_parser(
        "legacy-import",
        help="validate labelled legacy glyph CSVs and merge the font table")
    li.add_argument("csv", nargs="+", help="filled codes.csv files")
    li.add_argument("--catalog", default=None,
                    help="original codes.csv/mapping-template.csv to match")
    li.add_argument("--table", default=str(DEFAULT_TABLE))
    li.add_argument("--apply", action="store_true",
                    help="write the merged table (default: dry run)")
    li.add_argument("--json", default=None,
                    help="write a validation/import report as JSON")
    li.set_defaults(fn=cmd_legacy_import)

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
