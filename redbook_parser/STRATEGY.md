# Redbook Strategy — Spatial First, Scoped Encoding, Deterministic Rules

Status: **approved design · Step 1 (consolidation) in progress**
Doc owner: redbook extraction team
Supersedes: the string-replace patch approach in `budget/pdf_to_excel_v3.py`

## 1. The Core Strategy Shift

Stop treating the PDF as a flat text stream that we repair with global
string-replace patches. Treat it as **2D glyph objects** with coordinate
geometry and **scoped font maps**.

```
              Raw PDF Page (Fitz / PyMuPDF)
                         |
                         v
        1. Font-Scoped Decoding
           (font subset name + CID -> Devanagari)
                         |
                         v
        2. Spatial Bounding-Box Classifier
           (x-coordinates -> Columns)
           (y-coordinates -> Row Clusters)
                         |
                         v
        3. Deterministic State Machine
           (no string hacks, pure logic)
                         |
                         v
        4. Verification Engine
           (math checks: Detail == Total?)
```

The three failures of the old approach that this fixes:

1. **EXACT_FIXES applied fixes globally.** A CID maps to different glyphs
   in different embedded font objects. A fix learned from Font_A was applied
   to text that came out of Font_B, causing both missed fixes and
   misfires. Scoped per-font maps kill this.
2. **Regex column parsing lost multi-line context.** Flattened text lines
   can't tell where the description ends and the amount columns begin when
   descriptions wrap. X-coordinate cutoffs can.
3. **No verification.** `verify_budget.py` was written for the v2 schema and
   never adapted to v3, so the extraction was never mathematically audited.
   Verification becomes a first-class citizen, not a post-hoc manual script.

## 2. Font-Scoped Encoding (kills EXACT_FIXES)

### The problem

PDFs map character IDs (CIDs) to glyphs per embedded font object. CID `0x21`
in Font_A may be one glyph, and the same CID in Font_B another. A global
table like `EXACT_FIXES = {"सवार>": "सवारी"}` cannot be correct for all fonts.

### Two font worlds (do not conflate)

| World | File | Font | Decode path |
|-------|------|------|-------------|
| v2 (legacy) | `redbook.pdf` | Preeti / Kalimati byte-encoded | pdfplumber + Preeti byte→Unicode table |
| v3 (current) | `redbook8283.pdf` | Type0, **Identity-H**, per-page subsets each with own ToUnicode CMap | PyMuPDF applies CMap (~95%); **unmapped CIDs fall through** to `chr(cid)` control chars or ASCII artifacts |

For v3 the correct model is:

- The **CID = glyph id** (Identity-H). The gap is only CIDs *missing from a
  subset's ToUnicode CMap*.
- The scoped map is keyed by a resolved **font identity** (for example
  `Kalimati@cmap:bb98e63fdb`, or a `Kalimati@src:<pdf-hash>:xref<N>` fallback),
  consulted only when PyMuPDF's decoded char is garbage (control char /
  `\ufffd` / ASCII artifact).
- It is a *supplement* to PyMuPDF, not a shadow of the whole font.
- The Preeti byte→Unicode map stays in the v2 path.

### API note (validated in the spike, PyMuPDF 1.28)

Measured on the HoR `Notice_2083-03-31.pdf` and `Daily_Agenda` PDFs, which
share the exact Type0 / Identity-H architecture of redbook8283.pdf:

- **`page.get_texttrace()` is the ONLY API we need.** It returns span dicts
  carrying the **BaseFont name** plus a `chars` tuple of per-glyph
  `(unicode, glyph_id, origin, bbox)`. Font + CID + geometry in one pass.
- **Unmapped CIDs decode to `U+FFFD` in texttrace; the CID is the `glyph` id.**
  `rawdict`/`get_text` instead render `chr(cid)` fallbacks (control chars and
  ASCII artifacts) — that's the source of the old EXACT_FIXES table. So
  `rawdict` is useful to *see* the fallback, but the CID comes from texttrace.
- **bbox correlation between rawdict and texttrace FAILS** (different bbox
  semantics: texttrace = glyph box, rawdict char box = line box; only 69/1218
  matched). Do not attempt it.
- **Scoping is mandatory, not theoretical.** Measured on the notice: `cid=20`
  → `'1'` in subset F2 but `'2'` in F1; `cid=14` → `','` in F1/F7 but `'+'` in
  F4. Same CID, different glyphs across subsets. Within one `(font, cid)` the
  mapping was deterministic (0 ambiguities across 1,200+ glyphs).
- **Garbage is concentrated.** On the notice, one body font (F1) carried 12%
  unmapped glyphs (1,291 chars); the other six subsets were clean. A
  supplemental map only needs to cover the fonts that actually have gaps.
- ⚠️ The notice PDFs are **visual-order** text (Preeti-style: matras are
  separate glyphs that don't x-sort into logical order) — which is why the HoR
  pipeline OCRs them. The API/geometry findings transfer to the redbook; the
  *decode-quality* numbers and column geometry are redbook-specific and must
  be re-measured on redbook8283.pdf.

### Decode logic (fallback order for v3)

```python
def decode_char(char, font_name, page):
    # 1. If PyMuPDF already decoded cleanly, use it.
    if is_clean(char["c"]):            # Devanagari / digit / whitespace
        return char["c"]
    # 2. Font-scoped supplemental map (CID not in subset's ToUnicode CMap).
    cid = char["cid"]                  # glyph id from get_texttrace
    if font_name in FONT_CID_MAPS and cid in FONT_CID_MAPS[font_name]:
        return FONT_CID_MAPS[font_name][cid]
    # 3. DO NOT STRIP SILENTLY. Log for auditing; keep a visible marker.
    log_unmapped(font=font_name, cid=cid, page=page)
    return f"\u27E6cid:{cid}\u27E7"     # ⟦cid:102⟧ — visible in output
```

Unmapped glyphs keep a visible marker in the DB instead of vanishing. An
unextractable glyph must never abort a 556-page run; it gets flagged for
review.

## 3. Spatial Column Cutting over Regex

### The problem

Budget codes, descriptions, and amount columns were separated with regex on a
flattened text line. Multi-line descriptions broke row context and amounts
were misassigned.

### The fix

Use X-coordinate cutoffs. The Red Book layout is rigid **within a template**.
A mid-column X of a char/span picks its column.

```python
GRID_BOUNDS = {
    "budget_code":   (20.0,  85.0),
    "description":   (85.1, 280.0),
    "column_1":      (280.1, 330.0),
    "column_2":      (330.1, 380.0),
    "column_3":      (380.1, 430.0),
    "column_4":      (430.1, 480.0),
    "column_5":      (480.1, 530.0),
    "column_6":      (530.1, 580.0),
}

def assign_column(x0, x1):
    x_mid = (x0 + x1) / 2
    for col_name, (lo, hi) in GRID_BOUNDS.items():
        if lo <= x_mid <= hi:
            return col_name
    return "unknown"   # never silently drop — bucket + log
```

### Template classifier runs first

The redbook has **at least three templates** and they do NOT share columns:

| Template | Pages | Columns |
|----------|-------|---------|
| TOC / index | 1–16 (3–4 = summary index) | no table |
| Detail budget | 17–34 | code + desc + **6 amounts** (7–9 absent) |
| Summary by ministry | 35+ | different column order/count |

X-cutoffs are only valid **after** the page type is detected from header text.
The amount-column count must come from the template, or the 9-column
`BudgetRow` will over/under-fill. Chars in no band → `description`/`unknown`
bucket + log.

## 4. Verification as a First-Class Citizen

If the numbers don't add up, the extraction failed. No output is trusted
until it passes a mathematical audit.

### The mathematical invariants

Every hierarchy level in the Red Book must sum:

```
Σ line items   = Sub-Total (स्रोत जम्मा)
Σ sub-totals   = Grand Total (जम्मा)
```

### Engine sketch

```python
class BudgetVerificationEngine:
    def verify_page(self, page_rows):
        calculated = 0.0
        reported = None
        for row in page_rows:
            if row.is_detail_row:
                calculated += row.amount
            elif row.is_total_row:
                reported = row.amount
        if reported is not None:
            assert calculated == reported, (
                f"Math mismatch! {calculated} != {reported}")
```

### Constraints

- **Grouping** is per **(page, section)** — a page may contain several
  स्रोत जम्मा sub-totals plus one जम्मा grand total. Verify each against its
  own data rows, not a page-wide sum (v2's `verify` command already models
  this — reuse the logic, don't reinvent).
- **Scale applied consistently.** All amounts compared at the same scale
  (हजार ×1,000 / लाख ×100,000 / करोड ×10M).
- **Integer-currency exactness.** Values are integer rupees; assert exact
  equality (|diff| < 1). Only add tolerance if scale mismatches are later
  allowed.
- Failures are flagged for targeted review, never silently accepted.

## 5. Known bugs carried in from v3 (fix list)

Port v3 into the new package **behaviour-preserving**, then fix these in order:

1. **Dropped line bug** — `process_page_lines` finalizes the current row when
   it hits a non-amount line but has already consumed that line (`i += 1`),
   so the line that *caused* the finalize is silently dropped. The comment at
   v3:528-529 claims re-processing that does not happen.
2. **Description continuation via keyword whitelist** — `DESC_CONTINUE_KEYWORDS`
   is a hard-coded substring list. Descriptions lacking those words get cut.
   Replace with spatial grouping (Y-distance to the primary code row).
3. **Heading/skip keyword collision** — `HEADING_LABELS = ["शीर्षक","स्रोत"]`
   collides with the `स्रोत` skip in `HEADER_KEYWORDS`; order of checks wins.
   Also re-introduces the v2 "स्रोत जम्मा नेपाल sub-header → fake row" issue.
4. **Naive scale inheritance** — first match of हजार/लाख/करोड *anywhere* in
   page text; one-way inheritance (`page_scale != 1 or first_detail_page is None`).
   Scope scale strictly to table headers.
5. **Silent glyph stripping** — unknown CIDs → `[N]` → regex-deleted. Replace
   with the visible-marker + audit log from §2.
6. **Duplicate fix-table entries** — 129 entries, 14 exact-duplicate keys.
   Obsolete once font-scoped maps land; interim cleanup drops duplicates.

## 6. Revised Action Plan

```
+-------------------------------------------------------------------------+
| STEP 1: Environment & Test Harness  [DONE — 76 tests green]             |
| - Consolidate codebases into a single active module: redbook_parser/.    |
| - budget/*.py frozen as legacy archive (do not delete).                  |
| - pytest with unit tests for number parsing, Devanagari conversion,      |
|   scale multipliers, state machine, verification engine.                 |
| - Tiny gold-standard test set: 5 sample pages w/ known true totals.      |
+-------------------------------------------------------------------------+
| STEP 2: Spatial & Glyph Extraction (Replacing Repair Tables)             |
| - Extract text via bounding boxes (x0,y0,x1,y1) per char.                |
| - Font-scoped CMap dictionaries keyed by resolved font identity.         |
| - Log unmapped CIDs to unmapped_cids.log (page numbers) instead of       |
|   regex-stripping [N].                                                   |
| - Page-template classifier (TOC / detail / summary) before column maps.  |
+-------------------------------------------------------------------------+
| STEP 3: State Machine & Scale Inheritance Fixes                          |
| - Fix the dropped-line bug.                                              |
| - Scope scale (हजार/लाख/करोड) strictly to table headers.                |
| - Group multi-line descriptions by Y-distance to the primary code row.   |
+-------------------------------------------------------------------------+
| STEP 4: Automated Verification Engine                                    |
| - Math checks against every ministry/heading total.                      |
| - Flag failing pages/rows for targeted review.                           |
+-------------------------------------------------------------------------+
```

### Spike status (completed on HoR notice PDFs AND redbook8283.pdf)

Validated on HoR notice PDFs (see §2 API note):

- texttrace-only glyph pipeline (font + CID + bbox per char).
- Unmapped CID mechanics: U+FFFD in texttrace, `chr(cid)` in rawdict, CID in
  the `glyph` field.
- Font-scoped maps are required (same CID, different glyphs across subsets).
- Spatial line clustering by y-baseline works (`extract_glyphs` +
  `cluster_lines`, unit-tested).

Measured on redbook8283.pdf (pages 17/26/36 + right-edge sweep of 17-60):

- **Every glyph is drawn TWICE ~0.3pt apart** (texttrace reports both). Must
  dedup by `(font, cid, round(y), round(x))` — `extract_glyphs(dedup=True)`.
  Page 17: 1727 glyphs, 41 lines, 110 unmapped (6%).
- **Unmapped CIDs (U+FFFD):** 4, 6, 9, 12, 13, 14, 16, 24, 31, 33, 34, 49, 57,
  58, 59, 60, … — matches the AGENTS.md CID_CHAR_MAP key set. No FFFD glyph was
  observed beyond the map's range on the sampled pages.
- **Page 34 (index 33) is blank** (0 glyphs) — not a bug.
- **DETAIL template (17-34):** codes left-align x≈30-90; descriptions x≈90-350;
  **6 amount columns right-aligned ending at 392/452/527/602/643/671**; two
  priority-flag columns (प्राथमिकता/दिगो/लैङ्गिक संकेत) ending at 732/768.
  GRID_BOUNDS updated from these measurements.
- **SUMMARY template (35-60):** 8 amount columns at different right edges
  (~356/416/478/522/574/622/660/710…), i.e. a DIFFERENT grid. Detail bounds
  must NOT be reused. Ordering semantics unverified.
- **Page-17 header semantics** (CONFIRMED by hand-marking the page — see below):
  the 6 amount columns are the **financing split**:
  `यथार्थ खर्च (2080/81)` → year_actual, `संशोधित अनुमान (2081/82)` →
  year_revised, `जम्मा बजेट (2082/83)` → year_estimate, `नेपाल सरकार` →
  financial, `वैदेशिक अनुदान` → baideshik_anudan, `ऋण` → baideshik_rin;
  then three संकेत columns (प्राथमिकता/दिगो विकास/लैङ्गिक). This is NOT the
  current/capital split legacy v3 assumed — `current_exp`/`capital_exp` are
  absent from detail pages and the legacy field mapping has been corrected
  (spatial.py GRID_BOUNDS, parser.py amount→field order, model.py doc).

### Column semantics (confirmed by hand-marking page 17)

The user marked the page with a scaling-corrected box tool (see
`/tmp/opencode/mark_boxes.py`; mirrored from `racps/invitation-generator/
pick_rect.py`; fixed `factor=ceil(max(w/max_w,h/max_h))` subsampling +
multiply mapping + `root.geometry`, since i3 stretched the window to
1916×1021 and the earlier `round(1/scale)` / `orig/disp` scale collapsed or
squished boxes). Two JSON sets, verified by overlay (page17-overlay.png):

- `boxes.json` (full-page column bands, pt): b1 37-208 (शीर्षक/code+desc),
  b2 208-277 (स्रोत), b3 277-336 (नकासा विधि), b4 336-395 (यथार्थ),
  b5 395-454 (संशोधित), b6 454-530 (जम्मा बजेट), b7 530-605 (नेपाल सरकार),
  b8 605-647 (अनुदान), b9 647-673 (ऋण), b10 673-711 (प्राथमिकता),
  b11 711-747 (दिगो विकास), b12 747-786 (लैङ्गिक).
- `boxes-header.json` (header cells): b1 शीर्षक, b2 स्रोत, b3 नकासा विधि,
  b4 2080/81 यथार्थ, b5 2081/82 संशोधित, b6 2082/83 (spans), b7 जम्मा बजेट,
  b8 नेपाल सरकार, b9 वैदेशिक, b10 अनुदान, b11 ऋण, b12 प्राथमिकता संकेत,
  b13 दिगो विकास संकेत, b14 लैङ्गिक संकेत.

Amount band right edges (394.6/454.3/529.9/604.8/646.6/673.2) match the
right-edge sweep within ~2pt — the two methods agree.

Still needs redbook8283.pdf:

- Gold pages: 5 targets (pages 3, 17, 26, 34, 36) — must be hand-transcribed
  from the rendered pages (Step 1 scaffolding is ready). Page 34 is blank —
  substitute another transition page.
- Confirm DETAIL column semantics (financing split) against gold page 17.
- SUMMARY (35-60) GRID_BOUNDS + column semantics (mark with the box tool).
- FONT_CID_MAPS values keyed by Kalimati subset, sourced from the FFFD census.

## 7. Ground Truth (gold standard)

- "Known true totals" must be **hand-transcribed from the PDF by a human**
  — this is the ground truth everything else hangs on.
- Gold data lives in `tests/gold/` as one JSON file per page (code,
  description, all 12 columns, is_total, row_type) + a manifest.
- `tests/gold/record_gold.py` loads a parsed SQLite DB, dumps a page's rows
  for human cross-check against the PDF, and writes the JSON once confirmed.
- Target pages (cover the template space): a TOC/index page, a first detail
  page, a middle detail page, a last detail/transition page, a summary page.

## 8. Non-Goals (for now)

- No English translation of the redbook (that is the OCR/notice pipeline's
  job; this repo's budget work stops at structured Devanagari numbers).
- No changes to the HoR / notice automation pipeline (`parliament/` and `datasets/translations/`). That pipeline is separate
  and off-limits to budget work.
- No deletion of `budget/*.py`; they are archived for reference.
