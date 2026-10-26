# Data availability

## What this is

A tidy, verified panel of labour-approval statistics published by the
**Department of Foreign Employment (DoFE), Government of Nepal**
(`https://dofe.gov.np`), covering destination country, origin district, gender,
approval channel and reporting period. Built for econometric work on the volume,
composition and geographic origin of Nepali labour migration.

## Files

| File | Description |
|------|-------------|
| `panel_canonical.csv.gz` | **Primary analysis dataset, additive-only.** Gzipped CSV, one row per canonical `(granularity, fiscal year, window, section, entity, gender, channel, row_type)` with `row_type=detail` and `channel_class=component` only — summing it cannot double-count an aggregate. Filter `analysis_safe=true` (`entity_resolved AND verified AND channel_reviewed`) for the safe default; `analysis_safe_permissive` (`entity_resolved AND verified`) is for legalization-specific work only. |
| `panel_rollup.csv.gz` | Non-additive companion: aggregates, distinct measures and printed total/grand-total rows. Compare against the primary; never add to it. |
| `panel.csv` | Raw tidy-long extraction (one row per document cell), the provenance base for the canonical dataset. |
| `panel_archive.csv.gz` | **Archive.org backfill panel (separate).** Gzipped CSV of verified older monthly country reports (BS 2067–2075) recovered from `web.archive.org`. This is the **labour-approval** table ("कामदार गएको मुलुक"), split by `approval_type` (`institutional` / `individual`) — an axis **distinct** from the modern delivery channels (`channel_map` is null/TBD in `channels.json`; do not join on channel string). The newer BS 2073–2075 stage template also carries `entry_type` (`re_entry` / `new` / `legalization`). `scope` (`previous_cumulative` / `month` / `cumulative`, plus `pre_permission` / `final_approved` on the newer template) + `scope_class` (`prior_ytd` / `window` / `ytd` / `pre_approval` / `final_approval`) + `granularity` (`month`) do not map onto the live monthly schema, so it is kept out of `panel_canonical` and joined on `period_bs`. Carries canonical `name_canonical` + `iso3`, `entity_resolved`, and `analysis_safe = verified AND entity_resolved` (74,586 / 94,770 rows). `source_kind=archive_org`; every row `verified=True`. |
| `panel_archive_build.json` | Provenance for `panel_archive.csv.gz`: per-doc source SHA-256 + Wayback URL, and any duplicate-content captures dropped. |
| `agencies.csv` | Agency-level recruiting-agency pre-approval and institutional permit detail. |
| `series.csv` | Historical metric series (approvals, deaths, complaints, ...) from narrative DoFE reports. |
| `period_windows.csv` | Reporting-window lookup (`period_bs` → AD start/end) for date-based merges. |
| `codebook.json` | Machine-readable column dictionary, controlled vocabularies, row counts and per-file SHA-256 checksums. |
| `build.json` | Build manifest: git revision, build timestamp, row counts, checksums, audit results. |
| `source_attestation.json` | Frozen per-source fingerprints: page count + document and per-page text digests for every cached PDF. Verify offline with `python -m migration_parser provenance --verify [DIR]`. |
| `verification.json` | Panel-wide math-invariant audit summary. |
| `crosscheck.json` | Independent cross-check against opendatanepal CSVs. |
| `countries.json` / `districts.json` / `fiscal_years.json` / `channels.json` / `reconciliation.json` | Canonical reference data and the documented reconciliation rule. |

## Method and quality

- Every numeric cell is extracted from the printed PDF text layer and audited:
  `male + female = total`, component channels sum to the printed *With* total,
  *With − re-entry = Without*, and `Σ detail rows = printed Total`. Documents
  that pass are marked `verified=True`.
- Two source printing errors (Qatar, ±1 worker, in `report2020_annex_X`) are
  reproduced as printed and documented rather than silently corrected; they are
  the only `verified=False` rows.
- Cross-document overlap is handled explicitly (`reconciliation.json`): never mix
  monthly and annual granularities, country and district tables are the same
  measure along different dimensions, and one Annex table's printed year is
  overridden to its true year. After reconciliation there are **zero
  cross-document key conflicts** and no cross-document double counting.
- Three independent cross-checks against the `opendatanepal` digitisation agree
  to **< 0.05 %** on country, gender and total dimensions. A fourth check
  (`new_individual`) is reported as `not_comparable` because that opendata file
  is a top-N per-year ranking (10–12 destinations/year), not a full distribution.
- The primary file is guaranteed unique on its documented dedup key, and
  source-clipped entity names are suffixed so distinct countries can never merge
  under a `groupby` (see `README.md`).
- `series.csv` rows carry a `series_key` (`report|source_page|caption|metric|`
  `dimension|unit|year_basis|gender`). Rows within a key are additive-compatible
  (differ only by `name`/`fiscal_year`); summing `count` across keys would mix
  counts with percents/foreign currency, fiscal with calendar bases, or totals
  with male+female — so only sum within a key.
- `channel_reviewed=false` flags channels whose cross-template equivalence is a
  single-analyst judgment not covered by the independent cross-check — currently
  `legalization` and the old-template `new_entry`. These are not covered by any
  arithmetic audit (a printed total merely sums whichever channels a template
  defines), so the safe default `analysis_safe=true` excludes them. Use
  `analysis_safe_permissive=true` only for legalization-specific work, and report
  those results as a separate specification.
- Every source PDF is content-hashed at fetch (`pdf_sha256` on the live manifest,
  `source_pdf_sha256` on the archive manifest);
  `python -m migration_parser driftcheck [--recheck]` checks **both** so a source
  revised in place cannot silently be absorbed into a rebuild.
- Provenance is **offline-verifiable**: `source_attestation.json` freezes each
  source's page count plus document and per-page text digests. Anyone holding the
  original PDFs can run `python -m migration_parser provenance --verify` to prove
  they have exactly the pages the panel was built from, without redistributing
  the PDFs.

**Scope caveat for high-frequency designs.** Monthly windows in the primary panel
cover only 2025-04 → 2026-09; the archive panel adds BS 2067–2075
(2010/11–2018/19), including the newer-stage BS 2073–2075 reports. The Wayback
Machine's later BS 2080/81 and 2081/82 captures are progress reports rather than
monthly country tables. So the obvious population-scale experiments after BS
2075 (Malaysia 2018–20 reforms, Israel quota changes) still lack monthly
coverage in this package; closing that gap needs another source. Annual
data (through FY2081/82) is the best current input for those questions. See the
research-design warning in `README.md`.

Known limitations are listed in `README.md` (e.g. one pre-approval PDF with a
partly outlined text layer is incomplete — 90 % of `agencies.csv` is
`verified=False`; a handful of raw entity names are unresolved and kept verbatim).
Reproduce with `python -m migration_parser.cli build`; the exact revision is
recorded in `build.json` and regression-tested to be a clean ancestor of `HEAD`.

## Source and terms

All figures are republished from public DoFE PDFs; the original URLs are kept
per-row in `source_url` (and in `datasets/labour-migration/manifests/migration_manifest.json`). The
DoFE site does not state an explicit open licence — this package redistributes
**derived, factual tabulations** for research. Users should confirm reuse terms
with DoFE and cite the original reports. The opendatanepal CSVs are used only as
a cross-check, never as a source.

## Citation

> Nepali Labour Migration Panel (DoFE labour-approval statistics), compiled from
> Department of Foreign Employment reports. Dataset build recorded in
> `datasets/labour-migration/build.json`.

Also cite the underlying reports, e.g. *Nepal Labour Migration Report* (DoFE,
2020) and the DoFE monthly/yearly labour-approval statements.
