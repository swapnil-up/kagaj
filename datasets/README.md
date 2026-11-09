# Datasets

Committed, reusable outputs. Every dataset keeps its source URLs, extraction
code, and verification notes alongside it.

Each dataset directory carries a [`dataset.json`](labour-migration/dataset.json)
descriptor — what the data is, where it came from, which file to open first —
and [`index.json`](index.json) is the generated, merged view of all of them
(fingerprints included). This is what a catalog or query surface should read
instead of reverse-engineering each pipeline. See
[`docs/dataset-manifest.md`](../docs/dataset-manifest.md); regenerate with
`python -m kagaj_core.manifest index`.

| Dataset | Path | Rows / size | Coverage | Format |
|---|---|---|---|---|
| Labour-migration panel | [`labour-migration/`](labour-migration/) | 70,089 canonical rows (50,052 `analysis_safe`) | FY2074/75–2082/83 | CSV.GZ + JSON codebook |
| Parliament translations | [`translations/`](translations/) | 220 structured JSON docs, 601 files (~13 MB) | 7th HoR; NA sessions 19+ | TXT + JSON |
| KUKL water schedules | [`water/`](water/) | 7 branches, 231 source entries | 2083 Ashoj | JSON |
| `.gov.np` infrastructure | [`govweb/`](govweb/) | 2,837 hostnames, 1,187 apex entities (778 classified), 753 local levels (712 attributed), 20 observed | 2026-11 snapshot | CSV.GZ + JSON |

## Labour-migration panel

Start with [`labour-migration/README.md`](labour-migration/README.md) and
[`labour-migration/codebook.json`](labour-migration/codebook.json).

- **Primary analysis file:** `panel_canonical.csv.gz` — additive-only detail
  rows. Filter `analysis_safe=true` for the default specification.
- **Comparison file:** `panel_rollup.csv.gz` — printed totals, aggregates, and
  distinct measures. Compare against it; never add it to the primary.
- **Raw extraction:** `panel.csv.gz`.
- **Build fingerprint:** `build.json` (git revision + SHA-256 per artifact).
- **Citation and source notes:** `DATA_AVAILABILITY.md`.

## Parliament translations

Each document has up to three files:

| Suffix | Meaning |
|---|---|
| `-ocr.txt` | Raw Devanagari OCR |
| `.txt` | English translation |
| `.json` | Structured record (session, sections, speakers, bills, tags) |

See [`translations/INDEX.md`](translations/INDEX.md) for a browsable list grouped
by source. Rebuild the index with:

```bash
python datasets/build_index.py
```

Translations are derived from public parliamentary documents; the original
notice/verbatim URL is stored in the corresponding manifest.

## KUKL water schedules

[`water/schedule.json`](water/schedule.json) merges the latest schedule per
branch. The per-branch extract for a given month is
`datasets/water/<Branch>__<YYYY>_<Month>.json`. Each zone includes delivery days, time
windows, served areas, and contact details when published.

## `.gov.np` infrastructure observations

Start with [`govweb/DATASET.md`](govweb/DATASET.md) and
[`govweb/audit_summary.md`](govweb/audit_summary.md).

- **Primary file:** `sites.csv.gz` — one row per discovered `.gov.np` hostname.
  The unit is a hostname, not a local level.
- **Roster:** `roster.csv.gz` — the canonical local-level list. The raw roster
  carries 765 records; `roster_adjudication.json` resolves the 12 extras to the
  official 753.
- **Entities:** `entities.csv.gz` — one row per discovered apex hostname with its
  classified owning public body and evidence. 778 of 1,187 apexes are classified;
  409 are explicitly `unknown`, never guessed from a name.
- **Attribution:** `attribution.csv.gz` — the evidence-bearing join from a local
  level to its hostname. 712 of 753 are mapped; 41 are explicitly unresolved.
- **Observations:** `hosting`, `dns_mail`, `http_headers`, `tls`,
  `third_party_scripts`, `robots` — 20-hostname pilot sample only, not a census.
  `tls.csv.gz` is header-only because live TLS collection has not run.
- **Fingerprint:** `build.json`; reconciliation: `reconciliation.json`.

Collection is passive and never scans ports or bypasses `robots.txt`. Read the
interpretation rules in `DATASET.md` before quoting any figure.

## License

Repository code and datasets are MIT-licensed unless a dataset states otherwise.
The labour-migration panel additionally documents source terms and attribution
requirements in
[`labour-migration/DATA_AVAILABILITY.md`](labour-migration/DATA_AVAILABILITY.md).
