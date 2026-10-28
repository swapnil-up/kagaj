# Datasets

Committed, reusable outputs. Every dataset keeps its source URLs, extraction
code, and verification notes alongside it.

| Dataset | Path | Rows / size | Coverage | Format |
|---|---|---|---|---|
| Labour-migration panel | [`labour-migration/`](labour-migration/) | 70,089 canonical rows (50,052 `analysis_safe`) | FY2074/75–2082/83 | CSV.GZ + JSON codebook |
| Parliament translations | [`translations/`](translations/) | 220 structured JSON docs, 601 files (~13 MB) | 7th HoR; NA sessions 19+ | TXT + JSON |
| KUKL water schedules | [`water/`](water/) | 7 branches, 231 source entries | 2083 Ashoj | JSON |

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

## License

Repository code and datasets are MIT-licensed unless a dataset states otherwise.
The labour-migration panel additionally documents source terms and attribution
requirements in
[`labour-migration/DATA_AVAILABILITY.md`](labour-migration/DATA_AVAILABILITY.md).
