"""Nepali lexicon loading and scoring for shape-run inference."""

from __future__ import annotations

import gzip
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from kagaj_core.devanagari import canonical_key, validate

_PACKAGE = Path(__file__).resolve().parent
_REPO = _PACKAGE.parent
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _clean(words):
    seen = set()
    out = []
    for word in words:
        word = (word or "").strip()
        if not word or not _DEVANAGARI_RE.search(word):
            continue
        key = canonical_key(word, drop_joiners=True)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out


def _read_sqlite(path: Path):
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute("select value from word").fetchall()
    return [row[0] for row in rows if row and row[0]]


def _read_text(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [
            line.strip() for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        ]


def _default_path() -> Path | None:
    local = _REPO / "dictionary-data" / "nep_dict.sqlite3"
    if local.exists():
        return local
    committed = _PACKAGE / "data" / "nepali_lexicon.txt.gz"
    if committed.exists():
        return committed
    pairs = _REPO / "dictionary" / "eng_nep_pairs.txt"
    if pairs.exists():
        return pairs
    return None


class NepaliLexicon:
    """A deduplicated Devanagari word list with cheap surface scoring."""

    def __init__(self, words):
        self.words = tuple(_clean(words))
        self._keys = frozenset(
            canonical_key(word, drop_joiners=True) for word in self.words
        )

    @classmethod
    def load(cls, path=None) -> "NepaliLexicon":
        path = Path(path) if path is not None else _default_path()
        if path is None or not path.exists():
            return cls(())
        if _is_sqlite(path):
            return cls(_read_sqlite(path))
        return cls(_read_text(path))

    def __len__(self):
        return len(self.words)

    def __contains__(self, word):
        return canonical_key(word, drop_joiners=True) in self._keys

    def score(self, word):
        key = canonical_key(word, drop_joiners=True)
        if not key:
            return 0.0
        if key in self._keys:
            score = 1.0
        else:
            score = 0.0
            for candidate in self._keys:
                if candidate.startswith(key) or key.startswith(candidate):
                    score = max(score, 0.55)
                elif candidate.endswith(key) or key.endswith(candidate):
                    score = max(score, 0.45)
                elif len(key) >= 2 and key in candidate:
                    score = max(score, 0.3)
        if not validate(word):
            return score
        return score * 0.5


class LexiconIndex:
    """Lexicon entries grouped by shaped glyph count."""

    def __init__(self, lexicon: NepaliLexicon, shaper, max_words=None):
        self.lexicon = lexicon
        self.shaper = shaper
        self._shaped: dict[str, tuple] = {}
        self._by_length: dict[int, list[tuple[str, tuple]]] = defaultdict(list)
        words = lexicon.words[:max_words] if max_words else lexicon.words
        for word in words:
            shaped = self.shape_for(word)
            if shaped:
                self._by_length[len(shaped)].append((word, shaped))

    def shape_for(self, word):
        if word not in self._shaped:
            self._shaped[word] = self.shaper.shape_cached(word)
        return self._shaped[word]

    def candidates_by_length(self, length):
        return list(self._by_length.get(length, ()))
