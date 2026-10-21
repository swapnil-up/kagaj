# DDA Drug Price Extractor — Implementation Plan

## Overview

Extract government-fixed MRP (Maximum Retail Price) data from Nepal's Department of Drug Administration (DDA) gazette PDFs and price notices. Uses PaddleOCR for clean Devanagari text extraction, mark-boxes for column region definition, and Gemini for structured output.

## Source Assessment

| Asset | Format | Pages | Text Layer | Notes |
|-------|--------|-------|------------|-------|
| Gazette PDF (`gazette_r7pxsu0.pdf`) | PDF, 208KB | 4 | Garbled Devanagari (legacy font) | English drug names + numbers readable |
| Notice PDF (`notice%20regarding%20price_gcbymnz.pdf`) | PDF, 35KB | 1 | Same garbled encoding | Header/notice text |
| Price notices (content 181, 209, etc.) | Scanned JPGs | 1 each | No text layer | Need OCR |

**Current content on DDA site:** Only 2 PDFs in the MRP category. ~3-4 scanned JPG notices. Total: ~10 pages.

**Token cost estimate:** Negligible. ~50K input tokens total. ~$0.01-0.03 at Gemini Flash Lite rates.

## Architecture

```
PDF pages → PNG → PaddleOCR → text + bounding boxes
                                      ↓
                    mark-boxes column regions (user-marked)
                                      ↓
                    Spatial column classification
                                      ↓
                    Structured rows (drug | strength | unit | price)
                                      ↓
                    Gemini cleanup/normalization → JSON
```

**Why OCR first:** The PDF text layer has garbled Devanagari (legacy font encoding). PaddleOCR with `devanagari_PP-OCRv5_mobile_rec` produces clean Unicode Devanagari text with bounding boxes. Running through translation improves quality.

**Why mark-boxes:** Instead of guessing column positions with regex or hardcoded heuristics, the user visually marks the table columns on each page type. This gives precise spatial coordinates for column-based extraction, same approach as the redbook parser.

## Files to Create

### 1. `parliament/scripts/scrape_dda.py` — Manifest scraper

Scrape the DDA MRP category page for content entries with PDF/image attachments.

```python
# Pattern: follows scrape_notices.py
# - load_manifest() / save_manifest() for dda_medicines.json
# - Scrape dda.gov.np/category/mrp-of-medicines/ (single page)
# - For each entry: extract title, content URL, PDF/image URL
# - Also scan price-related content pages for JPG images
# - Deduplicate against existing manifest entries
```

**Manifest format** (`parliament/dda_medicines.json`):
```json
[
  {
    "serial": "1.",
    "title": "Gazette — MRP 2082",
    "url": "https://dda.gov.np/content/66/gazette/",
    "source_type": "pdf",
    "file_url": "https://giwmscdnone.gov.np/media/pdf_upload/gazette_r7pxsu0.pdf",
    "status": "pending",
    "scraped_at": "2026-08-20"
  },
  {
    "serial": "2.",
    "title": "Notice regarding price — 2082/12/26",
    "url": "https://dda.gov.np/content/209/",
    "source_type": "jpg",
    "file_url": "https://giwmscdnone.gov.np/media/albums/Bigyapti%2020821226_...jpg",
    "status": "pending",
    "scraped_at": "2026-08-20"
  }
]
```

### 2. `parliament/scripts/render_dda.py` — PDF to PNG rendering

Convert PDF pages to PNG images for mark-boxes and OCR.

```python
# Uses PyMuPDF (fitz) to render each page as PNG
# Output: output/dda/{stem}_page{N}.png
# DPI: 300 (good for OCR accuracy)
```

### 3. `parliament/scripts/dda_columns.py` — Column region definitions

Stores the marked column regions per page type. JSON file with spatial coordinates.

```python
# Pattern: similar to redbook_parser's spatial column definitions
# Loaded from: parliament/dda_column_regions.json
# Format: keyed by page type (e.g. "gazette_table", "notice_header")
```

**Column regions JSON** (`parliament/dda_column_regions.json`):
```json
{
  "gazette_table": {
    "dpi": 300,
    "description": "Standard DDA MRP gazette table layout",
    "columns": {
      "serial":   {"px": [50, 120, 110, 900]},
      "drug_name": {"px": [110, 120, 450, 900]},
      "strength":  {"px": [450, 120, 600, 900]},
      "unit":      {"px": [600, 120, 700, 900]},
      "price":     {"px": [700, 120, 850, 900]}
    },
    "rows": {
      "y_start": 120,
      "row_height": 30,
      "separator_y": [150, 180, 210]
    }
  }
}
```

### 4. `parliament/scripts/ocr_dda.py` — PaddleOCR extraction

Run PaddleOCR on rendered PNG images to get clean Devanagari text with bounding boxes.

```python
# Pattern: follows pdf_to_text.py's PaddleOCR usage
# - Uses devanagari_PP-OCRv5_mobile_rec model
# - Returns text lines with bounding box coordinates
# - Output: output/dda/{stem}_page{N}_ocr.json (text + boxes)
```

### 5. `parliament/scripts/spatial_dda.py` — Column classification

Use marked column regions to classify OCR results into structured columns.

```python
# Pattern: follows redbook_parser's spatial bounding-box approach
# - Load column regions from dda_column_regions.json
# - For each OCR text line, check which column region its bounding box falls in
# - Build structured rows: each row = {serial, drug_name, strength, unit, price}
# - Output: output/dda/{stem}_page{N}_rows.json
```

### 6. `parliament/scripts/dda_schema.py` — Gemini prompt + schema

Structured extraction prompt for Gemini to clean up and normalize the OCR'd data.

```python
# Gemini prompt for drug price extraction
# Input: raw OCR text (or structured rows from spatial_dda)
# Output: normalized JSON with all drug data
```

**Gemini prompt:**
```
You are an expert at extracting structured drug price data from Nepali government gazettes.

The following text has been OCR'd from a DDA MRP gazette. Clean up and normalize the data.

Return a JSON object with exactly this structure:
- source.title: Document title
- source.date_bs: Nepali date if found
- source.date_ad: Approximate AD date
- source.gazette_number: Gazette serial number if found
- drugs[].drug_name_en: English drug name (e.g. "Amoxycillin")
- drugs[].drug_name_np: Nepali/Devanagari name
- drugs[].strength: Dosage strength (e.g. "500 mg")
- drugs[].dosage_form: Form (e.g. "Tablet", "Capsule", "Syrup")
- drugs[].unit: Packaging unit (e.g. "per tablet", "per 10 ml bottle")
- drugs[].mrp_npr: Maximum Retail Price in NPR (number)
- drugs[].category: Drug category/class if mentioned
- drugs[].manufacturer: Manufacturer if listed
- drugs[].pack_size: Pack size if mentioned
- summary.total_drugs: Total number of drugs extracted
- summary.categories_found: List of unique categories
- summary.price_range: {"min": lowest MRP, "max": highest MRP}

Rules:
- Extract EVERY drug entry. Do not skip or summarize.
- If a field is not present, use null.
- Prices must be numbers (not strings).
- If OCR text is garbled, use context clues to reconstruct.
- Output valid JSON only.

--- BEGIN OCR TEXT ---
{text}
--- END OCR TEXT ---
```

### 7. `parliament/scripts/process_dda.py` — Orchestrator

Main pipeline script that ties everything together.

```python
# For each pending manifest entry:
#   1. Download PDF/JPG to output/dda/
#   2. If PDF: render to PNG (render_dda.py)
#   3. OCR the PNG (ocr_dda.py)
#   4. Classify into columns using marked regions (spatial_dda.py)
#   5. Call Gemini for cleanup/normalization (dda_schema.py)
#   6. Save output files:
#      - datasets/translations/dda-{stem}-ocr.txt (raw OCR text)
#      - datasets/translations/dda-{stem}.json (structured drug data)
#   7. Update manifest status → "done"
```

### 8. DB schema additions (in `parliament/scripts/init_db.py`)

```sql
CREATE TABLE IF NOT EXISTS drug_prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_title TEXT,
    source_url TEXT,
    gazette_date_bs TEXT,
    gazette_date_ad DATE,
    drug_name_en TEXT NOT NULL,
    drug_name_np TEXT,
    strength TEXT,
    dosage_form TEXT,
    unit TEXT,
    mrp_npr NUMERIC(10,2),
    category TEXT,
    manufacturer TEXT,
    pack_size TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drug_prices_name ON drug_prices (drug_name_en);
CREATE INDEX IF NOT EXISTS idx_drug_prices_mrp ON drug_prices (mrp_npr);
CREATE INDEX IF NOT EXISTS idx_drug_prices_category ON drug_prices (category);
```

### 9. `parliament/scripts/upsert_dda.py` — pgvector upsert (Phase 2)

Chunk by drug category, embed, upsert. Similar to `upsert_notice.py`.

```sql
CREATE TABLE IF NOT EXISTS drug_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES drug_prices(id),
    chunk_index INT,
    category TEXT,
    chunk_text TEXT,
    embedding VECTOR(768),
    drug_names TEXT[],
    price_range NUMRANGE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## CLI Usage

```bash
# Step 1: Scrape DDA MRP page
python parliament/scripts/scrape_dda.py

# Step 2: Render PDFs to PNG
python parliament/scripts/render_dda.py output/dda/gazette.pdf

# Step 3: Mark column regions (user interaction via mark-boxes)
python3 /home/swap/github/agent-tools/mark-boxes/mark_boxes.py output/dda/gazette_page1.png 300

# Step 4: Process one pending entry
GEMINI_API_KEY=$key python parliament/scripts/process_dda.py --max-count 1

# Step 5: Upsert to pgvector (Phase 2)
python parliament/scripts/upsert_dda.py datasets/translations/dda-*.json
```

## Implementation Order

1. **`scrape_dda.py`** — scrape DDA site, build manifest (~50 lines)
2. **`render_dda.py`** — PDF to PNG rendering (~30 lines)
3. **Mark columns** — run mark-boxes on rendered pages, save to `dda_column_regions.json`
4. **`ocr_dda.py`** — PaddleOCR extraction (~80 lines)
5. **`spatial_dda.py`** — column classification using marked regions (~120 lines)
6. **`dda_schema.py`** — Gemini prompt + schema (~80 lines)
7. **`process_dda.py`** — orchestrator (~200 lines)
8. Test with the 2 existing PDFs
9. **DB additions** — `drug_prices` table (~20 lines)
10. **`upsert_dda.py`** — pgvector upsert (~150 lines, Phase 2)
11. **GitHub Actions** — manual trigger workflow (~40 lines)

## Integration with Existing Infrastructure

| Component | Reuse from existing | Notes |
|-----------|-------------------|-------|
| Config | `config.py` — GEMINI_MODEL, API URLs, paths | Add DDA_MANIFEST, DDA_OUTPUT_DIR |
| HTTP | `requests` + `verify=False` + retry pattern | Same as notice scraper |
| OCR | PaddleOCR with `devanagari_PP-OCRv5_mobile_rec` | Same as `pdf_to_text.py` |
| Spatial | Redbook parser's bounding-box classification | New column regions for DDA tables |
| Gemini | Same API call pattern, `response_mime_type="application/json"` | New prompt in `dda_schema.py` |
| Output | `datasets/translations/dda-{stem}.json` + `datasets/translations/dda-{stem}-ocr.txt` | Same directory |
| DB | PostgreSQL + pgvector | New tables: `drug_prices`, `drug_chunks` |
| CI | GitHub Actions | New workflow: `translate-dda.yml` (manual trigger) |

## GitHub Actions

```yaml
# .github/workflows/translate-dda.yml
# Manual trigger (workflow_dispatch) — DDA publishes infrequently
# Steps: checkout → setup python → install deps → run process_dda.py → commit
```
