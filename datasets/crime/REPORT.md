# Violent crime in Nepal — what the CID bulletins show

Analysis of `datasets/crime/` (58 CID e-bulletins, Bhadra 2075 – Ashoj 2083).
All counts are cases registered by Nepal Police. "Violent" = heinous + serious
categories listed below; Kathmandu Valley is excluded from cross-month series
where the source omits it.

## Headline

1. **Violent crime is flat, not rising.** The per-month count moved from 346
   (2079/80) to 371 (2080/81), then 338 and 341 — an 8% fall from the 2080/81
   peak and no meaningful trend (+0.3 cases/month OLS).
2. **The composition changed sharply.** Heinous cases fell ~20% per month from
   the 2080/81 peak while serious cases rose ~18%. The increase is concentrated
   in attempted murder (+32%) and assault/grievous hurt (+52%) between 2081/82
   and 2082/83.
3. **Rape dominates.** It is ~48% of all violent cases and ~76% of heinous
   cases. The apparent 9% drop in 2082/83 is almost entirely one bad source
   value (2083 Jestha = 30 vs ~190–220 in neighbouring months).
4. **Registered crime overall grew faster.** Total registered cases rose from
   56,323 (2079/80) to 61,016 (2082/83), +8.3%, while violent cases stayed flat.
   Violent crime is 7–8.5% of registered cases — the rise in the headline
   total is driven by financial, property, and other offences.
5. **Geography is stable.** Koshi reports ~20% of heinous cases, followed by
   Lumbini and Madhesh (~15–16% each); Kathmandu Valley is ~15%. Per-capita
   comparisons use the population estimates in `population_nepal.csv`.

## Annual picture

Per-month averages avoid the uneven month coverage across fiscal years.
2075/76 is excluded: only its rape chart is available at province level, so it
is not comparable to the full heinous-plus-serious panel. Page 5 of that
bulletin does provide national totals for seven violent categories, but without
a province split they cannot be joined to the ex-valley monthly series.

| Fiscal year | Months | Violent total | Per month | Heinous/mo | Serious/mo |
|---|---:|---:|---:|---:|---:|
| 2079/80 | 12 | 4,153 | 346 | 229 | 117 |
| 2080/81 | 10 | 3,707 | 371 | 238 | 130 |
| 2081/82 | 11 | 3,719 | 338 | 213 | 126 |
| 2082/83 | 11 | 3,751 | 341 | 189 | 152 |
| 2083/84 | 3 | 1,056 | 352 | 210 | 142 |

Across the 48 months with both a heinous and a serious chart, the monthly total
averages **350.3 cases (SD 60.0)**, ranging from 242 to 462. The highest months
are Baishakh 2080 (462), Ashad 2083 (460), and Baishakh 2081 (456).

Registered cases from the annual five-year chart:

| FY | 2075/76 | 2076/77 | 2077/78 | 2078/79 | 2079/80 | 2080/81 | 2081/82 | 2082/83 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Registered | 38,814 | 41,898 | 40,120 | 46,902 | 56,323 | 59,204 | 58,472 | 61,016 |
| Registered per 100k | 136.6 | 144.6 | 136.7 | 158.9 | 189.9 | 198.8 | 195.5 | 203.2 |

Population denominators are in `population_nepal.csv`; see `annual_rates.csv`.

## What moved

Per-month averages by offence (using only months where that category is
reported; missing categories are never treated as zeros):

| Offence | 2079/80 | 2080/81 | 2081/82 | 2082/83 | Change 81/82 → 82/83 |
|---|---:|---:|---:|---:|---:|
| Rape | 172.4 | 178.6 | 158.0 | 144.5 | -9% |
| Attempted murder | 69.2 | 72.5 | 72.7 | 96.2 | **+32%** |
| Murder | 38.6 | 44.0 | 38.5 | 36.8 | -4% |
| Assault / grievous hurt | 12.9 | 13.0 | 15.5 | 23.6 | **+52%** |
| Dacoity | 11.9 | 17.1 | 15.2 | 11.3 | -26% |
| Burglary | 10.5 | 10.5 | 7.7 | 5.3 | -31% |
| Kidnapping | 9.9 | 9.6 | 9.7 | 7.0 | *category dropped* |
| Trafficking | 8.0 | 5.5 | 6.4 | 7.3 | +14% |
| Suicide abetment | 13.6 | 14.8 | 12.7 | 15.5 | +22% |

Two entries are **reporting artefacts, not trends**:

- Kidnapping collapses to near zero in 2082/83 because those heinous charts
  publish only three series. Do not read it as a decline.
- Abortion disappears after 2082/02 because the serious chart drops that
  category.

## The rape anomaly

Monthly rape (excluding the valley) sits around 200–260 in this period. Jestha
2083 is printed as **30**, far below its neighbours (2083-01 = 239, 2083-03 =
263). I checked the page image: the bulletin itself prints single digits for
every province (1, 8, 4, 3, 1, 6, 2, 6). This is a source error, not an
extraction error. The value is left as published. If it were in line with adjacent months, fiscal-year rape
would be roughly flat rather than down 9%, and the heinous decline would shrink
by about 8 points. Any story about rape falling in 2082/83 should not be built
on this series without re-checking the source page.

## Season and geography

- Monthly violent counts are mildly higher in Baishakh–Shrawan (months 1–4,
  ~41–47/month) and lower in Poush–Magh (months 9–10, ~31/month). The
  pattern is weak relative to month-to-month noise and should not be
  over-interpreted.
- Heinous-case share by province is remarkably stable across four years:
  Koshi 20–22%, Lumbini 16–17%, Madhesh 15–16%, Kathmandu Valley 13–17%,
  Bagmati 9–11%, Gandaki 7–8%, Sudurpashchim 8%, Karnali 7–8%.
- Total registered cases in 2082 are more urban-weighted: Kathmandu Valley
  24.7%, Madhesh 18.0%, Koshi 16.6%, Lumbini 13.6%.

## How far to trust this

- Coverage is **51 months**, with gaps (2078, 2079 Baishakh/Jestha, 2082
  Ashad/Shrawan, and two partial chart pages; 2075-11 reports rape only). This
  is not a continuous 90-month panel. Three 2079 months are reconstructed by
  differencing cumulative charts; one 2079 heinous chart is read from text
  labels.
- Category sets drift between eras. Comparisons are strongest within the
  2080–2083 window, which is why the report anchors there.
- The largest months cluster in Baishakh and Ashad, but missing months make
  seasonality tentative.
- The 2083/84 year is only three months old and is excluded from trend claims.
- Counts are registered cases, not victimisation. Reporting behaviour, police
  classification, and category changes can move the series independently of
  underlying crime.

## One-sentence version

Nepal's registered crime total rose 8% in four years, but the violent subset was
flat; the movement inside that flat total was a shift from heinous offences
(especially rape) toward attempted murder and assault, and the single largest
apparent drop — rape in 2082/83 — is largely an artefact of one anomalous printed
value.
