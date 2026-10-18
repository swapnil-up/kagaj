# AGENTS.md — Nepali Admin Copilot

## Repo Structure

```
translation/
├── cidmap/              # CID mapping: font-scoped CID → Devanagari
├── redbook_parser/      # Active budget extraction (PyMuPDF + spatial-first)
├── dictionary/          # Nepali-English dictionary builder
├── bill-tracker/        # Parliamentary notice/verbatim pipeline
│   ├── scripts/         # Python CLI (scrape, process, upsert)
│   ├── backend/         # FastAPI web app
│   ├── frontend/        # Vue 3 SPA
│   ├── pdf_to_text.py   # OCR CLI (used by bill-tracker scripts)
│   ├── notices.json     # Notice manifest (7th HoR)
│   ├── verbatims.json   # Verbatim manifest (NA sessions 19+)
│   ├── .env             # API keys (GEMINI_API_KEY, DATABASE_URL)
│   └── .venv/           # Python venv for bill-tracker
├── archive/budget/      # Frozen legacy budget extraction (v1/v2/v3)
├── tests/               # Pytest suite (tests redbook_parser)
├── ocr-env/             # Python venv for OCR (root-level, shared)
├── translations/        # Tracked output: OCR text, translations, JSON
├── output/              # Gitignored: generated files
└── .github/workflows/   # CI: scrape + translate (daily/weekly)
```

## Project Goal
Extract Devanagari text from Nepali government PDFs. Three pipelines:
- **OCR** — legacy fonts (Preeti/Kantipur): flatten-to-image + PaddleOCR + optional Gemini translation
- **Vector (v2)** — CID-keyed fonts (Kalimati): pdfplumber + font mapping → structured tables
- **Vector (v3)** — CID-keyed fonts via PyMuPDF + post-processing tables (redbook8283.pdf, 556pp)

## Current Status: v3 (PyMuPDF extraction working)

### Redbook parser consolidation (in progress)
- **`redbook_parser/`** is now the active budget module — the spatial-first /
  scoped-encoding redesign. Full design: `redbook_parser/STRATEGY.md`.
- **`archive/budget/*.py` is frozen legacy** (v1/v2/v3) — reference only, do not edit.
- **Tests:** `tests/` via pytest (uses the `redbook-env/` venv, gitignored):
  ```bash
  redbook-env/bin/python -m pytest tests/ -q
  ```
- **Gold standard:** `tests/gold/` — hand-transcribed pages (see
  `tests/gold/README.md`); `tests/gold/record_gold.py` seeds drafts from a DB.
- **CLI:** `redbook-env/bin/python -m redbook_parser.cli extract <pdf> --sqlite -o out.db`
  and `... verify <db>` (math audit of extracted rows vs stated totals).
  The unknown-CID workflow is `... census <pdf>` (list), `... review <pdf>`
  (HTML sheet to fill in the printed words), and `... derive <pdf> <cid_corrections.json>`
  (diff typed words against logical-order text to get per-CID Devanagari mappings).

### v3 Pipeline (baseline, being replaced)

### v3 Pipeline (`pdf_to_excel_v3.py`)
Uses PyMuPDF's built-in ToUnicode CMap decoding, supplemented with:
- **CID→Unicode table** (CID_CHAR_MAP): ~40 integer CID→Devanagari mappings for CIDs not in any font's ToUnicode CMap
- **Exact word-fix table** (EXACT_FIXES): ~100 entries for garbled word patterns, applied both pre- and post-CID mapping
- **State-machine line parser**: handles multi-line budget rows (code+desc on one line, 6 amounts on subsequent lines)
- **Scale inheritance**: detects लाख/करोड per page; continuation pages inherit scale from first detail page
- **Priority code handling**: extracts P1/0/3 priority/sdg/gender codes from multi-line patterns

**Results** (pages 17-60 of redbook8283.pdf):
- 1,319 data rows from 41 pages with budget codes
- 111 total rows (is_total=1)
- Pages 3-4: 39-62 rows (summary index)
- Pages 17-34: 31-36 rows each (detail budgets)
- Pages 35+: 11-12 rows each (summary by ministry)
- Scale: all detail pages in लाख (×100,000)
- Descriptions clean; remaining garbled chars use word-fix table

### Data Columns
| # | DB Column | Description |
|---|-----------|-------------|
| 1 | `year_actual` | यथार्थ (actual) |
| 2 | `year_revised` | संशोधित (revised) |
| 3 | `year_estimate` | अनुमान (estimate) |
| 4 | `total` | जम्मा (total) |
| 5 | `current_exp` | चालु (current expenditure) |
| 6 | `capital_exp` | पूँजीगत (capital expenditure) |
| 7 | `financial` | वित्तीय व्यवस्था |
| 8 | `baideshik_anudan` | बैदेशिक अनुदान |
| 9 | `baideshik_rin` | बैदेशिक ऋण |
| 10 | `prathamikta_sanket` | प्राथमिकता सङ्केत |
| 11 | `raniti_sanket` | रणनीति सङ्केत |
| 12 | `laigik_sanket` | लैङ्गिक सङ्केत |

- Columns 7-9 not yet populated on detail pages (only 6 amounts extracted)
- Priority codes captured for rows with P-prefix pattern
- Summary pages (35+) have different column layout; amounts may need different mapping

### v2 Pipeline (`pdf_to_excel_v2.py`) — unchanged, for redbook.pdf only

## Running

### OCR
```bash
ocr-env/bin/python bill-tracker/pdf_to_text.py notice.pdf                          # Devanagari
ocr-env/bin/python bill-tracker/pdf_to_text.py notice.pdf --html                   # HTML overlay
export GEMINI_API_KEY='key' && ocr-env/bin/python bill-tracker/pdf_to_text.py notice.pdf --translate
```

### v3 (redbook8283.pdf)
```bash
# Pages 1-60 → SQLite
python3 archive/budget/pdf_to_excel_v3.py output/redbook8283.pdf --max-pages 60 --sqlite -o output/redbook-v3-60.db

# Full extraction
python3 archive/budget/pdf_to_excel_v3.py output/redbook8283.pdf --sqlite -o output/redbook-v3.db
```

### v2 (redbook.pdf)
```bash
ocr-env/bin/python archive/budget/pdf_to_excel_v2.py output/redbook.pdf --max-pages 20 --sqlite
make slice PDF=output/redbook.pdf FROM=30 TO=50 DB=output/slice-30-50.db
```

## Setup

Dependencies are declared in `pyproject.toml` with optional groups. Install
into a venv with `pip install -e .[group]`:

```bash
# redbook_parser + cidmap (PyMuPDF extraction, tests)
uv venv redbook-env --python 3.12
uv pip install --python redbook-env/bin/python -e ".[redbook,test]"

# bill-tracker scripts (scrape, process, upsert)
uv venv bill-tracker/.venv --python 3.12
uv pip install --python bill-tracker/.venv/bin/python -e ".[billtracker]"

# OCR pipeline (PaddleOCR for legacy fonts)
uv venv ocr-env --python 3.10
uv pip install --python ocr-env/bin/python -e ".[ocr]"

# Everything except backend
uv venv dev-env --python 3.12
uv pip install --python dev-env/bin/python -e ".[dev]"
```

Available groups: `redbook`, `ocr`, `billtracker`, `backend`, `test`, `dev`, `all`.
Run `pip install -e .[all]` for a full install.

## Conventions
- **Venvs:** `ocr-env/` (root-level, gitignored); `bill-tracker/.venv/` (bill-tracker, gitignored); `redbook-env/` (redbook_parser, gitignored)
- **Output:** `output/` (gitignored — png, html, txt, db, xlsx, csv)
- **Translations:** `translations/` (tracked — committed OCR text + English translations)
- **Dictionary data:** `dictionary/` (tracked); binaries in `dictionary-data/` (gitignored)

## Font Architecture (redbook8283.pdf)
- Type0 font with Identity-H encoding, per-page font subsets each with own ToUnicode CMap
- Fitz applies the CMap correctly for ∼95% of glyphs; unmapped CIDs fall through to Identity-H → chr(cid)
- Control chars (\x04, \t, \x0e, etc.) for unmapped CIDs; literal ASCII chars (> < @ ^ 3 B) for higher-range unmapped CIDs
- Same CID maps to different Devanagari across different font instances → word-level fixes required
- Scale multiplier: page header (हजार/लाख/करोड) ×1000/×100000/×10M

## Known Issues
- Columns 7-9 (financial, baideshik_anudan, baideshik_rin) not captured on detail pages
- Summary pages (35+) may have different column ordering — not yet verified
- Per-instance CID mapping differences → word-fix table grows per page range
- Pages 1-16 (TOC) produce noise rows with empty descriptions
- No cross-verification yet (verify_budget.py not adapted for v3 schema)

## Notice Automation Pipeline

### Scripts
- `bill-tracker/scripts/scrape_notices.py` — scrapes `hr.parliament.gov.np` notices table. Two modes: `--list-only` (fast, incremental) and `--backfill` (fetches detail pages for PDF URLs). Output: `notices.json`. Stops at the 7th-HoR boundary: notices dated pre-2082-12 (the 6th HoR, dissolved 2025-09-12) are skipped, so the manifest only tracks the current parliament.
- `notices.json` — trimmed to the current (7th) House of Representatives (first session 2026-04-02). ~124 entries kept; older 6th-HoR notices moved to `notices-6th-hor.json`.
- `notices-6th-hor.json` — archive of the removed 6th-HoR-era notices (1,185 entries), kept with `ocr_path`/`translated_path` links to any existing `translations/` files so translated bills remain discoverable.
- `bill-tracker/scripts/process_notice.py` — picks 1 pending notice from manifest, backfills PDF URL if missing, downloads PDF, runs PaddleOCR (OCR only), then calls Gemini with a structured JSON prompt. Saves three files: `{stem}-ocr.txt` (Devanagari), `{stem}.txt` (full English translation), `{stem}.json` (structured metadata with sections, speakers, bills, agenda tags).
- `bill-tracker/scripts/upsert_notice.py` — reads a structured `{stem}.json` file, chunks sections, generates embeddings via `text-embedding-004`, and upserts to pgvector (both notice record + chunks).
- `bill-tracker/scripts/init_db.py` — creates the pgvector schema (`notices` + `chunks` tables).

### Output files (per notice)
| File | Content |
|------|---------|
| `translations/{stem}-ocr.txt` | Raw Devanagari OCR text |
| `translations/{stem}.txt` | Full English translation (narrative) |
| `translations/{stem}.json` | Structured JSON with session, sections, speakers, bills, tags |

### Database model (pgvector)
```sql
notices (id, title UNIQUE, date_bs, date_ad, meeting_type, meeting_number,
         chairperson, agenda_tags, ministries_mentioned, full_translation_en, ...)

chunks (id, notice_id FK, chunk_index, section_name, chunk_text,
        embedding VECTOR(768), speaker_names TEXT[], key_issues TEXT[], ...)
```
- Upsert key: `notices.title` (unique). Rerunning the same notice updates in place.
- Chunks are deleted + re-inserted on each upsert (simplifies iteration).

### Running locally (requires Postgres + pgvector, or Supabase/Neon URL)

**With Docker:**
```bash
docker compose up -d                              # start pgvector container
.venv/bin/python bill-tracker/scripts/init_db.py               # create schema
GEMINI_API_KEY=$key .venv/bin/python bill-tracker/scripts/process_notice.py --max-count 1
.venv/bin/python bill-tracker/scripts/upsert_notice.py translations/Notice_*.json
```

**With Supabase/Neon (no Docker):**
```bash
.venv/bin/python bill-tracker/scripts/init_db.py --url "postgresql://..."
GEMINI_API_KEY=$key .venv/bin/python bill-tracker/scripts/process_notice.py --max-count 1
.venv/bin/python bill-tracker/scripts/upsert_notice.py translations/Notice_*.json --url "postgresql://..."
```

### Running with Supabase/Neon
```bash
# Create free project at supabase.com or neon.tech, get connection string
.venv/bin/python bill-tracker/scripts/init_db.py --url "postgresql://user:pass@host:5432/db"
.venv/bin/python bill-tracker/scripts/upsert_notice.py translations/*.json
```

### Gemini structured prompt
Uses `response_mime_type="application/json"` with a schema that returns both `full_translation_en` + structured fields in one call. Model: `gemini-2.5-flash-lite` with `temperature=0.2`.

### Manifest (`notices.json`)
| Field | Description |
|-------|-------------|
| `serial` | Global 1-based index in manifest order (renumbered on every scrape; the site's per-page row number is not stored) |
| `title` | Notice title (e.g. "Notice 2083-03-31") |
| `url` | Detail page URL |
| `pdf_url` | Direct PDF attachment URL |
| `status` | `pending` / `done` / `failed` / `no_pdf` |
| `scraped_at` | Date first discovered |
| `ocr_path` | Path to saved OCR text (when done) |
| `translated_path` | Path to saved translation (when done) |
| `structured_path` | Path to structured JSON (when done, new notices only) |

### GitHub Actions
- `scrape-notices.yml` — weekly Monday 6am, commits new notices to `notices.json`
- `translate-notices.yml` — daily 4am, processes 1 pending notice, commits translated output

### SSL Note
The parliament site has a misconfigured SSL cert — both scripts use `verify=False`. The GitHub Actions runners also hit this issue; the `urllib3.disable_warnings()` in the scripts suppresses the noise.

## Verbatim Pipeline (National Assembly)

### Overview
Mirrors the notice pipeline for National Assembly meeting verbatims (ra.sabha / NA
meetings, 30+ page transcripts). Text-layer PDFs — OCR route via `pdf_to_text.py`
(no pdftotext decoder). Source: `na.parliament.gov.np/api/v1/verbatims?limit=500`.

### Scripts
- `bill-tracker/scripts/scrape_verbatims.py` — pulls all verbatims from the NA API into
  `verbatims.json` (single request, no pagination loop; keyed on stable API
  `na_id`). Keeps only verbatims from the **19th NA session onward** (BS 2082-10
  ~ Dec 2025 — a little before the 7th HoR, first session 2026-04-02 / BS
  2082-12); older sessions are skipped so they never re-enter the manifest.
  The 379 pre-19th-session entries live in `verbatims-archive.json`; 3 entries
  in the current set have no PDF → `status: no_pdf`.
- `bill-tracker/scripts/process_verbatim.py` — picks 1 pending verbatim, downloads PDF,
  runs OCR, splits the Devanagari text into ~10KB segments, calls Gemini
  per-segment, then **merges** the segment JSON back into one document.
  - Why segmentation: verbatims are 60-170KB of OCR text — too large for one
    Gemini call. `SEGMENT_CHARS = 10000`; each segment gets its own structured
    call; `merge_segments()` unions lists and first-wins session metadata.
  - **Checkpointing:** each completed segment is written to
    `output/verbatims/{stem}.segments/{idx}-{sha1hash}.json`, so if Gemini
    credits run out mid-verbatim the next run resumes at the first unfinished
    segment (keyed on content hash — OCR drift invalidates only affected
    segments). Existing `{stem}-ocr.txt` is reused so segment inputs stay
    deterministic. Cache is deleted only on full success; kept on
    pending/skipped/failed. On GitHub Actions the whole `output/verbatims/`
    dir persists across runs via the actions/cache service
    (`verbatim-segment-cache-*` keys).
  - Big files (OCR text, full translation) → `output/verbatims/` (gitignored);
    only the merged structured JSON → `translations/Verbatim_{na_id}.json`
    (tracked, ~50KB).
- `bill-tracker/scripts/upsert_verbatim.py` — reads `translations/Verbatim_*.json`, chunks
  sections, embeds via `gemini-embedding-001`, upserts to pgvector
  (`verbatims` + `verbatim_chunks` tables). Dedup key: `na_id` when present,
  else `title`.

### DB tables (`verbatims`, `verbatim_chunks`)
Mirror the `notices`/`chunks` schema but keyed on `na_id UNIQUE` (the NA API id)
and `title UNIQUE`. Same chunk columns (speaker_names, key_issues, embedding
VECTOR(768), etc.).

### Running
```bash
# Scrape manifest (one-shot; keeps sessions 19+, 52 entries)
.venv/bin/python bill-tracker/scripts/scrape_verbatims.py

# Process one verbatim (download → OCR → segmented translation)
GEMINI_API_KEY=$key .venv/bin/python bill-tracker/scripts/process_verbatim.py --max-count 1

# Upsert to pgvector
.venv/bin/python bill-tracker/scripts/init_db.py --url "postgresql://..."
.venv/bin/python bill-tracker/scripts/upsert_verbatim.py translations/Verbatim_*.json --url "postgresql://..."
```

### GitHub Actions
- `scrape-verbatims.yml` — weekly Monday 6:30am, commits new verbatims to `verbatims.json`
- `translate-verbatims.yml` — daily 4:30am/4:30pm, processes verbatims until quota, commits output

### Verbatim manifest (`verbatims.json`)
| Field | Description |
|-------|-------------|
| `serial` | Global 1-based index in manifest order |
| `na_id` | Stable NA API id (dedup key for upsert) |
| `title` | English title (e.g. "Complete Proceedings of the Twenty-First Session ... Meeting no. 33") |
| `title_np` | Devanagari title |
| `published_at` | Publication date (null on ~22 pre-2022 entries; BS date is in the title) |
| `attachment_url` | Direct PDF URL |
| `status` | `pending` / `done` / `failed` / `skipped` / `no_pdf` |
| `scraped_at` | Date first discovered |
| `ocr_path` / `translated_path` / `structured_path` | Paths to saved outputs (when done) |

`verbatims-archive.json` — the 379 pre-19th-session verbatims (sessions 1–18),
kept so the API ids stay discoverable; not reprocessed by any script.

## KUKL Water-Schedule Pipeline (`water_parser/`)

### Overview
Extracts monthly water-distribution schedules published per KUKL branch office
(https://kukl.org.np/downloads/water-distribution-schedule) into one normalised
JSON. Sources are **xlsx/doc** (modern; openpyxl flattens every sheet) or **pdf**
(legacy/scanned; PaddleOCR). Layouts differ branch-to-branch, so there is no
per-branch parser: the flattened text goes to Gemini with a fixed schema and
comes back as reservoirs → zones (DMA, days, time window, areas, contacts).

### CLI
```bash
# 1. fetch the schedule page → water/manifest.json (tracked; re-runnable)
python -m water_parser.cli scrape

# 2. download + flatten + Gemini-extract selected entries
python -m water_parser.cli process --month 2083_Ashoj
python -m water_parser.cli process --branch Baneshwor --force

# 3. merge latest month per branch → water/schedule.json (website artifact)
python -m water_parser.cli build

# inspect manifest status
python -m water_parser.cli list --month 2083_Ashoj
```

### Layout
| Path | Role |
|------|------|
| `water_parser/paths.py` | paths, KUKL constants, filename/month parsing |
| `water_parser/text.py` | xlsx→text (openpyxl) and pdf→text (OCR) front-ends |
| `water_parser/schema.py` | Gemini prompt + `build_prompt(text)` |
| `water_parser/gemini.py` | structured JSON client (requests only) |
| `water_parser/scripts/cmd_{scrape,process,build}.py` | command implementations |
| `water/<branch>__<month>.json` | tracked per-branch extract |
| `water/manifest.json` | tracked scrape/processing state |
| `water/schedule.json` | tracked merged artifact (latest per branch) |
| `output/water/{raw,text}/` | gitignored downloads + cached flattened text |

### Notes
- Flattened text is cached in `output/water/text/`, so re-running `process`
  after a prompt tweak skips the slow OCR pass (use `--force` to redo it).
- `schedule.json` zones gain a `search_terms` array (area names split on
  comma-like separators, both scripts) for the frontend fuzzy search.
- Requires `[water]` deps (pymupdf, openpyxl, requests, bs4, lxml, numpy,
  pdf2image, paddleocr). `bill-tracker/.env` supplies `GEMINI_API_KEY`.
- Tests: `redbook-env/bin/python -m pytest tests/test_water_parser.py -q`
  (the xlsx case is skipped when openpyxl is absent).


