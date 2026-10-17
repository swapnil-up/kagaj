"""Preeti (legacy ASCII font) → Devanagari Unicode decoder.

DoFE PDFs published before the modern template embed no Unicode CMap; the text
layer is Preeti, a legacy font that stores Devanagari glyphs at ASCII code
points (so ``k'?if`` extracts instead of पुरुष). The mapping is deterministic —
no OCR — and shared by every archive-backfill layout family.

Character map and post-rules are the canonical Preeti table from
https://github.com/Shuvayatra/preeti (``preeti.js``), which itself follows the
standard Preeti keyboard layout. Digits are clean ASCII in the PDFs, so numeral
code points that Preeti reuses (``!``→१, ``@``→२ …) are left mapped as the
table specifies; call :func:`ascii_digits` when you need the raw digits back.

    from migration_parser.preeti import decode
    decode("g]kfn ;/sf/")        # -> "नेपाल सरकार"
"""

from __future__ import annotations

import re

CHAR_MAP: dict[str, str] = {
    "\u00f7": "/",
    "v": "\u0916",
    "r": "\u091a",
    '"': "\u0942",
    "~": "\u091e\u094d",
    "z": "\u0936",
    "\u00e7": "\u0950",
    "f": "\u093e",
    "b": "\u0926",
    "n": "\u0932",
    "j": "\u0935",
    "\u00d7": "\u00d7",
    "V": "\u0916\u094d",
    "R": "\u091a\u094d",
    "\u00df": "\u0926\u094d\u092e",
    "^": "\u096c",
    "\u00db": "!",
    "Z": "\u0936\u094d",
    "F": "\u0901",
    "B": "\u0926\u094d\u092f",
    "N": "\u0932\u094d",
    "\u00cb": "\u0919\u094d\u0917",
    "J": "\u0935\u094d",
    "6": "\u091f",
    "2": "\u0926\u094d\u0926",
    "\u00bf": "\u0930\u0942",
    ">": "\u0936\u094d\u0930",
    ":": "\u0938\u094d",
    "\u00a7": "\u091f\u094d\u091f",
    "&": "\u096d",
    "\u00a3": "\u0918\u094d",
    "\u2022": "\u0921\u094d\u0921",
    ".": "\u0964",
    "\u00ab": "\u094d\u0930",
    "*": "\u096e",
    "\u201e": "\u0927\u094d\u0930",
    "w": "\u0927",
    "s": "\u0915",
    "g": "\u0928",
    "\u00e6": "\u201c",
    "c": "\u0905",
    "o": "\u092f",
    "k": "\u092a",
    "W": "\u0927\u094d",
    "\u00d6": "=",
    "S": "\u0915\u094d",
    "\u00d2": "\u00a8",
    "_": ")",
    "[": "\u0943",
    "\u00da": "\u2019",
    "G": "\u0928\u094d",
    "\u02c6": "\u092b\u094d",
    "C": "\u090b",
    "O": "\u0907",
    "\u00ce": "\u0919\u094d\u0916",
    "K": "\u092a\u094d",
    "7": "\u0920",
    "\u00b6": "\u0920\u094d\u0920",
    "3": "\u0918",
    "9": "\u0922",
    "?": "\u0930\u0941",
    ";": "\u0938",
    "'": "\u0941",
    "#": "\u0969",
    "\u00a2": "\u0926\u094d\u0918",
    "/": "\u0930",
    "+": "\u0902",
    "\u00aa": "\u0919",
    "t": "\u0924",
    "p": "\u0909",
    "|": "\u094d\u0930",
    "x": "\u0939",
    "\u00e5": "\u0926\u094d\u0935",
    "d": "\u092e",
    "`": "\u091e",
    "l": "\u093f",
    "h": "\u091c",
    "T": "\u0924\u094d",
    "P": "\u090f",
    "\u00dd": "\u091f\u094d\u0920",
    "\\": "\u094d",
    "\u00d9": ";",
    "X": "\u0939\u094d",
    "\u00c5": "\u0939\u0943",
    "D": "\u092e\u094d",
    "@": "\u0968",
    "\u00cd": "\u0919\u094d\u0915",
    "L": "\u0940",
    "H": "\u091c\u094d",
    "4": "\u0926\u094d\u0927",
    "\u00b1": "+",
    "0": "\u0923\u094d",
    "<": "?",
    "8": "\u0921",
    "\u00a5": "\u0930\u094d\u200d",
    "$": "\u096a",
    "\u00a1": "\u091c\u094d\u091e\u094d",
    ",": ",",
    "\u00a9": "\u0930",
    "(": "\u096f",
    "\u2018": "\u0945",
    "u": "\u0917",
    "q": "\u0924\u094d\u0930",
    "}": "\u0948",
    "y": "\u0925",
    "e": "\u092d",
    "a": "\u092c",
    "i": "\u0937\u094d",
    "\u2030": "\u091d\u094d",
    "U": "\u0917\u094d",
    "Q": "\u0924\u094d\u0924",
    "]": "\u0947",
    "\u02dc": "\u093d",
    "Y": "\u0925\u094d",
    "\u00d8": "\u094d\u092f",
    "E": "\u092d\u094d",
    "A": "\u092c\u094d",
    "M": "\u0903",
    "\u00cc": "\u0928\u094d\u0928",
    "I": "\u0915\u094d\u0937\u094d",
    "5": "\u091b",
    "\u00b4": "\u091d",
    "1": "\u091c\u094d\u091e",
    "\u00b0": "\u0919\u094d\u0922",
    "=": ".",
    "\u00c6": "\u201d",
    "\u2039": "\u0919\u094d\u0918",
    "%": "\u096b",
    "\u00a4": "\u091d\u094d",
    "!": "\u0967",
    "-": "(",
    "\u203a": "\u0926\u094d\u0930",
    ")": "\u0966",
    "\u2026": "\u2018",
    "\u00dc": "%",
}

POST_RULES: list[tuple[str, str]] = [
    ("\u094d\u093e", ""),
    ("(\u0924\u094d\u0930|\u0924\u094d\u0924)([^\u0909\u092d\u092a]+?)m", "$1m$2"),
    ("\u0924\u094d\u0930m", "\u0915\u094d\u0930"),
    ("\u0924\u094d\u0924m", "\u0915\u094d\u0924"),
    ("([^\u0909\u092d\u092a]+?)m", "m$1"),
    ("\u0909m", "\u090a"),
    ("\u092dm", "\u091d"),
    ("\u092am", "\u092b"),
    ("\u0907{", "\u0908"),
    ("\u093f((.\u094d)*[^\u094d])", "$1\u093f"),
    ("(.[\u093e\u093f\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c\u0902\u0903\u0901]*?){", "{$1"),
    ("((.\u094d)*){", "{$1"),
    ("{", "\u0930\u094d"),
    ("([\u093e\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c\u0902\u0903\u0901]+?)(\u094d(.\u094d)*[^\u094d])", "$2$1"),
    ("\u094d([\u093e\u093f\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c\u0902\u0903\u0901]+?)((.\u094d)*[^\u094d])", "\u094d$2$1"),
    ("([\u0902\u0901])([\u093e\u093f\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c\u0903]*)", "$2$1"),
    ("\u0901\u0901", "\u0901"),
    ("\u0902\u0902", "\u0902"),
    ("\u0947\u0947", "\u0947"),
    ("\u0948\u0948", "\u0948"),
    ("\u0941\u0941", "\u0941"),
    ("\u0942\u0942", "\u0942"),
    ("^\u0903", ":"),
    ("\u091f\u0943", "\u091f\u094d\u091f"),
    ("\u0947\u093e", "\u093e\u0947"),
    ("\u0948\u093e", "\u093e\u0948"),
    ("\u0905\u093e\u0947", "\u0913"),
    ("\u0905\u093e\u0948", "\u0914"),
    ("\u0905\u093e", "\u0906"),
    ("\u090f\u0947", "\u0910"),
    ("\u093e\u0947", "\u094b"),
    ("\u093e\u0948", "\u094c"),
]


def _compile(rules: list[tuple[str, str]]) -> list[tuple["re.Pattern[str]", str]]:
    """Compile JS-style rules (``$1`` backrefs) as Python ``re`` rules."""
    out = []
    for pat, repl in rules:
        py_repl = re.sub(r"\$(\d)", r"\\\1", repl)
        out.append((re.compile(pat), py_repl))
    return out


_POST_COMPILED = _compile(POST_RULES)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_DIGIT_MAP = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f",
                           "0123456789")
# Preeti reuses ASCII digits only for the punctuation range; the table maps
# shifted numerals (``!``->१ … ``(``->९) but leaves ``0``-``9`` as literal
# ASCII (they map to consonant half-forms). Detect the recovered Devanagari
# digits instead, and also accept raw ASCII digits.


def decode(text: str) -> str:
    """Decode Preeti-encoded ASCII into Devanagari Unicode."""
    if not text:
        return text
    mapped = "".join(CHAR_MAP.get(ch, ch) for ch in text)
    for pat, repl in _POST_COMPILED:
        mapped = pat.sub(repl, mapped)
    return mapped


def ascii_digits(text: str) -> str:
    """Devangari digits → ASCII (for numeric fields; leaves other text alone)."""
    return text.translate(_DIGIT_MAP)


def has_devanagari(text: str) -> bool:
    """True if ``text`` already contains Devanagari (i.e. is not Preeti)."""
    return bool(_DEVANAGARI.search(text or ""))
