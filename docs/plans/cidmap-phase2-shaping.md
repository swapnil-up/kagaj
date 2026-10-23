# CIDMap Phase 2 — Shape-run inference

Status: complete
Scope owner: cidmap

## Goal

Resolve unknown CIDs using full shaped glyph runs and a Nepali lexicon instead of
isolated outline matches. Suggestions remain read-only; no auto-commit and no
store changes.

## Decisions

- Commit a derived lexicon at `cidmap/data/nepali_lexicon.txt.gz` plus a
  provenance JSON and rebuild script.
- Add `uharfbuzz>=0.39` to the `redbook` extra.
- Shape-run candidates appear in review only with `--shape-runs`.

## Non-goals

- Automatic mapping commits.
- PDF `/ToUnicode` or `/ActualText` patching.
- Cross-document glyph registry.
- OCR in the inference path.

## Deliverables

### 1. `cidmap/runs.py`

```python
word_runs(page_glyphs, *, page=0, y_tol=3.0, gap=2.0) -> list[WordRun]
runs_with_unknown(runs) -> list[WordRun]
```

- Group by font and baseline.
- Split on horizontal gaps, whitespace, and punctuation.
- Collapse duplicate same-CID glyphs within ~1 pt.
- Preserve visual order.

### 2. `cidmap/shaping.py`

```python
class ShapedGlyph:
    name: str
    glyph_id: int
    cluster: int
    x_advance: int
    x_offset: int
    y_offset: int

class ReferenceShaper:
    shape(text) -> list[ShapedGlyph]
    shape_cached(text) -> list[ShapedGlyph]
```

Use `uharfbuzz` with the reference font. Extend `ReferenceIndex` with
`shape_for(name)` and `values_for(name)`, plus `shape_distance()` for outline
comparison. Composite glyphs are decomposed before matching.

### 3. Lexicon

`cidmap/lexicon.py`:

```python
class NepaliLexicon:
    load(path=None)
    __contains__(word)
    score(word)

class LexiconIndex:
    shape_for(word)
    candidates_by_length(n)
```

- Normalize with `canonical_key(drop_joiners=True)`.
- Exact > prefix/suffix > character n-gram.
- Penalize words rejected by `kagaj_core.devanagari.validate()`.
- Load order: explicit path, local SQLite, committed gzip, pairs file.

`cidmap/build_lexicon.py` rebuilds the committed gzip from
`dictionary-data/nep_dict.sqlite3`. Commit a provenance JSON with source,
word count, and SHA-256.

### 4. `cidmap/infer.py`

```python
infer_runs(doc, *, reference_font, lexicon=None, max_pages=None,
           max_candidates=5, max_word_candidates=2000,
           max_dp_candidates=200) -> list[RunInference]
```

For each word run with unknowns:

1. Collect observed embedded glyph shapes.
2. Filter lexicon words by shaped length and known-shape anchors.
3. Shape candidates with HarfBuzz.
4. Pre-rank with direct alignment, then align the best candidates with
   Needleman-Wunsch so reph and reordered clusters can move.
5. Map aligned clusters back to Unicode.
6. Assign values to unknown CIDs.
7. Rank by shape cost, gap/length penalties, lexicon score, validation, and
   context.

### 5. Review and CLI

- `cidmap review --shape-runs` adds run candidates such as `run: व्यय`.
- Requires `--reference-font`.
- `redbook review` passes the flag through.
- New `cidmap infer` command:
  - `--reference-font`
  - `--lexicon`
  - `--max-pages`
  - `--json`

### 6. Tests

- `tests/test_cidmap_runs.py`
- `tests/test_cidmap_shaping.py`
- `tests/test_cidmap_lexicon.py`
- `tests/test_cidmap_infer.py`
- existing `tests/test_cidmap_review.py` continues to pass unchanged

Real-PDF acceptance:

- Page 1: CID 1 in `⟦1⟧यय` -> `व्यय`.
- Page 1: CID 11 in `⟦11⟧ववरण` -> `विवरण`.
- Page 3: `⟦70⟧⟦81⟧प⟦62⟧ीय` -> `द्विपक्षीय`; CID 70=`ि`, CID 81=`द्व`,
  CID 62=`क्ष`. The earlier `व्यक्तिगत`/`क्त` target was a planning error; the
  actual PDF run and HarfBuzz order match `द्विपक्षीय`.
- Existing `probe`, `scan`, `review`, and `commit` behavior is unchanged without
  `--shape-runs`.

## Implementation order

1. Runs and tests.
2. Shaping and tests.
3. Lexicon, artifact, tests.
4. Inference, alignment, tests.
5. Review and CLI integration.
6. Real PDF tuning and docs.

## Progress log

- [x] Plan written
- [x] Word runs added
- [x] Reference shaping added
- [x] Lexicon added and committed
- [x] Shape-run inference added
- [x] Review/CLI integration
- [x] Real PDF acceptance verified
