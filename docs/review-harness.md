# Review harness

`kagaj_core.review` is the shared static-HTML decision sheet for unknown glyphs.
It is presentation only: adapters find the glyphs, render the evidence, and
commit the decisions. There is no server and no build step. PDF crops come from
`kagaj_core.review.crops`, which imports PyMuPDF and numpy lazily.

## Current adapters

| Adapter | Command | Key | Group | Tags | Export consumer |
|---|---|---|---|---|---|
| `cidmap/glyph_review.py` | `cidmap review` | `font_id╱cid` | font_id | none | `cidmap commit` (`cid_corrections.json`) |
| `cidmap/review.py` | `cidmap scan` | `font_id╱cid` | font_id | `verdict` | `cidmap commit` |

`redbook_parser/review/` remains a thin alias for `cidmap.glyph_review` and adds
the legacy CID hints. Both glyph adapters key by `font_id`. Texttrace only
reports the BaseFont name (`Kalimati`), which is shared by subsets; `cidmap.fonts` instead hashes the
font's ToUnicode CMap, or falls back to `BaseFont@src:<pdf-hash>:xref<N>`.
Pages where one BaseFont has multiple resources are skipped and surfaced in the
review notice rather than merged. Both adapters select their evidence in the
adapter and call the shared crop renderer.

## Font diagnosis

`cidmap probe <pdf>` is a read-only preflight for review. Per font subset it
reports the resolved identity, ToUnicode entry count, observed known/unknown
CIDs, coverage, character-class counts, and unknown CIDs with their pages.
Pages with duplicate BaseFont resources are still scanned for the unambiguous
fonts; the ambiguous spans are reported as issues.
`--reference-font` adds the same outline-match candidates the review sheet uses.
`--registry` annotates unknown CIDs with cross-document evidence. `--json`
writes the full report for tests or downstream tooling.

Character classes are diagnostic only: `decode.is_unknown()` still defines what
is unknown. The class report distinguishes valid Devanagari, PUA, Latin,
replacement/control artifacts, and ASCII-artifact-shaped glyphs, which is how
hybrid PDFs become visible before anyone edits the store.

`cidmap.fingerprint` adds a second identity layer for triage. A glyph
fingerprint hashes normalized outline geometry, independent of glyph ID and
name. A subset signature hashes the multiset of glyph outlines; it changes when
the subset's glyph set changes but does not encode CID order. A font signature
captures name-table/table/GSUB metadata. Subset fonts renumber and drop glyphs,
so subset signatures stay subset-specific and font signatures are best-effort;
neither is a canonical store key.

## Cross-document registry and promotion

`cidmap registry ingest <pdf>` records committed font-scoped values under
`(family_hash, outline_hash)`. The registry is evidence, not a decoder source:
the same glyph outline observed in another subset or document adds support
without changing `cid_mappings.json`.

- One document contributes one vote per glyph; re-ingesting is idempotent.
- Conflicting values freeze the entry as `conflict`.
- `cidmap review --registry ...` and `cidmap probe --registry ...` show
  registry values as candidates or annotations.
- `cidmap promote <pdf>` is dry-run by default. `--apply` writes only mappings
  with confirmed registry support or an exact reviewer-confirmed observation.
- Promotion never overwrites an existing value and uses the same decision
  validation as `cidmap commit`.

## Reference-outline bootstrap

`cidmap autoscope <pdf> --reference-font Kalimati.ttf` fills font-scoped
mappings from exact, unambiguous outline matches. It is dry-run by default.

- Candidates come from `probe --reference-font`; `.notdef` and private names are
  ignored.
- A value must score `<= 0.75` and lead the next distinct value by `1.0`.
- The command never overwrites a differing fallback or an existing font-scoped
  value. If a fallback agrees, it still writes the font-scoped value.
- `--apply` records `source=reference` with the glyph name, score, and first
  page. Registry ingestion can then record the same evidence.
- This is a bootstrap. Ambiguous and high-distance candidates still need the
  review harness. `--rejected-out` writes them as JSONL; they stay unknown in
  the store, so `cidmap review <pdf>` still queues them with crops.

## PDF ToUnicode repair

`cidmap repair <pdf> -o repaired.pdf` writes a copy whose `/ToUnicode` CMaps
include font-scoped values from `cid_mappings.json`. It is a text-extraction
repair only: page content, rendering, and `/ActualText` are unchanged.

- The command is dry-run by default and reports additions and conflicts.
- Existing CMap entries are preserved unless `--replace-conflicts` is passed.
- Only embedded Type0 fonts using Identity-H/Identity-V with an existing
  `/ToUnicode` stream are considered.
- The font identity is computed before patching; a repaired CMap gets a new
  identity hash, but extraction no longer needs the store.
- Each font receives a new stream object, so shared CMaps are not mutated in
  place. The source PDF and the store are never written.
- Use `--json` for the full plan and `--force` to replace an existing output.

## Crop rendering

`kagaj_core.review.crops.render_review_crop(doc, word=(page, bbox),
glyph=(page, bbox))` returns a `ReviewCrop` with two data-URI PNGs: the glyph
close-up and the printed-word crop, plus the glyph's percentage box inside the
word crop.

- Bboxes are in **unrotated text space**, the coordinate system returned by
  `page.get_texttrace` and the census. The renderer maps them into display
  space, so rotated pages work.
- The word rect is padded and intersected with the visible page before
  rendering. Overlay percentages are computed against that clipped rect, not
  the requested one.
- Word and glyph may come from different pages. In that case both crops render,
  but no overlay is drawn.
- Degenerate glyph boxes (zero-width matras, line-spanning boxes) are expanded;
  optional ink trimming finds the actual printed stroke.
- If one side fails, the other still renders. Empty or off-page crops become
  `None` instead of broken images.
- Glyph crops adapt their DPI to the target pixel size, bounded to 300-600 DPI.
  Word crops use 300 DPI and a pixel budget. Glyph crops stay tight to the
  character box so they do not pull in neighbouring text lines.

Cidmap reads OCR word boxes from rendered pages, so `cidmap/ocr.py` converts
them back into text space before matching and storing them.

## Adapter contract

1. Scan the source once and collect the items to review.
2. Choose the review key. It is opaque to core: `"Kalimati@cmap:abc123╱42"`.
   Never use a bare CID for a problem that can span font subsets.
3. Render crops with `render_review_crop` (or supply your own `src` strings).
   Data URIs and asset paths are both valid; paths let a large sheet use
   lazy-loaded files. Set `caption` when an item has several samples so each
   crop says which occurrence it shows.
4. Build `ReviewItem` values. Put adapter identifiers in `data`
   (`{"font_id": ..., "cid": 42, ...}`); they are copied into exports unchanged.
5. Set `input_placeholder` to the adapter's expected input. CID review expects
   a glyph/cluster (`"र्"`, `"ि"`), not the surrounding word. Add
   adapter-specific filters as `tags` (for example
   `tags={"verdict": "disagree"}`) and name them in `tag_filters`.
6. Pass a `session` string that identifies the adapter and source, e.g.
   `"redbook:" + pdf_path` or `"cidmap:" + pdf_path + ":" + store_path`.
7. Convert exported `ReviewDecision` records to the adapter's command shape.

```python
from kagaj_core.review import ReviewCandidate, ReviewItem, render_review
from kagaj_core.review.crops import render_review_crop

crop = render_review_crop(
    doc,
    word=(page, word_bbox),
    glyph=(page, glyph_bbox),
)
items = [
    ReviewItem(
        key=f"{font_id}╱{cid}",
        label=f"CID {cid}",
        group=font_id,
        context=context,
        candidates=(ReviewCandidate(value="क", count=12),),
        crops=(crop,),
        data={"font_id": font_id, "cid": cid},
        input_placeholder="glyph / cluster",
    )
]
html = render_review(items, session=f"redbook:{pdf_path}",
                     title="Unknown CID review")
```

## Behaviour

- Decisions persist in `localStorage` under `storage_key(session)`, so two PDFs
  or stores never share state. Only `{key, value, undecodable, inconsistent,
  note}` is stored.
- Keys: `1`–`9` pick a candidate, `Enter` accepts the typed or current value and
  advances, `K` keeps the current value, `U` marks undecodable, `I` flags
  inconsistent samples, `S`/`→` skips, `←` goes back.
- `inconsistent` is a third state, not a value: it means the same CID shows a
  different printed glyph shape across samples. It does **not** mean the CID
  appears in different words; judge the glyph crop, not the surrounding word.
  Add a note explaining what differs. Consumers treat it as an engineering
  follow-up, never as a mapping.
- Filters: undecided only, group, key search, and any adapter tags named in
  `tag_filters` (for example cidmap's `("verdict",)`).
- Progress and decided state update immediately; filters hide cards without
  discarding their input.
- Redbook cards show occurrence counts and pages, not a concatenation of
  unrelated glyph windows. Each crop is captioned with its page and sample
  number; the glyph close-up and word crop come from the same occurrence.
- The red box is the PDF character box. It can cover only part of a joined
  glyph or combining mark; the glyph close-up shows the shape to compare.
- `cidmap review` and the redbook alias accept an optional original font
  (`--reference-font Kalimati.ttf`). It extracts each embedded subset glyph,
  matches its outline against the reference font, and turns the reference
  font's cmap/GSUB roles into candidate buttons. This is only a hint: the
  embedded subset has its own glyph numbering, so the value is not a direct CID
  lookup. Keep the reference font out of git and confirm every candidate.
- `--shape-runs` adds whole-word candidates from `cidmap infer`: the candidate
  word is shaped with HarfBuzz, aligned to the observed run, and the aligned
  cluster supplies the unknown CID value. It is slower and remains a hint.
- Import/export are JSON. Export includes every card; consumers ignore blank and
  undecodable records.

## Export compatibility

Core exports the neutral shape:

```json
{"key": "Kalimati@cmap:abc123╱42", "value": "क", "undecodable": false,
 "inconsistent": false, "note": "",
 "data": {"font_id": "Kalimati@cmap:abc123", "cid": 42}}
```

- Redbook's new `cid_corrections.json` is font-scoped and can go straight to
  `cidmap commit`. `redbook derive` remains only for old word-based files:
  neutral legacy records and `[{"cid": 42, "correct": "क"}]`.
- `cidmap commit` accepts only neutral, font-scoped `decisions.json`. Legacy
  bare-CID or `{font, cid, decision}` files are rejected so old unscoped answers
  cannot silently overwrite subset-specific mappings.
- Empty values are rejected; use `undecodable` explicitly. Commit is
  all-or-nothing: a conflict leaves the store unchanged.
- Same-value re-submits are idempotent; different values for an existing
  `(font_id, cid)` are rejected because the review sheet is single-reviewer and
  there is no merge queue.

For a one-off conversion in Python, use
`kagaj_core.review.parse_decisions(records, convert=...)`.

## Storage and assets

- Session keys include the adapter and source path, so unrelated PDFs and
  stores never mix decisions.
- Persist decisions only, never images or full records, to stay inside the
  `localStorage` quota.
- Crops are strings; use data URIs for small reviews or files beside the HTML
  for large ones. Images use `loading="lazy"`.
- The HTML shell stays stdlib-only. PDF crops live in `review/crops.py` and
  import PyMuPDF/numpy lazily; keep OCR engines and parser imports in the
  adapter.

## Tests

- `tests/test_core_review.py` covers escaping, bootstrap safety, candidates,
  tags, filters, empty states, session keys, and the no-PDF-dependency contract.
- `tests/test_core_crops.py` covers page clipping, overlays, rotation, separate
  word/glyph pages, degenerate boxes, partial failures, DPI caps, and lazy
  imports.
- `tests/test_review.py` uses a fake document and asserts each page is extracted
  once; the real-PDF smoke test skips when the redbook is absent.
- `tests/test_cidmap_review.py` is the cidmap parity/regression suite for the
  shared shell, font-scoped commit, conflict rejection, and the third state.
- `tests/test_cidmap_fonts.py` covers CMap hashing, raw CMap entries, PDF-local
  fallback, and loud ambiguity when one BaseFont has multiple resources.
- `tests/test_cidmap_classify.py` covers the diagnostic character classes.
- `tests/test_cidmap_fingerprint.py` covers glyph stability, differentiation,
  subset signatures, and missing name-table metadata.
- `tests/test_cidmap_probe.py` covers coverage, class aggregation, unknown CIDs,
  reference candidates, and JSON output.
