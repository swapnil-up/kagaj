"""Small, dependency-free metrics and scorecards for extraction tests.

These helpers are intentionally generic: OCR/text jobs use character and word
error rates, while structured jobs use field accuracy over keyed rows. A
:class:`Scorecard` is a plain data object so it can be printed, asserted on in
tests, or written into a build report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


class ScoreError(AssertionError):
    """Raised when a scorecard falls below a requested threshold."""


@dataclass
class Scorecard:
    """Named metrics plus diagnostic details."""

    name: str
    metrics: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def add(self, metric: str, value: float) -> "Scorecard":
        self.metrics[metric] = float(value)
        return self

    def as_dict(self) -> dict:
        return {"name": self.name, "metrics": self.metrics,
                "details": self.details}

    def summary(self) -> str:
        if not self.metrics:
            return f"{self.name}: no metrics"
        parts = ", ".join(f"{key}={value:.4g}"
                          for key, value in sorted(self.metrics.items()))
        return f"{self.name}: {parts}"

    def require(self, **minimums: float) -> "Scorecard":
        """Raise :class:`ScoreError` when a metric is below its minimum."""
        for metric, minimum in minimums.items():
            value = self.metrics.get(metric)
            if value is None:
                raise ScoreError(f"{self.name}: metric {metric!r} missing")
            if value < minimum:
                raise ScoreError(
                    f"{self.name}: {metric}={value:.4g} < {minimum:.4g}")
        return self


def exact_match(reference: str, hypothesis: str, *,
                normalize: Callable[[str], str] | None = None) -> bool:
    """True when two strings are equal, optionally after normalization."""
    if normalize is not None:
        reference, hypothesis = normalize(reference), normalize(hypothesis)
    return reference == hypothesis


def accuracy(correct: int, total: int) -> float:
    """``correct / total`` with an empty set counted as perfect."""
    return 1.0 if total == 0 else correct / total


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Return precision, recall, and F1 from integer counts."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"precision": precision, "recall": recall, "f1": f1}


def levenshtein(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    """Edit distance with insertion, deletion, and substitution."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for i, ref_item in enumerate(reference, 1):
        current = [i]
        for j, hyp_item in enumerate(hypothesis, 1):
            cost = 0 if ref_item == hyp_item else 1
            current.append(min(current[-1] + 1,
                               previous[j] + 1,
                               previous[j - 1] + cost))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str, *,
                         normalize: Callable[[str], str] | None = None) -> float:
    """Levenshtein distance divided by reference length."""
    if normalize is not None:
        reference, hypothesis = normalize(reference), normalize(hypothesis)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


def word_error_rate(reference: str, hypothesis: str, *,
                    normalize: Callable[[str], str] | None = None) -> float:
    """Word-level edit distance divided by reference word count."""
    if normalize is not None:
        reference, hypothesis = normalize(reference), normalize(hypothesis)
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return levenshtein(ref_words, hyp_words) / len(ref_words)


def score_rows(expected: Iterable[Mapping[str, Any]],
               actual: Iterable[Mapping[str, Any]], *,
               key: str | Callable[[Mapping], Any],
               fields: Sequence[str],
               normalize: Callable[[Any], Any] | None = None,
               name: str = "rows") -> Scorecard:
    """Compare keyed rows field by field and return a :class:`Scorecard`."""
    key_fn = key if callable(key) else (lambda row: row.get(key))
    expected_rows = _index(expected, key_fn, "expected")
    actual_rows = _index(actual, key_fn, "actual")

    expected_keys = set(expected_rows)
    actual_keys = set(actual_rows)
    matched_keys = expected_keys & actual_keys
    missing = sorted(expected_keys - actual_keys, key=_sort_key)
    extra = sorted(actual_keys - expected_keys, key=_sort_key)

    per_field = {field: 0 for field in fields}
    row_matches = 0
    for row_key in matched_keys:
        expected_row = expected_rows[row_key]
        actual_row = actual_rows[row_key]
        all_equal = True
        for field in fields:
            expected_value = _normalize(expected_row.get(field), normalize)
            actual_value = _normalize(actual_row.get(field), normalize)
            if expected_value == actual_value:
                per_field[field] += 1
            else:
                all_equal = False
        row_matches += int(all_equal)

    total_fields = len(matched_keys) * len(fields)
    field_hits = sum(per_field.values())
    metrics = {
        "coverage": accuracy(len(matched_keys), len(expected_keys)),
        "row_accuracy": accuracy(row_matches, len(expected_keys)),
        "field_accuracy": accuracy(field_hits, total_fields),
    }
    for field, hits in per_field.items():
        metrics[f"field_accuracy.{field}"] = accuracy(hits, len(matched_keys))

    details = {
        "expected": len(expected_keys),
        "actual": len(actual_keys),
        "matched": len(matched_keys),
        "missing": missing,
        "extra": extra,
        "per_field": per_field,
    }
    return Scorecard(name=name, metrics=metrics, details=details)


def _index(rows: Iterable[Mapping[str, Any]], key_fn: Callable,
           label: str) -> dict:
    indexed: dict = {}
    for row in rows:
        row_key = key_fn(row)
        if row_key in indexed:
            raise ValueError(f"duplicate {label} key: {row_key!r}")
        indexed[row_key] = row
    return indexed


def _normalize(value: Any, normalize: Callable[[Any], Any] | None) -> Any:
    if normalize is None:
        return value
    return normalize(value)


def _sort_key(value: Any) -> str:
    return str(value)
