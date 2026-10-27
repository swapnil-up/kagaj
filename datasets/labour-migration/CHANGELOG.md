# Changelog

Dated notes for deliberate changes to the shipped datasets, codebook and docs.
Kept so that corrections are visible as corrections rather than quiet rewrites
(e.g. if a reader remembers an earlier README claim about the Qatar 2022 window).

## 2026-10-27

### Fixed — clipped country labels in doc 332

- `PyMuPDF.get_texttrace()` exposes the full strings hidden behind content 332's
  ~22 pt country column. Added document+serial overrides in
  `normalize.CLIPPED_COUNTRY_OVERRIDES`: S.N. 9 Korea, 14 Bulgaria, 30 North
  Macedonia, 76 Republic of the Congo, 55 a second Seychelles row.
- SN 55 is summed with SN 34 under the documented intra-document merge rule, so
  doc 332 Seychelles totals 64. The safe panel gains 3,042 resolved approvals
  and drops from 327 to 252 unresolved detail rows.

### Changed — archive unresolved rows quarantined

- `panel_archive.csv.gz` now ships only resolved rows (75,261; all
  `analysis_safe=True`). The 19,509 unresolved rows moved to
  `panel_archive_unresolved.csv.gz` with the same schema and
  `entity_resolved=False`.
- `panel_archive_build.json` records `n_rows_all`, `n_rows`, `n_unresolved`, and
  both output paths.

### Fixed — archive panel reproduces from the cached PDFs

- `historical.py` and `historical_new.py` now repair country names whose spaces
  were dropped by `find_tables()` (e.g. `BruneiDarussalam`, `SaudiArabia`) using
  the country/alias vocabulary, with a camel-case fallback for unmatched labels.
- `normalize.canonical_country()` accepts punctuation/space-stripped names via a
  collision-safe compact index, so `Hongkong`, `Macedonia` spacing variants and
  `Replic of congo` resolve without inventing new aliases.
- `historical._table_layout()` keeps a structural fallback when a scanned scope
  header no longer decodes; this restores BS 2071 Jestha (2,403 rows) instead of
  silently dropping it.
- `historical_new._word_rows()` recovers the final 1–3 country rows on a
  table-less continuation page (restores BS 2074 Shrawan and 2075 Shrawan).
- `archivepanel` keeps one row-set per printed month and drops ambiguous
  captures only when no capture agrees with its catalog month. It also strips
  `Total` contamination from newer-template country cells.
- Net effect: **75,261 resolved rows** and **19,509 quarantined rows** from the
  same 61 docs and 94,770 total rows. The 675 newly resolved rows are spacing /
  punctuation variants of names that were already in `countries.json`.

### Added — denominator and gap-fill reporting

- Pattern book now reports an explicit FY2075/76 gap-fill from
  `report2020_annex_X` (508,824 total; 490,117 deployment), with its two known
  Qatar ±1 errors flagged. It is never pooled with verified years.
- Documented the legacy-channel policy: old-template `new_entry` stays in
  deployment totals but is never allocated to a modern channel; `legalization`
  remains a separate policy series.

## 2026-10-26

### Added — newer-stage archive extractor (`historical_new.py`)

- Parses the BS 2073–2075 monthly stage template: `pre_permission` /
  `final_approved` scopes and `re_entry` / `new` / `legalization` entry types,
  including 5-, 6-, 8-, and 14-column country tables.
- `backfill --extract` sniffs the template from the first pages so the newer
  reports no longer go through the family-(a) extractor first.
- `fetch` now re-downloads missing cache files on a fresh clone, saves the
  manifest incrementally, retries with backoff, and uses HTTP/2 (Wayback rejects
  HTTP/1.1 with 429).

### Changed — archive panel rebuilt

- Rebuilt from 61 verified docs: **94,770 rows, 74,586 `analysis_safe`**, covering
  **BS 2067–2075** (was 25 docs / 54,360 / 40,977, BS 2067–2073).
- Added `entry_type` to the archive panel schema (`historical.py` `HistRow`,
  `paths.ARCHIVE_PANEL_COLUMNS`, `archivepanel`).
- The BS 2075 in-window monthly reports are now extracted; the 2080/81 and
  2081/82 captures remain progress reports, not monthly country tables.

## 2026-10-17

### Corrected — archive-backfill event-study claim (`README.md`, `DATA_AVAILABILITY.md`)

The earlier README implied the archive.org backfill would unlock the headline
natural experiments (Qatar 2022 World Cup, Malaysia 2018–20, Israel quotas) at
monthly frequency. An initial rewrite over-corrected it. Verified against
`output/migration/archive_org.json`:

- the Wayback Machine **does hold monthly country-capture reports inside the
  event window** — BS 2075 (`2075Baishakh`/`2075Jestha`/`2075Shrawan`/
  `2075bhadra`/`Ashad2075`/`Ashoj2075`, all HTTP 200) plus BS 2080/81 (Jestha)
  and BS 2081/82 (Asar) progress reports and a half-yearly Shrawan–Poush 080-81;
- **but those in-window captures are a newer DoFE template that the family-(a)
  extractor reads as 0 rows** (the same limitation already noted for BS 2080/81);
- the only *named* in-window filenames (`progressreport20732074.pdf`,
  `progressreport20742075.pdf`) are HTTP 404 (never archived);
- the archive panel that *does* rebuild covers **BS 2067–2073 (2010/11–2016/17)**;
- additionally, the filename-based `resolve` heuristic (`cmd_backfill`)
  under-counted the pre-2074 archive: it requires a year token *and* a report
  keyword, so it missed family-(a) reports named by bare month
  (`ashoj.pdf`/`baisakh.pdf`/… — these are **BS 2071/72** and extract fine).

So the event window is an **extractor gap, not a source hole**: closing it needs
a newer-template extractor (or a different source — DoFE directly, MoLESS
reports), not more filename-resolving. Annual data (through FY2081/82) is the
best currently available input for those questions.

### Changed — archive panel schema (`panel_archive.csv.gz`)

- Renamed `channel` → **`approval_type`** (`institutional` / `individual`, the
  printed श्रम स्वीकृतिको किसिम). This is **not** the modern delivery-channel axis;
  `channels.json` now carries an explicit `channel_map: null/TBD` block, and the
  docs warn against joining the two panels on channel string equality.
- Added `scope_class` (`prior_ytd` / `window` / `ytd`), `granularity` (`month`),
  `name_canonical`, `iso3`, `entity_resolved`, and
  `analysis_safe = verified AND entity_resolved`.
- Rebuilt: 25 docs, 54,360 rows, 40,977 `analysis_safe`.

### Changed — main-panel safe default (`panel_canonical.csv.gz`)

- `analysis_safe` is now `entity_resolved AND verified AND channel_reviewed`
  (drops the unreviewed `legalization` / old-template `new_entry` rows).
- Added `analysis_safe_permissive = entity_resolved AND verified` for deliberate
  legalization-specific specifications.

### Added — archive drift-check coverage

- `migration_parser driftcheck [--recheck]` now validates the archive manifest
  (`source_pdf_sha256`) as well as the live manifest, so the archive PDFs are not
  the one untracked set.
