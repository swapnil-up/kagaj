# CIDMap Phase 3 — Cross-document consensus and promotion

Status: complete
Scope owner: cidmap

## Goal

Turn reviewed glyph mappings into reusable evidence across documents, then
promote only well-supported values into the canonical store.

```text
review / infer / quorum
        |
        v
glyph registry (evidence)
        |
        v
cidmap promote --apply
        |
        v
canonical cid_mappings.json
        |
        v
decoder
```

The registry is evidence, not a decoder dependency. `cid_mappings.json` remains
the canonical source used by `decode` and `decoder`.

## Decisions

- Registry lives in committed JSON at `cidmap/data/glyph_registry.json`.
- Registry identity is `(family_hash, outline_hash)`, not `(font_id, cid)`;
  embedded subsets renumber glyphs.
- One document contributes one vote per glyph.
- Re-ingesting the same PDF is idempotent.
- Different values for the same glyph are a conflict and are never promoted.
- Promotion is dry-run by default; `--apply` is required to write.
- Promotion only fills missing values and never overwrites.
- Promotion uses the same validation path as `cidmap commit`.
- PDF `/ToUnicode` or `/ActualText` repair is deferred to Phase 4.

## Non-goals

- Automatic promotion without `--apply`.
- Changing decoder behavior or the store schema.
- OCR in the promotion path.
- PDF repair or rewritten source documents.
- Merging different font families by name alone.

## Deliverables

### 1. `cidmap/registry.py`

```python
RegistryObservation(
    family_hash, outline_hash, value, font_id, cid,
    doc_sha256, base_font, source, evidence, observed_at,
)

load(path=None) -> dict
save(registry, path) -> None
observe(registry, observation) -> None
ingest_document(doc, store, *, registry=None, max_pages=None) -> int
lookup(registry, family_hash, outline_hash) -> dict | None
resolve_glyph(registry, embedded, xref, cid, base_font="") -> tuple | None
```

Registry schema:

```json
{
  "schema_version": 1,
  "glyphs": {
    "<family_hash>:<outline_hash>": {
      "family_hash": "...",
      "outline_hash": "...",
      "base_font": "Kalimati",
      "value": "ि",
      "values": ["ि"],
      "status": "provisional",
      "support": 1,
      "documents": ["<pdf sha256>"],
      "observations": [],
      "conflicts": []
    }
  },
  "meta": {"updated": "..."}
}
```

Status rules:

- `conflict`: more than one distinct value for one glyph.
- `confirmed`: at least two independent documents, or a `review` observation.
- `provisional`: one document, no reviewer evidence.

### 2. CLI

```bash
python -m cidmap.cli registry ingest <pdf> \
  --store cidmap/data/cid_mappings.json \
  --registry cidmap/data/glyph_registry.json

python -m cidmap.cli registry query <pdf> --cid 1
python -m cidmap.cli registry query <pdf> --cid 1 --json
```

`ingest` records observations for store values that can be resolved to a font
subset and glyph outline. `query` resolves a CID through the PDF and prints the
registry entry and support.

### 3. `cidmap/decisions.py`

Extract the neutral-decision validation and application currently embedded in
`cidmap/cli.py`:

```python
apply_decisions(store, decisions) -> DecisionResult
```

Both `cidmap commit` and `cidmap promote --apply` call it so validation cannot
diverge.

### 4. `cidmap/confidence.py` and `cidmap promote`

```bash
python -m cidmap.cli promote <pdf> \
  --reference-font Kalimati.ttf \
  --store cidmap/data/cid_mappings.json \
  --registry cidmap/data/glyph_registry.json \
  --dry-run

python -m cidmap.cli promote <pdf> ... --apply
```

Candidate evidence:

- registry value, status, and independent-document support
- shape-run top value and agreement or disagreement
- lexicon/validation through the existing inference path
- existing store value and `undecodable` state

Promotion rules:

- conflict, missing evidence, invalid value, or existing mapping blocks promotion
- provisional one-document entries are blocked unless source is `review`
- shape-run disagreement blocks promotion
- `--json` writes the full candidate report
- dry-run never writes; `--apply` uses `apply_decisions`

### 5. Review and probe integration

Add optional `--registry` to `cidmap review` and `cidmap probe` to show registry
candidates. These commands remain read-only.

### 6. Tests

- `tests/test_cidmap_registry.py`
  - same glyph across documents increments support
  - same document is idempotent
  - value conflict is frozen
  - font families do not merge
  - deterministic load/save
- `tests/test_cidmap_confidence.py`
  - confirmed registry promotes
  - one-document provisional is blocked
  - review-sourced provisional is allowed
  - conflict, invalid value, and shape-run disagreement block
  - existing values are never overwritten
- `tests/test_cidmap_decisions.py`
  - shared commit validation behavior
- `tests/test_cidmap_promote.py`
  - dry-run and `--apply`
  - candidate JSON shape
- update CLI tests and review/probe tests as needed

### 7. Documentation

- Update `AGENTS.md` with `registry` and `promote`.
- Update `docs/review-harness.md`.
- Keep this plan's progress log current.

## Acceptance criteria

- Seeding from `redbook8283.pdf` records observations for the mapped CIDs.
- `registry query` resolves CID 1/11/70 to their stored values.
- Re-running ingest does not duplicate observations.
- `promote --dry-run` changes nothing; `--apply` only adds validated values.
- Existing `scan`, `review`, `commit`, `probe`, `infer`, and decoder behavior
  is unchanged.
- Targeted tests pass; full-suite failures remain the known missing-fixture
  baseline.

## Implementation order

1. Registry module and tests.
2. Seed registry from the current store and redbook.
3. Shared decisions helper.
4. Confidence policy and `promote`.
5. Review/probe registry evidence.
6. Docs, targeted tests, full suite.

## Verification

- `cidmap registry ingest /home/swap/Downloads/redbook8283.pdf` recorded six
  observations across three glyph entries from the current store. Re-running it
  added zero observations.
- `cidmap registry query ... --cid 1` resolved both `ि` and `व्` variants.
- `cidmap promote ... --dry-run` reported candidates and wrote nothing.
- Targeted cidmap/core suite: 151 passed.
- Full suite: 1193 passed, 7 skipped, 4 failed, 8 errors. The failures/errors
  are the known missing redbook fixture, missing pandas, migration drift, and a
  stale corpus source line; none are caused by Phase 3.

## Progress log

- [x] Plan written
- [x] Registry module
- [x] Registry CLI and seed
- [x] Shared decisions helper
- [x] Confidence and promotion
- [x] Review/probe integration
- [x] Docs and verification
