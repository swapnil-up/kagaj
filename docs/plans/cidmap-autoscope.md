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
- Two confidence tiers:
  - **exact**: the outline distance is zero (bbox, advance, contours, and
    bitmap all match). Accept it without the score threshold; reject only if
    another distinct value is also exact and context cannot disambiguate.
  - **near**: no exact match, so fall back to top score `<= 0.75` with at least
    a `1.0` gap to the next distinct value. Ambiguous near matches stay
    rejected.
- With `--reference-fonts`, exactness requires zero distance against every
  available copy; one non-exact copy demotes the value to near.
- With `--lexicon`, shape-run inference supplies context for near-tier matches
  and for ambiguous exact roles. Exact glyphs whose GSUB roles disagree can be
  mapped to the inferred cluster (for example Kalimati `vatu` gives `त्र` from
  `त + र्` components). The lexicon run is restricted to CIDs where it can
  change a decision, so it is opt-in and does not slow the default path.
- Record `match=exact|near` in the mapping metadata and plan JSON.
- An exact match may add a font-scoped override when a CID-wide fallback
  disagrees; the fallback is left unchanged and the override is recorded as
  `fallback_overridden`. Near matches still stop at a differing fallback.
- Log reference provenance (family, style, version, `head.created`, SHA-256,
  plus every copy for `--reference-fonts`) with the plan so a different font
  build is diagnosable.
- Never overwrite a differing fallback. If a fallback already agrees, still add
  the font-scoped value so repair can use it.
- Never overwrite an existing font-scoped value.
- Record `source=reference`, the reference glyph name, score, and first page in
  the CID metadata.
- Dry-run by default. `--apply` writes through the normal store save path.
- Inference is optional (`--lexicon`) and only runs for ambiguous exact or
  near candidate CIDs. Shape-only near matching remains the default.
- Resolve `--reference-font` through `cidmap/reference_fonts.py`: an existing
  path first, then family aliases in gitignored `reference-fonts/` or
  `CIDMAP_REFERENCE_FONTS`. Font binaries stay local and uncommitted.
- Proprietary fonts (Kokila, Mangal, Nirmala UI) must come from a licensed
  installation. Legacy 8-bit fonts (Preeti, Kantipur, Fontasy Himali) need a
  separate byte→Unicode decoder; their Latin cmaps do not provide Devanagari
  reference outlines.

## Deliverables

- `cidmap/autoscope.py`: candidate filtering, scope plan, apply, formatter.
- `cidmap/cli.py`: `cidmap autoscope <pdf> --reference-font ...`,
  `--reference-fonts ...`, and optional `--lexicon`.
- `cidmap/reference_fonts.py`: local alias resolver for reference fonts.
- `tests/test_cidmap_reference_fonts.py`: alias, nested-file, and
  adversarial fail-closed cases.
- Regression tests distinguish zero-distance matches with differing point
  counts (still exact) from near-zero bitmap-difference matches (near only).
- `tests/test_preeti.py`: independent Preeti fixtures, including matra and
  anusvara reordering. Preeti is a deterministic byte decoder, not an
  autoscope input.
- `tests/test_cidmap_autoscope.py`.
- Update `AGENTS.md` and `docs/review-harness.md`.

## Verification

- `cidmap autoscope ... --max-pages 20` selected 40 mappings across 9 fonts.
- Full PDF with `--lexicon` selected 228 mappings across 22 fonts: 211 exact,
  17 near, 149 with lexicon agreement, 117 fallback overrides; 105 rejected.
  Of the 63 `vatu`-collision cases, all but 13 now resolve through context.
- Full PDF shape-only (before lexicon) selected 178 mappings: 161 exact, 17
  near, 94 fallback overrides.
- Applying the earlier 150-mapping plan raised the store from 6 to 197
  font-scoped values across two documents.
- `cidmap registry ingest` added 150 observations; the registry now has 156
  observations across 35 glyphs from one document.
- The repaired copy changed extraction on 542 of 556 pages.
- Targeted cidmap/core suite: 160 passed. Full suite: 1226 passed, 7 skipped,
  3 failed, 8 errors after the composite-glyph fix and lexicon changes.
- Baseline was diffed against prior commit `4dd0664`: the same three failures
  (`missing pandas` twice, migration drift) and the same eight missing-PDF
  errors remain; six prior `test_review` fixture errors are gone. This is not
  an identical failure set: it is a strict subset with no new failures.
- Second document: `notice-new.pdf` selected 42 mappings in one Kalimati
  subset, rejected 22, and repair changed all 4 pages. The document also
  contains Kokila, Mangal, Fontasy Himali, Calibri, Preeti, and Arial; zero were
  mapped because no reference font was supplied for those families. This does
  not validate the thresholds on a different family; it shows the reference
  dependency explicitly.
- Registry ingest on the second document exposed a composite-glyph crash in
  `_outline_points`; fixed by switching to `DecomposingRecordingPen`. The
  registry now ingests both documents, but their glyph outlines do not overlap,
  so support remains provisional.
- A seeded 30-page sample of the 542 changed redbook pages is at
  `/tmp/opencode/redbook_changed_sample_30.md`. Automated proxies are not a
  spelling review: structurally valid tokens fell from 95.7% to 40.6%, and
  leading-mark tokens rose from 1.23% to 5.22%, because glyphs are recovered in
  visual order (`िववरण`, not `विवरण`). No human fluency check or error rate
  exists yet.

## Limits

- One document still yields only provisional registry support; promotion needs
  a second independent document or reviewer confirmation.
- High-distance and 13 ambiguous exact outline matches remain for manual
  review. `--rejected-out` writes them to a JSONL backlog; `cidmap review`
  still finds them as unknown CIDs and renders crops, but there is no
  automatic handoff from the backlog into the review UI.
- A correct reference outline proves glyph identity, not the surrounding word.
  Normal Nepali spelling review is still required.
- Preeti is not an outline-matching input. `migration_parser.preeti` maps bytes
  to glyphs and then applies matra, anusvara, and reph reordering rules; the new
  `tests/test_preeti.py` covers those independently of the redbook corpus.
  Kantipur/Fontasy Himali need separate verified byte tables.
