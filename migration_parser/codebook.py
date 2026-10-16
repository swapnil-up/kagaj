"""Machine-readable data dictionary for the shipped migration datasets.

The descriptions here are the single source of truth for
``migration/codebook.json`` (emitted by ``python -m migration_parser build``).
Human-readable prose lives in ``migration/README.md``.
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
        "doc_type": "Classified document type (annual | single_month | progress | annex | ...).",
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
        "report": "Source report key (status_2013_14, migration_2020, ...).",
        "source_page": "Page of the source PDF.",
        "caption": "Table caption as printed.",
        "metric": "Metric name (labour_approvals, deaths, complaints, ...).",
        "dimension": "Dimension the series is broken down by (country, cause, ...).",
        "unit": "Unit of measure.",
        "name": "Entity / category name (raw).",
        "fiscal_year": "Fiscal-year label (raw, as printed).",
        "year_basis": "fiscal | calendar.",
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
        "Primary analysis dataset: panel.csv with canonical entities/channels/fiscal years and "
        "within-document typo-row merges applied. Gzipped CSV."},
    "agencies.csv": {"primary": False, "role": "detail", "description":
        "Recruiting-agency-level pre-approval and institutional permit detail."},
    "series.csv": {"primary": False, "role": "series", "description":
        "Historical known-series matrices (approvals, deaths, complaints, ...) from narrative reports."},
}
