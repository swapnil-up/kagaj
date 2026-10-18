"""``water_parser process`` — download sources and extract per-branch JSON.

For each selected manifest entry:

1. download the attachment into ``output/water/raw/`` (cached by file name);
2. extract to the normalised reservoir/zone shape, then write
   ``water/<branch>__<month_key>.json`` (tracked).

Two extraction paths:

* **pdf + marked regions** → deterministic spatial extraction
  (:mod:`water_parser.extract`): column geometry + fixed field parsers, with only
  area-name transliteration going through Gemini;
* **otherwise** → flatten to reading-order text and send the whole thing to
  Gemini with the fixed schedule schema.

Selection: ``--month``, ``--branch``, ``--limit``, ``--force`` (reprocess done).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
import urllib3

from .. import columns as colmod
from .. import gemini, paths, schema, text, validate

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(name: str) -> str:
    return _SAFE_RE.sub("_", name).strip("_")


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(
        url, timeout=120, verify=False,
        headers={"User-Agent": "Mozilla/5.0 (compatible; water-parser/0.1)"},
    )
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _select(entries: list[dict], args) -> list[dict]:
    out = []
    for e in entries:
        if args.month and e["month_key"].lower() != args.month.lower():
            continue
        if args.branch and args.branch.lower() not in e["branch"].lower():
            continue
        if e["kind"] not in ("pdf", "xlsx"):
            continue
        if e.get("status") == "done" and not args.force:
            continue
        out.append(e)
    if args.limit:
        out = out[: args.limit]
    return out


def run(args) -> int:
    paths.load_env()
    if not paths.MANIFEST.exists():
        print("[process] no manifest — run `python -m water_parser.cli scrape` first")
        return 1

    manifest = json.loads(paths.MANIFEST.read_text())
    entries = manifest["entries"]
    selected = _select(entries, args)
    if not selected:
        print("[process] nothing to do (use --force to reprocess)")
        return 0

    print(f"[process] {len(selected)} file(s)")
    failures = 0
    for i, entry in enumerate(selected, 1):
        label = f"{entry['branch']} {entry['month_key']}"
        print(f"\n[process] ({i}/{len(selected)}) {label} [{entry['kind']}]")
        try:
            _process_one(entry, force=args.force)
        except Exception as err:  # keep going; record failure
            entry["status"] = "failed"
            entry["error"] = str(err)[:300]
            print(f"[process]   FAILED: {err}")
            failures += 1
        _save_manifest(manifest)

    _save_manifest(manifest)
    print(f"\n[process] done — {len(selected) - failures} ok, {failures} failed")
    return 0 if failures == 0 else 1


def _process_one(entry: dict, force: bool = False) -> None:
    filename = unquote(entry["filename"])
    raw_path = paths.RAW_DIR / _slug(filename)
    text_path = paths.TEXT_DIR / (_slug(raw_path.stem) + ".txt")

    regions = colmod.load_regions(paths.COLUMN_REGIONS)
    use_spatial = entry["kind"] == "pdf" and colmod.regions_for(regions, entry["branch"])

    if use_spatial:
        result = _extract_spatial(entry, raw_path, regions)
    else:
        result = _extract_llm(entry, raw_path, text_path, force)

    result["source"] = {
        "branch": entry["branch"],
        "month_key": entry["month_key"],
        "url": entry["url"],
        "file": filename,
        "kind": entry["kind"],
        "method": "spatial" if use_spatial else "llm",
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out_path = paths.WATER_DIR / f"{_slug(entry['branch'])}__{entry['month_key']}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    entry["structured_path"] = str(out_path.relative_to(paths.REPO_ROOT))
    entry["status"] = "done"
    entry.pop("error", None)

    reservoirs = result.get("reservoirs", [])
    zones = sum(len(r.get("zones", [])) for r in reservoirs)
    flags = sum(len(z.get("review_flags") or []) for r in reservoirs for z in r.get("zones", []))
    print(f"[process]   → {len(reservoirs)} reservoirs, {zones} zones"
          + (f", {flags} flags" if flags else "") + f" → {out_path.name}")


def _extract_spatial(entry: dict, raw_path: Path, regions: dict) -> dict:
    from .. import extract

    _download(entry["url"], raw_path)
    entry["downloaded_path"] = str(raw_path.relative_to(paths.REPO_ROOT))
    print(f"[process]   spatial path (marked regions)")
    return extract.extract_pdf(
        raw_path, regions, entry["branch"],
        branch_np=paths.branch_np(entry["branch"]),
        branch_en=entry["branch"],
        month_bs=paths.month_bs(entry["month_key"]),
        log=print,
    )


def _extract_llm(entry: dict, raw_path: Path, text_path: Path, force: bool) -> dict:
    # Reuse cached plain text across prompt iterations (OCR is the slow part).
    if text_path.exists() and not force:
        cached = text_path.read_text(encoding="utf-8")
        doc = {"kind": entry["kind"], "text": cached}
        print(f"[process]   cached text: {len(cached)} chars")
    else:
        _download(entry["url"], raw_path)
        entry["downloaded_path"] = str(raw_path.relative_to(paths.REPO_ROOT))
        doc = text.document_text(raw_path, log=print)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(doc["text"], encoding="utf-8")
        print(f"[process]   {doc['kind']}: {len(doc['text'])} chars of text")
    entry["text_path"] = str(text_path.relative_to(paths.REPO_ROOT))

    result = gemini.call_structured(schema.build_prompt(doc["text"]))
    for reservoir in result.get("reservoirs", []):
        for zone in reservoir.get("zones", []):
            zone["review_flags"] = validate.flag_zone(zone)
    return result


def _save_manifest(manifest: dict) -> None:
    paths.MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
