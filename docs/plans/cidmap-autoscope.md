# CIDMap autoscope — reference-outline bootstrap

Status: complete

## Goal

Increase usable font-scoped coverage before deciding whether to promote or
repair. The embedded subsets carry unusable cmaps, but their glyph outlines can
still be compared with the original reference font. An exact, unambiguous
outline match is strong enough to seed a font-scoped store mapping.

This is a conservative bootstrap, not a replacement for review.

## Decisions

- Walk the unknown CIDs reported by `probe --reference-font`.
- Group candidates by decoded value and keep the best score per value.
- Skip `.notdef` and other private glyph names.
- Accept only a top score `<= 0.75` with at least a `1.0` gap to the next
  distinct value. Ambiguous candidates stay rejected.
- Never overwrite a differing fallback. If a fallback already agrees, still add
  the font-scoped value so repair can use it.
- Never overwrite an existing font-scoped value.
- Record `source=reference`, the reference glyph name, score, and first page in
  the CID metadata.
- Dry-run by default. `--apply` writes through the normal store save path.
- Do not run inference inside this command; inference is slower and is a
  separate evidence path.

## Deliverables

- `cidmap/autoscope.py`: candidate filtering, scope plan, apply, formatter.
- `cidmap/cli.py`: `cidmap autoscope <pdf> --reference-font ...`.
- `tests/test_cidmap_autoscope.py`.
- Update `AGENTS.md` and `docs/review-harness.md`.

## Verification

- `cidmap autoscope ... --max-pages 20` selected 40 mappings across 9 fonts.
- Full PDF selected 150 mappings across 21 fonts; 145 were new CMap additions
  after five already-known CID 1 values were deduplicated.
- Applying the plan raised the store from 6 to 197 font-scoped values.
- `cidmap registry ingest` added 150 observations; the registry now has 156
  observations across 35 glyphs from one document.
- The repaired copy changed extraction on 542 of 556 pages.
- Targeted cidmap/core suite: 160 passed. Full suite: 1203 passed, 7
  skipped, 3 failed, 8 errors; all are the known missing pandas, redbook
  fixtures, and migration drift baseline.

## Limits

- One document still yields only provisional registry support; promotion needs
  a second independent document or reviewer confirmation.
- High-distance and ambiguous outline matches remain for manual review.
- A correct reference outline proves glyph identity, not the surrounding word.
  Normal Nepali spelling review is still required.
