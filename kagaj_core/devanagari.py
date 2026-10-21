"""Lossless Devanagari normalization, matching keys, and validation.

The policy is documented in ``docs/devanagari.md``. This module is stdlib-only
and knows nothing about OCR, PDFs, legacy fonts, or spelling correction.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NUKTA = "\u093c"
VIRAMA = "\u094d"
ZWJ = "\u200d"
ZWNJ = "\u200c"
JOINERS = frozenset({ZWJ, ZWNJ})

NUKTA_BASES = frozenset("कखगजडढफय")

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

SPLIT_MATRAS = frozenset({
    ("\u0947", "\u093e"),
    ("\u093e", "\u0947"),
    ("\u0948", "\u093e"),
    ("\u093e", "\u0948"),
})

_SPLIT_MATRA_RE = re.compile(r"\u0947\u093e|\u093e\u0947|\u0948\u093e|\u093e\u0948")
_DANDA_BEFORE_RE = re.compile(r"\s+([।॥])")
_DANDA_AFTER_RE = re.compile(r"([।॥])(?=[\u0900-\u097FA-Za-z0-9])")


@dataclass(frozen=True)
class Issue:
    """A non-mutating validation finding with a code-point span."""

    code: str
    message: str
    start: int
    end: int


def normalize(text: str) -> str:
    """Return the lossless storage form of *text* (NFC only).

    NFC can rewrite equivalent code points (for example ``U+0958`` becomes
    ``U+0915 U+093C``) but this function never removes joiners, folds digits,
    repairs OCR, or reorders visual text.
    """
    if not isinstance(text, str):
        raise TypeError("normalize() expects str")
    return unicodedata.normalize("NFC", text)


def canonical_key(text: str, *, drop_joiners: bool = False) -> str:
    """Return a lossy key for comparing Devanagari strings.

    The key applies, in order: NFC, optional joiner removal, Devanagari-to-ASCII
    digit folding, split two-part matra folding, whitespace collapsing, and
    danda spacing normalization. It never reorders visual text or repairs
    spelling. See ``docs/devanagari.md``.
    """
    if not isinstance(text, str):
        raise TypeError("canonical_key() expects str")

    key = normalize(text)
    if drop_joiners:
        key = key.replace(ZWJ, "").replace(ZWNJ, "")
    key = key.translate(DEVANAGARI_DIGITS)
    key = _SPLIT_MATRA_RE.sub(_fold_split_matra, key)
    key = " ".join(key.split())
    key = _DANDA_BEFORE_RE.sub(r"\1", key)
    key = _DANDA_AFTER_RE.sub(r"\1 ", key)
    return key


def validate(text: str) -> list[Issue]:
    """Lint structurally invalid Devanagari sequences without mutating text."""
    if not isinstance(text, str):
        raise TypeError("validate() expects str")

    issues: list[Issue] = []
    for index, char in enumerate(text):
        previous = text[index - 1] if index else ""
        span = (index, index + 1)

        if _is_matra(char):
            if index == 0:
                issues.append(Issue("leading-matra", "matra at start of text", *span))
            elif _is_matra(previous):
                if (previous, char) not in SPLIT_MATRAS:
                    issues.append(
                        Issue("matra-on-matra", "matra follows another matra", *span)
                    )
            elif _is_independent_vowel(previous):
                issues.append(
                    Issue("matra-on-vowel", "dependent matra follows an independent vowel", *span)
                )
            elif not _has_vowel_base(text, index):
                issues.append(
                    Issue("matra-position", "matra has no consonant base", *span)
                )
        elif char == VIRAMA:
            if index == 0:
                issues.append(Issue("leading-virama", "virama at start of text", *span))
            elif previous == VIRAMA:
                issues.append(Issue("double-virama", "two viramas in one cluster", *span))
            elif _is_independent_vowel(previous):
                issues.append(
                    Issue("virama-on-vowel", "virama follows an independent vowel", *span)
                )
            elif not _has_vowel_base(text, index):
                issues.append(
                    Issue("virama-position", "virama has no consonant base", *span)
                )
        elif char == NUKTA:
            if index == 0:
                issues.append(Issue("leading-nukta", "nukta at start of text", *span))
            elif previous == NUKTA:
                issues.append(Issue("double-nukta", "consonant has two nuktas", *span))
            elif previous == VIRAMA:
                issues.append(
                    Issue("nukta-after-virama", "nukta follows a virama", *span)
                )
            elif _is_matra(previous):
                issues.append(
                    Issue("nukta-after-matra", "nukta follows a matra", *span)
                )
            elif _is_independent_vowel(previous):
                issues.append(
                    Issue("nukta-on-vowel", "nukta follows an independent vowel", *span)
                )
            elif _is_consonant(previous):
                if previous not in NUKTA_BASES:
                    issues.append(
                        Issue(
                            "nukta-invalid-base",
                            f"nukta is not used on {previous!r}",
                            *span,
                        )
                    )
            else:
                issues.append(
                    Issue("nukta-position", "nukta has no consonant base", *span)
                )
        elif char in JOINERS:
            if index == 0 or previous != VIRAMA:
                issues.append(
                    Issue("joiner-position", "joiner is only valid after a virama", *span)
                )
        elif _is_sign(char):
            if index == 0 or previous.isspace() or previous in "।॥" or previous in JOINERS:
                issues.append(
                    Issue("leading-mark", "sign has no preceding aksara", *span)
                )
        elif _is_disallowed_control(char):
            issues.append(
                Issue("control-character", "control character in text", *span)
            )

    return issues


def segment_aksaras(text: str) -> list[str]:
    """Split *text* into orthographic syllables, preserving every character."""
    if not isinstance(text, str):
        raise TypeError("segment_aksaras() expects str")

    segments: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if _is_consonant(char):
            end = _consume_consonant_cluster(text, index)
            end = _consume_matra(text, end)
            end = _consume_signs(text, end)
            segments.append(text[index:end])
            index = end
        elif _is_independent_vowel(char):
            end = _consume_signs(text, index + 1)
            segments.append(text[index:end])
            index = end
        elif char.isspace():
            end = index + 1
            while end < length and text[end].isspace():
                end += 1
            segments.append(text[index:end])
            index = end
        elif char.isdigit():
            end = index + 1
            while end < length and text[end].isdigit():
                end += 1
            segments.append(text[index:end])
            index = end
        else:
            segments.append(char)
            index += 1

    return segments


def _fold_split_matra(match: re.Match) -> str:
    return "\u094b" if "\u0947" in match.group() else "\u094c"


def _is_consonant(char: str) -> bool:
    if len(char) != 1:
        return False
    codepoint = ord(char)
    return (
        0x0915 <= codepoint <= 0x0939
        or 0x0958 <= codepoint <= 0x095F
        or 0x0978 <= codepoint <= 0x097F
    )


def _is_independent_vowel(char: str) -> bool:
    if len(char) != 1:
        return False
    codepoint = ord(char)
    return (
        0x0905 <= codepoint <= 0x0914
        or 0x0960 <= codepoint <= 0x0961
        or 0x0972 <= codepoint <= 0x0977
    )


def _is_matra(char: str) -> bool:
    if len(char) != 1:
        return False
    codepoint = ord(char)
    return (
        0x093A <= codepoint <= 0x093B
        or 0x093E <= codepoint <= 0x094C
        or 0x094E <= codepoint <= 0x094F
        or 0x0955 <= codepoint <= 0x0957
        or 0x0962 <= codepoint <= 0x0963
    )


def _is_sign(char: str) -> bool:
    return len(char) == 1 and 0x0900 <= ord(char) <= 0x0903


def _is_disallowed_control(char: str) -> bool:
    return (
        unicodedata.category(char) in {"Cc", "Cf", "Cs"}
        and not char.isspace()
        and char not in JOINERS
    )


def _has_vowel_base(text: str, index: int) -> bool:
    if index == 0:
        return False
    previous = text[index - 1]
    if _is_consonant(previous):
        return True
    if previous == NUKTA and index >= 2 and _is_consonant(text[index - 2]):
        return True
    return False


def _consume_consonant_cluster(text: str, index: int) -> int:
    length = len(text)
    end = index + 1

    if end < length and text[end] == NUKTA:
        end += 1

    while end < length and text[end] == VIRAMA:
        after_virama = end + 1
        if after_virama < length and text[after_virama] == ZWJ:
            end = after_virama + 1
            if end < length and _is_consonant(text[end]):
                end += 1
                if end < length and text[end] == NUKTA:
                    end += 1
                continue
            break
        if after_virama < length and text[after_virama] == ZWNJ:
            end = after_virama + 1
            break
        if after_virama < length and _is_consonant(text[after_virama]):
            end = after_virama + 1
            if end < length and text[end] == NUKTA:
                end += 1
            continue
        end = after_virama
        break

    return end


def _consume_matra(text: str, index: int) -> int:
    length = len(text)
    if index >= length or not _is_matra(text[index]):
        return index

    first = text[index]
    end = index + 1
    if (
        end < length
        and _is_matra(text[end])
        and (first, text[end]) in SPLIT_MATRAS
    ):
        end += 1
    return end


def _consume_signs(text: str, index: int) -> int:
    length = len(text)
    while index < length and _is_sign(text[index]):
        index += 1
    return index
