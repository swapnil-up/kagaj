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
| `panel_canonical.csv.gz` | **Primary analysis dataset.** Gzipped CSV, one row per canonical `(granularity, fiscal year, window, section, entity, gender, channel, row_type)`. |
| `panel.csv` | Raw tidy-long extraction (one row per document cell), the provenance base for the canonical dataset. |
| `agencies.csv` | Agency-level recruiting-agency pre-approval and institutional permit detail. |
| `series.csv` | Historical metric series (approvals, deaths, complaints, ...) from narrative DoFE reports. |
| `codebook.json` | Machine-readable column dictionary, controlled vocabularies, row counts and per-file SHA-256 checksums. |
| `build.json` | Build manifest: git revision, build timestamp, row counts, checksums, audit results. |
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
  to **< 0.05 %** on country, gender and total dimensions.

Known limitations are listed in `README.md` (e.g. one pre-approval PDF with a
partly outlined text layer is incomplete; a handful of raw entity names are
unresolved and kept verbatim). Reproduce with
`python -m migration_parser.cli build`; the exact revision is recorded in
`build.json`.

## Source and terms

All figures are republished from public DoFE PDFs; the original URLs are kept
per-row in `source_url` (and in `bill-tracker/migration_manifest.json`). The
DoFE site does not state an explicit open licence — this package redistributes
**derived, factual tabulations** for research. Users should confirm reuse terms
with DoFE and cite the original reports. The opendatanepal CSVs are used only as
a cross-check, never as a source.

## Citation

> Nepali Labour Migration Panel (DoFE labour-approval statistics), compiled from
> Department of Foreign Employment reports. Dataset build recorded in
> `migration/build.json`.

Also cite the underlying reports, e.g. *Nepal Labour Migration Report* (DoFE,
2020) and the DoFE monthly/yearly labour-approval statements.
