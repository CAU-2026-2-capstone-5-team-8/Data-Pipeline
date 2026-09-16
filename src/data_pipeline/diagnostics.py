"""Structured diagnostics for provider normalization at experiment scale."""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class NormalizationDiagnostics:
    """Count candidate outcomes without changing the canonical output contract."""

    provider: str
    candidate_count: int = 0
    normalized_candidate_count: int = 0
    duplicate_candidate_count: int = 0
    edition_mismatch_count: int = 0
    normalization_failure_count: int = 0
    failure_counts: Counter[str] = field(default_factory=Counter)
    edition_mismatch_book_ids: set[str] = field(default_factory=set)

    def fail(self, reason: str) -> None:
        """Record one candidate-level normalization failure."""
        self.normalization_failure_count += 1
        self.failure_counts[reason] += 1

    def edition_mismatch(self, book_id: str) -> None:
        """Record one optional evidence item rejected for edition mismatch."""
        self.edition_mismatch_count += 1
        self.edition_mismatch_book_ids.add(book_id)
        self.failure_counts["edition_mismatch"] += 1
