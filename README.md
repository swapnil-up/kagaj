<div align="center">

# कागज · Kagaj

### Nepali government paper, as data.

Open extractors and datasets for Nepal's public PDFs — parliament, budgets,
labour migration, water schedules, and more.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen?style=flat-square)](#data-integrity)
[![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](LICENSE)
[![PRs](https://img.shields.io/badge/PRs-welcome-blue?style=flat-square)](#contributing)

</div>

---

## Why

Nepali government offices publish critical information as PDFs. A lot of it is
hard to use: legacy Preeti/Kantipur fonts with no Unicode layer, scanned tables,
CID-keyed Kalimati text, or spreadsheets that change layout every month.

Kagaj turns that paper into **structured, verifiable, reusable data** — and
keeps the tools open so anyone can extend them to a new office or document type.

## Datasets

| Dataset | What it is | Coverage | Format | Link |
|---|---|---|---|---|
| **Labour-migration panel** | DoFE labour approvals, deaths, return migration, remittances, agency detail | FY2074/75–2082/83 · 70,089 canonical rows | CSV.GZ + codebook | [`datasets/labour-migration/`](datasets/labour-migration/) |
| **Parliament translations** | HoR notices + National Assembly verbatims, English + structured JSON | 7th HoR · NA sessions 19+ · 220 structured docs | TXT / JSON | [`datasets/translations/`](datasets/translations/) |
| **KUKL water schedules** | Branch → reservoir → zone/DMA/day/time/areas | 2083 Ashoj · 7 branches · 231 source entries | JSON | [`datasets/water/schedule.json`](datasets/water/schedule.json) |
| **Budget (redbook)** | Ministry/program budget rows with a math audit against printed totals | 2082/83 redbook | SQLite / CSV / Excel | [`redbook_parser/`](redbook_parser/) |

The labour-migration panel is the most mature artifact. Every row carries a
`source_url`, each source document passes a printed-total audit, overlaps between
documents are reconciled explicitly, and the build is fingerprinted with
SHA-256 hashes (`datasets/labour-migration/build.json`). Start with
[`codebook.json`](datasets/labour-migration/codebook.json) and the
[dataset README](datasets/labour-migration/README.md).

A full catalog, with row counts and licenses, lives in
[`datasets/README.md`](datasets/README.md).

## Use the data

```python
import pandas as pd

panel = pd.read_csv(
    "datasets/labour-migration/panel_canonical.csv.gz",
    dtype={"period_bs": str},
)

# The safe default: verified rows with reviewed channels, additive-only.
safe = panel[panel["analysis_safe"] == True]

# Approvals by destination country, latest fiscal year.
latest = safe[safe["fiscal_year"] == safe["fiscal_year"].max()]
latest.groupby("name_canonical")["count"].sum().sort_values(ascending=False).head(10)
```

```python
import json

schedule = json.load(open("datasets/water/schedule.json"))
for branch in schedule["branches"]:
    print(branch["branch"], len(branch["reservoirs"]))
```

Bulk SQL / DuckDB:

```sql
SELECT fiscal_year, sum(count) AS approvals
FROM read_csv_auto('datasets/labour-migration/panel_canonical.csv.gz')
WHERE analysis_safe = true
GROUP BY fiscal_year
ORDER BY fiscal_year;
```

## The toolkit

| Module | Source | Method | Entry point |
|---|---|---|---|
| [`parliament/`](parliament/) | `hr.parliament.gov.np`, NA API | PaddleOCR + Gemini structured JSON → pgvector | `python parliament/scripts/process_notice.py` |
| [`redbook_parser/`](redbook_parser/) | Budget redbook | PyMuPDF spatial-first extraction + CID mapping | `python -m redbook_parser.cli extract` |
| [`migration_parser/`](migration_parser/) | `dofe.gov.np` | PyMuPDF tables + per-document math audit | `python -m migration_parser.cli build` |
| [`water_parser/`](water_parser/) | `kukl.org.np` | xlsx/doc flatten or PaddleOCR + Gemini | `python -m water_parser.cli build` |
| [`drug_prices/`](drug_prices/) | `dda.gov.np` | OCR + spatial columns (experimental) | `python drug_prices/scripts/process_dda.py` |
| [`cidmap/`](cidmap/) | Any CID-keyed PDF | Font-scoped CID → Devanagari mapping | `python -m cidmap.cli` |
| [`dictionary/`](dictionary/) | Legacy Nepali PDFs | OCR → StarDict dictionary | see `dictionary/README.md` |

Shared infrastructure: OCR (`paddleocr`), PDF text/geometry (`pymupdf`),
structured extraction (`gemini-2.5-flash-lite`), pgvector for semantic search,
and a static unknown-glyph review harness (`kagaj_core.review`).

## Quick start

```bash
git clone https://github.com/swapnil-up/kagaj.git
cd kagaj

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[redbook,test]"

# Run the test suite
.venv/bin/python -m pytest tests/ -q

# Rebuild the labour-migration dataset
.venv/bin/python -m migration_parser.cli build
```

Extras: `redbook`, `billtracker`, `ocr`, `water`, `test`, `dev`, `all`.
Most pipelines read `GEMINI_API_KEY` from a repo-root `.env`; copy
[`.env.example`](.env.example) to get started.

## Data integrity

This is the part we care about most:

- **Per-document audits** — extracted rows must reconcile with the printed
  subtotals and totals; a ±1 mismatch is recorded, not silently fixed.
- **Row-level provenance** — every panel row keeps its `source_url`; every
  series row keeps its report, page, and caption.
- **Fingerprinted builds** — `build.json` records the git revision and the
  SHA-256 of every shipped artifact.
- **Gold pages** — hand-transcribed pages in [`tests/gold/`](tests/gold/) treat
  extraction accuracy as a testable contract.

See [`docs/data-integrity.md`](docs/data-integrity.md) for the full model.

## Repository map

```text
parliament/        HoR notices + NA verbatims → translations + pgvector
redbook_parser/    Budget redbook extraction
migration_parser/  DoFE labour-migration panel
water_parser/      KUKL water-distribution schedules
drug_prices/       DDA drug-price extraction (experimental)
cidmap/            CID → Devanagari font mapping
kagaj_core/        Shared Devanagari + unknown-glyph review harness
dictionary/        Nepali–English dictionary builder

datasets/          Committed, reusable outputs (start here)
docs/              Architecture, integrity, roadmap, review harness, plans
tests/             Pytest suite + gold pages
archive/           Frozen legacy budget extractors (reference only)
```

## Contributing

Contributions are welcome — especially new document sources, extraction fixes
for legacy fonts, and help closing the remaining failed verbatim translations.
Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first.

## Citation & license

If you use the labour-migration panel, cite it using [`CITATION.cff`](CITATION.cff).
All code and data in this repository are released under the MIT License — see
[`LICENSE`](LICENSE).

## नेपालीमा

कागज नेपाल सरकारका PDF कागजातलाई खुला र संरचित डेटामा बदल्ने खुला परियोजना हो।
संसदका सूचना र बहस, बजेट, वैदेशिक रोजगारीको तथ्याङ्क, र KUKL को पानी वितरण
तालिका यसबाट निकालिएका छन्। सबै डेटा [`datasets/`](datasets/) मा राखिएको छ;
प्रत्येक डेटासेटको स्रोत, जाँच र प्रमाण कागजातसँगै उपलब्ध छ।
