# Changelog

Dated notes for deliberate changes to the shipped datasets, codebook and docs.
Kept so that corrections are visible as corrections rather than quiet rewrites
(e.g. if a reader remembers an earlier README claim about the Qatar 2022 window).

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
