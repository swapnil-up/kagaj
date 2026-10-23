# Architecture

Kagaj is a set of independent extractors that share OCR, PDF geometry, CID
mapping, and a structured-output client. Each pipeline is runnable on its own;
none depends on a web service.

## Three extraction families

### 1. OCR for legacy fonts

Some PDFs (Preeti, Kantipur) have no reliable Unicode layer — the text exists
only as glyphs. The OCR path rasterizes each page and runs PaddleOCR's
Devanagari model, returning Unicode text plus word-level bounding boxes.

Used by: `parliament/` (notices and verbatims), `water_parser/` (scanned
schedules), `drug_prices/`, `dictionary/`.

### 2. Vector extraction for CID-keyed fonts

Budget PDFs use Type0/Identity-H fonts with per-page ToUnicode CMaps. PyMuPDF
decodes most glyphs, but unmapped CIDs fall through as control characters. The
budget pipeline combines font-scoped CID→Devanagari mappings with spatial
parsing (codes and amounts are classified by column position) and then audits
the extracted rows against the printed totals.

Used by: `redbook_parser/`, with shared mappings in `cidmap/`.

### 3. Native table extraction

DoFE labour-approval PDFs have a usable vector text layer, so the migration
pipeline uses `PyMuPDF find_tables()` directly, repairs dropped cells, melts
wide tables into a tidy panel, and verifies every document.

Used by: `migration_parser/`. KUKL's modern `.xlsx`/`.doc` schedules take a
similar route via `openpyxl` before falling back to Gemini for normalisation.

## Structured output

Where layouts vary too much for a deterministic parser, flattened reading-order
text is sent to Gemini (`gemini-2.5-flash-lite`) with a fixed JSON schema. This
is used for water schedules and for parliamentary translations. The model never
invents rows silently: every output is saved next to the OCR text that produced
it.

## Shared infrastructure

| Concern | Location |
|---|---|
| OCR CLI | `parliament/pdf_to_text.py` |
| CID → Devanagari | `cidmap/data/cid_mappings.json` |
| Unknown-glyph review | `kagaj_core/review/` |
| pgvector schema | `parliament/scripts/init_db.py` |
| Tests | `tests/` (pytest) |
| Gold pages | `tests/gold/` |

### Unknown-glyph review

`kagaj_core.review` renders one static HTML decision sheet for any extractor.
Adapters scan the PDF and choose the key; `kagaj_core.review.crops` renders the
glyph close-up and word crop with its overlay, handling page rotation, clipping,
and partial failures. The HTML shell is stdlib-only; the crop helper imports
PyMuPDF lazily. Redbook and cidmap are the current adapters; see
`docs/review-harness.md` for the contract and export compatibility.

## Data flow (parliament)

```text
source site/API
   ↓ scrape
manifest (parliament/manifests/*.json)
   ↓ download + OCR
output/…-ocr.txt (gitignored scratch)
   ↓ Gemini structured call
datasets/translations/{stem}-ocr.txt / .txt / .json
   ↓ chunk + embed
pgvector (notices, chunks, verbatims, verbatim_chunks)
```

## Data flow (labour migration)

```text
dofe.gov.np
   ↓ scrape
datasets/labour-migration/manifests/migration_manifest.json
   ↓ download + extract + verify
output/migration/docs/*.csv (scratch)
   ↓ melt + normalize + reconcile
datasets/labour-migration/panel.csv
datasets/labour-migration/panel_canonical.csv.gz
datasets/labour-migration/panel_rollup.csv.gz
   ↓ build
build.json (git revision + SHA-256 fingerprints)
```

## Why not a web app?

The original repository shipped a Vue/FastAPI uploader. It was removed because
the durable value is in the datasets and CLIs, not in a single-file uploader
with no search or access control. A web surface can be rebuilt later on top of
the same CLI contracts without carrying the old app.
