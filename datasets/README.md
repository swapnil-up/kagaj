# Datasets

Committed, reusable outputs. Every dataset keeps its source URLs, extraction
code, and verification notes alongside it.

| Dataset | Path | Rows / size | Coverage | Format |
|---|---|---|---|---|
| Labour-migration panel | [`labour-datasets/labour-migration/`](labour-datasets/labour-migration/) | 70,104 canonical rows (50,004 `analysis_safe`) | FY2074/75–2082/83 | CSV.GZ + JSON codebook |
| Parliament translations | [`datasets/translations/`](datasets/translations/) | 218 structured JSON docs, 595 files (~13 MB) | 7th HoR; NA sessions 19+ | TXT + JSON |
| KUKL water schedules | [`datasets/water/`](datasets/water/) | 7 branches, 231 source entries | 2083 Ashoj | JSON |

## Labour-migration panel

Start with [`labour-datasets/labour-migration/README.md`](labour-datasets/labour-migration/README.md) and
[`labour-datasets/labour-migration/codebook.json`](labour-datasets/labour-migration/codebook.json).

- **Primary analysis file:** `panel_canonical.csv.gz` — additive-only detail
  rows. Filter `analysis_safe=true` for the default specification.
- **Comparison file:** `panel_rollup.csv.gz` — printed totals, aggregates, and
  distinct measures. Compare against it; never add it to the primary.
- **Raw extraction:** `panel.csv`.
- **Build fingerprint:** `build.json` (git revision + SHA-256 per artifact).
- **Citation and source notes:** `DATA_AVAILABILITY.md`.

## Parliament translations

Each document has up to three files:

| Suffix | Meaning |
|---|---|
| `-ocr.txt` | Raw Devanagari OCR |
| `.txt` | English translation |
| `.json` | Structured record (session, sections, speakers, bills, tags) |

See [`datasets/translations/INDEX.md`](datasets/translations/INDEX.md) for a browsable list grouped
by source. Rebuild the index with:

```bash
python datasets/build_index.py
```

Translations are derived from public parliamentary documents; the original
notice/verbatim URL is stored in the corresponding manifest.

## KUKL water schedules

[`datasets/water/schedule.json`](datasets/water/schedule.json) merges the latest schedule per
branch. The per-branch extract for a given month is
`datasets/water/<Branch>__<YYYY>_<Month>.json`. Each zone includes delivery days, time
windows, served areas, and contact details when published.

## License

Repository code and datasets are MIT-licensed unless a dataset states otherwise.
The labour-migration panel additionally documents source terms and attribution
requirements in
[`labour-datasets/labour-migration/DATA_AVAILABILITY.md`](labour-datasets/labour-migration/DATA_AVAILABILITY.md).
