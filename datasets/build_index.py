#!/usr/bin/env python3
"""Build datasets/translations/INDEX.md from the tracked manifests."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = REPO_ROOT / "datasets" / "translations"
OUT = TRANSLATIONS / "INDEX.md"

SOURCES = [
    ("Notices — 7th House of Representatives", REPO_ROOT / "parliament" / "manifests" / "notices.json", "title"),
    ("Notices — 6th House of Representatives (archive)", REPO_ROOT / "parliament" / "manifests" / "notices-6th-hor.json", "title"),
    ("Verbatims — National Assembly, sessions 19+", REPO_ROOT / "parliament" / "manifests" / "verbatims.json", "title"),
    ("Verbatims — National Assembly (archive)", REPO_ROOT / "parliament" / "manifests" / "verbatims-archive.json", "title"),
    ("Drug prices — Department of Drug Administration", REPO_ROOT / "drug_prices" / "manifests" / "dda_medicines.json", "title"),
]


def label(entry: dict, key: str) -> str:
    return str(entry.get(key) or entry.get("na_id") or entry.get("serial") or "untitled")


def main() -> None:
    lines = [
        "# Translation index",
        "",
        "Generated from the tracked manifests by `python datasets/build_index.py`.",
        "Do not edit by hand.",
        "",
    ]
    total = 0
    for heading, manifest_path, key in SOURCES:
        if not manifest_path.exists():
            continue
        try:
            entries = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        lines += [f"## {heading}", "", "| Document | Status | Files |", "|---|---|---|"]
        for entry in entries:
            status = entry.get("status", "?")
            stem = Path(entry.get("structured_path") or entry.get("translated_path") or "").name
            if not stem:
                stem = Path(entry.get("ocr_path") or "").name
            files = []
            for label_, field in (("ocr", "ocr_path"), ("en", "translated_path"), ("json", "structured_path")):
                path = entry.get(field)
                if not path:
                    continue
                name = Path(path).name
                target = quote(name)
                if (TRANSLATIONS / name).exists():
                    files.append(f"[{label_}]({target})")
                else:
                    files.append(f"{label_} (missing)")
            lines.append(f"| {label(entry, key)} | `{status}` | {' '.join(files) or '—'} |")
            total += 1
        lines.append("")
    lines += [
        "---",
        "",
        f"{total} manifest entries. Files live in this directory.",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({total} entries)")


if __name__ == "__main__":
    main()
