Module	Contents
kagaj_core/pdf.py	open, page geometry, get_texttrace
kagaj_core/ocr.py	PaddleOCR adapter, caching, word boxes
kagaj_core/llm.py	Gemini JSON client, retries, quota, prompt versioning
kagaj_core/devanagari.py	normalization + legacy-font transcoding
kagaj_core/tables.py	table specs, adapters, verification hooks
kagaj_core/provenance.py	hashes, build manifests
kagaj_core/eval.py	metrics/scorecards


“Table detection” is really three problems: find the table, infer columns, extract cells with semantics. Generic detectors are weak on Nepali scanned tables, and you have something better: template-specific geometry plus verification.
Proposed abstraction:
- TableSpec: page range, bbox, column bands, header rows, expected invariants.
- Adapters: PyMuPDF find_tables for vector tables, OCR word boxes + x-bands for scans, openpyxl for spreadsheets.
- A page/template classifier with confidence. Unknown template → human marks it once → becomes a spec (the DDA mark-box idea, generalized).
- Verification as a first-class hook: printed totals, row counts, checksums.



Rank by civic value × tractability × fit with existing infrastructure:
1. Budget redbook — finish and publish. It’s your second flagship and already close.
2. Parliament bills/acts — natural extension of parliament/; text-heavy, high value, reuses OCR + Gemini + entity extraction.
3. Public procurement (PPMO) — high accountability value, but check access/ToS before committing.
4. Nepal Gazette — huge and heterogeneous; start with one section, not the whole thing.
5. DDA drug prices — small; finish as a testbed for the table layer, not a flagship.
6. Local-government budgets — high value, layout chaos; later.


Weeks 1–2: eval harness + gold sets for redbook/migration/water; add a test.yml CI workflow (you currently have none).
Weeks 3–4: Devanagari normalizer + hard-case corpus; wire into parliament/water.
Weeks 5–6: extract kagaj_core OCR/LLM/provenance with two real consumers.
Weeks 7–8: TableSpec abstraction; migrate redbook + DDA.
Weeks 9–10: ship budget dataset + Parquet/schema/release; close the 34 failed verbatims.
Weeks 11–12: start bills/acts parser on the new substrate; write the design doc before coding.









What other countries/projects do
1. Per-font mapping tables, not one global map
- India: KrutiDev, Chanakya, DevLys, Shree-Lipi, APS, Akruti converters.
- Bangladesh: Bijoy/SutonnyMJ converters.
- Nepal: Preeti, Kantipur, Sagarmatha to Unicode.
- Myanmar: Zawgyi to Unicode.
The recurring lesson: font identity + version matters. KrutiDev 010 and 714 look related but assign different keys. krutiextract detects the font profile per document; banglakit classifies per text run, not per file.
2. Font-aware/hybrid decoding
bangla-pdf-decoder found a pattern very relevant to us: modern government PDFs often mix real Unicode base consonants with legacy/PUA/Latin-Extended glyphs for conjuncts. Applying a whole-document legacy table corrupts the Unicode parts. The fix is glyph-by-glyph classification: leave valid Devanagari alone, decode only the unknown glyphs.
3. Outline fingerprint lookups
OpenPecha’s pdf-cmap-fix does exactly what we built, but more formally:
- Tier 1: match by GID
- Tier 2: match by glyph name
- Tier 3: match by outline fingerprint
That is a strong validation of our Kalimati approach. It also suggests we should store outline fingerprints as a reusable registry, not just recompute against one font.
4. Repair /ToUnicode, don’t just work around it
Tools like pdf-cmap-fixer, RebuildPDFCMap, and pdf_manip rebuild or augment /ToUnicode streams from the embedded font’s cmap/glyph names/outlines. Once fixed, every downstream tool — search, copy/paste, screen readers, our parsers — benefits.
5. OCR as a cross-check, not always the primary path
A Nepali PDF extraction study found parsers fast but weak on non-Unicode fonts; PyTesseract was more consistent. But OCR is slower and hallucinates. The mature pattern is parse first, OCR as evidence, which is already what cidmap/ocr.py and quorum.py do.
6. Glyph recognition + language model
A DAS 2018 paper classifies individual glyph images into homoglyph groups, then uses a language model to recover the font-character mapping. That is the next step beyond outline matching: shape candidates + Nepali language plausibility.
7. Font identification / model selection
OCR-D identifies historical font families and routes pages to font-specific OCR models. The equivalent for us: identify the exact font family/version first, then apply the right reference font and mapping profile.
8. Human-in-the-loop post-correction
OCR-D’s PoCoWeb, Transkribus, and similar systems combine automatic correction with review queues and confidence thresholds. Our review harness is already in this family; the next upgrade is prioritizing only uncertain glyphs.
Smart additions for Kagaj
Ranked by value-to-effort:
A. Font fingerprint registry — highest value
Compute a stable fingerprint from the embedded font:
- glyph count/order
- outline hashes
- cmap/GSUB summary
- BaseFont + subset metadata
Store it in the mapping file. Then a decision made for Kalimati@… can be reused across every PDF containing the same font build. This turns per-document review into a growing font knowledge base.
B. Hybrid/PUA detector
Flag PDFs where some glyphs decode as valid Devanagari and others decode as:
- U+E000–U+F8FF PUA
- Latin-1/Latin Extended
- control/ASCII artifacts
Then decode only the broken run, not the whole document.
C. Use known CIDs as anchors inside the same subset
Many subsets have partial ToUnicode coverage. Those known CIDs can anchor:
- GSUB/ligature relationships
- neighboring glyph sequences
- word-level alignment
Instead of treating every unknown CID independently, propagate from the known ones.
D. Shape-run matching with HarfBuzz
Current approach matches one glyph. Better:
1. Generate candidate Unicode clusters/words.
2. Shape them with the reference font via HarfBuzz.
3. Compare the whole glyph run — IDs, outlines, advances, positions — with the PDF run.
This handles context-dependent variants, reordering, and ligatures much better than isolated glyph matching. This is probably the biggest remaining accuracy win.
E. Dictionary/language-model ranking
Use the existing dictionary/ data and kagaj_core.devanagari.validate() to rank candidate mappings:
- reject invalid matra/virama sequences
- prefer candidates that form dictionary words
- use character n-grams for names/rare words
This would let the system say “three shape candidates fit, but only one forms a valid Nepali word.”
F. Cross-document consensus
If the same font fingerprint appears in many PDFs, aggregate confirmed mappings across documents. Low-confidence mappings can be promoted once enough independent documents agree.
G. Patch the PDF with /ActualText
After confirmation, emit a repaired PDF with /ActualText or corrected /ToUnicode. Then the dataset is portable and doesn’t depend on our decoder.
H. Active-learning review
Use confidence scores from outline matching, OCR quorum, and dictionary ranking to auto-accept very high-confidence glyphs and send only uncertain ones to review.
Suggested roadmap
Phase 1 — cheap, immediate
1. Add font fingerprinting to embedded fonts.
2. Add hybrid/PUA/Latin-Extended detection.
3. Add anchor-coverage reporting: “this subset has 80% ToUnicode, 20% unknown.”
4. Add a cidmap probe <pdf> command showing font fingerprints, GSUB/cmap summary, and unknown glyph samples.
Phase 2 — accuracy
5. Add HarfBuzz shape-run candidate matching.
6. Add dictionary/validation ranking.
7. Expand gold pages and measure per-font accuracy.
Phase 3 — durability
8. Emit repaired /ToUnicode or /ActualText PDFs.
9. Build cross-document font consensus.
10. Add confidence thresholds and auto-accept rules.


Phase 1 — font intelligence and observability
Goal: stop treating every PDF subset as an isolated mystery. Add enough metadata to identify fonts, detect hybrid documents, and measure how much ToUnicode coverage each subset has.
1. Add cidmap/fingerprint.py
New module with three levels of identity:
- Glyph fingerprint — hash of normalized outline geometry: contour commands, quantized points, advance width, bbox. Stable for the same embedded glyph across documents, distinct for different shapes.
- Subset fingerprint — hash of the embedded font’s glyph set and glyph order.
- Family signature — name-table family/style, unitsPerEm, glyph count, OS/2 version, GSUB feature/lookup summary.
This separates “which exact subset is this?” from “which font family/build is this?”
Expose:
- EmbeddedFontFingerprints cache keyed by font xref.
- glyph_fingerprint(shape).
- font_signature(font_bytes_or_ttfont).
2. Extend font inspection without changing decode behavior
In cidmap/fonts.py:
- expose raw ToUnicode mappings even when _usable_cmap rejects an identity map;
- add cmap_entries(doc, xref) and cached access;
- add a FontProfile dataclass containing:
- base font, xref, current font_id
- family signature
- glyph count
- ToUnicode entry count
- observed CIDs
- known/unknown observed CIDs
- coverage ratio
- unknown CID list
No changes to get_value or commit semantics yet.
3. Add hybrid-character classification
New cidmap/classify.py:
char_class(char) -> "devanagari" | "pua" | "latin" | "ascii-artifact" |
                     "replacement" | "control" | "other"
Important: do not change is_unknown() semantics yet. First report the classes. The current _ASCII_ARTIFACTS set can false-positive on valid Latin text like B, 3, :, so we need evidence before tightening it.
Use it to report per font:
- how many observed glyphs are valid Devanagari
- how many are PUA
- how many are Latin/Latin-Extended
- how many are replacement/control artifacts
This is the detector for bangla-pdf-decoder-style hybrid PDFs.
4. Add cidmap probe <pdf>
A read-only diagnostic command, separate from scan/review:
python -m cidmap.cli probe redbook.pdf
python -m cidmap.cli probe redbook.pdf --reference-font Kalimati.ttf --json out.json
Output per font:
- BaseFont, xref, current font identity
- family signature short hash
- glyph count
- ToUnicode coverage: known_observed / observed
- unknown CIDs and occurrence counts
- character-class breakdown
- with --reference-font: top outline-match candidates for unknown CIDs
--json makes it usable from tests and future automation. --reference-font reuses the existing ReferenceIndex and EmbeddedFontCache.
5. Tests
Add:
- tests/test_cidmap_fingerprint.py
- same synthetic glyph produces the same fingerprint
- different glyphs differ
- renumbered glyph order does not change glyph fingerprint
- family signature differs across fonts
- tests/test_cidmap_probe.py
- coverage calculation from a synthetic CMap
- unknown CID listing
- character-class counts
- probe JSON shape
- extend tests/test_cidmap_fonts.py for raw CMap access.
Use synthetic fontTools fonts where possible, so tests do not need a real PDF.
6. Documentation
Update:
- AGENTS.md: add probe to the budget pipeline commands.
- docs/review-harness.md: explain font fingerprints, coverage, and hybrid classification.
- Possibly a short docs/cidmap.md if the probe workflow needs more detail.
What this unlocks
After Phase 1:
- We can see immediately whether a PDF is:
- fully broken legacy encoding,
- mostly Unicode with a few broken glyphs,
- PUA/hybrid,
- or a subset with decent anchor coverage.
- We can compare two PDFs and tell whether they use the same font build.
- We can measure progress per font instead of guessing from whole-document OCR diffs.
- We have the metadata needed for Phase 2: shape-run matching and dictionary ranking.
Phase 2 — after Phase 1
1. Shape-run matching with HarfBuzz
- add optional uharfbuzz;
- generate candidate Unicode clusters/words;
- shape them with the reference font;
- compare whole glyph runs, not isolated glyphs.
2. Dictionary/validation ranking
- use dictionary/ plus kagaj_core.devanagari.validate();
- rank shape candidates by valid Nepali word likelihood.
3. Anchor propagation
- use known CIDs in the same subset to seed GSUB and sequence inference.
Phase 3 — durability
- Emit repaired /ToUnicode or /ActualText PDFs.
- Add a cross-document glyph-fingerprint registry.
- Add confidence thresholds and auto-accept rules for review.
Open decisions
- Fingerprint scope: diagnostic only in Phase 1, or make glyph fingerprints the canonical store key now? I recommend diagnostic first, canonical later.
- HarfBuzz dependency: acceptable for Phase 2? It would become an optional extra.
- Reference fonts: Kalimati is GPL, so keep it user-supplied and do not commit binaries without a policy decision.