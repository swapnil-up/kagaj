# Kagaj explorer

A read-only query surface over the committed datasets, running entirely in the
browser. sql.js executes SQLite as WebAssembly against a single fetched file —
no backend, no build step, deployable as static files on Vercel.

## Run it

```bash
# 1. build the database from datasets/index.json
python datasets/build_sqlite.py

# 2. serve the repo root (the page fetches ../output/explorer/kagaj.sqlite.gz)
python -m http.server

# 3. open http://localhost:8000/explorer/
```

Opening `index.html` over `file://` will not work — browsers block the fetch.

## What's in it

| | |
|---|---|
| `kagaj.sqlite` | 36.6 MB, 19 tables — for `sqlite3` on the command line |
| `kagaj.sqlite.gz` | 2.4 MB — what the browser loads, decompressed with `DecompressionStream` |

Tables are generated from `datasets/index.json`: every `csv`/`csv.gz` artifact
declared in a dataset descriptor, except role `raw` (provenance) and any table
over 2 MB that is not `primary`/`canonical`/`rollup` — so the unfinished archive
backfill and the specialist `agencies`/`series` files stay in their CSVs. The
water schedule JSON is flattened into `water_branches` and `water_zones`.

Descriptor metadata is embedded as two tables so the page needs no other file:

- `catalog` — one row per dataset: grain, coverage, verification, sources, licence
- `catalog_tables` — one row per table: role, row count, description

## Using it

- **Browse** — pick a dataset, pick a table, page through it. Click a column
  header to sort.
- **Filter** — column + operator + value, added as removable chips. Composed
  with `AND`.
- **SQL** — the box runs `SELECT` / `WITH` / `EXPLAIN` only; `Ctrl/Cmd+Enter`
  runs it. One statement at a time. `browse` returns to the filterable view.
- **Export CSV** — downloads whatever the current query returned.

The database is opened in memory; nothing you type can modify the file on disk,
and non-`SELECT` statements are rejected before they reach SQLite.

## Notes

- Rebuild after any data change: `python datasets/build_sqlite.py` (the
  descriptor test does not cover this file — it is a build artifact, not a
  committed output).
- Parliament text is deliberately absent: document corpora are a semantic-search
  problem, tracked separately as A3 in `docs/roadmap.md`.
