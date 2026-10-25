# CIDMap Phase 1 — Font intelligence and observability

Status: complete
Scope owner: cidmap

## Goal

Stop treating every PDF font subset as an isolated mystery. Add diagnostics to
identify embedded fonts, detect hybrid documents, measure ToUnicode coverage,
and expose the results through `cidmap probe`.

Phase 1 is read-only. It does not change the mapping store, commit behaviour, or
`decode.is_unknown()`.

## Non-goals

- Canonical glyph-fingerprint store.
- Tightening `is_unknown()` based only on character ranges.
- HarfBuzz or shape-run matching.
- Dictionary/language-model ranking.
- PDF `/ToUnicode` or `/ActualText` patching.

## Deliverables

### 1. `cidmap/embedded.py`

Move `_EmbeddedFont` and `EmbeddedFontCache` out of `reference.py`.

```python
class EmbeddedFont:
    font: TTFont
    shape(cid) -> GlyphShape | None

class EmbeddedFontCache:
    get(xref) -> EmbeddedFont | None
    shape(xref, cid) -> GlyphShape | None
```

`reference.py` and `glyph_review.py` import from the new module. No behaviour
change.

### 2. `cidmap/fonts.py`

Expose raw ToUnicode mappings without changing `_usable_cmap()` semantics.

```python
cmap_mapping(doc, xref) -> dict[int, tuple[int, ...]] | None
```

Cache by extracted CMap bytes, not by document object.

### 3. `cidmap/classify.py`

```python
char_class(char) -> str
class_counts(chars) -> dict[str, int]
```

Classes: `devanagari`, `pua`, `latin`, `ascii-artifact`, `replacement`,
`control`, `other`.

`is_unknown()` stays unchanged in this phase. Probe reports the distribution
first so later tightening is evidence-based.

### 4. `cidmap/fingerprint.py`

Three levels:

```python
glyph_fingerprint(glyph_set, name, hmtx, upm) -> GlyphFingerprint
subset_signature(font: TTFont) -> str
font_signature(font: TTFont, base_font: str) -> FontSignature
```

- Glyph fingerprint: exact normalized outline hash plus coarse shape fields.
- Subset signature: hash of the sorted glyph fingerprints (glyph multiset,
  not CID order).
- Font signature: best-effort family/build metadata.

Limitation: subset fonts renumber and drop glyphs. `subset_signature` is
subset-specific; `family_hash` is not yet a canonical store key.

### 5. `cidmap/probe.py`

```python
probe_document(doc, *, max_pages=None, reference_font=None, reference_fonts=None) -> dict
format_probe(result) -> str
```

Per font:

- base font, xref, current font identity
- subset signature and family hash when extractable
- name-table metadata
- glyph count and ToUnicode entry count
- observed known/unknown CIDs and coverage ratio
- character-class counts
- unknown CIDs with occurrence counts and pages
- optional reference-font candidates

Scan each page once. On pages with duplicate BaseFont resources, scan the
unambiguous fonts and report the ambiguous ones as issues. Extract and
fingerprint only fonts that have unknown CIDs.

### 6. CLI

```bash
python -m cidmap.cli probe <pdf>
python -m cidmap.cli probe <pdf> --max-pages 20
python -m cidmap.cli probe <pdf> --reference-font Kalimati.ttf
python -m cidmap.cli probe <pdf> --json output/probe.json
```

### 7. Tests

- `tests/test_cidmap_classify.py`
- `tests/test_cidmap_fingerprint.py`
- `tests/test_cidmap_probe.py`
- update `tests/test_cidmap_fonts.py` for `cmap_mapping`
- update import/monkeypatch paths for the embedded-cache move

Use synthetic `fontTools` fonts. Real-PDF smoke tests may skip when fixtures are
absent.

### 8. Documentation

- `AGENTS.md`: add `probe` to the budget pipeline commands.
- `docs/review-harness.md`: add a font-diagnosis section.
- `cidmap/cli.py`: document the new subcommand.

## Acceptance criteria

- `cidmap probe /home/swap/Downloads/redbook8283.pdf` lists each font with
  coverage, class counts, and unknown CIDs.
- Adding `--reference-font /tmp/opencode/Kalimati.ttf` shows CID 1 candidates.
- `--json` output is stable and machine-readable.
- Existing `scan`, `review`, `commit`, and store schema are unchanged.
- Targeted tests pass; full-suite failures remain the pre-existing missing-PDF
  and corpus issues.

## Implementation order

1. `embedded.py` extraction and import updates.
2. `fonts.cmap_mapping()`.
3. `classify.py` and tests.
4. `fingerprint.py` and tests.
5. `probe.py` and tests.
6. CLI and docs.
7. Targeted tests plus real redbook probe.

## Progress log

- [x] Plan written
- [x] Embedded font module extracted
- [x] CMap coverage exposed
- [x] Character classification added
- [x] Fingerprints added
- [x] Probe added
- [x] CLI and docs updated
- [x] Tests and real PDF verified

## Verification

- Targeted cidmap/core review suite: 122 passed, 1 skipped.
- `cidmap probe` over `redbook8283.pdf`: 555 pages scanned, 27 fonts. The
  ambiguous Helvetica page is reported while its unambiguous fonts are still
  scanned. Kalimati subsets share family hash `456cb5e19b40...`; each subset
  has a distinct subset signature.
- `cidmap probe --reference-font Kalimati.ttf` returns the expected CID 1
  candidates (`व्` for xref 3059, `ि` for the narrow-matra subsets).
- Full `pytest tests/ -q`: 1266 passed, 7 skipped, 3 failed, 8 errors. The
  failures/errors are the pre-existing missing redbook fixture, missing pandas,
  corpus source drift, and migration drift issues.
