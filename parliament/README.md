# Parliament

Scrape, OCR, translate, and index Nepali parliamentary documents.

Two sources are tracked:

| Source | Publisher | Manifest |
|---|---|---|
| Notices, agendas, calendars | House of Representatives (`hr.parliament.gov.np`) | `manifests/notices.json` |
| Full verbatim transcripts | National Assembly API (`na.parliament.gov.np`) | `manifests/verbatims.json` |

The pipeline produces, per document:

| File | Location | Content |
|---|---|---|
| `{stem}-ocr.txt` | `datasets/translations/` | Raw Devanagari OCR |
| `{stem}.txt` | `datasets/translations/` | Full English translation |
| `{stem}.json` | `datasets/translations/` | Structured JSON (sections, speakers, bills, tags) |

## Scripts

All scripts run from the **repository root**.

| Script | Description |
|---|---|
| `scripts/scrape_notices.py` | Scrape the HoR notices list; `--backfill` resolves PDF URLs |
| `scripts/process_notice.py` | OCR + Gemini structured translation for one pending notice |
| `scripts/upsert_notice.py` | Chunk, embed, upsert to pgvector |
| `scripts/scrape_verbatims.py` | Pull NA verbatims from the API |
| `scripts/process_verbatim.py` | Segmented OCR + translation with checkpointing |
| `scripts/upsert_verbatim.py` | Chunk, embed, upsert verbatims to pgvector |
| `scripts/init_db.py` | Create the pgvector schema |
| `pdf_to_text.py` | Shared OCR CLI used by the processors |

## Running

```bash
# Scrape
python parliament/scripts/scrape_notices.py --backfill
python parliament/scripts/scrape_verbatims.py

# Process one document (requires GEMINI_API_KEY in the repo-root .env)
python parliament/scripts/process_notice.py --max-count 1
python parliament/scripts/process_verbatim.py --max-count 1

# Upsert to pgvector
python parliament/scripts/init_db.py
python parliament/scripts/upsert_notice.py datasets/translations/*.json
python parliament/scripts/upsert_verbatim.py datasets/translations/Verbatim_*.json
```

## Setup

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[billtracker,ocr]"
cp .env.example .env   # fill in GEMINI_API_KEY and DATABASE_URL
```

Postgres + pgvector can be started with the root `docker-compose.yml`.

## Notes

- The manifest only tracks the current 7th House of Representatives (notices
  dated 2082-12 onward) and National Assembly sessions 19+.
- Older notices and verbatims are kept in the `*-archive.json` manifests for
  discoverability, but are not reprocessed.
- Verbatim translations are segmented (10k chars) and checkpointed under
  `output/verbatims/`; only the merged JSON is committed.
