# Nepal crime data — plan and confirmed schema

Status: implemented (`crime/`, `datasets/crime/`). Dataset notes live in
[`datasets/crime/DATASET.md`](../../datasets/crime/DATASET.md).

## Question

Build a data-driven, long-run picture of **violent crime** in Nepal, separating
it from the financial and property offences that dominate recent registered-case
totals. Granularity is national monthly + annual; province/district is retained
as detail but not the headline.

## Sources

- CID monthly e-bulletins, `https://cid.nepalpolice.gov.np/publication/4/?page=1..6`
  — primary, 58 bulletins (Bhadra 2075 – Ashoj 2083).
- Nepal Police annual factsheets and secondary reports (INSEC, NHRC, UNODC) are
  context only; no machine-readable national API exists.

## Confirmed schema

Canonical keys are defined in `crime/schema.py`:

- **Months:** Bikram Sambat `YYYY-MM`; fiscal year Shrawan–Ashad.
- **Provinces:** the seven provinces plus `kathmandu_valley`. Some serious-crime
  charts omit the valley; `value_ex_valley` is the comparable series.
- **Offences:**
  - heinous: `murder`, `trafficking`, `rape`, `kidnapping`
  - serious: `attempted_murder`, `suicide_abetment`, `abortion`, `dacoity`,
    `burglary`, `assault`
- **Violent rows:** `month, fy, chart_kind, offense, offense_en, province,
  value, basis, method, confidence, issue_no, page, source_url`.
- **Annual rows:** `fy, series (registered|disposed|pending), value, as_of,
  complete, n_series, source_url`.

Rendered outputs: `violent_monthly.csv.gz`, `violent_national.csv.gz`,
`violent_by_fy.csv.gz`, `total_cases_monthly.csv.gz`, `annual_totals.csv`,
`category_coverage.csv.gz`, `month_status.csv.gz`, `offense_availability.csv.gz`,
`total_case_revisions.csv.gz`, `annual_revisions.csv`, `annual_rates.csv`,
`population_nepal.csv`, `build.json`, `verify.json`, and five charts.

## Extraction approach

The bulletin charts are vector graphics. Each chart is read as:

1. Data labels from the text layer (complete, including explicit zeros).
2. Bar rectangles from `page.get_drawings()` for the baseline, plot area, and
   validation only.
3. Province-major ordering: labels are sorted by `x` and split into
   `n_provinces` chunks of `n_series` values.
4. Title (`जघन्य` / `गम्भीर`) determines chart kind; legend labels are
   fuzzy-matched and backfilled from the known series order.
5. Raster charts with text labels fall back to a text-layer read.
6. Consecutive cumulative charts are differenced into monthly rows.

This is more robust than reading bar heights because bars for zero values are
omitted and chart scales change between issues.

## Pipeline

```bash
python -m crime.cli scrape --download
python -m crime.cli extract
python -m crime.cli build
python -m crime.cli verify
```

Intermediate PDFs and parsed JSON live in gitignored `output/crime/`.

## Open issues

- 2075 uses legacy 8-bit fonts; the standalone Phagun rape chart is decoded.
  Page 5's national offence table supplies national totals for seven violent
  categories, but no province split beyond rape.
- The 2075-11 heinous chart is partial (rape only) and is flagged alongside the
  2083 Bhadra serious chart.
- 2079 Jestha cannot be isolated from its cumulative chart; Asar–Bhadra are
  derived by differencing.
- The 2079 Ashoj heinous chart is raster but readable from text labels.
- The 2083 Bhadra serious chart is partial in the source (one series).
- The 2083 Jestha rape value (30) is a source anomaly and is left unsmoothed.
- Category sets drift between eras; `offense_availability.csv.gz` records
  availability rather than treating missing categories as zero.
- Population figures are estimates anchored to the 2021 census.
