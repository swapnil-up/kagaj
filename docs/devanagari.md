# Devanagari: terminology and normalization policy

Status: **specification and implementation**. The runtime is
`kagaj_core/devanagari.py`; the companion corpus is
`tests/devanagari/cases.jsonl`, and the schema is enforced by
`tests/devanagari/test_corpus.py`.

This document defines the vocabulary used by the corpus and the behaviour that
`normalize`, `canonical_key`, `validate`, and `segment_aksaras` must have. It
does **not** define a spelling corrector or a legacy-font transcoder.

## 1. Why this exists

Every pipeline currently cleans strings locally. Parliament OCR, redbook CID
decoding, and water-schedule extraction can therefore disagree about whether two
strings are "the same word". The corpus makes that disagreement explicit and is
enforced against the normalizer in `kagaj_core/devanagari.py`.

The central rule:

> Unicode text stores **logical** order. A font decides **visual** order.
> Stacked and side-by-side conjuncts can be the same code points. OCR reading
> order is not logical order.

## 2. Units: code point, glyph, aksara

| Term | Meaning |
|---|---|
| **Code point** | One Unicode scalar value, written `U+0915`. `क्ष` is three code points: `U+0915 U+094D U+0937`. |
| **Glyph** | A drawn shape in a font. One code point can have several glyphs (contextual forms); one glyph can represent several code points (a ligature). |
| **Aksara** | An orthographic syllable: a consonant cluster with its optional vowel sign and final signs, or an independent vowel with its signs. This is the unit a reader perceives, not a code point. |
| **Grapheme cluster** | A Unicode text-segmentation unit. It is close to an aksara but not identical, because Unicode grapheme rules do not know Devanagari orthography. |

`segment_aksaras` works on **aksaras**, not code points or bytes.

## 3. Building blocks

| Block | Code points | Notes |
|---|---|---|
| Independent vowels | `U+0905`–`U+0914` and `U+0960`–`U+0961` (अ आ इ ई उ ऊ ऋ ॠ ऌ ॡ ए ऐ ओ औ; extended vowels ऍ ऎ ऑ ऒ are also in the first range) | Carry their own vowel; no consonant base. |
| Consonants | `U+0915`–`U+0939` (क–ह) | Carry an inherent vowel unless suppressed. |
| Virama / halanta | `U+094D` (्) | Suppresses the inherent vowel of the preceding consonant. |
| Dependent vowel signs (matras) | `U+093E`–`U+094C`, plus extensions | Attach to a consonant or a consonant cluster. |
| Nukta | `U+093C` (़) | Dot below a consonant; changes the consonant. |
| Anusvara | `U+0902` (ं) | Nasalisation mark after a vowel. |
| Candrabindu | `U+0901` (ँ) | Nasalisation mark; not interchangeable with anusvara in all words. |
| Visarga | `U+0903` (ः) | Final aspiration mark. |
| Devanagari digits | `U+0966`–`U+096F` (०–९) | Decimal digits, distinct from ASCII `0`–`9`. |
| Danda / double danda | `U+0964`, `U+0965` (। ॥) | Sentence punctuation. |
| ZWJ / ZWNJ | `U+200D`, `U+200C` | Invisible join controls; see §7. |

A **matra** is a dependent vowel sign. Some matras have two visual parts but
are one code point (`ो` = `U+094B`, `ौ` = `U+094C`). Others may arrive from OCR
as two code points (`े` + `ा` = `U+0947 U+093E`); see §9.

An **aksara** normally has this shape:

```text
[ consonant (+ nukta) (+ virama consonant ...) ] + [ matra ] + [ anusvara | candrabindu | visarga ]
```

or:

```text
[ independent vowel ] + [ anusvara | candrabindu | visarga ]
```

Standalone signs, digits, punctuation, and whitespace are their own segments.

## 4. Live and dead consonants; half-forms; conjuncts

A **live consonant** still carries its inherent vowel (the unwritten `a`).
A **dead consonant** has that vowel suppressed, either by a visible **virama**
(हलन्त) or by a **half-form** glyph.

A **half-form** is the shape a dead consonant takes when it joins the next
consonant. The half-form is a glyph choice: the underlying text is still
`consonant + U+094D`.

A **conjunct** is two or more consonants joined without an intervening vowel.
In Unicode the consonants are separated by viramas:

```text
क्ष  = क + ् + ष       U+0915 U+094D U+0937
त्र  = त + ् + र       U+0924 U+094D U+0930
ज्ञ  = ज + ् + ञ       U+091C U+094D U+091E
```

A **ligature** is a single glyph that a font uses for a conjunct. Whether `क्ष`
is drawn as one ligature, as a stacked pair, or side by side is a font decision,
**not** a difference in Unicode text. The same three code points can render
differently in two fonts and are still the same word.

## 5. Reph and rakar

Two positioning forms of `र` are easy to confuse.

| Form | Logical order | Example | Meaning |
|---|---|---|---|
| **Reph** | `र + ् + C` | `अर्थ` = अ + र् + थ | `र` originates before the consonant and is drawn as a mark above/after the cluster. |
| **Rakar** | `C + ् + र` | `क्रम` = क् + र + म | `र` originates after the consonant and is drawn as an attached stroke. |

`कर्म` (क + र् + म, "karma") and `क्रम` (क् + र + म, "order") use the same four
letters in different logical positions. They are different words. An OCR pass
that reports visual order can swap them.

For `segment_aksaras`, a reph belongs to the **following** aksara:

```text
अर्थ  -> अ | र्थ
कर्म  -> क | र्म
कार्य -> का | र्य
```

## 6. Logical order versus visual order

Unicode stores text in **logical order**, the order in which the units are
pronounced and compared. Rendering reorders some units:

- `ि` (`U+093F`) is written after its consonant in logical order but is drawn
  before it: `कि` = क + ि.
- A reph is written `र + ्` before a consonant but drawn above/after it.
- A two-part matra such as `ो` is drawn on both sides of its consonant.

**Visual order** is what a reader sees, left to right. OCR engines and naive
PDF text extraction sometimes emit visual order. Visual order is not a valid
input representation for comparison. For example, a leading `ि` before a
consonant (`िक`) is structurally invalid; the logical text is `कि`.

## 7. ZWJ and ZWNJ

`U+200D` ZERO WIDTH JOINER (ZWJ) and `U+200C` ZERO WIDTH NON-JOINER (ZWNJ) are
format controls with orthographic meaning, not garbage characters.

After a virama:

| Sequence | Name | Effect |
|---|---|---|
| `क् + ष` | default | The font may form the `क्ष` ligature. |
| `क् + U+200D + ष` | ZWJ | Requests the half-form / prevents the default ligature. |
| `क् + U+200C + ष` | ZWNJ | Prevents joining; the virama is typically visible. |

All three are distinct text but can be considered the same word for matching.
A ZWJ may also appear **before** the virama (`C + U+200D + ् + C`). This is the
valid sequence that suppresses reph for `र` and requests the full consonant plus
the following conjunct form; `validate` accepts it and `segment_aksaras` keeps
it inside one aksara.

Therefore:

- `normalize` **preserves** ZWJ and ZWNJ.
- `canonical_key` **removes** them.
- `validate` rejects a ZWJ/ZWNJ that is neither after a virama nor a ZWJ
  directly before a virama after a consonant base (for example at the start of a
  word or after a matra).

## 8. Nukta and precomposed letters

Nukta `U+093C` is a combining mark with combining class 7. It modifies the
preceding consonant. Nepali text commonly uses it on `ड`, `ढ`, `फ`, `ज`, `क`,
`ख`, `ग`, and `य`, producing `ड़`, `ढ़`, `फ़`, `ज़`, `क़`, `ख़`, `ग़`, `य़`.

Unicode also has precomposed code points for some of these, for example
`U+0958` क़ and `U+095C` ड़. The native compositions `U+0929` ऩ, `U+0931` ऱ, and
`U+0934` ऴ are accepted in both forms (`न + ़`, `र + ़`, `ळ + ़`). The
precomposed and decomposed forms are canonically equivalent, but composition is
not symmetric; see §9.

Nukta is **phonemic**. `ज` and `ज़` are not the same letter, and `ड` and `ड़`
are not the same letter. A normalizer must not delete nukta merely because OCR
often inserts it incorrectly.

The corpus therefore distinguishes:

- **structurally valid nukta**: nukta directly after a consonant that can take
  it, before any virama or matra;
- **structurally invalid nukta**: nukta after a vowel, virama, or matra, or on a
  consonant outside the Nepali nukta set, including the reported OCR artifact
  `स्वप़्निल` (extra nukta on `प`);
- **lexical errors**: a structurally valid nukta used for the wrong word (for
  example `ज़ान` where the context is the name `जान`). `validate` may accept the
  structure; only a later `repair` or a human may decide the word.

## 9. What NFC and NFD do — and do not do

Unicode normalization is necessary but not sufficient.

**What NFC does:**

- Applies canonical ordering. Nukta (class 7) sorts before virama (class 9), so
  `क + ् + ़` is reordered to `क + ़ + ्`.
- Decomposes and recomposes many characters into canonical equivalents.
- Composes `U+0929` ऩ, `U+0931` ऱ, and `U+0934` ऴ normally.

**What NFC does not do:**

- **Composition exclusions.** `U+0958`–`U+095F` (क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़) have
  canonical decompositions but are excluded from composition. NFC turns
  `U+0958` into `U+0915 U+093C` (क + ़), and never produces the precomposed
  form. A lossless normalizer must accept both spellings.
- **Two-part matras.** The sequences `U+0947 U+093E` (`े` + `ा`) and
  `U+0948 U+093E` (`ै` + `ा`) do **not** compose to `U+094B` (`ो`) and
  `U+094C` (`ौ`), in logical or visual order. `U+094B` and `U+094C` are atomic
  and do not decompose. NFC leaves both representations alone.
- **Glyph identity.** NFC knows nothing about half-forms, stacked conjuncts, or
  ligatures. Those are font choices over the same code points.
- **ZWJ/ZWNJ semantics.** NFC preserves both controls; it does not know whether
  they are orthographically meaningful.
- **Logical order.** NFC does not repair visual-order OCR output.
- **Spelling.** NFC does not know that `सड़घीय` should be `संघीय`.

`normalize` is therefore "NFC plus input validation", while `canonical_key`
performs the additional lossy steps below.

## 10. Valid versus invalid sequences

Validity is layered. `validate` reports the first two layers; it does not
silently correct spelling.

| Layer | Question | Example |
|---|---|---|
| **Structural** | Is this a well-formed sequence of Devanagari units? | `िक` (leading matra) is invalid; `कि` is valid. |
| **Orthographic** | Is the nukta on a consonant that takes one? | `स्वप़्निल` (nukta on प) is invalid. |
| **Lexical** | Is this the intended word? | `ज़ान` may be structurally valid but wrong for the name `जान`. |

Structural rules used by the corpus:

- A matra must follow a consonant or a consonant cluster — never an independent
  vowel or the start of text.
- A virama must follow a consonant (or a nukta attached to one).
- A nukta must follow a consonant directly, before virama and matra.
- No double virama in one cluster.
- ZWJ/ZWNJ only after a virama, except a ZWJ placed between a consonant and its
  virama to suppress reph.
- No lone combining mark at the start of a token.
- Unknown control characters are invalid; normal whitespace (space, tab,
  newline) is allowed between tokens.

A case tagged `invalid.*` must be rejected by `validate`. The `expected` field
in such a case is the intended valid spelling, **not** an automatic repair
promise. Repair is deferred (§11.5).

A case tagged `repair.*` is a known lexical or OCR substitution whose structure
is still valid. `validate` must accept it; the corpus records the intended word
for the deferred `repair` stage. This is why `सड़घीय` is a repair case (nukta on
`ड`) while `खड़्का` is an invalid case (nukta after a virama).

## 11. Normalizer policy

The names below are the contract. The implementation lives in
`kagaj_core/devanagari.py`.

### 11.1 `normalize(text) -> str` — lossless

1. Apply Unicode NFC.
2. Reject or report invalid Unicode (surrogates, unknown controls) rather than
   silently dropping it.
3. Preserve:
   - ZWJ and ZWNJ;
   - nukta: NFC may rewrite a precomposed letter as base+nukta, but the mark
     must never be deleted;
   - Devanagari digits and punctuation;
   - whitespace runs;
   - all valid lexical variation.
4. Do not reorder logical units beyond what NFC requires. Do not "fix" visual
   order, spelling, or OCR substitutions.

Property: `normalize` may change code points but not words. It is idempotent.

### 11.2 `canonical_key(text, *, drop_joiners=False) -> str` — lossy

1. Start from `normalize(text)`.
2. If `drop_joiners=True`, remove ZWJ and ZWNJ. The default is `False` because
   joiners can carry CID-mapping meaning.
3. Fold Devanagari digits `U+0966`–`U+096F` to ASCII `0`–`9`.
4. Canonicalise split two-part matras to the atomic code points:
   - `U+0947 U+093E` and `U+093E U+0947` → `U+094B` (ो);
   - `U+0948 U+093E` and `U+093E U+0948` → `U+094C` (ौ).
5. Collapse whitespace runs to a single space and strip the ends.
6. Normalize danda spacing, not characters: remove whitespace before `।` and
   `॥`, and put one space after one when a letter or digit follows.
7. Leave nukta, punctuation other than danda spacing, and
   anusvara/candrabindu alone.

The key is idempotent. It may merge spellings that are the same word, but it
must not merge phonemically distinct letters (`ज` vs `ज़`) or reorder
visual-order text to logical order.

### 11.3 `validate(text) -> list[Issue]` — non-mutating

Returns structural and orthographic issues with offsets. It does not repair,
truncate, or drop text. It must flag every `invalid.*` corpus case, accept every
valid case, and accept structurally valid `repair.*` cases.

### 11.4 `segment_aksaras(text) -> list[str]`

Splits at aksara boundaries:

- a consonant, its nukta, and a following virama+consonant chain stay together;
- a matra belongs to the preceding cluster;
- anusvara, candrabindu, and visarga belong to the preceding aksara;
- a reph (`र + ्`) belongs to the following aksara;
- ZWNJ breaks a conjunct and stays attached to the preceding virama; ZWJ stays
  inside the cluster, including when it precedes the virama;
- digits, punctuation, and whitespace are separate segments.

Property: concatenating the result returns the input string exactly.

### 11.5 `repair(text)` — deferred

A future `repair` may map known OCR artifacts to intended spellings using the
corpus. It is explicitly out of scope here: it is lossy, context-dependent, and
must never run silently inside `normalize`. When implemented, every repair must
record the rule and the original text.

## 12. Non-goals

- Spelling correction or grammar.
- Transliteration to/from Latin script.
- Legacy Preeti/Kantipur glyph maps (these belong to `cidmap/` and
  `redbook_parser/legacy.py`).
- Font-specific shaping rules.
- Vedic accents and rare script extensions.
- Changing any existing parser.

## 13. Corpus schema

`tests/devanagari/cases.jsonl` is one JSON object per line. Every line has:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique, stable identifier. |
| `category` | string | Tag from the list below. |
| `rule` | string | `<operation>.<detail>`; `operation` is `normalize`, `canonical_key`, `segment`, `invalid`, or `repair`. |
| `input` | string | Raw text. |
| `expected` | string | Expected result, non-empty. Semantics depend on `rule` (§13.1). |
| `source` | string | Provenance: `path:line`, `cidmap/data/cid_mappings.json:line`, or an issue/spec reference. |
| `notes` | string | Why the case matters and what a reader should notice. |

Categories:

```text
order  reph  matra  nukta  zwj-zwnj  conjunct
invalid  digits-punctuation  valid-word  ocr-snippet
```

### 13.1 Expected values by operation

| `rule` prefix | `expected` is |
|---|---|
| `normalize.` | The exact output of `normalize(input)`. |
| `canonical_key.` | The exact output of `canonical_key(input)`. |
| `segment.` | The aksaras of `input` joined with `|`. |
| `invalid.` | The intended valid spelling for a human reader. `validate(input)` must report at least one issue; no automatic repair is implied. |
| `repair.` | The intended valid spelling. `validate(input)` must report no structural issue; the change belongs to the deferred repair stage. |

`canonical_key.joiners-dropped` cases are evaluated with `drop_joiners=True`.
All other `canonical_key.` cases use the default `drop_joiners=False`.

### 13.2 Adding a case

1. Pick the smallest input that demonstrates the rule.
2. Prefer a real `datasets/translations/**-ocr.txt` line or a `cidmap` entry,
   and cite `path:line`.
3. State the exact code points in `notes` when the case is invisible (ZWJ,
   ZWNJ, nukta ordering).
4. Keep `expected` non-empty.
5. Run `pytest tests/devanagari -q`.

## 14. References

- Unicode Standard, chapter 12 (South and Central Asia), Devanagari.
- Unicode Standard Annex #15: Unicode Normalization Forms.
- Unicode Standard Annex #29: Unicode Text Segmentation.
- `docs/architecture.md` for the OCR/CID/table extraction split.
- `cidmap/data/cid_mappings.json` for real CID→Devanagari fragments.
