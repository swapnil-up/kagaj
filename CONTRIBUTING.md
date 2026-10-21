# Contributing

Thanks for helping turn Nepali government paper into open data.

## Setup

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
```

`.[dev]` installs the redbook, billtracker, water, OCR, and test extras.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Some tests need the source PDFs (for example the redbook and gold-page tests).
They are skipped or fail loudly when the PDFs are absent; see the fixture paths
in `tests/conftest.py` and `tests/gold/README.md`.

## What to work on

- **New document sources.** Add a scraper plus an extractor. Keep the source
  URL on every emitted row.
- **OCR/extraction fixes.** Legacy Preeti/Kantipur glyphs and truncated table
  cells are the biggest sources of error.
- **Remaining verbatim failures.** 34 of 70 tracked verbatims are still failed;
  re-running `parliament/scripts/process_verbatim.py` picks up where it stopped.
- **DDA drug prices.** The `drug_prices/` pipeline is experimental; see
  `docs/plans/dda-drug-prices.md`.
- **Docs and dataset health.** Keep counts and paths accurate.

## Rules for data changes

1. **Provenance.** Every new row needs a `source_url` (and a hash when the
   source can change in place).
2. **Verify, don't smooth.** Reconcile against printed totals. If a source has a
   typo, record it rather than editing the number.
3. **Additive only.** For the migration panel, new rows go in the canonical
   detail table only if they cannot double-count an existing aggregate.
4. **Rebuild the fingerprint.** Run `python -m migration_parser.cli build` after
   changing the panel, and commit `build.json` with the data.
5. **No secrets.** `.env` is gitignored. Never commit API keys.

## Pull requests

- Keep changes focused; separate pure moves from content edits.
- Run the test suite.
- Update the affected README or `docs/` page when paths or behavior change.
- Describe the source and the verification you did for new data.
