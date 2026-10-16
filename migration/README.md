# Nepali Labour Migration Panel

Tidy, verified extraction of labour-approval tables published by the
Department of Foreign Employment (DoFE), `dofe.gov.np`.

`panel.csv` is **one row per (document × section × name × channel × gender)**.
Every row in the current build is `verified=True` (the printed male/female
totals, channel subtotals, and section grand totals all reconcile exactly
against the extracted cells — see `migration_parser/verify.py`).

## Book source

| Field | Meaning |
|-------|---------|
| `doc_id` | DoFE content id from the detail-page URL (`/content/{id}/`), else the manifest serial |
| `source_url` | Direct PDF URL (provenance) |
| `title` | Listing title (Devanagari) |
| `doc_type` | `single_month`, `cumulative`, `annual`, or `""` (see below) |

## Reporting period

The DoFE "month" is a **~4-week approval window**, not a calendar or BS month.
Where the PDF title block gives the exact window it is recorded as AD dates.

| Field | Meaning |
|-------|---------|
| `period_bs` | BS period parsed from the title, e.g. `2083 श्रावण` |
| `period_ad_start` | Window start, ISO date (`from YYYY-MM-DD`) |
| `period_ad_end` | Window end, ISO date (`to YYYY-MM-DD`) |

## Measurement

| Field | Meaning |
|-------|---------|
| `section` | `country` (destination country) or `district` (origin district) |
| `row_type` | `detail` (a country/district) or `total` (printed Total row) |
| `name` | Country or district name (as printed) |
| `sn` | Printed serial number (blank on continuation pages) |
| `channel` | Approval channel/group (see below) |
| `gender` | `male`, `female`, or `total` |
| `count` | Number of labour approvals (**integer people**) |
| `source_page` | 1-based page within the source PDF |
| `verified` | `True` when the whole document passed the math audit |

## Channels

Two printed templates exist; both are extracted. `channel` values differ
between them by design (no lossy re-mapping — reconciliation happens later).

**Modern template (21 numeric columns)** — monthly reports and yearly
statements from 2069/70 onward:

| `channel` | Printed group |
|-----------|---------------|
| `recruiting_agency` | Recruiting Agency |
| `individual_new` | Individual-New |
| `g2g` | Government-to-Government |
| `individual_reentry` | Individual-ReEntry |
| `legalization` | Legalization |
| `total_with_reentry` | Total With Re-Entry |
| `total_without_reentry` | Total Without Re-Entry |

**Older template (18 numeric columns)** — annual sanction statements
2073/74–2080/81; coarser, no Individual/G-to-G split:

| `channel` | Printed group |
|-----------|---------------|
| `recruiting_agency` | Recruiting Agency |
| `new_entry` | New Entry |
| `legalized_entry` | Legalized Entry |
| `re_entry` | Re-Entry |
| `total_with_reentry` | Total With Re-Entry |
| `total_without_reentry` | Total Without Re-Entry |

## Invariants enforced at extract time

Per (section, name):
- `male + female = total` for every channel group;
- component channels sum to `total_with_reentry` (per gender);
- `total_with_reentry − <re-entry channel> = total_without_reentry`.

Per section: `Σ detail rows = printed Total row`, for every numeric column.

## Coverage

Live DoFE catalogue (35 documents, `bill-tracker/migration_manifest.json`):

- **Monthly** — 17 reports, BS 2082 Shrawan → 2083 Shrawan. Extracted.
- **Yearly** — 7 statements, BS 2076/77 → 2082/83. Extracted.
- 1 older annual statement (2073/74, country-wise only). Extracted.

Not yet extracted (different layouts — see `MIGRATION_NOTES.md`):
institutional (संस्थागत) agency lists, pre-approval (पूर्व अनुमति) lists,
labour bulletins (narrative), and 2 scanned PDFs (no text layer).

## Reproduction

```bash
redbook-env/bin/python bill-tracker/scripts/scrape_migration.py   # refresh manifest
redbook-env/bin/python bill-tracker/scripts/process_migration.py --force
```

Per-document CSVs are written to `output/migration/docs/` and the combined
`migration/panel.csv` is rebuilt from them (idempotent).

## Historical series (`series.csv`)

The five narrative DoFE reports (not the tabular monthly/yearly statements)
print many "name × fiscal-year" matrices measuring **different metrics**. These
are extracted separately into `series.csv` — one row per
`(report × table × name × fiscal_year)` — because mixing them into `panel.csv`
would conflate incompatible measures.

| Field | Meaning |
|-------|---------|
| `report` | Source report key: `status_2013_14`, `status_2014_15`, `status_2015_17`, `country_intro_2019`, `migration_2020` |
| `source_page` | 1-based page in the source PDF |
| `caption` | Printed table caption (the primary disambiguator — always filter on this before summing) |
| `metric` | `labour_approval`, `deaths`, `deaths_by_cause`, `disability_compensation`, `complaints`, `assistance`, `no_objection_letters` |
| `dimension` | `country` (destination), `district` (origin), or `unknown` |
| `unit` | `count` (people) or `percent` (share tables) |
| `name` | Country/district (or other row label) |
| `fiscal_year` | BS/AD fiscal year token, normalised to `YYYY/YY` |
| `gender` | reserved (blank in current build) |
| `count` | value (people, or percentage when `unit=percent`) |
| `note` | cause for `deaths_by_cause` (e.g. `suicide`), else blank |

**Caveats**

- A few tables measure **shares (%)**, flagged by `unit=percent`; do not sum
  them with `count` rows.
- `deaths_by_cause` tables are **subsets** of the all-cause `deaths` tables in
  the same report — never add them together.
- The same metric can appear in several reports/years; deduplicate on
  `(metric, dimension, name, fiscal_year)` and prefer the latest report.
- Row totals (Σ years vs the printed `Total` column) verify exactly; column
  totals are skipped because continued tables print one cumulative Total row
  spanning pages.

Extracted sets — `labour_approval` by district and destination country
(male/female, 2012/13–2016/17), deaths (country/district, 2008/09–2016/17),
disability compensation, complaints, and assistance. Reproduce with:

```bash
redbook-env/bin/python bill-tracker/scripts/process_series.py
```

## Architecture

| File | Role |
|------|------|
| `migration_parser/model.py` | templates (`channels_for`), `DocMeta`, `WideRow` |
| `migration_parser/parser.py` | `extract_doc()` / `melt()` — wide live tables |
| `migration_parser/verify.py` | math audit of the wide tables |
| `migration_parser/series.py` | `extract_series()` — historical year-matrices |
| `migration_parser/periods.py` | AD-window / BS-period / doc-type parsing |
| `migration_parser/cli.py` | `python -m migration_parser.cli extract <pdfs>` |
| `bill-tracker/scripts/scrape_migration.py` | build `migration_manifest.json` (35 live docs) |
| `bill-tracker/scripts/process_migration.py` | download → extract → verify → `panel.csv` |
| `bill-tracker/scripts/process_series.py` | reports → `series.csv` |

Run everything from the repo root with the `redbook-env` venv (PyMuPDF,
requests, bs4). Tests: `redbook-env/bin/python -m pytest tests/ -q`.
Raw working data (PDFs, per-doc CSVs, historical reports) lives in the
gitignored `output/migration/`.

## Gotchas (hard-won; keep in mind before "fixing" the parser)

- The site wants a **browser-like User-Agent**; PDFs live at
  `giwmscdnone.gov.np/media/pdf_upload/`.
- `find_tables()` occasionally **drops a cell's text** (a merged or overflowing
  country/district name). `parser.py` recovers these from the raw page text
  (`_page_name_map`, `_split_sn_names`, `_repair_wrapped_name`).
- **Total** rows sometimes put the label in the S.N. column (col 0), not col 1;
  still-unlabeled totals are matched against the section column sums.
- Values use **space or comma** thousands separators (`"1 363"`) — `_to_int`
  handles both.
- For historical matrices the **caption is the metric** — extract it from the
  text block above the table (`Table/DATASET/Annex/Figure`) and propagate it
  across pages for continued tables. Never fall back to arbitrary prose.
- Reject **cross-tabs** (country × cause × year): a real matrix has one row per
  `(name, fiscal_year)`.
- Harmless noise: PyMuPDF "pymupdf_layout" warning and MuPDF zlib/syntax errors
  from scanned PDFs.

## Roadmap / not yet extracted

- `migration_2020` Annex **IX/X** (country × channel, FY 2017/18, no S.N. column)
  and **XI–XIII** (district Men/Women/Total by channel, 2017/18 & 2018/19) —
  extends the approvals panel backward.
- `preapproval` docs (5/7-col long country+agency layout).
- 2 **scanned** docs (no text layer) → OCR (`ocr-env` PaddleOCR).
- Canonical `countries.json` / `fiscal_years.json` (name-variant normalisation).
- Cross-check against `opendatanepal` CSVs (**cross-check only** — never fill
  gaps from them; it muddies provenance).


