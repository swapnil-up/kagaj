# Nepali Labour Migration Panel

Tidy, verified extraction of labour-approval tables published by the
Department of Foreign Employment (DoFE), `dofe.gov.np`.

The **analysis dataset is `panel_canonical.csv.gz`** — `panel.csv` with canonical
entities/channels/fiscal-years and within-document merges applied (see
*Cross-document reconciliation*). It is **additive-only**: it contains only
`row_type=detail` rows whose `channel_class=component`, so summing it (e.g.
`groupby` a country or a year) can never double-count an aggregate against its
components. Printed totals, `channel_class=aggregate` rows and distinct measures
live in the companion `panel_rollup.csv.gz`, which you compare against but never
add to the primary. Filter `analysis_safe=true` for the safe default set of rows
(it also drops the unreviewed `channel_reviewed=false` channels — see below).
`panel.csv` is the raw extraction; `agencies.csv` holds agency-level detail and
`series.csv` the historical metric series. A machine-readable data dictionary
ships as `codebook.json`; the build is fingerprinted in `build.json`.

**Default table and scope.** Use `panel_canonical.csv.gz` (filter
`analysis_safe=true`) for the headline destination/composition/origin analysis;
it is additive-only, every row passed its document's math audit, **and** every
row uses a `channel_reviewed=true` channel. `analysis_safe` is therefore
`entity_resolved AND verified AND channel_reviewed`; the looser
`analysis_safe_permissive` (`entity_resolved AND verified`) is provided only for
deliberate legalization-specific work, which must be reported as a separate
flagged specification rather than pooled with the reviewed channels. Explicitly **out of scope** for that
default: `panel_rollup.csv.gz` totals, the deaths/return/remittance series in
`series.csv` (different units and bases), and anything derived from the archive
backfill until it lands. Do not screen specifications on the outcome — the
default table and the safe-subset filter are fixed *before* estimation to avoid
p-hacking; any deviation should be reported as such.

**Source integrity.** Every source PDF is hashed when fetched — `pdf_sha256` on
the live manifest, `source_pdf_sha256` on the archive manifest. Run
`python -m migration_parser driftcheck [--recheck]` to catch a source revised in
place before trusting a rebuild; it checks **both** manifests (the archive PDFs
are the ones least likely to be re-examined by anyone else).

`panel.csv` is **one row per (document × section × name × channel × gender)**.
Almost every row is `verified=True`: the printed male/female totals, channel
subtotals, and section grand totals all reconcile exactly against the extracted
cells (see `migration_parser/verify.py`). The sole exception is one document
(`report2020_annex_X`) whose printed Recruiting-Agency total is off by one in
the source (Qatar; see Notes below) — its rows are `verified=False`.

## Book source

| Field | Meaning |
|-------|---------|
| `doc_id` | DoFE content id from the detail-page URL (`/content/{id}/`), else the manifest serial |
| `source_url` | Direct PDF URL (provenance) |
| `doc_type` | classified document type, e.g. `annual`, `single_month`, `progress`, `annex` (see below) |

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

**Report-Annex template** — the `migration_2020` Annex tables (FY2017/18 &
FY2018/19), which predate the live templates and carry **no S.N. column**:

| `channel` | Printed group | Table |
|-----------|---------------|-------|
| `recruiting_agency` | Recruiting Agency | IX, X |
| `new_entry` | New Entry | IX |
| `regularized_entry` | Regularized Entry | IX |
| `re_entry` | Re-Entry | IX |
| `individual_new` | Individual-New | X |
| `individual_regularization` | Individual-Regularization | X |
| `individual_renew` | Individual-Renew | X |
| `total_with_reentry` / `total_without_reentry` | Total With/Without Re-Entry | IX |
| `total_with_renew` / `total_without_renew` | Total With/Without Renew | X |
| `individual` | Individual mode (New, Renew & Regularization) | XII |

Note Table X prints its two totals in the **opposite order** (Without, then
With) to Table IX; each table's With/Without/Re-Entry role is declared in
`migration_parser/annex.py` (`ANNEX_COUNTRY`), so the swap is handled.

**Pre-approval (पूर्व अनुमति)** documents (#030–#032) print a country summary
`SN | Country | Male | Female | Total`. These are emitted with
`channel="preapproval"` (a whole-document channel, not one of the templates
above); they have no channel breakdown, so the component/With invariants do not
apply — only `Σ countries = Total` and `M+F=T`.

### Canonical channel mapping

The raw `channel` values above are preserved. For cross-year aggregation,
`migration/channels.json` (+ `normalize.canonical_channel()`) maps every source
channel to one canonical channel with a `class`:

| class | meaning | members |
|-------|---------|---------|
| `component` | a deployment channel (summable) | `recruiting_agency`, `individual_new`, `g2g`, `individual_reentry`, `legalization`, `new_entry` |
| `aggregate` | a printed total / roll-up — **never sum with components** | `total_with_reentry`, `total_without_reentry`, `individual` (Annex XII) |
| `measure` | a distinct non-channel measure | `preapproval` |

Justified equivalences (asserted, with per-entry `note` in the JSON):

| source | → canonical | note |
|--------|-------------|------|
| `legalized_entry`, `regularized_entry`, `individual_regularization` | `legalization` | same concept across old/Annex IX/Annex X |
| `re_entry`, `individual_renew` | `individual_reentry` | same concept |
| `total_with_renew` / `total_without_renew` | `total_with_reentry` / `total_without_reentry` | Annex X wording |
| `new_entry` | `new_entry` (**not** merged) | old template does not split individual_new vs g2g, so it stays distinct rather than being mis-counted as `individual_new` |

The `normalize` stage appends `channel_canonical` + `channel_class` to
`panel_normalized.csv`.



Per (section, name):
- `male + female = total` for every channel group;
- component channels sum to the template's *With* total (per gender) —
  `total_with_reentry` normally, `total_with_renew` for Annex Table X;
- *With* total − the re-entry/renew channel = the *Without* total.

Per section: `Σ detail rows = printed Total row`, for every numeric column
(live wide tables; the Annex country tables have no separate Total row to check).

## Coverage

Live DoFE catalogue (35 documents, `bill-tracker/migration_manifest.json`):

- **Monthly** — 17 reports, BS 2082 Shrawan → 2083 Shrawan. Extracted.
- **Yearly** — 7 statements, BS 2076/77 → 2082/83. Extracted.
- 1 older annual statement (2073/74, country-wise only). Extracted.

From the `migration_2020` report Annexes (extends approvals backward):

- **Table IX/X** — country × channel, FY 2074/75 (2017/18). Extracted.
- **Table XI–XIII** — origin district × Men/Women/Total, FY 2074/75 (XI: RA,
  XII: individual mode) and FY 2075/76 (XIII: RA). Extracted.
- **Pre-approval** (#030 Ashadh 2075, #031 Jestha 2075, #032 FY2073/74) —
  country × Male/Female/Total summaries. Extracted (`channel="preapproval"`).

Institutional (संस्थागत) and pre-approval **agency-level** lists are extracted
into the tracked `agencies.csv` (see below).

Not yet extracted (different layouts — see `MIGRATION_NOTES.md`):
labour bulletins (narrative; #033–#035 carry no approval table) and 2 scanned
PDFs (#018 handwritten, #026 printed-English RA-wise list — no usable text layer).

## Reproduction

Everything is driven through the `migration_parser` package CLI:

```bash
# One-command reproducible build (offline, from cached PDFs) + packaging:
redbook-env/bin/python -m migration_parser.cli build

# Refresh the manifest from the live site first, then build:
redbook-env/bin/python -m migration_parser.cli build --scrape

# Re-normalise / re-verify / re-package from the existing panel only:
redbook-env/bin/python -m migration_parser.cli build --skip-extract
```

Run a single stage with `python -m migration_parser.cli <stage>` where `<stage>`
is one of `scrape`, `process`, `annex`, `agencies`, `series`, `normalize`,
`reconcile`, `verify`, `crosscheck`, `build`.

`build` runs `process → annex → agencies → series → normalize → reconcile →
verify → crosscheck`, then packages the results and writes `build.json` (git
revision, row counts, SHA-256 checksums, audit pass/fail) and `codebook.json`.
It finishes non-zero if any audit fails.

Per-document CSVs are written to `output/migration/docs/` (manifest docs as
`{serial}_{id}.csv`, Annex tables as `annex_{IX..XIII}.csv`, pre-approval
summaries as `preapproval_0{30,31,32}.csv`) and the combined `migration/panel.csv`
is rebuilt from **all** of them (idempotent). `agencies.csv` is written directly.

## Historical series (`series.csv`)

The five narrative DoFE reports (not the tabular monthly/yearly statements)
print many "name × fiscal-year" matrices measuring **different metrics**. These
are extracted separately into `series.csv` — one row per
`(report × table × name × fiscal_year)` — because mixing them into `panel.csv`
would conflate incompatible measures.

| Field | Meaning |
|-------|---------|
| `series_key` | **Summation-safe block key** = `report\|source_page\|caption\|metric\|dimension\|unit\|year_basis\|gender`. Rows sharing a key differ only in `name`/`fiscal_year`/`note`; sum `count` **only within a key**. Keys are single-valued in unit/basis/gender by construction, so summing across keys can never silently mix counts with percents, fiscal with calendar, or totals with male+female. |
| `report` | Source report key: `status_2013_14`, `status_2014_15`, `status_2015_17`, `country_intro_2019`, `migration_2020`, `migration_2024` |
| `source_page` | 1-based page in the source PDF |
| `caption` | Printed table caption (the primary disambiguator — always filter on this before summing) |
| `metric` | `labour_approval`, `deaths`, `deaths_by_cause`, `return_migration`, `migration_stock`, `detention`, `hospitalisation`, `mrrc_cases`, `remittance_receiving`, `remittance_use`, `remittance_cost`, `migration_cost`, `disability_compensation`, `complaints`, `assistance`, `no_objection_letters` |
| `dimension` | `country` (destination), `district` (origin), `province` (origin), `occupation`, `skill`, `residence_status`, `case_type`, `remittance_use`, `category`, or `unknown` |
| `unit` | `count` (people), `percent` (share; decimals kept), `npr` (amount per remitter), or `usd` (cost/earnings) |
| `name` | Country/district/province/occupation (or other row label) |
| `fiscal_year` | `YYYY/YY` fiscal year, `YYYY` when `year_basis=calendar`, blank for snapshots |
| `year_basis` | `fiscal` (default), `calendar`, or `snapshot` — never sum across bases |
| `gender` | `male`, `female`, `total`, or blank for plain matrix rows |
| `count` | value (people, percentage when `unit=percent`, NPR when `unit=npr`) |
| `note` | cause for `deaths_by_cause`; destination for `dimension=occupation`; MRRC period; hospital/shelter section; remittance priority; else blank |

**Caveats**

- A few tables measure **shares (%)**, flagged by `unit=percent`; do not sum
  them with `count` rows.
- `year_basis` distinguishes fiscal-year series from calendar-year series
  (Japan residents 2013–2023) and undated `snapshot` tables (jail/detention,
  hospital/shelter, MRRC, remittance); filter on it before summing `fiscal_year`.
- Percent tables keep their decimals (`unit=percent`); counts/NPR are integers.
- `deaths_by_cause` tables are **subsets** of the all-cause `deaths` tables in
  the same report — never add them together.
- The same metric can appear in several reports/years; deduplicate on
  `(metric, dimension, name, fiscal_year)` and prefer the latest report.
- Row totals (Σ years vs the printed `Total` column) verify exactly; column
  totals are skipped because continued tables print one cumulative Total row
  spanning pages.

Extracted sets — `labour_approval` by district and destination country
(male/female, 2012/13–2016/17), deaths (all-cause by year and gender
2008/09–2023/24, plus country/district/cause breakdowns to 2016/17), disability
compensation, complaints, and assistance. The all-cause deaths series is read
from the transposed "Cause of Death" table in the Nepal Labour Migration
Report 2024 (Table 4.1, years down the rows; all-cause = row sum, which equals
the printed totals) — with the 2020 report's "Cause of Death by Year" (printed
Total M/F) and the status reports as fallbacks. Overlapping years match exactly
across all three sources.

Newer additions (2026 coverage sweep):

- **All-cause deaths by origin province and sex** — 2024 Tables 4.2 (destination
  country) and 4.4 (province), 2022/23–2023/24; province totals reconcile to the
  national all-cause series.
- **`return_migration`** — returnee counts by sex for 2022/23–2023/24 from 2024
  Annex 12 (destination country) and Annex 13 (origin district). Annex 13 sums
  reproduce the printed Grand Total exactly (2022/23 T=546,023; 2023/24
  T=537,246). Extracted by `extract_year_gender_blocks` (district name column +
  repeated year/sex blocks, single-letter `Women` folded to `female`).
- **`dimension=occupation`** — 2016/17 occupation profiles by destination
  (recruitment-agency only) from status-report Tables 25–31; `note` holds the
  destination. Read as counts (the trailing single-letter percentage block is
  ignored).
- **Skill / occupation composition crosstabs** — 2024 T3.7 (skill × mode),
  T3.10 (destination × skill, with a `Total N` **count** column beside the `%`
  columns) and T3.13 (occupation × mode × sex), for 2022/23–2023/24; year runs
  down column 0, category down column 1. `extract_measure_crosstab` handles the
  one- or two-row header, carrying a merged mode group (`G2G`/`Individual`/…)
  across its sex columns and reading decimals (incl. `"1.08 %"`). The paired
  province × top-5 table T3.2 is skipped (`_SKIP_CAPTION_RE`) as it does not fit
  the name × year shape.
- **Calendar-year series** — 2024 Table 3.19 (mid- to long-term Nepali residents
  in Japan by status of residence, 2013–2023), tagged `year_basis=calendar` and
  `dimension=residence_status`. Extracted by `extract_calendar_year_matrix`.
- **Welfare / harm snapshots** (`year_basis=snapshot`) — 2024 Table 4.5
  jail/detention by country (`metric=detention`), T4.6 hospitalised/shelters by
  country (`metric=hospitalisation`, section in `note`), T4.7 MRRC cases by type
  × sex (`metric=mrrc_cases`, only the `Total N` row is a count), T4.8
  remittance-receiving households by province (`metric=remittance_receiving`,
  `unit` = `percent`/`npr`), and T4.9 use of remittances by priority × 2011/2023
  (`metric=remittance_use`, `year_basis=calendar`). Also 2020 T17 cause of death
  by destination (`deaths_by_cause`, country), T19 remittance transfer cost (%,
  `note`=amount tier), and 2019 T12 migration cost vs earnings (`unit=usd`).
- **2018/19 labour permits by destination and sex** — Country Profile 2019
  Table 8 (32 destinations × Male/Female/Total, both `No.` counts and `%`
  shares, `fiscal_year=2018/19`).

Reproduce with:

```bash
redbook-env/bin/python -m migration_parser.cli series
```

## Agency-level lists (`agencies.csv`)

Two families of agency-grained tables are extracted into the tracked
`migration/agencies.csv` — one row per (document × agency):

| `measure` | Source docs | Columns used |
|-----------|-------------|--------------|
| `preapproval` | #030–#032 detail tables | `sn, lot_no, country, agency, male, female, total` |
| `institutional` | #027 (2077/78), #028 (2076/77) | `sn, agency, male, female, total` |

Fields: `measure, doc_id, period_bs, period_ad_start, period_ad_end, doc_type,
sn, lot_no, country, agency, male, female, total, source_page, verified,
source_url`. The pre-approval detail tables are parsed from the PDF text layer
(agency names are English); the institutional lists likewise. Verification:
`M+F=T` per row; institutional docs reconcile exactly to the printed Grand
Total (#027 → 55,879/5,549/61,428; #028 → 157,137/15,129/172,266).

**Caveat — `preapproval_032` is incomplete.** Its source PDF has one fully blank
page and several pages whose text layer was rasterised to outlines (visible but
not extractable). 306 of 23,994 detail rows are absent, so all its
`verified=False`; the missing rows cannot be recovered without OCR of outlined
pages. All other docs are complete.

## Entity & period normalisation

Raw names vary across sources (case, prefix, truncation, spelling) so
cross-document aggregation needs a canonical layer. Three tracked reference
files plus a normaliser apply it **without mutating the raw columns**:

| File | Contents |
|------|----------|
| `migration/countries.json` | 170 canonical destinations: `name`, `iso3`, `aliases[]`, `resolved`; flagged non-countries carry `kind`/`note` |
| `migration/districts.json` | 79 canonical districts: `name`, `province`, `aliases[]`; pre-2018 `Rukum`/`Nawalparasi` splits carry `note` |
| `migration/fiscal_years.json` | `fiscal_years[]` (BS label ↔ AD start/end, `ad_source`) + `months[]` (BS month name ↔ Devanagari variants) |

`migration_parser/normalize.py` loads these and resolves a raw name → canonical
record; the `normalize` stage writes the normalised companions
**`migration/panel_normalized.csv`** and
**`migration/agencies_normalized.csv`** by *appending* columns:

- panel: `entity_type, name_canonical, iso3, province, entity_note, entity_resolved, fiscal_year, channel_canonical, channel_class, channel_reviewed, granularity, reconciled_fiscal_year, period_override, analysis_safe, analysis_safe_permissive`
- agencies: `country_canonical, country_iso3, fiscal_year`

`fiscal_year` is derived from the row's BS period — annual labels directly,
monthly labels via the BS-month index (Shrawan..Ashadh ⇒ one FY), and for older
annual docs whose BS period the parser could not read (empty `period_bs`) from a
content-id map in `normalize.py`.

**Caveats**

- 480 detail rows are `entity_resolved=false`: flagged groupings
  (`Africa`, `West-Indies`), the ambiguous printed `MALABO`/`Kango`/`Saipan`/
  `East Africa Djibouti`, and the source-clipped `Republic o`/`REPUBLI` names
  (content 332's country column clips labels to ~22 pt, losing which "Republic
  of…"). They are kept verbatim, never force-mapped. The clipped names are
  additionally suffixed with their source serial (`Republic o (sn 9)`,
  `REPUBLI (sn 55)`) so they are unique in `name_canonical` and never merge under
  a groupby — see *Cross-document reconciliation*.
- Province values are lowercase keys and always one of the seven modern
  provinces (`koshi`, `madhesh`, `bagmati`, `gandaki`, `lumbini`, `karnali`,
  `sudurpashchim`) — never a compound. The two pre-2018 unified districts are
  each mapped to a single province via their historical district HQ
  (`Nawalparasi` → `gandaki`, `Rukum` → `karnali`); the split is documented per
  row in `entity_note` and in `districts.json`. (These appear only in the
  pre-split annual reports, FY2074/75–2079/80.)
- `panel_normalized.csv`/`agencies_normalized.csv` are **generated** (and
  gitignored — they are ~30 MB near-duplicates of the raw files); rerun the
  script after any panel rebuild.

```bash
redbook-env/bin/python -m migration_parser.cli normalize
```

## Cross-document reconciliation

The panel mixes documents that describe overlapping quantities, so summing them
naively double-counts. `migration/reconciliation.json` records the rule and the
`reconcile` stage applies + audits it, writing two gitignored files:
`migration/panel_canonical.csv` (**additive-only**: `row_type=detail` ×
`channel_class=component`) and `migration/panel_rollup.csv` (aggregates, measures
and printed totals). The split is enforced — reconcile fails if any non-component
row reaches the primary, or if the primary is not unique on the documented dedup
key. After packaging these become `panel_canonical.csv.gz` / `panel_rollup.csv.gz`.

**Rule** (see the JSON for the full text): never mix granularities — within a
fiscal year use *either* all monthly docs *or* the annual doc; Table IX/X
(country) and XI/XII/XIII (district) are the same measure along different
dimensions (pick one); pre-approval (`channel_class=measure`) is a distinct
stage. Dedup key: `granularity, reconciled_fiscal_year, period_ad_start,
section, name_canonical, gender, channel_canonical, row_type`.

Two applied corrections documented in the JSON:

1. **Period override.** `report2020_annex_X` is *printed* FY2074/75 but its data
   is FY2018/19 — its recruiting-agency total (208,351) equals Table XIII's
   (208,349), while Table XI (2017/18) 323,877 equals Table IX's 323,876. Rows
   get `reconciled_fiscal_year=2075/76` and `period_override=true`; the raw
   period columns are left as printed.
2. **Intra-document merges.** Where the source lists one country under two
   spellings (e.g. `Combodia` + `Cambodia` in doc 332), the rows resolve to one
   entity and are summed (`merged_rows`, `raw_names` in the output).

`granularity` (`month`/`year`/`measure`), `channel_reviewed`,
`analysis_safe` (`entity_resolved AND verified AND channel_reviewed`) and
`analysis_safe_permissive` (`entity_resolved AND verified`) are appended by the
`normalize` stage. `channel_reviewed=false` marks a channel whose cross-template
equivalence is a *single-analyst judgment call* not covered by the opendata
cross-check — currently `legalization` and the old-template `new_entry`. The safe
default `analysis_safe=true` excludes them; reach for `analysis_safe_permissive`
only when legalization is the object of study, and report those results as a
separate specification rather than pooling them with the reviewed channels. The audit asserts **no canonical key is produced by more than one
document** (currently 0 conflicts; 1599 intra-doc merges), that the primary is
unique on the dedup key, and that the annual doc reconciles to the sum of its
months.

**Source-clipped entities never merge.** Content 332's country column clips
labels to ~22 pt, turning four different countries into the literal string
`Republic o` (S.N. 9/14/30/76) and one more into `REPUBLI` (S.N. 55). The full
names are unrecoverable from the PDF text layer (verified). Normalisation
therefore suffixes the source serial — `Republic o (sn 9)` … — and keeps
`entity_resolved=false`, so a downstream `groupby(name_canonical)` can never
silently merge them. The `dedup_key` alone is now sufficient for resolved rows;
unresolved rows are additionally keyed by `(doc_id, sn)` as a belt-and-suspenders
guard.

```bash
redbook-env/bin/python -m migration_parser.cli normalize
redbook-env/bin/python -m migration_parser.cli reconcile
```

## Panel-wide verification

`migration_parser/panel_verify.py` re-checks the math invariants on the *melted*
panel (canonicalising channels first, since the panel stores the raw printed
names), independently of extraction:

```
Male + Female                       = Total            (each channel)
Σ component channels (per gender)   = Total with Re-Entry
Total with Re-Entry − Re-entry      = Total without Re-Entry
Σ detail rows                       = printed Total
```

`migration_parser/scripts/cmd_verify.py` (the `verify` stage) runs it over
`migration/panel.csv` and writes the tracked `migration/verification.json`.
Failures listed in `reconciliation.json` → `known_arithmetic_errors` (currently
the two Qatar 1-worker mismatches in `report2020_annex_X`) are tolerated; any
other failure exits non-zero.

**`verified` contract.** `verified=True` on a row means *its document's*
extraction-time math audit passed (`verify.py`); `verified=False` marks a
document with a known printing error we reproduce rather than "correct". Panel
result: 102,744 rows, 2 known failures, 0 unexpected; only `report2020_annex_X`
is unverified.

```bash
redbook-env/bin/python -m migration_parser.cli verify
```

## Cross-check against opendatanepal

opendatanepal digitised part of the same DoFE data (Nepal Labor Migration
Report 2022) into tidy CSVs. It is used **only as an independent cross-check** —
never to fill panel gaps. The `crosscheck` stage joins opendata rows to the panel
on `(fiscal_year, entity, channel, gender)` and writes the tracked
`migration/crosscheck.json`.

| check | panel mapping | opendata × panel |
|-------|---------------|------------------|
| `ra_by_country` | recruiting_agency / total | 544,833 × 544,855 (**0.004%**) |
| `women_renewing` | individual_reentry / female | 50,430 × 50,430 (**0.000%**) |
| `new_approvals_total` | total_without_reentry / total | 113,355 × 113,312 (**0.038%**) |
| `new_individual` | individual_new / total | — (**not comparable**, see below) |

The three comparable checks agree to **< 0.05%** — strong independent validation
of the country, gender and total dimensions. `new_individual` is *not
comparable by construction*: the opendata file is a **top-N per-year ranking**,
listing only 10–12 destinations each year (10/10/10/12 rows for 2018/19 →
2021/22), not the full country distribution, so no aggregate comparison is
meaningful. It is reported as `status: not_comparable` in `crosscheck.json` and
excluded from pass/fail. opendata covers FY 2018/19 → 2021/22 only; its
`Others`/`GCC countries` aggregate rows are skipped.

```bash
redbook-env/bin/python -m migration_parser.cli crosscheck
```

## Packaging & data availability

`python -m migration_parser.cli build` produces the shipped artifacts and is the
canonical way to reproduce them:

| Shipped file | Rows | Role |
|--------------|------|------|
| `panel_canonical.csv.gz` | 70,104 | **primary analysis dataset** — additive-only (gzipped) |
| `panel_rollup.csv.gz` | 31,041 | aggregates + measures + printed totals (gzipped; never sum with the primary) |
| `panel.csv` | 102,744 | raw tidy-long extraction (provenance) |
| `agencies.csv` | 26,224 | agency-level pre-approval / institutional detail |
| `series.csv` | 9,208 | historical metric series from narrative reports |
| `period_windows.csv` | 28 | reporting-window lookup (`period_bs` → AD start/end) for date merges |
| `codebook.json` | — | machine-readable column dictionary + vocabularies + per-file checksums |
| `build.json` | — | build manifest: git revision, timestamp, row counts, SHA-256, audit pass/fail |
| `source_attestation.json` | — | frozen per-source page count + per-page text digests (offline `provenance --verify`) |

`build` gzips `panel_canonical`/`panel_rollup` deterministically (mtime=0), writes
`period_windows.csv`, and writes `build.json` + `codebook.json`; it exits non-zero
if any audit (reconcile, verify, crosscheck) fails, if the codebook columns or
**controlled vocabulary values** drift from the shipped data (this is what caught
`year_basis=snapshot`), or (`--require-clean`) if the tree is dirty. The recorded
`build.json.git.commit` is a real ancestor of `HEAD` with `dirty=false`
(regression-tested), so provenance verifies from a clean clone. See
`DATA_AVAILABILITY.md` for citation, licence and caveats.

**Analysis helpers** (`migration_parser/analysis.py`) make the two remaining traps
hard to fall into: `merge_periods(df, "date")` joins an external series on the
exact `period_ad_start`/`period_ad_end` window (~4 weeks, not a calendar month),
and `fiscal_year_panel(df, prefer="annual")` returns a single per-fiscal-year
basis so monthly and annual rows are never summed together.

The near-duplicate `panel_normalized.csv` / `agencies_normalized.csv` and the
uncompressed `panel_canonical.csv` are **generated** and gitignored.

## Architecture

| File | Role |
|------|------|
| `migration_parser/model.py` | templates (`channels_for`), `DocMeta`, `WideRow` |
| `migration_parser/parser.py` | `extract_doc()` / `melt()` — wide live tables |
| `migration_parser/verify.py` | math audit of the wide tables |
| `migration_parser/panel_verify.py` | independent math audit of the melted panel |
| `migration_parser/series.py` | `extract_series()` — historical year-matrices |
| `migration_parser/annex.py` | `extract_annex()` — migration_2020 Annex IX–XIII |
| `migration_parser/agencies.py` | `extract_summary/_detail/_institutional()` — pre-approval & institutional |
| `migration_parser/normalize.py` | canonical entity / fiscal-year / channel resolution |
| `migration_parser/periods.py` | AD-window / BS-period / doc-type parsing |
| `migration_parser/analysis.py` | analysis helpers: window merge, per-FY basis (`load_panel`, `merge_periods`, `fiscal_year_panel`) |
| `migration_parser/paths.py` | shared paths & DoFE constants (no bill-tracker dependency) |
| `migration_parser/codebook.py` | column dictionary → `codebook.json` |
| `migration_parser/cli.py` | `python -m migration_parser.cli <stage>` dispatcher |
| `migration_parser/scripts/cmd_scrape.py` | build `migration_manifest.json` (35 live docs) |
| `migration_parser/scripts/cmd_process.py` | download → extract → verify → `panel.csv` |
| `migration_parser/scripts/cmd_annex.py` | `migration_2020` Annex tables → `panel.csv` |
| `migration_parser/scripts/cmd_agencies.py` | pre-approval/institutional → `panel.csv` + `agencies.csv` |
| `migration_parser/scripts/cmd_series.py` | reports → `series.csv` |
| `migration_parser/scripts/cmd_normalize.py` | append canonical entity/period/channel columns |
| `migration_parser/scripts/cmd_reconcile.py` | apply + audit cross-document reconciliation |
| `migration_parser/scripts/cmd_verify.py` | panel-wide math audit → `verification.json` |
| `migration_parser/scripts/cmd_crosscheck.py` | opendatanepal cross-check → `crosscheck.json` |
| `migration_parser/scripts/cmd_build.py` | reproducible build + packaging → `build.json`, `codebook.json` |
| `migration/countries.json` · `districts.json` · `fiscal_years.json` · `channels.json` · `reconciliation.json` | canonical reference data |

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
- The `migration_2020` **Annex country tables have no S.N. column** (name in
  col 0) and Table X prints its totals **Without-then-With** (opposite of IX);
  `annex.py` handles both via the per-table config.
- **Source arithmetic typos exist.** Annex Table X (p150) prints Qatar's
  Recruiting-Agency total as 68955 while its Men+Women = 68956; the extractor
  reproduces the printed numbers and marks `report2020_annex_X` `verified=False`
  rather than silently "correcting" the source.
- **Outlined/blanks in a text PDF.** `preapproval_032` (294 pp) has one blank
  page and pages whose text was converted to vector outlines (visible, no text
  layer, no embedded image) — 306 rows are unrecoverable from the text layer.
- Harmless noise: PyMuPDF "pymupdf_layout" warning and MuPDF zlib/syntax errors
  from scanned PDFs.

## Coverage audit & gaps (table/chart sweep)

A full sweep (every `find_tables()` block + every printed `Table/Figure/Annex`
label, newest report → oldest) confirmed what the pipeline captures and what it
still drops. We currently extract **two shapes only**: name × *fiscal-year*
matrices (`series.csv`) and the live DoFE wide templates (`panel.csv` /
`agencies.csv`). Everything else is skipped.

### Per-source status

| Source | Captured | Gaps |
|--------|----------|------|
| Live DoFE monthly (modern 21-col) | country/district × channel × sex, RA lists | — |
| Live DoFE yearly (old 18-col) | same | — |
| Pre-approval / institutional (serials 27–32) | captured | — |
| **Migration Report 2024** | 23 tables (approvals 2017/18–2023/24; skill/occupation crosstabs 3.7/3.10/3.13; deaths 4.1; deaths by country 4.2 & province 4.4; Japan residents 3.19; jail/detention 4.5; hospital/shelter 4.6; MRRC 4.7; remittance households 4.8; remittance use 4.9; trainees 4.11; Annexes 12 + 13) | T3.1, T3.17, Fig 3.19, Annexes 2–11 |
| **Migration Report 2020** | T15 disability, T16 deaths, T17 cause×country, T19 remittance cost | T2/T21 skills, T3–5 returnée, T20 savings bond, T26 occupation, Annexes I–X |
| **Country Profile 2019** | T8 permits by destination & sex, T9 welfare assistance, T12 migration cost | T5–7, T13, T17/18 (16 numeric tables) |
| **Status 2015/17** | 26 tables (T25–31 occupation profiles added) | T1, T7, T11, DATASET 4/7 |
| **Status 2014/15** | 26 tables | T1, T7–14, T21, DATASET 7, Annex II |
| **Status 2013/14** | 8 tables | T1, T2, Fig 3/4, T5, T7–9, Annex IV |
| Bulletins #033–035 (`no_table`) | — | welfare-fund claims/compensation, minimum wage, training-by-district, annual targets |

### Systematic blind spots

1. **Calendar-year series** — partially addressed: `year_basis` + 
   `norm_cal_year()` capture column-oriented calendars (Japan 2013–2023). Still
   invisible: Korea EPS 2008–2016 (years down rows, multi-measure) and
   census/absent-population 1911–2011 (figure-embedded).
2. **Cross-tabs / multi-dimensional tables** — partially addressed:
   `extract_measure_crosstab` captures the 2024 skill/occupation × mode/sex
   cross-tabs, and year×sex/country×sex blocks handle T4.2/T4.4 and Annex 12/13.
   Remaining: cause × country, province × destination × sex (T3.17), and
   destination × province top-5 (T3.2).
3. **Single-period breakdowns** — e.g. per-year province/country cuts.
4. **Unmodelled metrics** — mostly addressed: return migration, jail/detention,
   hospitalised/shelters, MRRC cases and remittance households/use are now
   captured as `year_basis=snapshot`. Remaining: migration cost, jail/
   hospitalisation outside 2024.
5. **Figure-embedded data tables** — e.g. Figure 3.19 (EPS-TOPIK) is really a
   data table; most other figures are visual duplicates of tables.
6. **Bulletin one-offs** — small welfare/training tables.

### Backlog (highest value → lowest)

- [x] **1. Deaths by origin province & sex** — 2024 T4.2 (sex × destination) and
      T4.4 (province × year × sex, 2022/23–2023/24). **done**
- [x] **2. Return migration** — 2024 Annex 12 (destination country) and Annex 13
      (origin district), by sex, 2022/23–2023/24. **done**; T3.17 (province ×
      destination × sex, p70–71) deferred — its nested run-on `Total` rows are
      lossy and Annex 12/13 cover the same metric at country/district level.
- [x] **3. Occupation / skill composition** — Status T25–31 (occupation × sex by
      destination, 2016/17, counts); 2024 T3.6 (skill × year) and the T3.7/T3.10/
      T3.13 crosstabs (skill/occupation × mode/sex, 2022/23–2023/24). **done**;
      2020 T26 (transposed top-5-by-occupation) still open under item 6.
- [~] **4. Calendar-year series** — `year_basis` flag + `norm_cal_year` +
      `extract_calendar_year_matrix` added; Japan residents (2024 T3.19,
      2013–2023) captured. Open: Korea EPS (2015/17 T1, years down rows,
      multi-measure), census/absent-population figures (2011/2021) — both need
      row-oriented or figure-table handling.
- [x] **5. Remittance & welfare** — 2024 T4.5 (jail/detention), T4.6
      (hospitalised/shelters), T4.7 (MRRC cases), T4.8 (receiving households),
      T4.9 (use). **done**
- [~] **6. Remaining breakdowns** — 2020 T17 (cause of death by country), T19
      (remittance cost), 2019 T8 (permits by destination & sex) and T12
      (migration cost) **done**. Open: 2020 T20 (savings bond), 2019 T13
      (prose migration-cost components), 2020 T2/T21/T3–5, Annexes I–X,
      bulletin one-offs.

Implementation note: features 1–3 were built on a shape-generalising layer in
`series.py` that keys on *caption → metric* and emits **dimensions** (`name`,
`gender`, `fiscal_year`, `note`) rather than the strict name × year matrix:
`extract_year_gender_blocks` (repeated year/sex blocks down the rows — used for
T4.2/T4.4 and Annex 12/13), `extract_cross_tab` (row-caption dispatcher), and
`extract_occupation_profile` (occupation × sex from a caption-named
destination-year). `extract_cross_tab` skips `Total`/`Grand Total` rows on the
**raw** label before `_clean_name` strips a trailing "Total" (which otherwise
turned "Grand Total" into "Grand" and double-counted grand totals).

## Roadmap / what's left

**Normalisation & reconciliation**
- ~~Canonical `countries.json` / `districts.json` / `fiscal_years.json` entity
  normalisation~~ **done** (see *Entity & period normalisation*).
- ~~Canonical **channel mapping** across the three templates (modern 7-channel /
  old 6-channel / Annex typologies)~~ **done** (see *Canonical channel mapping*).
- ~~**Cross-document reconciliation & dedup**: overlapping periods/measures
  (annual vs cumulative vs monthly; #029 vs Annex; pre-approval vs final)~~ **done**
  (see *Cross-document reconciliation*).
- ~~Panel-wide **verification pass**: per-period totals, duplicate/overlap
  detection, documented `verified` contract~~ **done** (see *Panel-wide
  verification*) — overlap detection now lives in *Cross-document
  reconciliation*.

**Coverage extension** — see *Coverage audit & gaps* for the prioritised backlog
(narrative-report tables/charts not yet extracted).
- **Archive.org backfill** of older monthly progress reports (before BS 2082) —
  see *Archive.org backfill — yield analysis & plan* below.
- **Bulletins #033–#035** — the last `no_table` docs (narrative); assess whether
  they add numbers or merely restate.
- Optional: manually transcribe **#026** (2079/80 RA-wise agency list) if that
  granularity is needed.

### Archive.org backfill — yield analysis & plan

> **Research-design warning (read before scoping a paper).** High-frequency
> coverage in the *primary panel* starts in 2025/26: its monthly windows run
> 2025-04 → 2026-09 only. The headline natural experiments a migration economist
> would reach for — the Qatar 2022 World Cup, the Malaysia 2018–20 policy swings,
> the Israel quota changes — sit in **BS 2075–2081 (2018/19–2024/25)**. The
> Wayback archive **does capture monthly country reports inside that window**
> (BS 2075 Baishakh/Jestha/Shrawan/Bhadra/Ashoj, plus BS 2080/81 and BS 2081/82
> progress reports), but they are a **newer DoFE template that the current
> family-(a) extractor reads as 0 rows** — the same limitation already noted for
> BS 2080/2081 below. The window is therefore an **extractor gap, not a source
> hole**: closing it needs a *new-template extractor* (or a different source —
> DoFE directly, MoLESS reports), not more filename-resolving. The archive panel
> that *does* extract covers **BS 2067–2073 (2010/11–2016/17)**. Annual data
> (through FY2081/82) is the best input currently available for those questions.
> Do not write "event study" or "high-frequency" into a design doc against the
> current data without stating this. (Corrects an earlier README claim that the
> archive held *no* in-window captures — see `migration/CHANGELOG.md`,
> 2026-10-17.)

Assessed read-only via the Wayback Machine. **Family (a)** (monthly country-wise)
is now extracted (`migration_parser/historical.py`) and shipped as a separate
archive panel (BS 2067–2073); families (b)/(c) are still pending. The original
goal was to extend `panel.csv` backward from BS 2082 (2025/26) to ~BS 2065
(2008/09). The BS 2075–2081 in-window captures are a newer template (unscoped,
above); note also that the filename-based `resolve` skips family-(a) reports
whose names carry no year token (e.g. the bare-month `ashoj.pdf`/`baisakh.pdf`
set, which are actually **BS 2071/72** and extract fine) — so the manifest
under-counts the pre-2074 archive by filename heuristics, separate from the
template gap.

**Verified facts** (two live docs pulled via
`https://web.archive.org/web/{ts}id_/{url}`):

- Captures resolve to `application/pdf` and are **native vector PDFs** —
  `find_tables()` works, 0 images.
- Devanagari is **legacy Preeti-encoded** and extracts garbled (`k'?if`=पुरुष,
  `dlxnf`=महिला, `hDdf`=जम्मा, `;+:Yftut`=संस्थागत, `AolQmut`=व्यक्तिगत), but
  **numerals are clean ASCII** and **country names are Latin** → deterministic
  decode, **no OCR** (unlike the scanned `#018`/`#026`).
- Sample: `Monthly report_2067 Magha (Final Approval)` (8pp, country-wise final
  approvals) and `FY_Wise_Monthly_Data_2065_2069` (4pp, BS 2065–2068 month
  totals).

**Source inventory** (`output/migration/archive_org.json`): 9,156 URLs / 757 PDF
captures for `dofe.gov.np`; ~53 candidate report docs by filename:

| Family | Coverage | Notes |
|--------|----------|-------|
| Monthly country-wise | BS 2067–2069 (~19 reports) | each printed in `Sastha & Ujuri` / `Sushasan` / `Purba` variants |
| FY-wise monthly totals | `FY_Wise_Monthly_Data_2065_2069` (BS 2065–2068) | month × M/F/T time series |
| Quarterly | 2070/71 (1st + 2nd), 2071/72 (2nd) | cumulative |
| Yearly | `yearly_progress_report_2072-2073` | annual |
| Progress | 2073/74, 2074/75 | annual / cumulative |
| Pre-approval | `F.A. 067-68 PRE report`, `kartik-purba` | pre-approval counts |

The `feo.gov.np` archive is a near-bust (mostly `302/404`; the one prize,
`Report_FinalApproval_CountryWise2_23`, is only a redirect → not captured).
Un-downloaded `opendatanepal` datasets (`country-wise ... 2050/51–2072/73`,
`issuance of labour permits 2009/10–2023/24`, district-wise legalization,
households-receiving-remittance) are small summary CSVs → **cross-check only**.

**Scope-check (5 Wayback docs pulled and inspected, read-only):**

| Sample | Era | pp | images | `find_tables` (cols) | Layout |
|--------|-----|----|--------|----------------------|--------|
| `monthly_2069_shrawan` | BS 2069 | 17 | 0 | 25 tables, 11–12 col | country × repeated M/F/T blocks |
| `monthly_2069_kartik` | BS 2069 | 19 | 0 | 27 tables, 11–12 col | same family |
| `longrun_2050_2068` | 2050/51–2067/68 | 2 | 0 | 3 tables, 16–20 col | **transposed** year × country matrix |
| `quarter_2070_71_2nd` | 2070/71 | 25 | 1 | 15 tables but mostly prose | narrative + scattered tables |
| `yearly_2072_2073` | 2072/73 | **235** | 8 | **2 tables in first 10pp** | huge narrative; `find_tables` fails |

All five are native vector PDFs, Devanagari **Preeti-encoded** (`k'?if`=पुरुष,
`hDdf`=जम्मा), numerals clean ASCII → the decoder is the shared prerequisite.

**Two legacy encodings per document.** The PDFs embed *both* a `Preeti` font and
a `PCSNEPALI` font (plus Times/Helvetica for numerals). Table labels (gender,
`hDdf`, channel) are `Preeti`; some title/caption runs are `PCSNEPALI`, whose
codes differ (e.g. कात्तिक is `sflts` in PCSNEPALI vs `sflt{s` in Preeti). Decode
therefore **must be font-scoped per span** (`page.get_text("dict")`), not applied
to the flattened string: ASCII digit runs in Latin fonts must be left untouched.
`migration_parser/preeti.py` implements the Preeti map (font-scoped caller);
PCSNEPALI is a **documented TODO** (titles/captions only so far — the numeric
data tables and gender labels are Preeti).

**Conclusion (corrects an earlier assumption):** "mirror `annex.py`" is **too
optimistic**. The archive is **at least three layout families** — (a) monthly
country × period-scope M/F/T matrices, (b) a transposed long-run year × country
table, (c) large narrative quarterly/annual progress reports where
`find_tables()` returns ~0 (the 235-pp yearly doc detects almost nothing). (c)
needs a flow/text parser, not the wide-table machinery. Budget the backfill as a
*family of extractors* sharing one Preeti decoder, not a single reuse.

**Decisions**

- Scope: **monthly + quarterly + yearly + pre-approval**.
- Storage: recovered rows go **into `panel.csv` via a new `source_kind` column**
  (`live` default / `archive_org`); pre-approval → `agencies.csv`; FY-month
  totals → `series.csv`.
- **Genre triage required**: filenames mix Final Approval, Purba Swikriti
  (pre-approval), Sastha Darta & Ujuri (registration/complaints) and Sushasan
  (governance) — only approval / pre-approval tables feed the panel.
- Older templates differ from the live ones (period-scope columns ×
  institutional/individual/total × M/F/T) **and from each other** (see the
   scope-check above), so dedicated per-family extractors are needed, not
   `parser.py` and not a single `annex.py` clone. Confirmed on the full 52-doc
   archive set: three distinct vintages (2067–68 / 2069–70 / 2073+), only the
   middle one matching family (a).

**Plan** (phased; each shippable)

1. ~~`migration_parser/preeti.py`: Preeti→Unicode map + `decode`; unit tests on
   known tokens~~ **done** (canonical Shuvayatra table, font-scoped). PCSNEPALI
   map still TODO (titles/captions only).
2. **family (a)** monthly country × period-scope M/F/T — **extractor done**
   (`migration_parser/historical.py` + `cli backfill --extract <pdf|dir>`).
   The target is the **12-col labour-approval table** ("कामदार गएको मुलुक", col 2
   = श्रम स्वीकृतिको किसिम → संस्थागत/व्यक्तिगत, three period-scope M/F/T blocks at
   col 3/6/9). The sibling 11-col table at col 2 ("पूर्व स्वीकृति लिएको मुलुक") is
   the **pre-approval** product and is deliberately *not* this family. Each
   country prints institutional + individual rows plus a जम्मा subtotal (the
   subtotal is skipped; `M+F` is authoritative since the printed Total cell is
   unreliable in later vintages). Grand-total rows omit the type cell (blocks
   shift to col 2), located by the first numeric cell; a grand total is optional
   and, when absent, validation falls back to `M+F=T` + `previous+month=cumulative`
   + `Σ detail = printed total`. Header decode is Preeti-scoped; numerals are
   ASCII/PCSNEPALI and country names Latin, so they are **not** decoded.
   `resolve`/`fetch` wired (`cli backfill --list|--resolve|--fetch`): 52 monthly
   candidates resolved from the Wayback inventory into the tracked
   `bill-tracker/migration_archive_manifest.json` (deduped by `(year, month)`,
   `final`/`monthly`/`report` preferred) and all 52 downloaded to
   `output/migration/archive_pdfs/` with `source_pdf_sha256`/`source_pdf_bytes`.
   **Extraction yield across the full set** (`--extract`): **25 docs fully
   verified** (BS 2067–2073); the rest are unverified — duplicated/misaligned
   captures (e.g. a spurious "Republic of Korea from EPS" row) or a printed total
   that does not reconcile. In-window captures (BS 2075, 2080/81, 2081/82) still
   yield 0 rows — a **newer template** the family-(a) extractor does not parse.
3. **Separate archive panel** (`migration/panel_archive.csv.gz` +
   `panel_archive_build.json`) built by `cli archivepanel` from the verified
   backfill docs — kept out of `panel.csv` because the three period-scopes
   (`previous_cumulative`/`month`/`cumulative`) don't map onto the live monthly
   schema. Ships BS 2067–2073 (25 docs, 54,360 rows), `source_kind=archive_org`,
   all `verified=True`. Columns beyond the live panel:
   - `approval_type` — `institutional` / `individual`, the printed श्रम स्वीकृतिको
     किसिम axis. This is **not** the modern delivery-channel axis; the
     correspondence is an open domain item documented as `channel_map: null/TBD`
     in `channels.json`. **Do not join to `panel_canonical.channel_canonical`.**
   - `scope` (`previous_cumulative`/`month`/`cumulative`) plus `scope_class`
     (`prior_ytd`/`window`/`ytd`) and `granularity` (`month`). Join to the live
     panel on `period_bs` (+ `granularity`), not on scope.
   - `name_canonical` + `iso3` (from `countries.json`, same resolver as the main
     panel), `entity_resolved`, and `analysis_safe`
     (= `verified AND entity_resolved`), the same safe-default discipline as the
     main panel. `name_canonical` is kept — not just the boolean — so a
     `groupby(name_canonical)` on resolved rows can't split alias variants
     (`UAE` vs `United Arab Emirates`) into separate buckets. 40,977 of 54,360
     rows are `analysis_safe=true`; the rest carry unresolved printed names
     (misspellings, clipped labels, ambiguous groupings, the spurious "Republic
     of Korea from EPS" row) kept verbatim, `name_canonical` falling back to the
     raw name.
   Supersedes the earlier pre-approval-table panel (that read the wrong sibling
   table). Note the main panel's `individual` channel is the *aggregate* "Individual
   (all modes)"; the archive's `individual` is a raw approval type — the string
   match is a trap.
4. **family (b)** transposed long-run year × country extractor; **family (c)**
   narrative/quarterly series extractor (flow/text, not `find_tables`).
5. Pre-approval family; docs: update the coverage table above + `DATA_AVAILABILITY.md`.

**Risks**: ~half the candidate filenames are `404/302` (uncaptured) → uneven
month coverage; per-vintage layout drift will surface families beyond the three
sampled (the 235-pp yearly doc is the known outlier); the Preeti map may be
incomplete (fall back to manifest metadata).

**Validation & delivery**
- ~~**Cross-check** against `opendatanepal` CSVs (**cross-check only** — never
  fill gaps from them; it muddies provenance)~~ **done** (see *Cross-check
  against opendatanepal*).
- ~~Final packaging: tidy CSV(s) + codebook~~ **done** — `panel_canonical.csv.gz`
  (primary), `panel.csv`, `agencies.csv`, `series.csv`; machine-readable
  `codebook.json`; build manifest `build.json`; and `DATA_AVAILABILITY.md`.
  Parquet/wide convenience view deferred (would need `pyarrow`).

**Closed**
- 2 **scanned** docs marked `skipped` in the manifest: #026 (printed-English
  RA-wise agency list, 2079/80 — OCR too lossy) and #018 (handwritten, rotated
  annual progress report — OCR infeasible). Recoverable only by manual
  transcription if ever needed.


