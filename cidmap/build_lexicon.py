"""Rebuild the committed Nepali lexicon used by cidmap inference."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from kagaj_core.devanagari import canonical_key

_PACKAGE = Path(__file__).resolve().parent
_REPO = _PACKAGE.parent


def _words_from(source: Path):
    with sqlite3.connect(str(source)) as conn:
        rows = conn.execute("select value from word").fetchall()
    seen = set()
    words = []
    for row in rows:
        word = (row[0] or "").strip()
        if not word or not any("\u0900" <= char <= "\u097f" for char in word):
            continue
        key = canonical_key(word, drop_joiners=True)
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
    return sorted(words)


def build(source: Path, output: Path, provenance: Path) -> dict:
    words = _words_from(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{word}\n" for word in words).encode("utf-8")
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
            handle.write(payload)
    digest = hashlib.sha256(payload).hexdigest()
    meta = {
        "source": source.name,
        "rows": len(words),
        "sha256": digest,
        "builder": "cidmap.build_lexicon",
    }
    provenance.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        default=_REPO / "dictionary-data" / "nep_dict.sqlite3",
    )
    parser.add_argument(
        "--output", type=Path,
        default=_PACKAGE / "data" / "nepali_lexicon.txt.gz",
    )
    parser.add_argument(
        "--provenance", type=Path,
        default=_PACKAGE / "data" / "nepali_lexicon.json",
    )
    args = parser.parse_args(argv)
    meta = build(args.source, args.output, args.provenance)
    print(f"wrote {args.output} ({meta['rows']} words, {meta['sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
