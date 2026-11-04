# Dataset descriptor (`dataset.json`)

Every committed dataset under `datasets/<id>/` carries a `dataset.json`. It is
the stable, human-authored half of a dataset's metadata: what the data is, where
it came from, which files are the artifacts, and how to rebuild it. Volatile
numbers — row counts, byte sizes, SHA-256 fingerprints — live in the dataset's
existing build file (`build.json`) and are merged in at index time.

This is what a frontend, a catalog page, or a future `duckdb`/SQLite exporter
reads instead of reverse-engineering each pipeline.

## Naming

Two different things are called "manifest" in this repo, so they get different
filenames:

| Term | Meaning | Example |
|---|---|---|
| **Inventory** | the list of *source documents* scraped or processed | `parliament/manifests/notices.json`, `datasets/water/manifest.json` |
| **Descriptor** | the metadata *about the dataset itself* | `datasets/<id>/dataset.json` |

`dataset.json` never duplicates an inventory; it points at one via `inventories`.

## Shape

```jsonc
{
  "schema_version": "1.0",
  "id": "labour-migration",            // must equal the directory name
  "title": "Labour-migration panel",
  "status": "active",                  // active | experimental | archived
  "description": "One paragraph a catalog page can show as-is.",
  "grain": "one row per document × period × section × entity × channel × gender",
  "coverage": {
    "start": "FY2074/75",
    "end": "FY2082/83",
    "note": "optional qualifier (Bikram Sambat, partial months, …)"
  },
  "sources": [
    { "name": "Department of Foreign Employment", "url": "https://dofe.gov.np" }
  ],
  "artifacts": [
    { "path": "panel_canonical.csv.gz", "role": "primary", "format": "csv.gz" },
    { "path": "codebook.json",          "role": "metadata", "format": "json" }
  ],
  "inventories": ["datasets/labour-migration/manifests/migration_manifest.json"],
  "freshness": { "fingerprint": "build.json" },   // or ["build.json", "panel_archive_build.json"]
  "verification": {
    "status": "verified",              // verified | partial | none
    "method": "printed totals reconciled per document; gold-page tests",
    "report": "reconciliation.json"
  },
  "pipeline": {
    "package": "migration_parser",
    "cli": "python -m migration_parser.cli build",   // or a list of commands
    "plan": "docs/plans/… .md"          // optional
  },
  "docs": ["README.md", "DATA_AVAILABILITY.md"],
  "license": { "code": "MIT", "data": "MIT + source attribution; see DATA_AVAILABILITY.md" }
}
```

### Field rules

**Required:** `schema_version`, `id`, `title`, `status`, `description`, `grain`,
`coverage` (`start`, `end`), `sources`, `artifacts`, `verification`, `docs`,
`license`.

- `id` — `^[a-z0-9][a-z0-9-]*$`, must match the directory name.
- `status` — `active` (shipped and maintained), `experimental` (pipeline exists,
  output not trusted yet), `archived` (kept, not updated).
- `grain` — one sentence describing what one row/record *is*. This is the single
  most useful field for a consumer deciding whether a dataset answers their
  question.
- `coverage.start` / `coverage.end` — free-form strings; keep them consistent
  across datasets (`FY2074/75`, `Ashoj 2083`, `2075 Bhadra`).
- `sources[].url` — `http(s)://…`, or `"various"` when a dataset aggregates many
  URLs that the inventory already lists.
- `artifacts[].role` — `primary` (start here) · `canonical` · `raw` · `rollup` ·
  `reference` · `metadata` · `report` · `chart`. Exactly one `primary` or
  `canonical` per dataset.
- `artifacts[].format` — `csv` · `csv.gz` · `json` · `txt` · `md` · `png` ·
  `sqlite` · `db`.
- `artifacts[].path` — relative to the dataset directory; must exist; may not
  point outside it.
- `artifacts[].pattern` — optional glob, for document corpora whose files cannot
  be listed one by one (`{"path": ".", "pattern": "*.json"}`). `path` must then
  be a directory, at least one file must match, and the descriptor file never
  matches its own pattern. Patterns are independent globs and may overlap
  (`*.txt` also matches `*-ocr.txt`); `index.json` reports `file_count` and
  `bytes` for these instead of a single hash.
- `inventories` — repo-root-relative paths to source-document inventories.
- `freshness.fingerprint` — one build file, or a list of them, holding
  `sha256`/`bytes`/`rows` per artifact; merged into `datasets/index.json`.
  Either `build.json` (keyed by `files` or `artifacts`) or omitted when the
  dataset has no build step.
- `verification.status` — `verified` (reconciled against printed totals or an
  independent source), `partial`, `none`.
- `pipeline` — optional, but strongly encouraged: the exact command that
  regenerates the artifacts (`cli` is a string, or a list when a dataset has
  more than one entry point).
- `docs` — repo-relative-to-dataset files a reader should open; all must exist.
  Lookup tables and build reports belong here rather than in `artifacts`, since
  they are not fingerprinted data outputs.

**Optional:** `tags` (list of strings), `notes` (list of strings, rendered as
caveats), `search` (free-form hints for a future query surface).

## What `dataset.json` deliberately does *not* hold

- **Row counts, byte sizes, SHA-256** — those come from the fingerprint file.
  Two sources of truth for a hash is how hashes go stale.
- **Column descriptions** — `codebook.json` already owns these for
  labour-migration; the index reads CSV headers directly for the rest.
- **Document lists** — that is the inventory's job.

## Validation

```bash
python -m kagaj_core.manifest validate          # errors + warnings
python -m kagaj_core.manifest index             # regenerate datasets/index.json
python -m kagaj_core.manifest validate --quick  # skip SHA-256 recomputation
```

Errors (exit 1, fail CI):

- descriptor missing, unparseable, or wrong `schema_version`
- `id` ≠ directory name; unknown `status` / `role` / `format` / `verification.status`
- required field absent or empty
- artifact, doc, inventory, or plan path that does not exist
- artifact path escaping the dataset directory, or declared twice
- fingerprint file declares an artifact the descriptor does not (or vice versa)
- fingerprint `bytes` or `sha256` disagreeing with the file on disk

Warnings (exit 0):

- dataset has no fingerprint file (freshness unknown)
- artifact not covered by the fingerprint file (unhashed)
`tests/test_dataset_manifest.py` runs validation on every descriptor and
regenerates `datasets/index.json`, failing if the committed copy is stale.

## `datasets/index.json`

Generated, committed, deterministic (no timestamps — freshness comes from each
dataset's fingerprint file). It is the merged view a catalog or explorer reads:

```jsonc
{
  "schema_version": "1.0",
  "datasets": [
    {
      "id": "…", "title": "…", "status": "…", "description": "…",
      "grain": "…", "coverage": { … }, "sources": [ … ], "tags": [ … ],
      "verification": { … }, "pipeline": { … }, "license": { … },
      "docs": [ … ], "inventories": [ … ], "notes": [ … ],
      "freshness": { "fingerprints": ["build.json"], "generated_at": "…", "commit": "…" },
      "artifacts": [
        { "path": "…", "role": "primary", "format": "csv.gz",
          "bytes": 616537, "rows": 70089, "sha256": "…",
          "columns": ["month", "offense", "value"] }
      ]
    }
  ]
}
```

`bytes` is stat'd from disk; `rows`, `sha256` and `generated_at`/`commit` come
from the fingerprint file; `columns` is the header row for `csv`/`csv.gz`
artifacts. Regenerate after any data change — the test enforces it.
