# CIDMap Phase 4 — PDF ToUnicode repair

Status: complete

## Goal

Produce a repaired copy of a PDF whose `/ToUnicode` CMaps decode the CIDs the
canonical store already knows. The source PDF is never modified and the store is
never written by this command.

This is a text-extraction repair, not a content repair. Glyph rendering, page
content streams, and `/ActualText` are left untouched.

## Decisions

- Repair only embedded Type0 fonts using `Identity-H` or `Identity-V`.
- Repair only fonts that already have a `/ToUnicode` stream. Do not invent
  mappings for fonts with no CMap.
- Use font-scoped store values only. CID-wide fallbacks are not safe to apply
  across font subsets.
- Add missing CIDs by default. Existing CMap values are preserved unless
  `--replace-conflicts` is passed; conflicts are always reported.
- Compute the font identity before patching. The CMap hash is the identity the
  store was keyed on; rewriting the CMap changes that hash.
- Install a new stream object and point the font's `/ToUnicode` at it. Shared
  CMap streams are not mutated in place.
- Write atomically to a separate output path. Refuse to overwrite the input.
- Dry-run by default; `-o/--output` writes. Refuse to overwrite an existing
  output without `--force`.
- No store changes, no automatic promotion, no OCR.

## Deliverables

- `cidmap/repair.py`: plan builder, CMap serializer, atomic writer, formatter.
- `cidmap/cli.py`: `cidmap repair <pdf> [-o out.pdf] [--replace-conflicts]`.
- `cidmap/fonts.py`: public `font_identity()` helper.
- `tests/test_cidmap_repair.py`.
- Update `AGENTS.md`, `docs/review-harness.md`, and the CLI module docstring.

## Verification

- `cidmap repair /home/swap/Downloads/redbook8283.pdf` planned six font patches
  from the committed store, all CID 1 additions.
- Writing a copy changed text extraction on 9 of 556 pages and preserved page
  count; the source PDF and store were unchanged.
- A synthetic PDF with a deliberately corrupted `/ToUnicode` value extracts
  `A` after `--replace-conflicts`.
- `cmap_mapping` now expands continuous `bfrange` entries; without this the
  serializer would drop most ranged CIDs.
- Targeted cidmap/core suite: 157 passed; full
  suite: 1199 passed, 7 skipped, 4 failed, 8 errors (known baseline).

## Acceptance

- A synthetic PDF with a deliberately wrong ToUnicode mapping extracts the
  original text after `repair --replace-conflicts`.
- Additions are serialized and round-trip through the CMap parser.
- Conflicts are reported and skipped without `--replace-conflicts`.
- Re-running repair on an already-correct PDF reports no changes and writes
  nothing.
- Real-PDF smoke test reports a plan without altering the source.
- Full suite has no new failures beyond the known baseline.
