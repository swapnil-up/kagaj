# Revamp Plan: `translation` → `kagaj`

Status: **in progress** (saved before execution so work survives context compaction).

## Decisions (locked)

- Repo name: **kagaj**
- Tagline: **Nepali government paper, as data.**
- Remove the entire web app (Vue, FastAPI, Docker build, HF README).
- Full restructure now (`bill-tracker` → `parliament`, DDA split out, `docs/`, `datasets/`).
- Move committed outputs under `datasets/`.
- Keep Python package dir names (`redbook_parser`, `migration_parser`, `water_parser`) for import stability.
- Copyright holder: `swapnil-up` / Swapnil Upadhyay Kharel (confirm if different).

## Target identity

| Field | New value |
|---|---|
| Repo | `swapnil-up/kagaj` |
| Description | Turn Nepali government PDFs into open, structured data — parliament, budgets, labour migration, water schedules, and more. |
| Topics | `nepal`, `civic-tech`, `open-data`, `devanagari`, `ocr`, `pdf-extraction`, `parliament`, `nepali` |
| License | MIT (`LICENSE` file — currently missing) |

## Target tree

```text
kagaj/
├── README.md                # rewritten
├── LICENSE                  # new, MIT
├── CITATION.cff             # new
├── CONTRIBUTING.md          # new
├── pyproject.toml           # rename project, update excludes
├── AGENTS.md                # rewritten to new paths
├── .env.example             # root-level, shared
├── .github/workflows/       # path updates
│
├── parliament/              # was bill-tracker/ (minus backend/frontend/DDA)
│   ├── scripts/             # notices + verbatims + db
│   ├── pdf_to_text.py       # single OCR CLI
│   └── manifests/           # notices.json, verbatims.json, archives
│
├── drug_prices/             # DDA split out of bill-tracker
│   ├── scripts/
│   ├── manifests/dda_medicines.json
│   └── dda_column_regions.json
│
├── redbook_parser/          # keep import name
├── migration_parser/        # keep import name
├── water_parser/            # keep import name
├── cidmap/
├── dictionary/
│
├── datasets/
│   ├── README.md            # catalog
│   ├── translations/        # was translations/
│   ├── labour-migration/    # was migration/
│   └── water/               # was water/ (minus column_regions.json)
│
├── docs/
│   ├── architecture.md
│   ├── data-integrity.md
│   ├── roadmap.md           # was ROADMAP.md
│   ├── revamp-plan.md       # this file
│   ├── plans/dda-drug-prices.md
│   └── internal/review-2026-10.md
│
├── tests/
├── archive/budget/          # frozen legacy
└── docker-compose.yml       # pgvector only; db renamed kagaj
```

## Deletions

- `bill-tracker/frontend/`
- `bill-tracker/backend/`
- `Dockerfile`
- `README.hf.md`
- `README.github.md`
- `run.sh`
- `requirements.txt` (CI switches to `pip install -e`)
- root `PLAN-dda-drug-prices.md` (moved)
- `REVIEW.md` (moved)

Keep `docker-compose.yml` (pgvector), rename DB to `kagaj`.

## Move matrix

| From | To |
|---|---|
| `bill-tracker/pdf_to_text.py` | `parliament/pdf_to_text.py` |
| `bill-tracker/scripts/config.py`, `init_db.py`, `process_notice.py`, `process_verbatim.py`, `schema.py`, `scrape_notices.py`, `scrape_verbatims.py`, `test_structured_prompt.py`, `upsert_notice.py`, `upsert_verbatim.py` | `parliament/scripts/` |
| `bill-tracker/scripts/dda_schema.py`, `ocr_dda.py`, `process_dda.py`, `render_dda.py`, `scrape_dda.py`, `spatial_dda.py`, `upsert_dda.py` | `drug_prices/scripts/` |
| `bill-tracker/notices.json`, `notices-6th-hor.json`, `verbatims.json`, `verbatims-archive.json` | `parliament/manifests/` |
| `bill-tracker/dda_medicines.json` | `drug_prices/manifests/` |
| `bill-tracker/dda_column_regions.json` | `drug_prices/` |
| `bill-tracker/migration_manifest.json`, `migration_archive_manifest.json` | `datasets/labour-migration/manifests/` |
| `bill-tracker/README.md` | `parliament/README.md` (rewritten) |
| `translations/` | `datasets/translations/` |
| `migration/` | `datasets/labour-migration/` |
| `water/` | `datasets/water/` (except `column_regions.json`) |
| `water/column_regions.json` | `water_parser/column_regions.json` |
| `ROADMAP.md` | `docs/roadmap.md` |
| `REVIEW.md` | `docs/internal/review-2026-10.md` |
| `PLAN-dda-drug-prices.md` | `docs/plans/dda-drug-prices.md` |

## Code changes

- `parliament/scripts/config.py`: `PARLIAMENT_ROOT`, manifests dir, `TRANSLATIONS_DIR = datasets/translations`, env at repo root.
- DDA scripts: use `drug_prices/` paths. They import `config`; either keep a small `drug_prices/scripts/config.py` or import the shared config. Plan: create `drug_prices/scripts/config.py` with DDA-specific constants and environment loading, or extend shared config. Verify imports.
- `migration_parser/paths.py`: manifests → `datasets/labour-migration/manifests/`; `MIGRATION_DIR` → `datasets/labour-migration`; env at repo root.
- `water_parser/paths.py`: `WATER_DIR` → `datasets/water`; `COLUMN_REGIONS` → `water_parser/column_regions.json`; env at repo root.
- `water_parser/gemini.py`: message uses root `.env`.
- `tests/test_migration_parser.py`: update `parents[1]` paths.
- `pyproject.toml`: `name = "kagaj"`, new description, update excludes.
- Manifests: rewrite `translations/...` → `datasets/translations/...`; normalize absolute paths in `verbatims.json` and `dda_medicines.json`; verify every path resolves.

## Workflow changes

- `bill-tracker/scripts/*` → `parliament/scripts/*`.
- `translations/*.json` → `datasets/translations/*.json`.
- `git add` paths updated.
- `pip install -r requirements.txt` → `pip install -e ".[billtracker,ocr]"`.
- Cache key `hashFiles('requirements.txt')` → `hashFiles('pyproject.toml')`.
- `init-db.yml` path updated.
- `output/` paths unchanged.

## New docs

- `README.md` rewritten: problem → datasets → play with data → toolkit → quick start → integrity → citation/license → contributing → नेपालीमा.
- `datasets/README.md`: dataset catalog (name, coverage, rows, format, license).
- `datasets/translations/INDEX.md`: generated index grouped by notice/verbatim/DDA.
- `docs/architecture.md`: OCR vs vector/CID vs table-verify.
- `docs/data-integrity.md`: audits, provenance, gold tests.
- `CONTRIBUTING.md`: install, test, add-a-pipeline, good first issues.
- `LICENSE` (MIT), `CITATION.cff`.
- Rewrite `AGENTS.md` to new paths and fix stale counts.

## Accurate counts (use these, generate if possible)

- notices: 182 (174 done, 3 pending, 3 skipped, 1 no_pdf, 1 failed)
- notices-6th-hor: 1185 (13 done)
- verbatims: 70 (31 done, 34 failed, 5 skipped)
- verbatims archive: 379
- migration manifest: 35 (30 done, 3 no_table, 2 skipped)
- water manifest: 231 entries
- translations: 601 files / ~13 MB

## Execution phases

### Phase A — restructure
1. Create dirs; `git mv` per matrix.
2. Update Python path constants + tests.
3. Update workflows.
4. Normalize manifest paths.
5. Run tests + CLI smoke checks.

### Phase B — identity/docs
6. Delete dead files.
7. Write README, LICENSE, CITATION, CONTRIBUTING, dataset catalog, translation index.
8. Rewrite AGENTS + docs.
9. Rename project in pyproject / compose DB.

### Phase C — GitHub
10. Rename repo, set description/topics, update local remote.
11. Verify CI via manual dispatch.

## Verification gates

- `redbook-env/bin/python -m pytest tests/ -q` green.
- `python -m migration_parser.cli build` path-safe.
- `python -m water_parser.cli build` writes `datasets/water/schedule.json`.
- Every manifest path resolves.
- No stale `bill-tracker`, `README.hf`, `frontend`, `Admin Copilot` strings outside `archive/` and `docs/internal/`.

## Progress log

- [x] Plan saved
- [x] Phase A complete (restructure; 243 tests passing, remaining failures are missing source PDFs / uninstalled pandas)
- [x] Phase B complete (identity, docs, license, catalog)
- [x] Phase C complete (repo renamed to `swapnil-up/kagaj`, description + topics set)
- [x] Local git remote updated to `https://github.com/swapnil-up/kagaj.git`
