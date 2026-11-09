# Architecture

Kagaj is a set of independent extractors that share OCR, PDF geometry, CID
mapping, and a structured-output client. Each pipeline is runnable on its own;
none depends on a web service.

## Four extraction families

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

### 4. Passive network observation

Not every Kagaj source is a PDF. `govweb/` measures Nepal's public-sector web
infrastructure from the outside, using only ordinary DNS lookups, one TLS
handshake, one HTTPS root request, published `robots.txt` files, and the public
Certificate Transparency log. It never scans ports, probes for vulnerabilities
or bypasses `robots.txt`; an unobserved host is recorded as missing evidence,
never as a passing result.

The unit of record is a **hostname**. Attribution to a local level is a separate,
evidence-bearing join (`attribution.csv.gz`), so the grain does not have to
change when an office outside the 753 local levels is discovered. Entity
classification (`entities.csv.gz`) carries that a step further: every apex
hostname gets an owning-public-body type and scope, or an explicit `unknown`,
so the whole `.gov.np` universe is analysable and not only the municipal slice.

Used by: `datasets/govweb/`, plan in `docs/plans/govweb-audit.md`.

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
| Dataset descriptors | `kagaj_core/manifest.py` + `datasets/<id>/dataset.json` → `datasets/index.json` |
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
datasets/labour-migration/panel.csv.gz
datasets/labour-migration/panel_canonical.csv.gz
datasets/labour-migration/panel_rollup.csv.gz
   ↓ build
build.json (git revision + SHA-256 fingerprints)
```

## Data flow (govweb)

```text
oag.gov.np local-level report API      crt.sh Certificate Transparency
   ↓ roster                              ↓ discover-ct
datasets/govweb/roster.json            datasets/govweb/sources/crtsh_gov_np.json
   │                                      │
   │  local-body e-office directory      │
   │  Wikidata P856, OSM website tags    │
   └──────────────┬──────────────────────┘
                  ↓ attribute (ranked, evidence-bearing)
        datasets/govweb/attribution.json (712/753 local levels)
                  ↓ merge into the hostname universe
        sites.csv.gz (2,837 hostnames, 1,187 apexes)
                  ↓ entities (apex → owning public body, evidence-bearing)
        datasets/govweb/entities.json (778 classified, 409 unknown)
                  ↓ deterministic sample
        tls_sample.json (20 hostnames, not a census)
                  ↓ passive collection (cache in output/govweb/)
        datasets/govweb/observations/*.json
                  ↓ build + analyze + verify
        ten tidy CSVs + build.json + audit_report.json + reconciliation.json
```

## Why not a web app?

The original repository shipped a Vue/FastAPI uploader. It was removed because
the durable value is in the datasets and CLIs, not in a single-file uploader
with no search or access control. A web surface can be rebuilt later on top of
the same CLI contracts without carrying the old app.
