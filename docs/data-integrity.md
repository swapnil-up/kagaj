# Data integrity

Every pipeline makes claims about numbers. This document describes how those
claims are tested and what the limits are.

## Per-document audits

The labour-migration pipeline (`migration_parser/`) checks, for each source
document:

- male + female = total, per channel;
- components sum to the printed *With* figure;
- *With − re-entry = Without*;
- detail rows sum to the printed total.

A mismatch is recorded in the dataset rather than "fixed" in the source values.
The shipped panel has two known ±1 source typos, preserved deliberately.

The budget pipeline (`redbook_parser/`) runs a similar audit against printed
page and section totals (`redbook_parser/verify.py`).

## Panel-wide audits

`migration_parser/panel_verify.py` re-checks the invariants on the melted panel,
independently of extraction. `python -m migration_parser.cli verify` runs it.

## Provenance

- Every migration panel row carries `source_url`.
- Every series row carries `report`, `source_page`, and `caption`.
- Source PDFs are hashed when fetched (`pdf_sha256` on the live manifest,
  `source_pdf_sha256` on the archive manifest).
- `python -m migration_parser.cli driftcheck` detects a source revised in place.

## Fingerprinted builds

`python -m migration_parser.cli build` writes
`datasets/labour-migration/build.json` with:

- the git revision (and whether the tree was dirty);
- row counts;
- the SHA-256 of every shipped artifact.

The build exits non-zero if an audit fails or if the codebook drifts from the
shipped headers.

## Gold pages

`tests/gold/` contains hand-transcribed pages for the budget parser. Extraction
accuracy is treated as a testable contract, not an eyeball check. See
`tests/gold/README.md`.

## Known gaps

- 34 of 70 tracked National Assembly verbatims are still marked `failed`
  (quota or segmentation limits). Re-running the processor resumes from the
  checkpoint.
- Some source PDFs are absent from a fresh clone (they are downloaded on
  demand), so a few tests are environment-dependent.
- The archived 6th-HoR notices and pre-19th-session verbatims are discoverable
  but not reprocessed.
- Drug-price extraction is experimental and has no shipped dataset yet.
