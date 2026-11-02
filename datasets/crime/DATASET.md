# Crime in Nepal — CID monthly bulletins

Structured extraction of the Crime Investigation Department's monthly
e-bulletins (`cid.nepalpolice.gov.np/publication/4/`). Values are transcribed
from the vector charts in each bulletin; chart data labels are the source of
truth and bars are used only for baselines and scale checks.

Coverage: 58 bulletins, Bhadra 2075 — Ashoj 2083 (51 months with usable
province-by-offence charts, 51 months with totals). All dates are Bikram Sambat.

## Files

| File | Grain | Key columns |
|---|---|---|
| `violent_monthly.csv.gz` | month × offence × province | `month`, `chart_kind`, `offense`, `province`, `value`, `basis`, `method`, `confidence` |
| `violent_national.csv.gz` | month × offence | `value`, `value_ex_valley`, `provinces_reported`, `categories_reported`, `source` (`province_sum` or `table_labels`) |
| `violent_by_fy.csv.gz` | fiscal year × offence | `value` (ex-valley), `months_reported` |
| `category_coverage.csv.gz` | month × offence | `provinces_reported`, `reported` |
| `offense_availability.csv.gz` | offence | `months_reported`, `first_month`, `last_month` |
| `month_status.csv.gz` | month × chart kind | `offenses_reported`, `basis`, `method`, `partial_chart` |
| `total_cases_monthly.csv.gz` | month × province | `value`, `as_of` |
| `total_cases_national.csv.gz` | month | `value`, `method` (`province_sum` or `line_labels`) |
| `national_total_revisions.csv.gz` | month | cross-source `values`, `differs` |
| `total_case_revisions.csv.gz` | month × province | cross-bulletin `values`, `differs` |
| `annual_totals.csv` | fiscal year × series | `series`, `value`, `as_of`, `complete` |
| `annual_revisions.csv` | fiscal year × series | cross-bulletin `values`, `differs` |
| `annual_rates.csv` | fiscal year | `registered_cases`, `population`, `registered_per_100k` |
| `population_nepal.csv` | fiscal year | `population`, `calendar_year`, `source` |
| `verify.json` | run summary | integrity checks |
| `build.json` | provenance | git revision, counts, SHA-256 per artifact |
| `charts/*.png` | rendered charts | see below |

`month` is `YYYY-MM` in Bikram Sambat. `fy` is the Nepali fiscal year
(`YYYY/YY`), running Shrawan–Ashad. `basis` is `monthly` or `derived`;
`method` is `chart_labels`, `text_labels`, `cumulative_difference`, or
`table_labels`. National totals use `method=province_sum` where province detail
exists, `method=table_labels` for the 2075-11 national offence table, and
`method=line_labels` for the nine months filled from quarterly registered-case
line charts. `value_ex_valley` is blank for table rows because the source table
has no province split.

Population denominators are the NSO medium-scenario projection
(`Population Projection for Nepal 2021-2051`) for 2021–2027; 2019–2020 use
World Bank WDI `SP.POP.TOTL`. The fiscal-year value is the calendar year
containing the FY midpoint (January).

## Offences

Heinous (`chart_kind = heinous`): `murder`, `trafficking`, `rape`,
`kidnapping`.

Serious (`chart_kind = serious`): `attempted_murder`, `suicide_abetment`,
`abortion`, `dacoity`, `burglary`, `assault`.

The Nepali label for each is in `crime/schema.py`; `offense_en` carries the
English rendering. Category sets change by era: 2082–2083 heinous charts often
omit kidnapping, and serious charts drop abortion from 2082 onward. Missing
series are gaps, never zeros.

## Provinces

`koshi`, `madhesh`, `bagmati`, `gandaki`, `lumbini`, `karnali`,
`sudurpashchim`, `kathmandu_valley`.

Some serious-crime charts report only the seven provinces and omit Kathmandu
Valley. `value_ex_valley` is the comparable series across all months; province
detail is kept as printed.

## Method

1. `python -m crime.cli scrape --download` refreshes `crime/manifests/bulletins.json`
   and downloads PDFs to `output/crime/pdfs/`.
2. `python -m crime.cli extract` parses each PDF to `output/crime/parsed/`.
3. `python -m crime.cli build` writes the committed CSV/chart artifacts.
4. `python -m crime.cli verify` runs integrity checks into `verify.json`.

Charts are read from the PDF drawing layer: bar rectangles establish the plot
baseline, while every printed data label (including zeros) is grouped by
province and series order. Titles determine heinous vs serious; legend labels
are fuzzy-matched and backfilled from the known series order. When a chart is
raster but its labels are text, the labels are read from the text layer.

Cumulative issues are differenced in `build`: 2079 Asar = cumulative Asar −
cumulative Jestha; 2079 Shrawan = cumulative through Shrawan − cumulative
through Asar; 2079 Bhadra = the two-month FY2079/80 cumulative − derived
Shrawan. Derived rows are tagged `basis=derived` and
`method=cumulative_difference`.

## Known caveats

- **Cumulative issues.** 2079 Jestha–Bhadra bulletins publish year-to-date
  charts rather than monthly ones. Jestha cannot be isolated and stays out of
  the monthly panel; Asar, Shrawan, and Bhadra are derived by differencing
  consecutive snapshots. Original cumulative rows remain in the intermediate
  JSON and are excluded from the committed monthly trend.
- **2075 legacy font.** The single 2075 bulletin uses legacy 8-bit fonts for
  some chart text. Decoding recovers its standalone Phagun rape chart, so
  province-level `rape` is available for 2075-11. Page 5 also prints a monthly
  national offence table; it supplies national totals for murder, attempted
  murder, trafficking, suicide abetment, kidnapping, assault, and rape, but no
  province split except for the separate rape chart. Those table rows are
  marked `source=table_labels`; other violent series start in 2079-03.
- **2078 and 2079 Baishakh** use an older layout without province-by-offence
  charts.
- **Raster charts and partial pages.** The 2079 Ashoj heinous chart is an
  embedded image; its text labels are read from the PDF text layer. The
  2075-11 heinous chart publishes only rape, and the 2083 Bhadra serious chart
  publishes only attempted murder; both are flagged as partial in
  `month_status.csv.gz`.
- **2083 Jestha rape = 30** is a source anomaly. Verified against page 10 of
  the bulletin: every province prints a single-digit rape value
  (1, 8, 4, 3, 1, 6, 2, 6; 30 excluding the valley). Neighbouring months are
  ~200–260. It is left as printed rather than smoothed.
- **Annual series.** The five-fiscal-year chart publishes two or three series.
  Older bulletins label the third series differently; each fiscal year is taken
  from the latest bulletin that reports it, so `disposed` and `pending` stay
  internally consistent. `n_series` records the source chart's width.
- **2075/76 annual** reports disposed + pending 54 cases below registered; the
  discrepancy is reported in `verify.json`, not adjusted.
- `total_cases_monthly` is deduplicated by `(month, province)`, preferring the
  earliest `as_of` (the most contemporaneous report). Later bulletins revise
  earlier months; all observations and conflicts are in
  `total_case_revisions.csv.gz`. `annual_revisions.csv` does the same for the
  five-year chart.

## Charts

- `annual_totals.png` — registered vs disposed by fiscal year.
- `heinous_monthly.png`, `serious_monthly.png` — monthly series, excluding
  Kathmandu Valley.
- `violent_by_fiscal_year.png` — stacked annual totals of all violent
  categories; faded bars are incomplete years.
- `total_cases_monthly.png` — nationwide registered cases per month.

## Source

Every row carries `source_url`. PDFs are hashed into `build.json` when present.
The bulletins are published by the Crime Investigation Department, Nepal
Police.
