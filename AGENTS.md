# AGENTS.md — Kagaj

Kagaj turns Nepali government PDFs into open, structured data. It is a
collection of independent extractors plus the committed datasets they produce.

## Repo structure

```text
kagaj/
├── parliament/              # HoR notices + NA verbatims
│   ├── scripts/             # scrape / process / upsert / init_db
│   ├── pdf_to_text.py       # shared OCR CLI
│   └── manifests/           # notices.json, verbatims.json, archives
├── drug_prices/             # DDA drug-price extraction (experimental)
│   ├── scripts/
│   ├── manifests/
│   └── dda_column_regions.json
├── redbook_parser/          # budget redbook extraction (active)
├── migration_parser/        # DoFE labour-migration panel
├── water_parser/            # KUKL water schedules
├── kagaj_core/              # shared primitives (devanagari, review harness)
├── cidmap/                  # font-scoped CID → Devanagari mapping
├── dictionary/              # Nepali–English StarDict builder
├── datasets/                # committed outputs (START HERE)
│   ├── labour-datasets/labour-migration/    # panels + codebook + build.json
│   ├── datasets/translations/        # parliamentary OCR / EN / JSON + INDEX.md
│   └── datasets/water/               # per-branch schedules + schedule.json
├── docs/                    # architecture, integrity, roadmap, review harness, plans
├── tests/                   # pytest + gold pages
├── archive/budget/          # frozen legacy budget extractors
├── .github/workflows/       # scrape + translate crons
├── pyproject.toml           # packages + optional dependency extras
└── docker-compose.yml       # pgvector for parliament upserts
```

## Datasets (committed)

| Dataset | Path | Notes |
|---|---|---|
| Labour-migration panel | `datasets/labour-migration/` | 70,104 canonical rows; `analysis_safe` filter; `build.json` hashes |
| Parliament translations | `datasets/translations/` | 595 files; indexed in `INDEX.md` |
| KUKL water schedules | `datasets/water/` | `schedule.json` is the website artifact |

## Setup

Dependencies are declared in `pyproject.toml`. Create a venv with the extras you
need:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"   # all CLI pipelines + tests
```

Available extras: `redbook`, `ocr`, `billtracker`, `water`, `test`,
`dev`, `all`. `.env` lives at the **repo root** (gitignored); copy
`.env.example`. `GEMINI_API_KEY` and `DATABASE_URL` are read from there.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
```

Some tests need source PDFs that are downloaded on demand (redbook gold pages,
archive drift checks). Failures caused only by missing PDFs are expected in a
fresh clone.

## Parliament pipeline

Sources: `hr.parliament.gov.np` (notices) and the NA verbatims API.

```bash
python parliament/scripts/scrape_notices.py --backfill
python parliament/scripts/scrape_verbatims.py

python parliament/scripts/process_notice.py --max-count 1
python parliament/scripts/process_verbatim.py --max-count 1

python parliament/scripts/init_db.py
python parliament/scripts/upsert_notice.py datasets/translations/*.json
python parliament/scripts/upsert_verbatim.py datasets/translations/Verbatim_*.json
```

- Manifests: `parliament/manifests/notices.json`, `verbatims.json`; archives in
  `notices-6th-hor.json` and `verbatims-archive.json`.
- Outputs: `datasets/translations/{stem}-ocr.txt`, `{stem}.txt`, `{stem}.json`.
- Verbatims are segmented (10k chars) and checkpointed under
  `output/verbatims/`; only the merged JSON is committed.
- pgvector schema: `notices`/`chunks` and `verbatims`/`verbatim_chunks`.

## Labour-migration pipeline

```bash
python -m migration_parser.cli scrape
python -m migration_parser.cli process
python -m migration_parser.cli build
python -m migration_parser.cli verify
```

- Manifests: `datasets/labour-migration/manifests/`.
- Tracked outputs: `datasets/labour-migration/`.
- `panel_canonical.csv.gz` is additive-only; `panel_rollup.csv.gz` holds
  aggregates and printed totals.
- `build.json` records git revision + SHA-256 per artifact. Rebuild it after
  data changes.

## Budget pipeline (`redbook_parser/`)

```bash
python -m redbook_parser.cli extract <pdf> --sqlite -o out.db
python -m redbook_parser.cli verify out.db
python -m redbook_parser.cli census <pdf>
python -m cidmap.cli probe <pdf> [--reference-font Kalimati.ttf] [--registry cidmap/data/glyph_registry.json] [--json out.json]
python -m cidmap.cli infer <pdf> --reference-font Kalimati.ttf [--json out.json]
python -m cidmap.cli review <pdf> [--reference-font Kalimati.ttf] [--shape-runs] [--registry cidmap/data/glyph_registry.json]
python -m cidmap.cli registry ingest <pdf> --store cidmap/data/cid_mappings.json --registry cidmap/data/glyph_registry.json
python -m cidmap.cli registry query <pdf> --cid 1
python -m cidmap.cli promote <pdf> --reference-font Kalimati.ttf [--apply] [--json out.json]
python -m cidmap.cli autoscope <pdf> --reference-font Kalimati.ttf [--apply] [--json out.json] [--rejected-out rejected.jsonl]
python -m cidmap.cli autoscope <pdf> --reference-fonts kalimati [--lexicon] [--apply]
python -m cidmap.cli repair <pdf> -o repaired.pdf [--replace-conflicts] [--json out.json]
python -m cidmap.build_lexicon   # rebuild cidmap/data/nepali_lexicon.txt.gz
python -m redbook_parser.cli review <pdf>   # thin alias, adds legacy hints
python -m redbook_parser.cli derive <pdf> cid_corrections.json
```

- `cidmap probe` is read-only: per-font ToUnicode coverage, character classes,
  fingerprints, and unknown CIDs. Use it before review to spot hybrid fonts.
- `cidmap infer` is read-only shape-run inference; `review --shape-runs` adds
  the same candidates to the review sheet. Both need a reference font.
- `cidmap registry ingest` records glyph fingerprints from committed mappings;
  `registry query` resolves one CID through the cross-document registry.
- `cidmap promote` is dry-run by default. `--apply` only adds values backed by
  confirmed registry evidence; `commit` and `promote` share validation.
- `cidmap autoscope` bootstraps font-scoped values from exact, unambiguous
  reference outlines. It is dry-run by default and never overwrites a differing
  fallback. `--reference-fonts` requires exact agreement across every available
  copy; `--lexicon` adds shape-run context for near and ambiguous-exact roles.
  `--rejected-out` writes rejected candidates as JSONL for review triage; they
  remain unknown CIDs in the store.
- `cidmap repair` is dry-run by default. `-o/--output` writes a copy with
  font-scoped store values added to `/ToUnicode`; existing CMap values are kept
  unless `--replace-conflicts` is passed. The source PDF and store are unchanged.
- Local reference fonts live in gitignored `reference-fonts/` (or directories
  listed in `CIDMAP_REFERENCE_FONTS`). Pass a path or a family alias such as
  `kalimati`, `kokila`, `mangal`, `preeti`, or `kantipur`; never commit font
  binaries. Proprietary fonts must come from a licensed local installation.
  Legacy 8-bit fonts still need a separate byte→Unicode decoder; they are not
  usable as Unicode reference outlines.
- Unknown-CID workflow: `census` → `review` → `commit` → `registry ingest`
  → `repair`.
- `cidmap review` exports neutral decisions; `derive` accepts them and legacy
  `{cid, correct}` files. Shared harness: `kagaj_core/review/`,
  contract in `docs/review-harness.md`.
- Design notes: `redbook_parser/STRATEGY.md`.
- `archive/budget/` is frozen legacy (v1/v2/v3) — do not edit.

## Water pipeline

```bash
python -m water_parser.cli scrape
python -m water_parser.cli process --month 2083_Ashoj
python -m water_parser.cli build
```

- Manifest and outputs: `datasets/water/`.
- Column regions: `water_parser/column_regions.json`.
- Flattened text is cached in `output/water/`; use `--force` to redo OCR.
- `schedule.json` is generated; do not hand-edit.

## Drug-price pipeline (experimental)

```bash
python drug_prices/scripts/scrape_dda.py
python drug_prices/scripts/process_dda.py
python drug_prices/scripts/upsert_dda.py datasets/translations/dda-*.json
```

Plan: `docs/plans/dda-drug-prices.md`. No shipped dataset yet.

## Conventions

- **Venvs** are gitignored (`.venv/`, `redbook-env/`, `ocr-env/`).
- **Scratch output** goes to `output/` (gitignored).
- **Committed data** goes to `datasets/`; use `.gz` for large CSVs.
- **Paths** are resolved relative to the package, never the CWD.
- **Review crops:** pass text-space bboxes to
  `kagaj_core.review.crops.render_review_crop`; it handles rotation, page
  clipping, adaptive glyph zoom, and the word overlay.
- **Provenance:** every emitted row needs `source_url`; source PDFs are hashed
  when they can change in place.
- **Verification:** reconcile against printed totals; record mismatches rather
  than smoothing them.
- **Do not add comments** to code unless they explain non-obvious intent.

## GitHub Actions

| Workflow | Schedule | Purpose |
|---|---|---|
| `scrape-notices.yml` | Mon 06:00 | update `parliament/manifests/notices.json` |
| `scrape-verbatims.yml` | Mon 06:30 | update `parliament/manifests/verbatims.json` |
| `translate-notices.yml` | 04:00 / 16:00 | process notices until quota, commit translations |
| `translate-verbatims.yml` | 04:30 / 16:30 | process verbatims, persist segment cache |
| `init-db.yml` | manual | create pgvector schema |

Required secrets: `GEMINI_API_KEY`, `DATABASE_URL`.

## Known issues

- 34 of 70 tracked verbatims are still `failed`, plus 3 pending notices.
- Some legacy-font conjuncts and rephas are still misrecognised by OCR.
- Summary pages in the redbook have a different column layout from detail pages.
- `drug_prices/` is not complete and has no verified output.
- The retired web app was removed; do not reintroduce it into this repo.
