"""Machine-readable data dictionary for the shipped migration datasets.

The descriptions here are the single source of truth for
``datasets/labour-migration/codebook.json`` (emitted by ``python -m migration_parser build``).
Human-readable prose lives in ``datasets/labour-migration/README.md``.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"

# Column descriptions per dataset. Keys must match the actual header rows; the
# build verifies this and fails loudly on drift.
COLUMNS: dict[str, dict[str, str]] = {
    "panel.csv": {
        "doc_id": "Source document id (DoFE content id, or report2020_annex_*, preapproval_0NN).",
        "period_bs": "Printed BS period as printed (year, or 'year month' for monthly reports).",
        "period_ad_start": "AD start date of the reporting window (ISO), when printed.",
        "period_ad_end": "AD end date of the reporting window (ISO), when printed.",
        "doc_type": "Classified document type as emitted (annual | single_month | cumulative).",
        "section": "Table section: country | district.",
        "row_type": "detail (an entity) | total (printed Total row) | grand_total.",
        "name": "Entity name exactly as printed (raw, unresolved).",
        "sn": "Source serial number / row order within the document.",
        "channel": "Raw channel label as printed (template-specific).",
        "gender": "male | female | total.",
        "count": "Approved labour permits in this cell.",
        "source_page": "Page of the source PDF the row came from.",
        "verified": "True when the source document's extraction passed its math audit.",
        "source_url": "URL of the source PDF.",
    },
    "panel_canonical.csv.gz": {
        "doc_id": "Source document id.",
        "period_bs": "Printed BS period (raw).",
        "period_ad_start": "AD start date of the reporting window (ISO).",
        "period_ad_end": "AD end date of the reporting window (ISO).",
        "doc_type": "Classified document type.",
        "section": "Table section: country | district.",
        "row_type": "detail | total | grand_total.",
        "name": "Entity name exactly as printed (raw).",
        "sn": "Source serial number / row order.",
        "channel": "Raw channel label as printed.",
        "gender": "male | female | total.",
        "count": "Approved labour permits (summed across merged typo-rows).",
        "source_page": "Source PDF page.",
        "verified": "Source document passed its extraction math audit.",
        "source_url": "URL of the source PDF (first contributing document).",
        "entity_type": "country | district (empty on printed total rows).",
        "name_canonical": "Canonical entity name (countries.json / districts.json).",
        "iso3": "ISO-3166 alpha-3 country code (empty for districts/totals).",
        "province": "Nepali province name (districts only).",
        "entity_note": "Provenance note for the canonical entity (e.g. a pre-2018 unified district assigned to its HQ province); empty when none.",
        "entity_resolved": "true when the raw name matched a canonical entity.",
        "fiscal_year": "Canonical BS fiscal year label, e.g. '2079/80'.",
        "channel_canonical": "Canonical channel (channels.json).",
        "channel_class": "component | aggregate | measure | unknown.",
        "granularity": "month | year | measure (aggregation level of the document).",
        "reconciled_fiscal_year": "Fiscal year after documented period overrides.",
        "period_override": "true when reconciled_fiscal_year differs from fiscal_year.",
        "merged_rows": "Number of raw rows collapsed into this canonical key.",
        "raw_names": "Semicolon-joined distinct printed names merged into this row.",
        "analysis_safe": "true when entity_resolved AND the source doc passed its math audit "
                          "AND channel_reviewed; the safe default filter before aggregating. "
                          "Excludes the unreviewed legalization / old-template new_entry rows.",
        "analysis_safe_permissive": "true when entity_resolved AND the source doc passed its "
                                    "math audit, ignoring channel_reviewed. Use only for "
                                    "deliberate legalization-specific specifications.",
        "channel_reviewed": "true when the channel's cross-template equivalence is independently "
                            "reviewed; false flags a single-analyst judgment call (currently "
                            "legalization, new_entry) — treat those channels with caution.",
    },
    "panel_rollup.csv.gz": {
        "doc_id": "Source document id.",
        "period_bs": "Printed BS period (raw).",
        "period_ad_start": "AD start date of the reporting window (ISO).",
        "period_ad_end": "AD end date of the reporting window (ISO).",
        "doc_type": "Classified document type.",
        "section": "Table section: country | district.",
        "row_type": "detail | total | grand_total.",
        "name": "Entity name exactly as printed (raw).",
        "sn": "Source serial number / row order.",
        "channel": "Raw channel label as printed.",
        "gender": "male | female | total.",
        "count": "Approvals in this cell.",
        "source_page": "Source PDF page.",
        "verified": "Source document passed its extraction math audit.",
        "source_url": "URL of the source PDF.",
        "entity_type": "country | district (empty on printed total rows).",
        "name_canonical": "Canonical entity name.",
        "iso3": "ISO-3166 alpha-3 country code (empty for districts/totals).",
        "province": "Nepali province name (districts only).",
        "entity_note": "Provenance note for the canonical entity.",
        "entity_resolved": "true when the raw name matched a canonical entity.",
        "fiscal_year": "Canonical BS fiscal year label.",
        "channel_canonical": "Canonical channel (channels.json).",
        "channel_class": "component | aggregate | measure | unknown (all non-component here).",
        "channel_reviewed": "true when the channel's cross-template equivalence is independently reviewed.",
        "granularity": "month | year | measure.",
        "reconciled_fiscal_year": "Fiscal year after documented period overrides.",
        "period_override": "true when reconciled_fiscal_year differs from fiscal_year.",
        "merged_rows": "Number of raw rows collapsed into this canonical key.",
        "raw_names": "Semicolon-joined distinct printed names merged into this row.",
        "analysis_safe": "true when entity_resolved AND the source doc passed its math audit "
                         "AND channel_reviewed.",
        "analysis_safe_permissive": "true when entity_resolved AND the source doc passed its "
                                    "math audit (ignores channel_reviewed).",
    },
    "period_windows.csv": {
        "period_bs": "Printed BS period label for the reporting window.",
        "fiscal_year": "Canonical BS fiscal year the window falls in.",
        "period_ad_start": "AD start date of the ~4-week reporting window (ISO).",
        "period_ad_end": "AD end date of the reporting window (ISO).",
        "doc_id": "Source document id(s) that report this window.",
        "granularity": "month | year (the aggregation level of the window).",
    },
    "agencies.csv": {
        "measure": "Measure kind (preapproval | institutional).",
        "doc_id": "Source document id.",
        "period_bs": "Printed BS period (raw).",
        "period_ad_start": "AD start date of the reporting window (ISO).",
        "period_ad_end": "AD end date of the reporting window (ISO).",
        "doc_type": "Classified document type.",
        "sn": "Source serial number / row order.",
        "lot_no": "Recruiting-agency licence / lot number, when printed.",
        "country": "Destination country as printed (raw).",
        "agency": "Recruiting agency name as printed (raw).",
        "male": "Male permits.",
        "female": "Female permits.",
        "total": "Total permits (male + female).",
        "source_page": "Source PDF page.",
        "verified": "Source document passed its extraction math audit.",
        "source_url": "URL of the source PDF.",
    },
    "series.csv": {
        "series_key": "Summation-safe block key = report|source_page|caption|metric|"
                      "dimension|unit|year_basis|gender|note. Sum `count` only within a "
                      "key; never across keys (mixes units / bases / genders). `note` is "
                      "keyed because it carries the sub-measure (e.g. the cause of a "
                      "cause-of-death table) that can otherwise collide across sibling "
                      "tables sharing one caption.",
        "report": "Source report key (status_2013_14, migration_2020, ...).",
        "source_page": "Page of the source PDF.",
        "caption": "Table caption as printed.",
        "metric": "Metric name (labour_approvals, deaths, complaints, ...).",
        "dimension": "Dimension the series is broken down by (country, cause, ...).",
        "unit": "Unit of measure.",
        "name": "Entity / category name (raw).",
        "fiscal_year": "Fiscal-year label (raw, as printed).",
        "year_basis": "fiscal | calendar | snapshot (never sum across bases).",
        "gender": "male | female | total | (blank for matrix rows).",
        "count": "Value for this cell.",
        "note": "Extraction note, when any.",
    },
}

# Dataset -> shipped filename, primary flag, description.
DATASETS = {
    "panel.csv": {"primary": False, "role": "raw", "description":
        "Raw tidy-long panel exactly as extracted from the live DoFE wide tables and report annex tables."},
    "panel_canonical.csv.gz": {"primary": True, "role": "canonical", "description":
        "Primary analysis dataset. Additive-only: component detail rows with canonical "
        "entities/channels/fiscal years and within-document typo-row merges applied. "
        "Aggregate rows, printed totals and distinct measures are NOT here — they live in "
        "panel_rollup.csv.gz, so summing this file can never double-count an aggregate "
        "against its components. Gzipped CSV."},
    "panel_rollup.csv.gz": {"primary": False, "role": "rollup", "description":
        "Non-additive companion to panel_canonical.csv.gz: channel_class=aggregate rows, "
        "printed total/grand_total rows and separate measures (pre-approval). Compare against, "
        "never sum with, the primary file."},
    "agencies.csv": {"primary": False, "role": "detail", "description":
        "Recruiting-agency-level pre-approval and institutional permit detail."},
    "series.csv": {"primary": False, "role": "series", "description":
        "Historical known-series matrices (approvals, deaths, complaints, ...) from narrative reports."},
    "period_windows.csv": {"primary": False, "role": "lookup", "description":
        "Lookup of DoFE reporting windows (period_bs -> AD start/end) for date-based merges."},
}

# Documented controlled vocabularies (supersets). The build fails if the shipped
# data contains a value NOT listed here, so a new category can never appear
# silently (this is what let `year_basis=snapshot` drift past the docs).
EXPECTED_VOCAB: dict[str, dict[str, set[str]]] = {
    "panel_canonical.csv.gz": {
        "section": {"country", "district"},
        "gender": {"male", "female", "total"},
        "row_type": {"detail", "total", "grand_total"},
        "granularity": {"month", "year", "measure", ""},
        "channel_class": {"component", "aggregate", "measure", "unknown"},
        "channel_reviewed": {"true", "false", ""},
        "analysis_safe": {"true", "false", ""},
        "analysis_safe_permissive": {"true", "false", ""},
        "doc_type": {"annual", "single_month", "cumulative", ""},
        "entity_type": {"country", "district", ""},
    },
    "series.csv": {
        "unit": {"count", "percent", "npr", "usd"},
        "year_basis": {"fiscal", "calendar", "snapshot"},
        "gender": {"male", "female", "total", ""},
    },
    "agencies.csv": {
        "measure": {"preapproval", "institutional"},
    },
}
