"""Embedding-based semantic search with temporal awareness.

Results are filtered through KnowledgeStore.query_as_of() to respect
bitemporal visibility. This ensures search results honor the same
temporal guarantees as direct queries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable, Optional

from .core import KnowledgeStore


@dataclass(frozen=True)
class SearchResult:
    """A single search result with score and temporal context."""
    core_id: str
    revision_id: str
    score: float
    text: str


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Protocol for embedding computation backends.

    Default recommendation: Qwen3-Embedding-0.6B (from model registry)
    for fast iteration. 600M params, 32-1024 dims, 100+ languages.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (same length as texts).
        """
        ...

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        ...


class SearchIndex:
    """Temporal-aware semantic search over a KnowledgeStore.

    Combines embedding similarity with bitemporal filtering to return
    only results that are visible at the queried point in time.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        backend: EmbeddingBackend,
    ) -> None:
        self._store = store
        self._backend = backend
        self._vectors: dict[str, list[float]] = {}  # revision_id -> vector
        self._texts: dict[str, str] = {}  # revision_id -> text

    def add(self, revision_id: str, text: str) -> None:
        """Index a revision's text for search.

        Args:
            revision_id: The revision to index.
            text: The text content to embed and index.
        """
        vectors = self._backend.embed([text])
        self._vectors[revision_id] = vectors[0]
        self._texts[revision_id] = text

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        """Index multiple revisions at once.

        Args:
            items: List of (revision_id, text) pairs.
        """
        if not items:
            return
        revision_ids, texts = zip(*items)
        vectors = self._backend.embed(list(texts))
        for rid, vec, txt in zip(revision_ids, vectors, texts):
            self._vectors[rid] = vec
            self._texts[rid] = txt

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search for similar content with optional temporal filtering.

        Args:
            query: Query text to search for.
            k: Maximum number of results to return.
            valid_at: If provided with tx_id, filter by bitemporal visibility.
            tx_id: If provided with valid_at, filter by bitemporal visibility.

        Returns:
            List of SearchResult ordered by descending score.
        """
        if not self._vectors:
            return []

        query_vec = self._backend.embed([query])[0]

        # Score all indexed revisions
        scored: list[tuple[float, str]] = []
        for revision_id, vec in self._vectors.items():
            score = _cosine_similarity(query_vec, vec)
            scored.append((score, revision_id))

        # Sort by score descending
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Filter by temporal visibility if requested
        results: list[SearchResult] = []
        for score, revision_id in scored:
            if len(results) >= k:
                break

            revision = self._store.revisions.get(revision_id)
            if revision is None:
                continue

            # Temporal filter: check if this revision is the winner at the query point
            if valid_at is not None and tx_id is not None:
                winner = self._store.query_as_of(
                    revision.core_id,
                    valid_at=valid_at,
                    tx_id=tx_id,
                )
                if winner is None or winner.revision_id != revision_id:
                    continue

            results.append(SearchResult(
                core_id=revision.core_id,
                revision_id=revision_id,
                score=score,
                text=self._texts.get(revision_id, ""),
            ))

        return results

    @property
    def size(self) -> int:
        """Number of indexed vectors."""
        return len(self._vectors)


class NumpyIndex:
    """Zero-dependency brute-force cosine similarity index.

    Good for small stores (< 100K vectors). For larger stores,
    swap in a FAISS or Annoy backend implementing EmbeddingBackend.
    """

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension
        self._vectors: dict[str, list[float]] = {}
        self._texts: dict[str, str] = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Simple bag-of-characters embedding (for testing only).

        For real use, replace with a proper embedding model backend.
        """
        vectors = []
        for text in texts:
            vec = [0.0] * self._dimension
            for i, ch in enumerate(text.lower()):
                vec[ord(ch) % self._dimension] += 1.0
            # L2 normalize
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vec = [x / norm for x in vec]
            vectors.append(vec)
        return vectors

    def search_vectors(
        self,
        query: list[float],
        vectors: dict[str, list[float]],
        k: int,
    ) -> list[tuple[str, float]]:
        """Brute-force cosine similarity search."""
        scored = []
        for key, vec in vectors.items():
            score = _cosine_similarity(query, vec)
            scored.append((key, score))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
