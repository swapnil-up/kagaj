# Migration panel — current data problems

_Last audited: 2026-10-27. Regenerate with `python -m migration_parser.cli audit`._

The Phase 0 audit reports **0 critical issues** on the safe panel. The remaining
problems are coverage and measurement constraints that must be stated in any
paper or design:

| Problem | Impact | Current treatment |
|---|---|---|
| Safe panel is 50,052 of 70,089 canonical rows (28 documents). | Unreviewed legalization and old-template new-entry rows are excluded. | Use `analysis_safe=true`; report permissive/legalization specifications separately. |
| Reviewed-channel coverage changes across the template break. | `analysis_safe` is not a total-approval series: reviewed share was 88.3% in 2079/80 and 85.6% in 2080/81, but ~100% from 2081/82. Safe-total growth overstates or sign-flips countries with large old-template `new_entry`/`legalization` blocks (e.g. Portugal, South Korea, Japan, Croatia, Malta). | Use `deployment_verified` (total verified minus legalization) for long-run volume, `modern_consistent` for channel comparisons, and label reviewed-channel results explicitly. See the pattern book's denominator sections. |
| BS 2075/76 has country rows but none are safe. | No destination-level country total for that year in the verified main panel. | The only source is `report2020_annex_X`, which is `verified=false` and has two known Qatar ±1 errors. Use the pattern book's flagged gap-fill (508,824 total, 490,117 deployment) only as a sensitivity; never pool it with verified years. |
| Monthly country coverage starts only in BS 2081/82, and 2081/82 has 3 monthly documents. | Annual-vs-monthly comparisons for 2081/82 are not meaningful; high-frequency designs before 2081/82 are unavailable. | Use annual data for long-run analysis; use monthly only for 2082/83 onward. |
| BS 2083/84 is partial (2 monthly documents). | The latest fiscal year is incomplete. | Label as partial; do not compare its level to complete years. |
| Archive panel is separate: BS 2067–2075, monthly, `approval_type` axis. | It cannot be joined to modern `channel_canonical` or treated as the same monthly series. | Join only on period; report archive results separately. 75,261 resolved rows ship in `panel_archive.csv.gz`; 19,509 unresolved rows are quarantined in `panel_archive_unresolved.csv.gz`. |
| Historical `series.csv` overlaps across reports (323 labour-approval entity-years appear in more than one report). | Naive stacking double-counts and can mix units/bases. | Deduplicate on entity-year, prefer the latest report, and sum only within `series_key`. |
| Template changes: old 6-channel, modern 7-channel, newer archive stage template. | Raw channel labels are not comparable across years. | Use canonical channels for the live panel; never join archive `approval_type` to modern channels. |
| District sex columns are reversed in two source tables: BS 2075/76 (annex XIII) and the individual-re-entry group in BS 2078/79. | Raw district female totals are implausible (e.g. 49% in 2078/79 vs 7% nationally). | The research builder swaps male/female for those cells only; after the swap district totals reconcile with country totals (within 1 row). |
| The exploratory HTML report is not a paper. | Narrative values can drift from the data. | It now reads the safe gzip panel; use the Phase 1 pattern book for analysis and verify every number before publication. |

Other known caveats from the dataset documentation remain in force: the two
Qatar ±1 printing errors, 252 unresolved entity names, `preapproval_032`
incompleteness, and the absence of district×destination flows.
