"""Pipeline orchestrator — the ONE canonical execution path for DKS.

Orchestrates: extract → resolve → commit → index for ingestion,
and embed → search → filter for queries.

The commitment boundary runs through this module: extraction and resolution
are non-deterministic, but once committed to the KnowledgeStore, everything
becomes deterministic data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .core import (
    ClaimCore,
    KnowledgeStore,
    MergeResult,
    Provenance,
    TransactionTime,
    ValidTime,
)
from .extract import ExtractionResult, Extractor
from .index import EmbeddingBackend, SearchIndex, SearchResult
from .resolve import CascadingResolver, ResolutionDecision, Resolver


class Pipeline:
    """End-to-end orchestrator for DKS operations.

    This is the canonical execution path. All operations flow through here:
    - ingest(): text → claims → committed revisions
    - query(): question → search → temporal-filtered results
    - merge(): combine two pipelines deterministically
    """

    def __init__(
        self,
        store: KnowledgeStore | None = None,
        extractor: Extractor | None = None,
        resolver: Resolver | None = None,
        embedding_backend: EmbeddingBackend | None = None,
    ) -> None:
        self.store = store or KnowledgeStore()
        self._extractor = extractor
        self._resolver = resolver
        self._index: SearchIndex | None = None
        if embedding_backend is not None:
            self._index = SearchIndex(self.store, embedding_backend)

    def ingest(
        self,
        text: str,
        *,
        valid_time: ValidTime,
        transaction_time: TransactionTime,
        provenance: Provenance | None = None,
        claim_types: list[str] | None = None,
        confidence_bp: int = 5000,
    ) -> list[str]:
        """Extract claims from text, resolve entities, commit to store, index.

        This is the main ingestion path. It crosses the commitment boundary:
        non-deterministic extraction → deterministic storage.

        Args:
            text: Unstructured input text.
            valid_time: When the facts in the text were true.
            transaction_time: When this ingestion is happening.
            provenance: Source provenance (auto-generated if None).
            claim_types: Optional filter for extraction.
            confidence_bp: Default confidence for extracted claims (0-10000).

        Returns:
            List of revision_ids for all committed revisions.
        """
        if self._extractor is None:
            raise ValueError("No extractor configured. Set extractor in Pipeline init.")

        # Phase 1: Extract (non-deterministic)
        extraction = self._extractor.extract(text, claim_types=claim_types)

        # Phase 2: Resolve entities (non-deterministic)
        resolved_claims = []
        for claim in extraction.claims:
            if self._resolver is not None:
                resolved_slots = {}
                for role, value in claim.slots.items():
                    decision = self._resolver.resolve(value)
                    if decision is not None:
                        resolved_slots[role] = decision.resolved_entity_id
                    else:
                        resolved_slots[role] = value
                resolved_claim = ClaimCore(
                    claim_type=claim.claim_type,
                    slots=resolved_slots,
                )
            else:
                resolved_claim = claim
            resolved_claims.append(resolved_claim)

        # Phase 3: Commit to store (COMMITMENT BOUNDARY — deterministic from here)
        revision_ids: list[str] = []
        prov = provenance or Provenance(source="pipeline:ingest")

        for i, claim in enumerate(resolved_claims):
            extraction_prov = extraction.provenance[i] if i < len(extraction.provenance) else prov
            revision = self.store.assert_revision(
                core=claim,
                assertion=text[:500],
                valid_time=valid_time,
                transaction_time=transaction_time,
                provenance=extraction_prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            # Phase 4: Index for search
            if self._index is not None:
                self._index.add(revision.revision_id, text)

        return revision_ids

    def query(
        self,
        question: str,
        *,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
        k: int = 5,
    ) -> list[SearchResult]:
        """Search for relevant claims with temporal filtering.

        Args:
            question: Natural language query.
            valid_at: When the facts should be true (for temporal filter).
            tx_id: Transaction time cutoff (for temporal filter).
            k: Maximum number of results.

        Returns:
            List of SearchResult ordered by relevance.
        """
        if self._index is None:
            raise ValueError("No embedding backend configured. Set embedding_backend in Pipeline init.")

        return self._index.search(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    def query_exact(
        self,
        core_id: str,
        *,
        valid_at: datetime,
        tx_id: int,
    ):
        """Direct query by core_id with bitemporal coordinates.

        This bypasses search and goes straight to the deterministic core.
        """
        return self.store.query_as_of(
            core_id,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    def merge(self, other: "Pipeline") -> MergeResult:
        """Merge another pipeline's store into this one.

        Note: Only the KnowledgeStore data is merged. The search index
        is NOT automatically rebuilt — call rebuild_index() after merge
        if search is needed.

        Returns:
            MergeResult with merged store and any conflicts.
        """
        result = self.store.merge(other.store)
        self.store = result.merged
        if self._index is not None:
            self._index._store = self.store
        return result

    def rebuild_index(self) -> int:
        """Rebuild the search index from all revisions in the store.

        Returns:
            Number of revisions indexed.
        """
        if self._index is None:
            raise ValueError("No embedding backend configured.")

        items = []
        for revision_id, revision in self.store.revisions.items():
            items.append((revision_id, revision.assertion))
        self._index.add_batch(items)
        return len(items)
