"""Pipeline orchestrator — the ONE canonical execution path for DKS.

Orchestrates: extract → resolve → commit → index for ingestion,
and embed → search → filter for queries.

The commitment boundary runs through this module: extraction and resolution
are non-deterministic, but once committed to the KnowledgeStore, everything
becomes deterministic data.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from .core import (
    ClaimCore,
    KnowledgeStore,
    MergeResult,
    Provenance,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)
from .extract import ExtractionResult, Extractor, PDFExtractor, TextChunker
from .index import (
    CrossEncoderReranker,
    DenseSearchIndex,
    EmbeddingBackend,
    HybridSearchIndex,
    KnowledgeGraph,
    SearchIndex,
    SearchResult,
    TfidfSearchIndex,
)
from .resolve import CascadingResolver, ResolutionDecision, Resolver

import time as _time
import json as _json


@dataclass
class AuditEvent:
    """A single decision point in the retrieval pipeline."""
    stage: str         # e.g. "classify", "search", "expand", "diversify", "rerank"
    action: str        # What happened
    inputs: dict       # What went in
    outputs: dict      # What came out
    duration_ms: float # How long it took
    metadata: dict = field(default_factory=dict)  # Extra details


@dataclass
class AuditTrace:
    """Complete audit trail for a retrieval operation."""
    operation: str     # "query", "reason", "synthesize", "ask", etc.
    question: str
    strategy: str = ""
    events: list[AuditEvent] = field(default_factory=list)
    started_at: str = ""
    total_duration_ms: float = 0.0

    def add(self, stage: str, action: str, inputs: dict, outputs: dict,
            duration_ms: float, **metadata) -> None:
        self.events.append(AuditEvent(
            stage=stage, action=action, inputs=inputs,
            outputs=outputs, duration_ms=duration_ms, metadata=metadata,
        ))

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "operation": self.operation,
            "question": self.question,
            "strategy": self.strategy,
            "started_at": self.started_at,
            "total_duration_ms": self.total_duration_ms,
            "events": [
                {
                    "stage": e.stage,
                    "action": e.action,
                    "inputs": e.inputs,
                    "outputs": e.outputs,
                    "duration_ms": e.duration_ms,
                    "metadata": e.metadata,
                }
                for e in self.events
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return _json.dumps(self.to_dict(), indent=indent, default=str)


class Pipeline:
    """End-to-end orchestrator for DKS operations.

    This is the canonical execution path. All operations flow through here:
    - ingest(): text → claims → committed revisions
    - ingest_pdf(): PDF → text → chunks → committed revisions
    - ingest_directory(): directory of PDFs → batch ingestion
    - query(): question → search → temporal-filtered results
    - query_multi(): question → multi-document retrieval
    - merge(): combine two pipelines deterministically
    """

    def __init__(
        self,
        store: KnowledgeStore | None = None,
        extractor: Extractor | None = None,
        resolver: Resolver | None = None,
        embedding_backend: EmbeddingBackend | None = None,
        *,
        search_index: TfidfSearchIndex | DenseSearchIndex | HybridSearchIndex | SearchIndex | None = None,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self.store = store or KnowledgeStore()
        self._extractor = extractor
        self._resolver = resolver
        self._index: TfidfSearchIndex | DenseSearchIndex | HybridSearchIndex | SearchIndex | None = search_index
        if self._index is None and embedding_backend is not None:
            self._index = SearchIndex(self.store, embedding_backend)
        self._reranker = reranker
        self._tx_counter = 0
        # Track chunk siblings: source -> [revision_ids in order]
        self._chunk_siblings: dict[str, list[str]] = {}
        # Audit trail
        self._audit_enabled = False
        self._last_audit: AuditTrace | None = None

    # ---- Audit Trail ----

    def enable_audit(self, enabled: bool = True) -> None:
        """Enable or disable audit trail recording."""
        self._audit_enabled = enabled

    def last_audit(self) -> AuditTrace | None:
        """Return the audit trace from the last audited operation."""
        return self._last_audit

    def _begin_audit(self, operation: str, question: str) -> AuditTrace | None:
        """Start a new audit trace if auditing is enabled."""
        if not self._audit_enabled:
            return None
        trace = AuditTrace(
            operation=operation,
            question=question,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        return trace

    def _finish_audit(self, trace: AuditTrace | None, t0: float) -> None:
        """Finalize and store an audit trace."""
        if trace is None:
            return
        trace.total_duration_ms = (_time.time() - t0) * 1000
        self._last_audit = trace

    def render_audit(self, trace: AuditTrace | None = None) -> str:
        """Render an audit trace as a human-readable markdown report.

        Args:
            trace: The audit trace to render. Uses last_audit() if None.

        Returns:
            Markdown-formatted string showing the full decision tree.
        """
        if trace is None:
            trace = self._last_audit
        if trace is None:
            return "No audit trace available."

        lines = []
        lines.append(f"# Audit Report: {trace.operation}")
        lines.append("")
        lines.append(f"**Question:** {trace.question}")
        if trace.strategy:
            lines.append(f"**Strategy:** {trace.strategy}")
        lines.append(f"**Started:** {trace.started_at}")
        lines.append(f"**Total Duration:** {trace.total_duration_ms:.1f}ms")
        lines.append("")

        # Decision tree
        lines.append("## Decision Pipeline")
        lines.append("")

        for i, event in enumerate(trace.events):
            # Stage header with timing
            pct = (event.duration_ms / trace.total_duration_ms * 100
                   if trace.total_duration_ms > 0 else 0)
            lines.append(
                f"### {i+1}. {event.stage.upper()}: {event.action} "
                f"({event.duration_ms:.1f}ms, {pct:.0f}%)"
            )
            lines.append("")

            # Inputs
            if event.inputs:
                lines.append("**Inputs:**")
                for k, v in event.inputs.items():
                    if isinstance(v, list) and len(v) > 5:
                        lines.append(f"- {k}: [{len(v)} items]")
                    elif isinstance(v, str) and len(v) > 100:
                        lines.append(f"- {k}: {v[:100]}...")
                    else:
                        lines.append(f"- {k}: {v}")
                lines.append("")

            # Outputs
            if event.outputs:
                lines.append("**Outputs:**")
                for k, v in event.outputs.items():
                    if isinstance(v, list) and len(v) > 5:
                        lines.append(f"- {k}: [{len(v)} items]")
                    elif isinstance(v, str) and len(v) > 100:
                        lines.append(f"- {k}: {v[:100]}...")
                    else:
                        lines.append(f"- {k}: {v}")
                lines.append("")

            # Metadata
            if event.metadata:
                lines.append("**Details:**")
                for k, v in event.metadata.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")

        # Summary table
        lines.append("## Timing Breakdown")
        lines.append("")
        lines.append("| Stage | Action | Duration | % |")
        lines.append("|-------|--------|----------|---|")
        for event in trace.events:
            pct = (event.duration_ms / trace.total_duration_ms * 100
                   if trace.total_duration_ms > 0 else 0)
            lines.append(
                f"| {event.stage} | {event.action} | "
                f"{event.duration_ms:.1f}ms | {pct:.0f}% |"
            )

        return "\n".join(lines)

    def _next_tx(self) -> TransactionTime:
        """Auto-generate next transaction time."""
        self._tx_counter += 1
        return TransactionTime(
            tx_id=self._tx_counter,
            recorded_at=datetime.now(timezone.utc),
        )

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

            # For document chunks, use full chunk text as assertion (from evidence_ref)
            if extraction_prov.evidence_ref and len(extraction_prov.evidence_ref) > 500:
                assertion = extraction_prov.evidence_ref
            else:
                assertion = text[:500]

            revision = self.store.assert_revision(
                core=claim,
                assertion=assertion,
                valid_time=valid_time,
                transaction_time=transaction_time,
                provenance=extraction_prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            # Phase 4: Index for search (use full chunk text for better search)
            if self._index is not None:
                index_text = extraction_prov.evidence_ref or text[:500]
                self._index.add(revision.revision_id, index_text)

        return revision_ids

    def ingest_pdf(
        self,
        path: str | Path,
        *,
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
    ) -> list[str]:
        """Ingest a single PDF file: extract text, chunk, commit, index.

        Args:
            path: Path to the PDF file.
            valid_time: When the facts are true (defaults to open-ended from now).
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker (uses default if None).

        Returns:
            List of revision_ids for all committed chunks.
        """
        pdf_extractor = PDFExtractor(chunker=chunker)
        extraction = pdf_extractor.extract_pdf(path)

        if not extraction.claims:
            return []

        vt = valid_time or ValidTime(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=None,
        )
        tt = transaction_time or self._next_tx()

        revision_ids: list[str] = []

        for i, claim in enumerate(extraction.claims):
            prov = extraction.provenance[i] if i < len(extraction.provenance) else Provenance(
                source=f"pdf:{Path(path).name}",
            )

            # Use full chunk text as the assertion for search
            assertion = prov.evidence_ref or str(claim.slots)

            revision = self.store.assert_revision(
                core=claim,
                assertion=assertion,
                valid_time=vt,
                transaction_time=tt,
                provenance=prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            # Index the chunk text for search
            if self._index is not None:
                self._index.add(revision.revision_id, assertion)

        # Track chunk siblings for context expansion
        source_name = Path(path).name
        self._chunk_siblings[source_name] = revision_ids

        return revision_ids

    def ingest_text(
        self,
        text: str,
        *,
        source: str = "text",
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> list[str]:
        """Ingest raw text: chunk, commit, index. No PDF or extractor needed.

        This is the simplest ingestion path for plain text content.

        Args:
            text: Raw text to ingest.
            source: Source identifier for provenance.
            valid_time: When the facts are true.
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for chunks.
            chunk_size: Characters per chunk.
            chunk_overlap: Overlap between chunks.

        Returns:
            List of revision_ids for committed chunks.
        """
        chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap, min_chunk=10)
        chunks = chunker.chunk(text)

        if not chunks:
            # If chunker produces nothing (text too short), use raw text
            if text.strip():
                chunks = [text.strip()]
            else:
                return []

        vt = valid_time or ValidTime(start=datetime(2020, 1, 1, tzinfo=timezone.utc))
        tt = transaction_time or self._next_tx()

        revision_ids: list[str] = []
        for i, chunk_text in enumerate(chunks):
            core = ClaimCore(
                claim_type="document.chunk@v1",
                slots={
                    "source": canonicalize_text(source),
                    "chunk_idx": str(i),
                    "text": canonicalize_text(chunk_text[:200]),
                },
            )
            prov = Provenance(source=source, evidence_ref=chunk_text)

            revision = self.store.assert_revision(
                core=core,
                assertion=chunk_text,
                valid_time=vt,
                transaction_time=tt,
                provenance=prov,
                confidence_bp=confidence_bp,
                status="asserted",
            )
            revision_ids.append(revision.revision_id)

            if self._index is not None:
                self._index.add(revision.revision_id, chunk_text)

        # Track siblings for context expansion
        self._chunk_siblings[source] = revision_ids

        return revision_ids

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        pattern: str = "*.pdf",
        valid_time: ValidTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
        progress: bool = True,
    ) -> dict[str, list[str]]:
        """Ingest all PDFs in a directory.

        Args:
            directory: Path to directory containing PDFs.
            pattern: Glob pattern for files (default: *.pdf).
            valid_time: When the facts are true.
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker.
            progress: Print progress to stderr.

        Returns:
            Dict mapping filename → list of revision_ids.
        """
        directory = Path(directory)
        pdf_files = sorted(directory.glob(pattern))

        if not pdf_files:
            return {}

        results: dict[str, list[str]] = {}
        errors: dict[str, str] = {}

        for i, pdf_path in enumerate(pdf_files):
            if progress:
                print(
                    f"\r  [{i+1}/{len(pdf_files)}] {pdf_path.name[:60]}...",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

            try:
                revision_ids = self.ingest_pdf(
                    pdf_path,
                    valid_time=valid_time,
                    confidence_bp=confidence_bp,
                    chunker=chunker,
                )
                results[pdf_path.name] = revision_ids
            except Exception as e:
                errors[pdf_path.name] = str(e)
                if progress:
                    print(
                        f"\n  ERROR: {pdf_path.name}: {e}",
                        file=sys.stderr,
                    )

        if progress:
            total_chunks = sum(len(v) for v in results.values())
            print(
                f"\n  Done: {len(results)} files, {total_chunks} chunks, {len(errors)} errors",
                file=sys.stderr,
            )

        # Rebuild search index after batch ingestion
        if hasattr(self._index, 'rebuild'):
            self._index.rebuild()

        return results

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
            raise ValueError(
                "No search index configured. "
                "Set embedding_backend or search_index in Pipeline init."
            )

        # If re-ranker is configured, retrieve more candidates then re-rank
        if self._reranker is not None:
            candidates = self._index.search(
                question,
                k=k * 4,  # Over-retrieve for better re-ranking
                valid_at=valid_at,
                tx_id=tx_id,
            )
            return self._reranker.rerank(question, candidates, top_k=k)

        return self._index.search(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    def query_multi(
        self,
        question: str,
        *,
        k: int = 10,
        group_by_source: bool = True,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> dict[str, list[SearchResult]]:
        """Multi-document retrieval: find relevant chunks across all sources.

        Returns results grouped by source document, enabling cross-document
        reasoning.

        Args:
            question: Natural language query.
            k: Total results to retrieve before grouping.
            group_by_source: If True, group results by source document.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            Dict mapping source filename → list of SearchResult.
        """
        results = self.query(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

        if not group_by_source:
            return {"all": results}

        grouped: dict[str, list[SearchResult]] = {}
        for result in results:
            # Get the source from the claim's slots
            core = self.store.cores.get(result.core_id)
            source = "unknown"
            if core and "source" in core.slots:
                source = core.slots["source"]
            grouped.setdefault(source, []).append(result)

        return grouped

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

    # ---- Context Expansion ----

    def expand_context(
        self,
        result: SearchResult,
        *,
        window: int = 2,
    ) -> list[SearchResult]:
        """Expand a search result to include surrounding chunks from the same document.

        When a relevant chunk is found, this retrieves the N chunks before
        and after it from the same source document, providing full context
        for reasoning.

        Args:
            result: A SearchResult to expand context around.
            window: Number of chunks before/after to include.

        Returns:
            Ordered list of SearchResults (including the original).
        """
        core = self.store.cores.get(result.core_id)
        if core is None:
            return [result]

        source = core.slots.get("source", "")
        if not source:
            return [result]

        # Find sibling chunks for this source
        siblings = self._chunk_siblings.get(source)

        # If siblings not tracked, try to reconstruct from store
        if siblings is None:
            siblings = self._reconstruct_siblings(source)

        if not siblings:
            return [result]

        # Find position of this result in the sibling list
        try:
            pos = siblings.index(result.revision_id)
        except ValueError:
            return [result]

        # Get window of surrounding chunks
        start = max(0, pos - window)
        end = min(len(siblings), pos + window + 1)

        expanded = []
        for rid in siblings[start:end]:
            rev = self.store.revisions.get(rid)
            if rev:
                expanded.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=result.score if rid == result.revision_id else result.score * 0.5,
                    text=rev.assertion,
                ))

        return expanded

    def _reconstruct_siblings(self, source: str) -> list[str]:
        """Reconstruct sibling chunk order from store data."""
        # Find all chunks from this source
        chunks: list[tuple[int, str]] = []  # (chunk_idx, revision_id)
        for rev_id, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            if core and core.slots.get("source") == source:
                try:
                    idx = int(core.slots.get("chunk_idx", "0"))
                except (ValueError, TypeError):
                    idx = 0
                chunks.append((idx, rev_id))

        if not chunks:
            return []

        chunks.sort()
        siblings = [rid for _, rid in chunks]
        self._chunk_siblings[source] = siblings
        return siblings

    def query_with_context(
        self,
        question: str,
        *,
        k: int = 5,
        context_window: int = 1,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search with automatic context expansion.

        Like query(), but each result includes surrounding chunks from
        the same document for extended context.

        Args:
            question: Natural language query.
            k: Number of seed results.
            context_window: Chunks before/after each result to include.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResults including expanded context, ordered
            by seed result relevance with context chunks adjacent.
        """
        seeds = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        if context_window <= 0:
            return seeds

        seen: set[str] = set()
        expanded: list[SearchResult] = []

        for seed in seeds:
            context = self.expand_context(seed, window=context_window)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        return expanded

    # ---- Persistence ----

    def save(self, directory: str | Path) -> None:
        """Save the entire pipeline state to disk.

        Saves:
        - KnowledgeStore → canonical JSON (deterministic, reproducible)
        - TF-IDF index → pickle (for fast reload)
        - Knowledge graph → pickle (for fast reload)
        - Pipeline metadata → JSON

        Args:
            directory: Directory to save into (created if needed).
        """
        import json
        import pickle

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        # 1. Save the deterministic store
        self.store.to_canonical_json_file(str(directory / "store.json"))

        # 2. Save TF-IDF index state
        tfidf_component = None
        dense_component = None

        if isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index._tfidf
            dense_component = self._index._dense
        elif isinstance(self._index, TfidfSearchIndex):
            tfidf_component = self._index._tfidf
        elif isinstance(self._index, DenseSearchIndex):
            dense_component = self._index._dense

        if tfidf_component is not None:
            tfidf_state = {
                "texts": tfidf_component._texts,
                "revision_ids": tfidf_component._revision_ids,
                "fitted": tfidf_component._fitted,
            }
            with open(directory / "tfidf_state.pkl", "wb") as f:
                pickle.dump(tfidf_state, f)
            if tfidf_component._fitted:
                with open(directory / "tfidf_vectorizer.pkl", "wb") as f:
                    pickle.dump(tfidf_component._vectorizer, f)
                with open(directory / "tfidf_matrix.pkl", "wb") as f:
                    pickle.dump(tfidf_component._matrix, f)

        # 2b. Save dense embeddings
        if dense_component is not None:
            dense_component.save_embeddings(directory / "dense_embeddings.pkl")

        # 3. Save knowledge graph
        if hasattr(self, "_graph") and self._graph is not None:
            graph_state = {
                "adjacency": self._graph._adjacency,
                "clusters": self._graph._clusters,
                "revision_cluster": self._graph._revision_cluster,
                "cluster_labels": self._graph._cluster_labels,
            }
            with open(directory / "graph.pkl", "wb") as f:
                pickle.dump(graph_state, f)

        # 4. Save chunk siblings map
        if self._chunk_siblings:
            with open(directory / "chunk_siblings.pkl", "wb") as f:
                pickle.dump(self._chunk_siblings, f)

        # 5. Save metadata
        meta: dict[str, Any] = {
            "version": "0.5.0",
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "tx_counter": self._tx_counter,
        }
        if isinstance(self._index, HybridSearchIndex):
            meta["index_type"] = "hybrid"
            meta["indexed"] = self._index._dense.size
        elif isinstance(self._index, DenseSearchIndex):
            meta["index_type"] = "dense"
            meta["indexed"] = self._index._dense.size
        elif isinstance(self._index, TfidfSearchIndex):
            meta["index_type"] = "tfidf"
            meta["indexed"] = self._index.size
        if hasattr(self, "_graph") and self._graph is not None:
            meta["graph_nodes"] = self._graph.total_nodes
            meta["graph_edges"] = self._graph.total_edges
            meta["graph_clusters"] = self._graph.total_clusters

        with open(directory / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, directory: str | Path) -> "Pipeline":
        """Load a saved pipeline from disk.

        Args:
            directory: Directory containing saved pipeline state.

        Returns:
            Fully restored Pipeline with store, index, and graph.
        """
        import json
        import pickle

        directory = Path(directory)

        # 1. Load the deterministic store
        store = KnowledgeStore.from_canonical_json_file(
            str(directory / "store.json")
        )

        # 2. Load metadata
        with open(directory / "meta.json") as f:
            meta = json.load(f)

        # 3. Restore search index
        search_index = None
        index_type = meta.get("index_type", "tfidf")

        # 3a. Restore TF-IDF component (used by tfidf and hybrid)
        tfidf = None
        if (directory / "tfidf_state.pkl").exists():
            from .index import TfidfIndex

            with open(directory / "tfidf_state.pkl", "rb") as f:
                tfidf_state = pickle.load(f)

            tfidf = TfidfIndex.__new__(TfidfIndex)
            tfidf._texts = tfidf_state["texts"]
            tfidf._revision_ids = tfidf_state["revision_ids"]
            tfidf._fitted = tfidf_state["fitted"]

            if tfidf._fitted and (directory / "tfidf_vectorizer.pkl").exists():
                with open(directory / "tfidf_vectorizer.pkl", "rb") as f:
                    tfidf._vectorizer = pickle.load(f)
                with open(directory / "tfidf_matrix.pkl", "rb") as f:
                    tfidf._matrix = pickle.load(f)
            else:
                from sklearn.feature_extraction.text import TfidfVectorizer
                tfidf._vectorizer = TfidfVectorizer()
                tfidf._matrix = None

        # 3b. Restore dense component (used by dense and hybrid)
        dense = None
        if (directory / "dense_embeddings.pkl").exists():
            from .index import SentenceTransformerIndex
            dense = SentenceTransformerIndex.__new__(SentenceTransformerIndex)
            # Set defaults before loading
            dense._batch_size = 64
            dense._dirty = True
            try:
                from sentence_transformers import SentenceTransformer
                dense._model = SentenceTransformer("all-MiniLM-L6-v2")
                dense._dimension = dense._model.get_sentence_embedding_dimension()
            except ImportError:
                dense._model = None
                dense._dimension = 384
            dense.load_embeddings(directory / "dense_embeddings.pkl")

        # 3c. Assemble the correct index type
        if index_type == "hybrid" and tfidf is not None and dense is not None:
            from .index import HybridSearchIndex
            search_index = HybridSearchIndex.__new__(HybridSearchIndex)
            search_index._store = store
            search_index._tfidf = tfidf
            search_index._dense = dense
            search_index._alpha = 0.5
            search_index._rrf_k = 60
        elif index_type == "dense" and dense is not None:
            from .index import DenseSearchIndex
            search_index = DenseSearchIndex.__new__(DenseSearchIndex)
            search_index._store = store
            search_index._dense = dense
        elif tfidf is not None:
            search_index = TfidfSearchIndex.__new__(TfidfSearchIndex)
            search_index._store = store
            search_index._tfidf = tfidf

        # 4. Create pipeline
        pipeline = cls(store=store, search_index=search_index)
        pipeline._tx_counter = meta.get("tx_counter", 0)

        # 5. Restore knowledge graph
        if (directory / "graph.pkl").exists():
            from .index import KnowledgeGraph

            with open(directory / "graph.pkl", "rb") as f:
                graph_state = pickle.load(f)

            graph = KnowledgeGraph()
            graph._adjacency = graph_state["adjacency"]
            graph._clusters = graph_state["clusters"]
            graph._revision_cluster = graph_state["revision_cluster"]
            graph._cluster_labels = graph_state["cluster_labels"]
            pipeline._graph = graph

        # 6. Restore chunk siblings
        if (directory / "chunk_siblings.pkl").exists():
            with open(directory / "chunk_siblings.pkl", "rb") as f:
                pipeline._chunk_siblings = pickle.load(f)

        return pipeline

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
            raise ValueError("No search index configured.")

        items = []
        for revision_id, revision in self.store.revisions.items():
            items.append((revision_id, revision.assertion))
        self._index.add_batch(items)

        # Rebuild index matrix
        if hasattr(self._index, 'rebuild'):
            self._index.rebuild()

        return len(items)

    def stats(self) -> dict[str, Any]:
        """Return store and index statistics."""
        s: dict[str, Any] = {
            "cores": len(self.store.cores),
            "revisions": len(self.store.revisions),
            "relations": len(self.store.relations),
        }
        if self._index is not None:
            s["indexed"] = self._index.size
        return s

    # ---- Knowledge Graph ----

    def build_graph(
        self,
        *,
        similarity_threshold: float = 0.15,
        max_neighbors: int = 10,
        n_clusters: int = 50,
    ) -> KnowledgeGraph:
        """Build a knowledge graph linking related chunks.

        Uses TF-IDF similarity to discover connections between chunks.
        Clusters chunks into topics for efficient navigation.

        Args:
            similarity_threshold: Minimum cosine similarity for a link.
            max_neighbors: Maximum neighbors per chunk.
            n_clusters: Number of topic clusters.

        Returns:
            KnowledgeGraph with adjacency lists and topic clusters.
        """
        # Get the TF-IDF component from whichever index type we have
        tfidf_component = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf_component = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf_component = self._index._tfidf

        if tfidf_component is None:
            raise ValueError("Graph building requires TfidfSearchIndex or HybridSearchIndex.")

        self._graph = KnowledgeGraph()
        self._graph.build_from_tfidf(
            tfidf_component,
            similarity_threshold=similarity_threshold,
            max_neighbors=max_neighbors,
            n_clusters=n_clusters,
        )
        return self._graph

    @property
    def graph(self) -> KnowledgeGraph | None:
        """Access the knowledge graph (None if not built)."""
        return getattr(self, "_graph", None)

    def neighbors(
        self,
        revision_id: str,
        *,
        k: int = 5,
    ) -> list[SearchResult]:
        """Find chunks related to a given chunk via the knowledge graph.

        Args:
            revision_id: The revision to find neighbors of.
            k: Maximum neighbors to return.

        Returns:
            List of SearchResult for neighboring chunks.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        neighbor_ids = self._graph.neighbors(revision_id, k=k)
        results = []
        for nid, score in neighbor_ids:
            rev = self.store.revisions.get(nid)
            if rev:
                results.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=nid,
                    score=score,
                    text=rev.assertion,
                ))
        return results

    def topics(self) -> list[dict[str, Any]]:
        """List all discovered topic clusters.

        Returns:
            List of dicts with cluster_id, size, and label terms.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")
        return self._graph.topics()

    def topic_chunks(
        self,
        cluster_id: int,
        *,
        k: int = 10,
    ) -> list[SearchResult]:
        """Get chunks belonging to a topic cluster.

        Args:
            cluster_id: The cluster to retrieve.
            k: Maximum chunks to return.

        Returns:
            List of SearchResult for chunks in the cluster.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        member_ids = self._graph.cluster_members(cluster_id)[:k]
        results = []
        for rid in member_ids:
            rev = self.store.revisions.get(rid)
            if rev:
                results.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=1.0,
                    text=rev.assertion,
                ))
        return results

    # ---- Data Exploration & Interactive Review ----

    def profile(self) -> dict[str, Any]:
        """Generate a comprehensive corpus profile for interactive exploration.

        Returns a structured overview of the corpus that lets users understand
        their data: what topics exist, how sources distribute, where potential
        quality issues are, and what entities were discovered.

        Must be called AFTER build_graph().

        Returns:
            Dict with:
              - summary: basic stats (chunks, sources, clusters, edges)
              - clusters: list of cluster profiles (id, size, labels, sources, samples)
              - sources: per-source stats (chunk count, clusters covered, topics)
              - boilerplate: detected boilerplate patterns and their frequency
              - quality_flags: list of potential quality issues detected
        """
        import re
        import hashlib
        from collections import Counter

        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        n_chunks = len(self.store.revisions)
        rev_to_cluster = getattr(self._graph, '_revision_cluster', {})

        # ---- Source analysis ----
        source_chunks: dict[str, list[str]] = {}  # source -> [revision_ids]
        source_clusters: dict[str, set[int]] = {}  # source -> {cluster_ids}
        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            source_chunks.setdefault(source, []).append(rid)
            cid = rev_to_cluster.get(rid)
            if cid is not None:
                source_clusters.setdefault(source, set()).add(cid)

        n_sources = len(source_chunks)

        # ---- Cluster profiles ----
        cluster_profiles = []
        clusters = getattr(self._graph, '_clusters', {})
        cluster_labels = getattr(self._graph, '_cluster_labels', {})

        for cid, members in sorted(clusters.items()):
            # Source distribution within this cluster
            cluster_sources: Counter = Counter()
            for rid in members:
                core = self.store.cores.get(
                    self.store.revisions[rid].core_id
                ) if rid in self.store.revisions else None
                source = core.slots.get("source", "?") if core else "?"
                cluster_sources[source] += 1

            # Sample chunks (first 3)
            samples = []
            for rid in members[:3]:
                rev = self.store.revisions.get(rid)
                if rev:
                    samples.append({
                        "revision_id": rid,
                        "text": rev.assertion[:200],
                    })

            # Quality flags for this cluster
            flags = []
            if len(cluster_sources) == 1:
                flags.append("single_source")
            dominant_source, dominant_count = cluster_sources.most_common(1)[0]
            if dominant_count / max(len(members), 1) > 0.8:
                flags.append(f"dominated_by:{dominant_source[:30]}")

            cluster_profiles.append({
                "cluster_id": cid,
                "size": len(members),
                "labels": cluster_labels.get(cid, [])[:6],
                "source_count": len(cluster_sources),
                "top_sources": cluster_sources.most_common(3),
                "samples": samples,
                "flags": flags,
            })

        # Sort by size descending
        cluster_profiles.sort(key=lambda c: -c["size"])

        # ---- Boilerplate detection ----
        sentence_doc_freq: Counter = Counter()
        sentence_text: dict[str, str] = {}  # hash -> sentence text
        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", rid) if core else rid
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            seen_hashes: set[str] = set()
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.strip())
                if len(normed) < 20:
                    continue
                h = hashlib.md5(normed.lower().encode()).hexdigest()[:16]
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    sentence_doc_freq[h] += 1
                    if h not in sentence_text:
                        sentence_text[h] = normed[:120]

        # Top repeated sentences (likely boilerplate)
        boilerplate_candidates = [
            {"text": sentence_text[h], "frequency": freq, "hash": h}
            for h, freq in sentence_doc_freq.most_common(20)
            if freq >= max(3, n_sources // 10)
        ]

        # ---- Quality flags ----
        quality_flags = []
        if n_sources < 3:
            quality_flags.append({
                "type": "low_source_diversity",
                "message": f"Only {n_sources} source documents. Cross-document linking may be limited.",
            })

        # Check for source dominance
        source_sizes = [(s, len(rids)) for s, rids in source_chunks.items()]
        source_sizes.sort(key=lambda x: -x[1])
        if source_sizes:
            top_source, top_count = source_sizes[0]
            if top_count / max(n_chunks, 1) > 0.3:
                quality_flags.append({
                    "type": "source_dominance",
                    "message": f"Source '{top_source[:40]}' contains {top_count}/{n_chunks} chunks ({top_count*100//n_chunks}%). Consider balancing.",
                })

        # Check for boilerplate prevalence
        if len(boilerplate_candidates) > 5:
            total_bp_freq = sum(b["frequency"] for b in boilerplate_candidates)
            quality_flags.append({
                "type": "high_boilerplate",
                "message": f"{len(boilerplate_candidates)} repeated sentences detected (total {total_bp_freq} occurrences). Consider reviewing.",
            })

        # Check for single-source clusters
        single_source_clusters = sum(1 for c in cluster_profiles if "single_source" in c["flags"])
        if single_source_clusters > len(cluster_profiles) // 3:
            quality_flags.append({
                "type": "isolated_clusters",
                "message": f"{single_source_clusters}/{len(cluster_profiles)} clusters have content from a single source.",
            })

        # ---- Source stats ----
        source_stats = []
        for source, rids in sorted(source_chunks.items(), key=lambda x: -len(x[1])):
            source_stats.append({
                "source": source,
                "chunks": len(rids),
                "clusters": len(source_clusters.get(source, set())),
                "fraction": len(rids) / max(n_chunks, 1),
            })

        return {
            "summary": {
                "chunks": n_chunks,
                "sources": n_sources,
                "clusters": len(clusters),
                "edges": sum(len(adj) for adj in self._graph._adjacency.values()),
            },
            "clusters": cluster_profiles,
            "sources": source_stats[:20],  # Top 20 sources
            "boilerplate": boilerplate_candidates,
            "quality_flags": quality_flags,
        }

    def render_profile(self, profile: dict[str, Any] | None = None) -> str:
        """Render a corpus profile as readable text.

        Args:
            profile: Output from profile(). If None, calls profile().

        Returns:
            Formatted text summary.
        """
        if profile is None:
            profile = self.profile()

        lines: list[str] = []
        s = profile["summary"]
        lines.append(f"=== Corpus Profile ===")
        lines.append(f"Chunks: {s['chunks']:,}  |  Sources: {s['sources']}  |  "
                     f"Clusters: {s['clusters']}  |  Edges: {s['edges']:,}")

        # Quality flags
        flags = profile.get("quality_flags", [])
        if flags:
            lines.append(f"\n--- Quality Flags ({len(flags)}) ---")
            for f in flags:
                lines.append(f"  [{f['type']}] {f['message']}")

        # Top clusters
        lines.append(f"\n--- Top Clusters ---")
        for c in profile["clusters"][:10]:
            labels = ", ".join(c["labels"][:4])
            flags_str = f"  [{', '.join(c['flags'])}]" if c["flags"] else ""
            lines.append(f"  Cluster {c['cluster_id']}: {c['size']} chunks, "
                        f"{c['source_count']} sources  |  {labels}{flags_str}")

        # Top sources
        lines.append(f"\n--- Top Sources ---")
        for src in profile["sources"][:10]:
            lines.append(f"  {src['source'][:50]:50s}  {src['chunks']:4d} chunks  "
                        f"{src['clusters']:2d} clusters  ({src['fraction']*100:.1f}%)")

        # Boilerplate
        bp = profile.get("boilerplate", [])
        if bp:
            lines.append(f"\n--- Detected Boilerplate ({len(bp)} patterns) ---")
            for b in bp[:5]:
                lines.append(f"  [{b['frequency']}x] {b['text'][:80]}...")

        return "\n".join(lines)

    def delete_cluster(
        self,
        cluster_id: int,
        *,
        reason: str = "User deleted cluster via interactive review",
    ) -> dict[str, Any]:
        """Delete all chunks in a cluster by retracting their revisions.

        This is a soft delete — the data remains in the store as retracted
        revisions, preserving the full audit trail. The chunks will no longer
        appear in search results or entity linking.

        Args:
            cluster_id: The cluster to delete.
            reason: Reason for deletion (stored in retraction metadata).

        Returns:
            Dict with retracted_count and affected_sources.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        clusters = getattr(self._graph, '_clusters', {})
        members = clusters.get(cluster_id, [])
        if not members:
            return {"retracted_count": 0, "affected_sources": []}

        # Retract each revision in the cluster
        retracted = 0
        affected_sources: set[str] = set()
        tx_time = self._next_tx()

        from .core import Provenance as _P

        for rid in members:
            rev = self.store.revisions.get(rid)
            if rev and rev.status == "asserted":
                core = self.store.cores.get(rev.core_id)
                source = core.slots.get("source", "?") if core else "?"
                affected_sources.add(source)

                self.store.assert_revision(
                    core=core,
                    assertion=rev.assertion,
                    valid_time=rev.valid_time,
                    transaction_time=tx_time,
                    provenance=_P(source="cluster_delete", evidence_ref=reason),
                    confidence_bp=rev.confidence_bp,
                    status="retracted",
                )
                retracted += 1

        # Remove from graph
        for rid in members:
            self._graph._adjacency.pop(rid, None)
        clusters.pop(cluster_id, None)
        rev_cluster = getattr(self._graph, '_revision_cluster', {})
        for rid in members:
            rev_cluster.pop(rid, None)

        return {
            "retracted_count": retracted,
            "affected_sources": sorted(affected_sources),
            "reason": reason,
        }

    def review_entities(
        self,
        *,
        top_k: int = 50,
    ) -> dict[str, Any]:
        """Analyze entities for interactive review.

        Runs entity extraction (same method as link_entities) and categorizes
        entities into quality tiers based on source diversity and cluster spread:
        - high: appears across many sources and clusters (likely real domain term)
        - medium: moderate spread, may need review
        - flagged: concentrated in few sources or clusters (likely boilerplate)

        Must be called AFTER build_graph().

        Args:
            top_k: Number of top entities to analyze.

        Returns:
            Dict with high/medium/flagged entity lists, each entry containing
            the entity text, frequency, source count, cluster count, and
            a quality_score (0-100).
        """
        import math

        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        # Run link_entities to get the statistically-filtered entities
        link_result = self.link_entities(min_shared_entities=1)
        top_entities = link_result.get("top_entities", [])

        rev_to_cluster = getattr(self._graph, '_revision_cluster', {})
        n_chunks = len(self.store.revisions)

        # Compute total sources
        all_sources: set[str] = set()
        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            all_sources.add(source)
        n_sources_total = len(all_sources)
        n_clusters_total = len(set(rev_to_cluster.values())) if rev_to_cluster else 1

        # For each top entity, compute quality metrics
        import re
        word_re = re.compile(r'\b([a-z]{3,})\b')

        # Build entity -> revisions map using same approach as link_entities
        entity_revisions: dict[str, set[str]] = {}
        for rid, rev in self.store.revisions.items():
            tokens = word_re.findall(rev.assertion.lower())
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                entity_revisions.setdefault(bg, set()).add(rid)
            for t in set(tokens):
                entity_revisions.setdefault(t, set()).add(rid)

        entities_analyzed = []
        for entity, freq in top_entities[:top_k]:
            rids = entity_revisions.get(entity, set())

            # Source and cluster diversity
            sources: set[str] = set()
            clusters: set[int] = set()
            for rid in rids:
                rev = self.store.revisions.get(rid)
                if rev:
                    core = self.store.cores.get(rev.core_id)
                    source = core.slots.get("source", "?") if core else "?"
                    sources.add(source)
                cid = rev_to_cluster.get(rid)
                if cid is not None:
                    clusters.add(cid)

            # Quality score (0-100):
            # Source diversity (0-40): % of total sources containing entity
            source_frac = len(sources) / max(n_sources_total, 1)
            source_score = min(40, int(40 * min(source_frac / 0.05, 1)))

            # Cluster diversity (0-40): % of total clusters containing entity
            cluster_frac = len(clusters) / max(n_clusters_total, 1)
            cluster_score = min(40, int(40 * min(cluster_frac / 0.1, 1)))

            # Frequency (0-20): moderate frequency is optimal (~0.5-3% of corpus)
            freq_ratio = len(rids) / max(n_chunks, 1)
            if freq_ratio < 0.002:
                freq_score = 10
            elif freq_ratio <= 0.03:
                freq_score = 20  # Sweet spot
            elif freq_ratio <= 0.05:
                freq_score = 10
            elif freq_ratio <= 0.10:
                freq_score = 0
            else:
                freq_score = -20  # Very ubiquitous = penalty

            quality = source_score + cluster_score + freq_score

            entities_analyzed.append({
                "entity": entity,
                "frequency": freq,
                "source_count": len(sources),
                "cluster_count": len(clusters),
                "quality_score": quality,
            })

        # Categorize
        high = [e for e in entities_analyzed if e["quality_score"] >= 60]
        medium = [e for e in entities_analyzed if 30 <= e["quality_score"] < 60]
        flagged = [e for e in entities_analyzed if e["quality_score"] < 30]

        return {
            "high": high,
            "medium": medium,
            "flagged": flagged,
            "total_analyzed": len(entities_analyzed),
        }

    def accept_entities(
        self,
        entities: list[str],
        *,
        reason: str = "User accepted via interactive review",
    ) -> int:
        """Accept entities as valid domain terms.

        Stores acceptance decisions as claims in the KnowledgeStore,
        making them persistent and auditable.

        Args:
            entities: List of entity strings to accept.
            reason: Reason for acceptance.

        Returns:
            Number of entity decisions stored.
        """
        from .core import ClaimCore as _CC, Provenance as _P
        from .core import ValidTime as _VT
        from datetime import datetime as _dt

        now = _dt.now()
        tx = self._next_tx()
        count = 0

        for entity in entities:
            core = _CC(
                claim_type="dks.entity_review@v1",
                slots={"entity": entity, "decision": "accepted"},
            )
            self.store.assert_revision(
                core=core,
                assertion=f"Entity '{entity}' accepted: {reason}",
                valid_time=_VT(start=now, end=None),
                transaction_time=tx,
                provenance=_P(source="interactive_review"),
                confidence_bp=9000,
            )
            count += 1

        return count

    def reject_entities(
        self,
        entities: list[str],
        *,
        reason: str = "User rejected via interactive review",
    ) -> int:
        """Reject entities as noise/boilerplate.

        Stores rejection decisions as claims in the KnowledgeStore,
        making them persistent and auditable. Rejected entities will
        be excluded from future entity linking.

        Args:
            entities: List of entity strings to reject.
            reason: Reason for rejection.

        Returns:
            Number of entity decisions stored.
        """
        from .core import ClaimCore as _CC, Provenance as _P
        from .core import ValidTime as _VT
        from datetime import datetime as _dt

        now = _dt.now()
        tx = self._next_tx()
        count = 0

        for entity in entities:
            core = _CC(
                claim_type="dks.entity_review@v1",
                slots={"entity": entity, "decision": "rejected"},
            )
            self.store.assert_revision(
                core=core,
                assertion=f"Entity '{entity}' rejected: {reason}",
                valid_time=_VT(start=now, end=None),
                transaction_time=tx,
                provenance=_P(source="interactive_review"),
                confidence_bp=9000,
            )
            count += 1

        return count

    def get_entity_decisions(self) -> dict[str, str]:
        """Retrieve all entity review decisions.

        Returns:
            Dict mapping entity -> "accepted" or "rejected".
        """
        decisions: dict[str, str] = {}
        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            if core and core.claim_type == "dks.entity_review@v1":
                entity = core.slots.get("entity", "")
                decision = core.slots.get("decision", "")
                if entity and decision:
                    decisions[entity] = decision
        return decisions

    # ---- Source Management ----

    def source_detail(self, source: str) -> dict[str, Any]:
        """Get detailed statistics for a specific source document.

        Args:
            source: The source identifier (e.g. filename).

        Returns:
            Dict with chunk_count, clusters (with sizes), entities found,
            page_range, avg_chunk_length, and quality_flags.
        """
        chunks: list[dict[str, Any]] = []
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.slots.get("source") != source:
                continue
            chunks.append({
                "revision_id": rid,
                "core_id": rev.core_id,
                "text": rev.assertion,
                "page": core.slots.get("page_start"),
                "confidence_bp": rev.confidence_bp,
            })

        if not chunks:
            return {"source": source, "chunk_count": 0, "found": False}

        # Cluster distribution
        cluster_dist: dict[int, int] = {}
        rev_cluster = {}
        if hasattr(self, "_graph") and self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})
        for c in chunks:
            cid = rev_cluster.get(c["revision_id"])
            if cid is not None:
                cluster_dist[cid] = cluster_dist.get(cid, 0) + 1

        # Text stats
        lengths = [len(c["text"]) for c in chunks]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
        pages = sorted({c["page"] for c in chunks if c["page"] is not None})

        # Quality flags
        quality_flags: list[str] = []
        short_chunks = sum(1 for l in lengths if l < 100)
        if short_chunks > len(chunks) * 0.3:
            quality_flags.append("many_short_chunks")
        if len(cluster_dist) == 1:
            quality_flags.append("single_cluster")

        return {
            "source": source,
            "found": True,
            "chunk_count": len(chunks),
            "cluster_distribution": cluster_dist,
            "page_range": f"{min(pages)}-{max(pages)}" if pages else None,
            "total_pages": len(pages),
            "avg_chunk_length": round(avg_len),
            "shortest_chunk": min(lengths) if lengths else 0,
            "longest_chunk": max(lengths) if lengths else 0,
            "quality_flags": quality_flags,
        }

    def delete_source(
        self,
        source: str,
        *,
        reason: str = "User deleted source via interactive review",
    ) -> dict[str, Any]:
        """Delete all chunks from a source by retracting their revisions.

        Soft delete — data remains as retracted revisions for audit trail.

        Args:
            source: The source identifier to delete.
            reason: Reason for deletion.

        Returns:
            Dict with retracted_count.
        """
        from .core import Provenance as _P

        tx_time = self._next_tx()
        retracted = 0

        for rid, rev in list(self.store.revisions.items()):
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.slots.get("source") != source:
                continue

            self.store.assert_revision(
                core=core,
                assertion=rev.assertion,
                valid_time=rev.valid_time,
                transaction_time=tx_time,
                provenance=_P(source="source_delete", evidence_ref=reason),
                confidence_bp=rev.confidence_bp,
                status="retracted",
            )
            retracted += 1

        return {
            "source": source,
            "retracted_count": retracted,
            "reason": reason,
        }

    # ---- Chunk Browsing ----

    def browse_cluster(
        self,
        cluster_id: int,
        *,
        limit: int = 20,
        preview_length: int = 200,
    ) -> dict[str, Any]:
        """Browse chunks within a specific cluster.

        Args:
            cluster_id: The cluster to browse.
            limit: Max chunks to return.
            preview_length: Text preview truncation length.

        Returns:
            Dict with cluster_id, chunk_count, and list of chunk previews.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        clusters = getattr(self._graph, '_clusters', {})
        members = clusters.get(cluster_id, [])

        chunks: list[dict[str, Any]] = []
        for rid in members[:limit]:
            rev = self.store.revisions.get(rid)
            if rev is None:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            text = rev.assertion
            chunks.append({
                "revision_id": rid,
                "source": source,
                "preview": text[:preview_length] + ("..." if len(text) > preview_length else ""),
                "length": len(text),
                "status": rev.status,
            })

        return {
            "cluster_id": cluster_id,
            "total_members": len(members),
            "showing": len(chunks),
            "chunks": chunks,
        }

    def browse_source(
        self,
        source: str,
        *,
        limit: int = 20,
        preview_length: int = 200,
    ) -> dict[str, Any]:
        """Browse chunks from a specific source document.

        Args:
            source: The source identifier.
            limit: Max chunks to return.
            preview_length: Text preview truncation length.

        Returns:
            Dict with source, chunk_count, and list of chunk previews.
        """
        chunks: list[dict[str, Any]] = []
        rev_cluster = {}
        if hasattr(self, "_graph") and self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None or core.slots.get("source") != source:
                continue

            text = rev.assertion
            page = core.slots.get("page_start")
            chunks.append({
                "revision_id": rid,
                "page": page,
                "cluster_id": rev_cluster.get(rid),
                "preview": text[:preview_length] + ("..." if len(text) > preview_length else ""),
                "length": len(text),
            })

            if len(chunks) >= limit:
                break

        total = sum(
            1 for rid, rev in self.store.revisions.items()
            if rev.status == "asserted"
            and self.store.cores.get(rev.core_id)
            and self.store.cores.get(rev.core_id).slots.get("source") == source
        )

        return {
            "source": source,
            "total_chunks": total,
            "showing": len(chunks),
            "chunks": chunks,
        }

    def chunk_detail(self, revision_id: str) -> dict[str, Any]:
        """Get full details of a single chunk.

        Args:
            revision_id: The revision ID to inspect.

        Returns:
            Dict with full text, metadata, cluster info, and neighbors.
        """
        rev = self.store.revisions.get(revision_id)
        if rev is None:
            return {"revision_id": revision_id, "found": False}

        core = self.store.cores.get(rev.core_id)
        source = core.slots.get("source", "?") if core else "?"

        # Cluster info
        cluster_id = None
        if hasattr(self, "_graph") and self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})
            cluster_id = rev_cluster.get(revision_id)

        # Neighbors from graph
        neighbor_previews: list[dict[str, Any]] = []
        if hasattr(self, "_graph") and self._graph is not None:
            adj = self._graph._adjacency.get(revision_id, {})
            for nid, weight in sorted(adj.items(), key=lambda x: -x[1])[:5]:
                n_rev = self.store.revisions.get(nid)
                if n_rev is None:
                    continue
                n_core = self.store.cores.get(n_rev.core_id)
                n_source = n_core.slots.get("source", "?") if n_core else "?"
                neighbor_previews.append({
                    "revision_id": nid,
                    "source": n_source,
                    "weight": round(weight, 4),
                    "preview": n_rev.assertion[:150],
                })

        return {
            "revision_id": revision_id,
            "found": True,
            "core_id": rev.core_id,
            "source": source,
            "text": rev.assertion,
            "length": len(rev.assertion),
            "status": rev.status,
            "confidence_bp": rev.confidence_bp,
            "cluster_id": cluster_id,
            "page": core.slots.get("page_start") if core else None,
            "slots": dict(core.slots) if core else {},
            "neighbors": neighbor_previews,
            "valid_time": {
                "start": rev.valid_time.start.isoformat() if rev.valid_time.start else None,
                "end": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
            },
        }

    # ---- Quality Report ----

    def quality_report(self) -> dict[str, Any]:
        """Generate a comprehensive corpus quality report with automated issue detection.

        Scans the entire corpus for quality issues and returns a structured
        report with actionable suggestions. No external dependencies required.

        Returns:
            Dict with sections: summary, issues (list), per_source stats,
            and recommendations.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        issues: list[dict[str, Any]] = []
        rev_cluster = getattr(self._graph, '_revision_cluster', {})
        clusters = getattr(self._graph, '_clusters', {})

        # Collect per-source and per-chunk data
        source_chunks: dict[str, list[str]] = {}
        chunk_lengths: dict[str, int] = {}
        orphan_chunks: list[str] = []

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            ct = core.claim_type
            if ct != "document.chunk@v1" and not ct.startswith("dks."):
                continue
            if ct.startswith("dks."):
                continue  # Skip internal claims (entity reviews, etc.)

            source = core.slots.get("source", "unknown")
            source_chunks.setdefault(source, []).append(rid)
            chunk_lengths[rid] = len(rev.assertion)

            if rid not in rev_cluster:
                orphan_chunks.append(rid)

        total_chunks = len(chunk_lengths)
        if total_chunks == 0:
            return {
                "summary": {"total_chunks": 0, "total_sources": 0, "issues": 0},
                "issues": [],
                "per_source": {},
                "recommendations": [],
            }

        # Issue 1: Very short chunks (< 50 chars)
        short_threshold = 50
        short_chunks = [
            rid for rid, l in chunk_lengths.items() if l < short_threshold
        ]
        if short_chunks:
            issues.append({
                "type": "short_chunks",
                "severity": "warning",
                "count": len(short_chunks),
                "description": f"{len(short_chunks)} chunks under {short_threshold} characters",
                "suggestion": "Review short chunks — they may be headers, footers, or incomplete extractions",
                "examples": short_chunks[:5],
            })

        # Issue 2: Very long chunks (> 2000 chars)
        long_threshold = 2000
        long_chunks = [
            rid for rid, l in chunk_lengths.items() if l > long_threshold
        ]
        if long_chunks:
            issues.append({
                "type": "long_chunks",
                "severity": "info",
                "count": len(long_chunks),
                "description": f"{len(long_chunks)} chunks over {long_threshold} characters",
                "suggestion": "Long chunks may reduce search precision — consider re-chunking",
                "examples": long_chunks[:5],
            })

        # Issue 3: Orphan chunks (not assigned to any cluster)
        if orphan_chunks:
            issues.append({
                "type": "orphan_chunks",
                "severity": "info",
                "count": len(orphan_chunks),
                "description": f"{len(orphan_chunks)} chunks not assigned to any cluster",
                "suggestion": "Rebuild graph or inspect orphan content",
                "examples": orphan_chunks[:5],
            })

        # Issue 4: Single-source clusters
        single_source_clusters: list[int] = []
        for cid, members in clusters.items():
            sources_in_cluster = set()
            for rid in members:
                core = self.store.cores.get(
                    self.store.revisions[rid].core_id
                ) if rid in self.store.revisions else None
                if core:
                    sources_in_cluster.add(core.slots.get("source", "?"))
            if len(sources_in_cluster) == 1:
                single_source_clusters.append(cid)

        if single_source_clusters:
            issues.append({
                "type": "single_source_clusters",
                "severity": "info",
                "count": len(single_source_clusters),
                "description": f"{len(single_source_clusters)}/{len(clusters)} clusters draw from only one source",
                "suggestion": "Single-source clusters may indicate unique content or poor inter-document linking",
                "cluster_ids": single_source_clusters,
            })

        # Issue 5: Source imbalance (one source has > 50% of chunks)
        for source, rids in source_chunks.items():
            fraction = len(rids) / total_chunks
            if fraction > 0.5 and len(source_chunks) > 1:
                issues.append({
                    "type": "source_imbalance",
                    "severity": "warning",
                    "source": source,
                    "fraction": round(fraction, 3),
                    "description": f"'{source}' contains {fraction:.0%} of all chunks",
                    "suggestion": "Dominant source may bias search results — consider balancing corpus",
                })

        # Issue 6: Low-confidence chunks
        low_conf_threshold = 3000
        low_conf = [
            rid for rid in chunk_lengths
            if self.store.revisions[rid].confidence_bp < low_conf_threshold
        ]
        if low_conf:
            issues.append({
                "type": "low_confidence",
                "severity": "warning",
                "count": len(low_conf),
                "description": f"{len(low_conf)} chunks with confidence below {low_conf_threshold}bp",
                "suggestion": "Review low-confidence chunks for extraction quality",
                "examples": low_conf[:5],
            })

        # Per-source stats
        per_source: dict[str, dict[str, Any]] = {}
        for source, rids in source_chunks.items():
            lengths = [chunk_lengths[r] for r in rids]
            per_source[source] = {
                "chunks": len(rids),
                "avg_length": round(sum(lengths) / len(lengths)),
                "min_length": min(lengths),
                "max_length": max(lengths),
                "clusters": len({rev_cluster.get(r) for r in rids if r in rev_cluster}),
            }

        # Generate recommendations
        recommendations: list[str] = []
        severity_counts = {"warning": 0, "info": 0}
        for issue in issues:
            severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1

        if severity_counts["warning"] == 0:
            recommendations.append("Corpus quality looks good — no warnings detected")
        if severity_counts["warning"] > 3:
            recommendations.append("Multiple warnings — consider a cleanup pass before querying")
        if len(source_chunks) == 1:
            recommendations.append("Single-source corpus — consider adding more sources for richer cross-referencing")

        return {
            "summary": {
                "total_chunks": total_chunks,
                "total_sources": len(source_chunks),
                "total_clusters": len(clusters),
                "issues": len(issues),
                "warnings": severity_counts.get("warning", 0),
            },
            "issues": issues,
            "per_source": per_source,
            "recommendations": recommendations,
        }

    def render_quality_report(self, report: dict[str, Any] | None = None) -> str:
        """Render a quality report as human-readable text.

        Args:
            report: Output from quality_report(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if report is None:
            report = self.quality_report()

        lines: list[str] = []
        s = report["summary"]
        lines.append("=" * 60)
        lines.append("  CORPUS QUALITY REPORT")
        lines.append("=" * 60)
        lines.append(f"  Chunks: {s['total_chunks']}  |  Sources: {s['total_sources']}  |  Clusters: {s['total_clusters']}")
        lines.append(f"  Issues: {s['issues']} ({s['warnings']} warnings)")
        lines.append("")

        if report["issues"]:
            lines.append("  ISSUES:")
            lines.append("-" * 60)
            for issue in report["issues"]:
                icon = "!!" if issue["severity"] == "warning" else ".."
                lines.append(f"  [{icon}] {issue['description']}")
                lines.append(f"       -> {issue['suggestion']}")
                lines.append("")
        else:
            lines.append("  No issues detected.")
            lines.append("")

        if report["per_source"]:
            lines.append("  PER-SOURCE STATS:")
            lines.append("-" * 60)
            for source, stats in sorted(
                report["per_source"].items(), key=lambda x: -x[1]["chunks"]
            ):
                name = source[:45]
                lines.append(
                    f"  {name:<45s} {stats['chunks']:4d} chunks  "
                    f"avg {stats['avg_length']:4d} chars  "
                    f"{stats['clusters']} clusters"
                )
            lines.append("")

        if report["recommendations"]:
            lines.append("  RECOMMENDATIONS:")
            lines.append("-" * 60)
            for rec in report["recommendations"]:
                lines.append(f"  - {rec}")
            lines.append("")

        return "\n".join(lines)

    def render_browse(self, result: dict[str, Any]) -> str:
        """Render browse_cluster or browse_source result as human-readable text.

        Args:
            result: Output from browse_cluster() or browse_source().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []

        if "cluster_id" in result:
            lines.append(f"  Cluster {result['cluster_id']}: {result['total_members']} chunks (showing {result['showing']})")
        else:
            lines.append(f"  Source: {result['source']} — {result['total_chunks']} chunks (showing {result['showing']})")

        lines.append("-" * 60)

        for i, chunk in enumerate(result.get("chunks", []), 1):
            source = chunk.get("source", "")
            page = chunk.get("page", "")
            page_str = f" p.{page}" if page else ""
            cluster = chunk.get("cluster_id")
            cluster_str = f" [c{cluster}]" if cluster is not None else ""
            lines.append(f"  {i}. {source}{page_str}{cluster_str} ({chunk['length']} chars)")
            lines.append(f"     {chunk['preview']}")
            lines.append("")

        return "\n".join(lines)

    def render_chunk_detail(self, detail: dict[str, Any]) -> str:
        """Render chunk_detail result as human-readable text.

        Args:
            detail: Output from chunk_detail().

        Returns:
            Formatted text string.
        """
        if not detail.get("found"):
            return f"  Chunk {detail['revision_id']}: not found"

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"  CHUNK DETAIL: {detail['revision_id'][:40]}")
        lines.append("=" * 60)
        lines.append(f"  Source:     {detail['source']}")
        lines.append(f"  Status:    {detail['status']}")
        lines.append(f"  Length:    {detail['length']} chars")
        lines.append(f"  Cluster:   {detail.get('cluster_id', 'N/A')}")
        lines.append(f"  Confidence: {detail['confidence_bp']}bp")

        if detail.get("page"):
            lines.append(f"  Page:      {detail['page']}")

        lines.append("")
        lines.append("  TEXT:")
        lines.append("-" * 60)
        lines.append(f"  {detail['text']}")
        lines.append("")

        if detail.get("neighbors"):
            lines.append(f"  NEIGHBORS ({len(detail['neighbors'])}):")
            lines.append("-" * 60)
            for n in detail["neighbors"]:
                lines.append(f"  [{n['weight']:.4f}] {n['source']}")
                lines.append(f"    {n['preview'][:120]}...")
                lines.append("")

        return "\n".join(lines)

    # ---- Temporal Analysis ----

    def ingestion_timeline(self) -> list[dict[str, Any]]:
        """Show when knowledge was added over time (ingestion timeline).

        Returns a chronological list of ingestion events grouped by
        transaction time, showing what was added and from which source.

        Returns:
            List of dicts with tx_id, timestamp, source, chunk_count.
        """
        tx_groups: dict[int, dict[str, Any]] = {}

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            ct = core.claim_type
            if ct.startswith("dks."):
                continue  # Skip internal claims

            tx_id = rev.transaction_time.tx_id
            if tx_id not in tx_groups:
                tx_groups[tx_id] = {
                    "tx_id": tx_id,
                    "timestamp": rev.transaction_time.recorded_at,
                    "sources": {},
                    "chunk_count": 0,
                }

            source = core.slots.get("source", "unknown")
            tx_groups[tx_id]["sources"][source] = (
                tx_groups[tx_id]["sources"].get(source, 0) + 1
            )
            tx_groups[tx_id]["chunk_count"] += 1

        result = []
        for info in sorted(tx_groups.values(), key=lambda x: x["timestamp"]):
            result.append({
                "tx_id": info["tx_id"],
                "timestamp": info["timestamp"].isoformat(),
                "sources": dict(info["sources"]),
                "chunk_count": info["chunk_count"],
            })

        return result

    def scan_contradictions(self, *, k: int = 10, threshold: float = 0.6) -> list[dict[str, Any]]:
        """Scan entire corpus for claims that potentially contradict each other.

        Unlike contradictions(topic), this scans all chunks without a topic filter.
        Uses search similarity to find related chunks, then checks for
        negation patterns and opposing assertions. Works purely with
        text heuristics (no LLM required).

        Args:
            k: Number of candidate pairs to evaluate.
            threshold: Minimum similarity to consider as related.

        Returns:
            List of contradiction pairs with evidence.
        """
        # Negation signals that suggest contradiction
        negation_markers = {
            "not", "no", "never", "neither", "nor", "cannot", "can't",
            "don't", "doesn't", "didn't", "won't", "wouldn't", "isn't",
            "aren't", "wasn't", "weren't", "hardly", "rarely", "seldom",
            "without", "lack", "fail", "false", "incorrect", "wrong",
            "unlike", "contrary", "however", "but", "although", "despite",
            "rather than", "instead of", "on the other hand",
        }

        contrast_phrases = {
            "in contrast", "on the contrary", "conversely", "whereas",
            "while others", "some argue", "critics", "challenged",
            "disputed", "debated", "controversial", "disagree",
        }

        results: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        # Get all asserted document chunks
        doc_revisions = []
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.claim_type.startswith("dks."):
                continue
            doc_revisions.append((rid, rev))

        # For each chunk, search for related chunks from different sources
        for rid, rev in doc_revisions:
            if len(results) >= k:
                break

            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "") if core else ""

            # Search for similar content
            search_results = self.query(rev.assertion[:200], k=5)

            for sr in search_results:
                if sr.revision_id == rid:
                    continue
                if sr.score < threshold:
                    continue

                # Get candidate
                cand_rev = self.store.revisions.get(sr.revision_id)
                if cand_rev is None:
                    continue
                cand_core = self.store.cores.get(cand_rev.core_id)
                cand_source = cand_core.slots.get("source", "") if cand_core else ""

                # Skip same-source pairs
                if source == cand_source:
                    continue

                pair_key = tuple(sorted([rid, sr.revision_id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Check for negation asymmetry
                text_a = rev.assertion.lower()
                text_b = cand_rev.assertion.lower()

                neg_a = sum(1 for m in negation_markers if m in text_a)
                neg_b = sum(1 for m in negation_markers if m in text_b)
                negation_diff = abs(neg_a - neg_b)

                contrast_a = sum(1 for p in contrast_phrases if p in text_a)
                contrast_b = sum(1 for p in contrast_phrases if p in text_b)

                # Score the contradiction likelihood
                score = 0.0
                evidence: list[str] = []

                if negation_diff >= 2:
                    score += 0.4
                    evidence.append(f"Negation asymmetry ({neg_a} vs {neg_b})")
                elif negation_diff == 1:
                    score += 0.2
                    evidence.append("Mild negation difference")

                if contrast_a + contrast_b > 0:
                    score += 0.3
                    evidence.append("Contains contrast language")

                # Different temporal context can indicate evolving understanding
                if rev.valid_time.start and cand_rev.valid_time.start:
                    time_gap = abs(
                        (rev.valid_time.start - cand_rev.valid_time.start).days
                    )
                    if time_gap > 365:
                        score += 0.1
                        evidence.append(f"Published {time_gap // 365}+ years apart")

                if score >= 0.2:
                    results.append({
                        "chunk_a": {
                            "revision_id": rid,
                            "source": source,
                            "text": rev.assertion[:300],
                        },
                        "chunk_b": {
                            "revision_id": sr.revision_id,
                            "source": cand_source,
                            "text": cand_rev.assertion[:300],
                        },
                        "similarity": round(sr.score, 4),
                        "contradiction_score": round(score, 3),
                        "evidence": evidence,
                    })

        # Sort by contradiction score
        results.sort(key=lambda x: -x["contradiction_score"])
        return results[:k]

    def evolution(self, topic: str, *, k: int = 20) -> dict[str, Any]:
        """Show how understanding of a topic has changed across documents.

        Retrieves chunks related to the topic and organizes them by
        temporal order, showing the progression of knowledge.

        Args:
            topic: The topic to trace evolution for.
            k: Max chunks to retrieve.

        Returns:
            Dict with topic, timeline of chunks ordered by valid_time,
            and source diversity info.
        """
        search_results = self.query(topic, k=k)

        entries: list[dict[str, Any]] = []
        sources_seen: set[str] = set()

        for sr in search_results:
            rev = self.store.revisions.get(sr.revision_id)
            if rev is None or rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            sources_seen.add(source)

            entries.append({
                "revision_id": sr.revision_id,
                "source": source,
                "text": rev.assertion[:400],
                "score": round(sr.score, 4),
                "valid_start": rev.valid_time.start.isoformat() if rev.valid_time.start else None,
                "ingested_at": rev.transaction_time.recorded_at.isoformat(),
            })

        # Sort by valid_time (earliest first)
        entries.sort(
            key=lambda x: x["valid_start"] or "9999"
        )

        return {
            "topic": topic,
            "total_chunks": len(entries),
            "source_count": len(sources_seen),
            "sources": sorted(sources_seen),
            "timeline": entries,
        }

    def staleness_report(self, *, age_days: int = 365) -> dict[str, Any]:
        """Identify old claims that may need updating.

        Flags chunks whose valid_time start is older than the threshold,
        grouped by source.

        Args:
            age_days: Chunks older than this are flagged as stale.

        Returns:
            Dict with stale_count, by_source breakdown, and oldest chunks.
        """
        from datetime import timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)

        stale: list[dict[str, Any]] = []
        by_source: dict[str, int] = {}

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.claim_type.startswith("dks."):
                continue

            vt_start = rev.valid_time.start
            if vt_start and vt_start.tzinfo is None:
                from datetime import timezone as tz
                vt_start = vt_start.replace(tzinfo=tz.utc)

            if vt_start and vt_start < cutoff:
                source = core.slots.get("source", "unknown")
                by_source[source] = by_source.get(source, 0) + 1
                stale.append({
                    "revision_id": rid,
                    "source": source,
                    "valid_start": vt_start.isoformat(),
                    "age_days": (datetime.now(timezone.utc) - vt_start).days,
                    "preview": rev.assertion[:150],
                })

        # Sort by age (oldest first)
        stale.sort(key=lambda x: -x["age_days"])

        return {
            "stale_count": len(stale),
            "threshold_days": age_days,
            "by_source": by_source,
            "oldest": stale[:20],
        }

    def render_timeline(self, timeline: list[dict[str, Any]] | None = None) -> str:
        """Render ingestion_timeline() output as human-readable text.

        Args:
            timeline: Output from ingestion_timeline(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if timeline is None:
            timeline = self.ingestion_timeline()

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  INGESTION TIMELINE")
        lines.append("=" * 60)

        for event in timeline:
            ts = event["timestamp"][:19]  # Trim to seconds
            sources = ", ".join(
                f"{s} ({c})" for s, c in event["sources"].items()
            )
            lines.append(f"  [{ts}] TX-{event['tx_id']}: {event['chunk_count']} chunks")
            lines.append(f"    Sources: {sources}")
            lines.append("")

        if not timeline:
            lines.append("  No ingestion events recorded.")

        return "\n".join(lines)

    def render_evolution(self, result: dict[str, Any]) -> str:
        """Render evolution() output as human-readable text.

        Args:
            result: Output from evolution().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"  TOPIC EVOLUTION: {result['topic']}")
        lines.append("=" * 60)
        lines.append(f"  {result['total_chunks']} chunks across {result['source_count']} sources")
        lines.append("")

        for entry in result["timeline"]:
            date = entry["valid_start"][:10] if entry["valid_start"] else "unknown"
            lines.append(f"  [{date}] {entry['source'][:40]} (score: {entry['score']})")
            lines.append(f"    {entry['text'][:150].replace(chr(10), ' ')}...")
            lines.append("")

        return "\n".join(lines)

    def render_contradictions(self, pairs: list[dict[str, Any]]) -> str:
        """Render contradictions() output as human-readable text.

        Args:
            pairs: Output from contradictions().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  POTENTIAL CONTRADICTIONS")
        lines.append("=" * 60)

        if not pairs:
            lines.append("  No contradictions detected.")
            return "\n".join(lines)

        for i, pair in enumerate(pairs, 1):
            lines.append(f"  #{i} (score: {pair['contradiction_score']}, similarity: {pair['similarity']})")
            lines.append(f"    Evidence: {', '.join(pair['evidence'])}")
            lines.append(f"    A [{pair['chunk_a']['source'][:30]}]:")
            lines.append(f"      {pair['chunk_a']['text'][:150].replace(chr(10), ' ')}...")
            lines.append(f"    B [{pair['chunk_b']['source'][:30]}]:")
            lines.append(f"      {pair['chunk_b']['text'][:150].replace(chr(10), ' ')}...")
            lines.append("")

        return "\n".join(lines)

    # ---- Source Comparison ----

    def compare_sources(
        self,
        source_a: str,
        source_b: str,
        *,
        similarity_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Compare two source documents for overlap and divergence.

        Analyzes shared topics, unique content, overlapping chunks,
        and potential contradictions between two sources.

        Args:
            source_a: First source identifier.
            source_b: Second source identifier.
            similarity_threshold: Min similarity to consider overlap.

        Returns:
            Dict with overlap_pairs, unique_to_a, unique_to_b,
            shared_topics, and comparison summary.
        """
        # Collect chunks per source
        chunks_a: list[tuple[str, str]] = []  # (rid, text)
        chunks_b: list[tuple[str, str]] = []

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            source = core.slots.get("source", "")
            if source == source_a:
                chunks_a.append((rid, rev.assertion))
            elif source == source_b:
                chunks_b.append((rid, rev.assertion))

        if not chunks_a or not chunks_b:
            return {
                "source_a": source_a,
                "source_b": source_b,
                "found_a": bool(chunks_a),
                "found_b": bool(chunks_b),
                "overlap_pairs": [],
                "unique_to_a": len(chunks_a),
                "unique_to_b": len(chunks_b),
                "similarity_summary": "Cannot compare — one or both sources empty",
            }

        # Find overlapping chunks using search
        overlap_pairs: list[dict[str, Any]] = []
        matched_a: set[str] = set()
        matched_b: set[str] = set()

        for rid_a, text_a in chunks_a:
            results = self.query(text_a[:200], k=5)
            for sr in results:
                if sr.revision_id == rid_a:
                    continue
                if sr.score < similarity_threshold:
                    continue
                # Check if this result is from source_b
                cand_rev = self.store.revisions.get(sr.revision_id)
                if cand_rev is None:
                    continue
                cand_core = self.store.cores.get(cand_rev.core_id)
                if cand_core and cand_core.slots.get("source") == source_b:
                    pair_key = tuple(sorted([rid_a, sr.revision_id]))
                    if pair_key not in {tuple(sorted([p["rid_a"], p["rid_b"]])) for p in overlap_pairs}:
                        overlap_pairs.append({
                            "rid_a": rid_a,
                            "rid_b": sr.revision_id,
                            "similarity": round(sr.score, 4),
                            "text_a": text_a[:200],
                            "text_b": cand_rev.assertion[:200],
                        })
                        matched_a.add(rid_a)
                        matched_b.add(sr.revision_id)

        # Sort by similarity
        overlap_pairs.sort(key=lambda x: -x["similarity"])

        # Extract topic words from overlapping chunks
        shared_words: dict[str, int] = {}
        for pair in overlap_pairs:
            words = set(pair["text_a"].lower().split()) & set(pair["text_b"].lower().split())
            for w in words:
                if len(w) > 3:
                    shared_words[w] = shared_words.get(w, 0) + 1

        shared_topics = sorted(shared_words, key=lambda w: -shared_words[w])[:10]

        unique_a = len(chunks_a) - len(matched_a)
        unique_b = len(chunks_b) - len(matched_b)

        # Generate summary
        overlap_pct_a = len(matched_a) / len(chunks_a) * 100 if chunks_a else 0
        overlap_pct_b = len(matched_b) / len(chunks_b) * 100 if chunks_b else 0

        return {
            "source_a": source_a,
            "source_b": source_b,
            "found_a": True,
            "found_b": True,
            "chunks_a": len(chunks_a),
            "chunks_b": len(chunks_b),
            "overlap_pairs": overlap_pairs[:20],
            "overlap_count": len(overlap_pairs),
            "unique_to_a": unique_a,
            "unique_to_b": unique_b,
            "shared_topics": shared_topics,
            "overlap_pct_a": round(overlap_pct_a, 1),
            "overlap_pct_b": round(overlap_pct_b, 1),
        }

    def render_comparison(self, result: dict[str, Any]) -> str:
        """Render compare_sources() result as human-readable text.

        Args:
            result: Output from compare_sources().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  SOURCE COMPARISON")
        lines.append("=" * 60)
        lines.append(f"  A: {result['source_a']}")
        lines.append(f"  B: {result['source_b']}")

        if not result.get("found_a") or not result.get("found_b"):
            lines.append(f"  {result.get('similarity_summary', 'Missing source(s)')}")
            return "\n".join(lines)

        lines.append(f"  A chunks: {result['chunks_a']}  |  B chunks: {result['chunks_b']}")
        lines.append(f"  Overlapping pairs: {result['overlap_count']}")
        lines.append(f"  A overlap: {result['overlap_pct_a']}%  |  B overlap: {result['overlap_pct_b']}%")
        lines.append(f"  Unique to A: {result['unique_to_a']}  |  Unique to B: {result['unique_to_b']}")
        lines.append("")

        if result.get("shared_topics"):
            lines.append(f"  Shared topics: {', '.join(result['shared_topics'][:8])}")
            lines.append("")

        if result.get("overlap_pairs"):
            lines.append("  TOP OVERLAPPING PAIRS:")
            lines.append("-" * 60)
            for pair in result["overlap_pairs"][:5]:
                lines.append(f"  [{pair['similarity']:.3f}]")
                lines.append(f"    A: {pair['text_a'][:120].replace(chr(10), ' ')}...")
                lines.append(f"    B: {pair['text_b'][:120].replace(chr(10), ' ')}...")
                lines.append("")

        return "\n".join(lines)

    # ---- Corpus Insights ----

    def insights(self) -> dict[str, Any]:
        """Generate proactive insights and recommendations for corpus improvement.

        Combines quality report, staleness, contradiction scanning, and
        corpus statistics into a prioritized list of actionable suggestions.

        Returns:
            Dict with prioritized actions, corpus health score, and suggestions.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        actions: list[dict[str, Any]] = []

        # 1. Quality issues
        qr = self.quality_report()
        for issue in qr["issues"]:
            priority = 1 if issue["severity"] == "warning" else 2
            actions.append({
                "priority": priority,
                "category": "quality",
                "action": issue["suggestion"],
                "detail": issue["description"],
            })

        # 2. Staleness
        stale = self.staleness_report(age_days=365)
        if stale["stale_count"] > 0:
            pct = stale["stale_count"] / max(qr["summary"]["total_chunks"], 1) * 100
            actions.append({
                "priority": 2 if pct < 30 else 1,
                "category": "freshness",
                "action": f"Review {stale['stale_count']} stale chunks ({pct:.0f}% of corpus)",
                "detail": f"Chunks older than 365 days across {len(stale['by_source'])} sources",
            })

        # 3. Source coverage gaps
        sources = self.list_sources()
        if len(sources) == 1:
            actions.append({
                "priority": 1,
                "category": "coverage",
                "action": "Add more sources for richer cross-referencing",
                "detail": "Single-source corpus limits search and contradiction detection",
            })
        elif len(sources) >= 2:
            biggest = sources[0]["chunks"]
            total = sum(s["chunks"] for s in sources)
            if biggest / total > 0.5:
                actions.append({
                    "priority": 2,
                    "category": "balance",
                    "action": f"Corpus dominated by '{sources[0]['source'][:40]}' ({biggest}/{total} chunks)",
                    "detail": "Consider adding more sources on underrepresented topics",
                })

        # 4. Entity review suggestions
        try:
            review = self.review_entities(top_k=20)
            if review["flagged"]:
                actions.append({
                    "priority": 2,
                    "category": "entities",
                    "action": f"Review {len(review['flagged'])} flagged entities for quality",
                    "detail": "Use accept_entities/reject_entities to curate",
                })
        except Exception:
            pass

        # Sort by priority
        actions.sort(key=lambda x: x["priority"])

        # Health score (0-100)
        warning_count = qr["summary"].get("warnings", 0)
        health = max(0, 100 - warning_count * 15 - min(stale["stale_count"], 10) * 3)

        return {
            "health_score": health,
            "total_actions": len(actions),
            "actions": actions,
            "summary": {
                "chunks": qr["summary"]["total_chunks"],
                "sources": qr["summary"]["total_sources"],
                "clusters": qr["summary"]["total_clusters"],
                "stale": stale["stale_count"],
                "warnings": warning_count,
            },
        }

    def suggest_queries(self, *, n: int = 5) -> list[dict[str, str]]:
        """Suggest interesting queries to explore based on corpus content.

        Analyzes cluster labels and source topics to generate query
        suggestions that would exercise different parts of the knowledge base.

        Args:
            n: Number of suggestions to generate.

        Returns:
            List of dicts with query text and rationale.
        """
        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        suggestions: list[dict[str, str]] = []

        # Get cluster labels
        topics = self.topics()
        top_clusters = sorted(topics, key=lambda x: -x["size"])

        # 1. Suggest queries from largest clusters (what corpus is ABOUT)
        for cluster in top_clusters[:min(2, len(top_clusters))]:
            labels = cluster.get("labels", [])
            if labels:
                q = " ".join(labels[:3])
                suggestions.append({
                    "query": q,
                    "rationale": f"Core topic ({cluster['size']} chunks)",
                    "type": "exploratory",
                })

        # 2. Cross-cluster queries (bridge different topics)
        if len(top_clusters) >= 2:
            labels_a = top_clusters[0].get("labels", [])[:2]
            labels_b = top_clusters[1].get("labels", [])[:2]
            if labels_a and labels_b:
                suggestions.append({
                    "query": f"How does {' '.join(labels_a)} relate to {' '.join(labels_b)}?",
                    "rationale": "Cross-topic bridge query",
                    "type": "reasoning",
                })

        # 3. Contradiction-probing queries
        if len(top_clusters) >= 1:
            labels = top_clusters[0].get("labels", [])
            if labels:
                suggestions.append({
                    "query": f"What are the debates about {labels[0]}?",
                    "rationale": "Probe for contradictory claims",
                    "type": "analytical",
                })

        # 4. Coverage gap query
        sources = self.list_sources()
        if sources:
            smallest = sources[-1]
            suggestions.append({
                "query": f"What does {smallest['source'][:40]} cover?",
                "rationale": f"Least-represented source ({smallest['chunks']} chunks)",
                "type": "coverage",
            })

        return suggestions[:n]

    def render_insights(self, result: dict[str, Any] | None = None) -> str:
        """Render insights() output as human-readable text.

        Args:
            result: Output from insights(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if result is None:
            result = self.insights()

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  CORPUS INSIGHTS")
        lines.append("=" * 60)

        health = result["health_score"]
        bar = "#" * (health // 5) + "-" * (20 - health // 5)
        lines.append(f"  Health: [{bar}] {health}/100")

        s = result["summary"]
        lines.append(f"  {s['chunks']} chunks | {s['sources']} sources | {s['clusters']} clusters")
        lines.append(f"  {s['stale']} stale | {s['warnings']} warnings")
        lines.append("")

        if result["actions"]:
            lines.append("  RECOMMENDED ACTIONS:")
            lines.append("-" * 60)
            for i, action in enumerate(result["actions"], 1):
                icon = "!!" if action["priority"] == 1 else ".."
                lines.append(f"  {i}. [{icon}] [{action['category']}] {action['action']}")
                lines.append(f"       {action['detail']}")
            lines.append("")
        else:
            lines.append("  No actions needed — corpus looks healthy!")
            lines.append("")

        return "\n".join(lines)

    def link_entities(
        self,
        *,
        min_entity_length: int = 3,
        min_shared_entities: int = 2,
        max_edges_per_node: int = 10,
    ) -> dict[str, Any]:
        """Create entity-based cross-references between chunks.

        Extracts key noun phrases from each chunk, finds chunks that share
        entities across different documents, and adds explicit edges to
        the knowledge graph. This enables multi-hop reasoning that follows
        actual conceptual links rather than just keyword similarity.

        Must be called AFTER build_graph().

        Args:
            min_entity_length: Minimum character length for an entity.
            min_shared_entities: Minimum shared entities to create a link.
            max_edges_per_node: Maximum entity edges per chunk.

        Returns:
            Dict with:
              - total_entities: int (unique entities found)
              - total_links: int (new graph edges added)
              - top_entities: list of (entity, count) tuples
        """
        import re
        from collections import Counter

        if not hasattr(self, "_graph") or self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        # Step 1: Statistical entity extraction
        #
        # Principled approach — no stopword lists, no hardcoded patterns.
        # The math decides what's noise vs. signal:
        #
        #   0. Detect boilerplate: sentences repeated across many documents
        #      are template text (footers, headers, signatures) — exclude them
        #   1. Tokenize each chunk into words (pure alphabetic only)
        #   2. Extract candidate unigrams and bigrams
        #   3. Compute IDF across all chunks — terms in too many or too few
        #      chunks are automatically excluded
        #   4. For bigrams, use PMI to keep only real collocations
        #   5. Per chunk, keep only the top-K most discriminative terms
        #
        import math
        from collections import Counter

        n_chunks = len(self.store.revisions)
        if n_chunks == 0:
            return {"total_entities": 0, "total_links": 0, "top_entities": []}

        # IDF band: only keep terms appearing in [min_df, max_df] fraction of chunks
        # Scale gracefully: small corpus (< 50 chunks) uses min_df=2, large uses 3+
        min_df = 2 if n_chunks < 50 else max(3, int(n_chunks * 0.004))
        max_df_frac = 0.10 if n_chunks > 100 else 0.50  # More lenient for small corpora
        max_df = max(min_df + 1, int(n_chunks * max_df_frac))

        # Step 0: Boilerplate detection
        # Sentences that appear in many different source documents are template
        # text (newsletter footers, author bios, social links). We detect these
        # by hashing normalized sentences and counting source-document frequency.
        import hashlib

        sentence_sources: dict[str, set[str]] = {}  # sentence_hash -> source set
        chunk_boilerplate: dict[str, set[str]] = {}  # rev_id -> set of boilerplate hashes

        for rev_id, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", rev_id) if core else rev_id
            # Split into sentences (simple split on . ! ? followed by space/newline)
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            hashes = set()
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.lower().strip())
                if len(normed) < 20:
                    continue  # Too short to be meaningful boilerplate
                h = hashlib.md5(normed.encode()).hexdigest()[:12]
                hashes.add(h)
                sentence_sources.setdefault(h, set()).add(source)
            chunk_boilerplate[rev_id] = hashes

        # A sentence appearing in >5% of source documents is boilerplate
        n_sources = len({
            (self.store.cores.get(r.core_id).slots.get("source", rid)
             if self.store.cores.get(r.core_id) else rid)
            for rid, r in self.store.revisions.items()
        })
        boilerplate_threshold = max(3, int(n_sources * 0.05))
        boilerplate_hashes = {
            h for h, sources in sentence_sources.items()
            if len(sources) >= boilerplate_threshold
        }

        # For each chunk, build clean text (boilerplate sentences removed)
        chunk_clean_text: dict[str, str] = {}
        for rev_id, rev in self.store.revisions.items():
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            clean_parts = []
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.lower().strip())
                if len(normed) < 20:
                    clean_parts.append(sent)
                    continue
                h = hashlib.md5(normed.encode()).hexdigest()[:12]
                if h not in boilerplate_hashes:
                    clean_parts.append(sent)
            chunk_clean_text[rev_id] = " ".join(clean_parts)

        # Tokenize: pure alphabetic words (3+ chars) — excludes URLs,
        # hashes, codes, mixed alphanumeric noise. Acronyms (2+ uppercase)
        # are extracted separately and kept as-is.
        word_re = re.compile(r'\b([a-z]{3,})\b')
        acronym_re = re.compile(r'\b([A-Z]{2,})\b')

        # Pass 1: Collect document frequencies for unigrams and bigrams
        chunk_tokens: dict[str, list[str]] = {}  # rev_id -> token list
        chunk_acronyms: dict[str, set[str]] = {}  # rev_id -> acronym set
        unigram_df: Counter = Counter()   # term -> num chunks containing it
        bigram_df: Counter = Counter()    # "w1 w2" -> num chunks containing it
        unigram_tf_total: Counter = Counter()  # total corpus frequency
        acronym_df: Counter = Counter()   # ACRONYM -> num chunks containing it

        for rev_id in self.store.revisions:
            text = chunk_clean_text.get(rev_id, "")
            tokens = word_re.findall(text.lower())
            chunk_tokens[rev_id] = tokens

            # Extract acronyms separately (from clean text)
            acrs = set(acronym_re.findall(text))
            chunk_acronyms[rev_id] = acrs
            for acr in acrs:
                acronym_df[acr] += 1

            # Unique terms in this chunk (for DF counting)
            unique_unigrams = set(tokens)
            for t in unique_unigrams:
                unigram_df[t] += 1
                unigram_tf_total[t] += tokens.count(t)

            # Unique bigrams in this chunk
            unique_bigrams = set()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                unique_bigrams.add(bg)
            for bg in unique_bigrams:
                bigram_df[bg] += 1

        # Filter acronyms by IDF band (same as words)
        good_acronyms: dict[str, float] = {}
        for acr, df in acronym_df.items():
            if df < min_df or df > max_df:
                continue
            if len(acr) < 2:
                continue
            good_acronyms[acr] = math.log(n_chunks / df)

        # Identify function/ubiquitous words from the data: words appearing
        # in >50% of chunks. These are grammar words and corpus boilerplate.
        # Derived entirely from corpus statistics, no hardcoded lists.
        function_threshold = max(n_chunks // 2, 5)
        function_words = {
            term for term, df in unigram_df.items()
            if df > function_threshold
        }

        # Pass 2: Compute IDF scores, filter to informative band
        # IDF = log(N / df) — higher = more discriminative
        good_unigrams: dict[str, float] = {}
        for term, df in unigram_df.items():
            if df < min_df or df > max_df:
                continue
            if len(term) < min_entity_length:
                continue
            if term in function_words:
                continue
            good_unigrams[term] = math.log(n_chunks / df)

        # For bigrams: require IDF band + positive PMI
        # PMI(w1, w2) = log(P(w1,w2) / (P(w1) * P(w2)))
        # Positive PMI means the words co-occur more than chance
        total_tokens = sum(len(t) for t in chunk_tokens.values())
        total_bigrams = max(total_tokens - n_chunks, 1)  # approximate

        # For bigrams, also track source-document frequency
        # (a bigram only from one doc's boilerplate isn't a real entity)
        bigram_sources: dict[str, set[str]] = {}
        for rev_id in self.store.revisions:
            core = self.store.cores.get(self.store.revisions[rev_id].core_id)
            source = core.slots.get("source", rev_id) if core else rev_id
            tokens = chunk_tokens.get(rev_id, [])
            seen_bg: set[str] = set()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                if bg not in seen_bg:
                    seen_bg.add(bg)
                    bigram_sources.setdefault(bg, set()).add(source)

        good_bigrams: dict[str, float] = {}
        for bigram, df in bigram_df.items():
            if df < min_df or df > max_df:
                continue
            w1, w2 = bigram.split(" ", 1)
            if len(w1) < 3 or len(w2) < 3:
                continue
            # Cross-source requirement: must appear in 2+ source docs
            # (skip for tiny corpora with <=4 sources)
            min_bg_sources = 2 if n_sources > 4 else 1
            if len(bigram_sources.get(bigram, set())) < min_bg_sources:
                continue
            # Neither component can be a function word
            if w1 in function_words or w2 in function_words:
                continue
            # PMI filter: keep only collocations
            p_bigram = df / max(n_chunks, 1)
            p_w1 = unigram_df.get(w1, 1) / max(n_chunks, 1)
            p_w2 = unigram_df.get(w2, 1) / max(n_chunks, 1)
            pmi = math.log(max(p_bigram, 1e-10) / max(p_w1 * p_w2, 1e-10))
            if pmi <= 0.5:
                continue  # Require meaningful collocation (PMI > 0.5)
            # IDF of the bigram, weighted by source diversity
            idf = math.log(n_chunks / df)
            n_bg_sources = len(bigram_sources.get(bigram, set()))
            # Source ratio: fraction of distinct sources vs chunks containing it
            # High ratio = appears broadly across docs (technical term)
            # Low ratio = concentrated in few docs (single-author boilerplate)
            source_ratio = n_bg_sources / max(df, 1)
            good_bigrams[bigram] = idf * (1 + pmi) * (1 + source_ratio)

        # Pass 3: For each chunk, select top-K discriminative entities
        max_entities_per_chunk = 15

        chunk_entities: dict[str, set[str]] = {}
        entity_chunks: dict[str, set[str]] = {}

        for rev_id, tokens in chunk_tokens.items():
            # Score candidates by TF-IDF
            token_counts = Counter(tokens)
            candidates: list[tuple[str, float]] = []

            # Unigram candidates
            for term, count in token_counts.items():
                if term in good_unigrams:
                    tf = 1 + math.log(count)  # Sublinear TF
                    score = tf * good_unigrams[term]
                    candidates.append((term, score))

            # Bigram candidates
            bigram_counts: Counter = Counter()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                bigram_counts[bg] += 1

            for bg, count in bigram_counts.items():
                if bg in good_bigrams:
                    tf = 1 + math.log(count)
                    score = tf * good_bigrams[bg]
                    candidates.append((bg, score))

            # Acronym candidates
            for acr in chunk_acronyms.get(rev_id, set()):
                if acr in good_acronyms:
                    candidates.append((acr, good_acronyms[acr]))

            # Take top-K by score
            candidates.sort(key=lambda x: -x[1])
            entities = set()
            for term, _ in candidates[:max_entities_per_chunk]:
                entities.add(term)

            chunk_entities[rev_id] = entities
            for entity in entities:
                entity_chunks.setdefault(entity, set()).add(rev_id)

        # Pass 4: Cluster-spread filter
        # Remove entities that only appear within a single topical cluster.
        # Boilerplate entities ("chocolate milk") appear in many chunks but
        # always alongside the same newsletter content = same cluster.
        # Real technical entities ("neural networks") span diverse topics.
        rev_to_cluster = getattr(self._graph, '_revision_cluster', None)
        if rev_to_cluster and len(rev_to_cluster) > 0 and n_chunks > 50:
            # Only apply cluster filter on large enough corpora where
            # clustering is meaningful. For small corpora (<50 chunks),
            # the clusters are too coarse to be a useful filter.
            n_actual_clusters = len(set(rev_to_cluster.values()))
            min_clusters = 2 if n_actual_clusters >= 5 else 1
            filtered_entity_chunks: dict[str, set[str]] = {}
            for entity, rev_ids in entity_chunks.items():
                clusters = set()
                for rid in rev_ids:
                    cid = rev_to_cluster.get(rid)
                    if cid is not None:
                        clusters.add(cid)
                if len(clusters) >= min_clusters:
                    filtered_entity_chunks[entity] = rev_ids
            entity_chunks = filtered_entity_chunks

            # Rebuild chunk_entities to only include surviving entities
            for rev_id in chunk_entities:
                chunk_entities[rev_id] = {
                    e for e in chunk_entities[rev_id]
                    if e in entity_chunks
                }

        # Pass 5: Apply user entity decisions (reject list)
        decisions = self.get_entity_decisions()
        rejected = {e for e, d in decisions.items() if d == "rejected"}
        if rejected:
            for rev_id in chunk_entities:
                chunk_entities[rev_id] -= rejected
            entity_chunks = {
                e: rids for e, rids in entity_chunks.items()
                if e not in rejected
            }

        # Step 2: Find cross-document entity links
        # For each pair of chunks from different sources, count shared entities
        total_links = 0

        for rev_id, entities in chunk_entities.items():
            core = self.store.cores.get(
                self.store.revisions[rev_id].core_id
            )
            source = core.slots.get("source", "") if core else ""

            # Find candidate neighbors via shared entities
            neighbor_scores: dict[str, int] = {}
            for entity in entities:
                for other_id in entity_chunks.get(entity, set()):
                    if other_id == rev_id:
                        continue
                    # Only cross-document links
                    other_core = self.store.cores.get(
                        self.store.revisions[other_id].core_id
                    )
                    other_source = other_core.slots.get("source", "") if other_core else ""
                    if other_source == source:
                        continue
                    neighbor_scores[other_id] = neighbor_scores.get(other_id, 0) + 1

            # Add edges for chunks with enough shared entities
            edges_added = 0
            for neighbor_id, shared_count in sorted(
                neighbor_scores.items(), key=lambda x: -x[1]
            ):
                if shared_count < min_shared_entities:
                    break
                if edges_added >= max_edges_per_node:
                    break

                # Add to graph (score = shared entity count / max possible)
                max_shared = min(len(chunk_entities.get(rev_id, set())),
                                 len(chunk_entities.get(neighbor_id, set())))
                edge_score = shared_count / max(max_shared, 1)

                if rev_id not in self._graph._adjacency:
                    self._graph._adjacency[rev_id] = []
                # Check if edge already exists
                existing = {nid for nid, _ in self._graph._adjacency.get(rev_id, [])}
                if neighbor_id not in existing:
                    self._graph._adjacency[rev_id].append((neighbor_id, edge_score))
                    total_links += 1
                    edges_added += 1

        # Compute stats
        all_entities = set()
        for entities in chunk_entities.values():
            all_entities.update(entities)

        entity_counts = Counter()
        for entity, chunks in entity_chunks.items():
            if len(chunks) >= 2:  # Only entities appearing in multiple chunks
                entity_counts[entity] = len(chunks)

        return {
            "total_entities": len(all_entities),
            "total_links": total_links,
            "top_entities": entity_counts.most_common(20),
        }

    # ---- Reasoning Layer ----

    def reason(
        self,
        question: str,
        *,
        k: int = 5,
        hops: int = 2,
        expand_k: int = 3,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> ReasoningResult:
        """Multi-hop retrieval: iteratively expand context to answer complex questions.

        Unlike simple query(), reason() performs multiple retrieval rounds:
        1. Initial retrieval: get top-k chunks for the question
        2. Extract key terms from retrieved chunks
        3. Expand: query with extracted terms to find related context
        4. Repeat for `hops` iterations
        5. Deduplicate and rank all found chunks

        Args:
            question: Natural language question.
            k: Results per hop.
            hops: Number of expansion rounds.
            expand_k: Number of expansion queries per hop.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            ReasoningResult with all retrieved chunks, sources, and reasoning trace.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        all_results: dict[str, SearchResult] = {}  # revision_id -> result
        trace: list[dict[str, Any]] = []
        seen_queries: set[str] = set()

        # Hop 0: initial retrieval
        initial = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in initial:
            all_results[r.revision_id] = r
        trace.append({
            "hop": 0,
            "query": question,
            "results": len(initial),
            "new": len(initial),
        })
        seen_queries.add(question.lower().strip())

        # Expansion hops
        for hop in range(1, hops + 1):
            # Extract key terms from current results
            expansion_terms = self._extract_expansion_terms(
                list(all_results.values()),
                seen_queries,
                max_terms=expand_k,
            )

            new_this_hop = 0
            for term in expansion_terms:
                if term.lower().strip() in seen_queries:
                    continue
                seen_queries.add(term.lower().strip())

                hop_results = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in hop_results:
                    if r.revision_id not in all_results:
                        all_results[r.revision_id] = r
                        new_this_hop += 1

            trace.append({
                "hop": hop,
                "expansion_terms": expansion_terms,
                "new": new_this_hop,
                "total": len(all_results),
            })

            if new_this_hop == 0:
                break  # No new information found

        # Rank all results by relevance to original question
        final_results = self._rerank_for_question(
            question, list(all_results.values())
        )

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return ReasoningResult(
            question=question,
            results=final_results,
            sources=sources,
            trace=trace,
            total_hops=len(trace) - 1,
        )

    def discover(
        self,
        seed_query: str,
        *,
        k: int = 5,
        depth: int = 2,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Discover related knowledge by traversing the similarity graph.

        Starting from seed results, find progressively more distant but
        related chunks. Useful for exploratory analysis.

        Args:
            seed_query: Starting query.
            k: Results per expansion.
            depth: How many levels of expansion.
            similarity_threshold: Minimum score to follow.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            All discovered chunks, ordered by discovery path.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        discovered: dict[str, SearchResult] = {}
        frontier: list[str] = []  # queries to explore

        # Start with seed
        seed_results = self.query(seed_query, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in seed_results:
            if r.score >= similarity_threshold:
                discovered[r.revision_id] = r
                # Extract text snippets as new queries
                frontier.append(r.text[:200])

        for level in range(depth):
            new_frontier: list[str] = []
            for text in frontier[:k]:
                # Use first few significant words as expansion query
                words = text.split()[:10]
                expansion = " ".join(words)
                results = self.query(expansion, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    if r.revision_id not in discovered and r.score >= similarity_threshold:
                        discovered[r.revision_id] = r
                        new_frontier.append(r.text[:200])
            frontier = new_frontier
            if not frontier:
                break

        return list(discovered.values())

    def coverage(
        self,
        topic: str,
        *,
        k: int = 20,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> CoverageReport:
        """Analyze what the store knows about a topic.

        Returns a structured report of all related knowledge, grouped by
        source document and subtopic.

        Args:
            topic: Topic to analyze.
            k: Maximum chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            CoverageReport with sources, subtopics, and gap analysis.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)

        # Group by source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Extract subtopics (key terms from results)
        all_text = " ".join(r.text for r in results)
        subtopics = self._extract_key_terms(all_text, max_terms=10)

        return CoverageReport(
            topic=topic,
            total_chunks=len(results),
            sources=by_source,
            subtopics=subtopics,
            source_count=len(by_source),
        )

    def evidence_chain(
        self,
        claim: str,
        *,
        k: int = 5,
        max_chain_length: int = 5,
        min_relevance: float = 0.05,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "EvidenceChain":
        """Build an evidence chain supporting or refuting a claim.

        Given a claim like "transformers are better than RNNs for NLP",
        this method finds:
        1. Direct evidence (chunks that directly address the claim)
        2. Supporting evidence (chunks that support the direct evidence)
        3. Contradicting evidence (chunks that challenge the claim)
        4. Links between evidence chunks through the knowledge graph

        The chain traces how evidence connects across documents, enabling
        cross-document reasoning.

        Args:
            claim: A factual claim to investigate.
            k: Number of chunks to retrieve per search.
            max_chain_length: Maximum links in a single evidence chain.
            min_relevance: Minimum score threshold.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            EvidenceChain with supporting, contradicting, and linked evidence.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Find direct evidence
        direct = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        direct = [r for r in direct if r.score >= min_relevance]

        # Step 2: Extract the key aspects of the claim for targeted search
        key_terms = self._extract_key_terms(claim, max_terms=5)

        # Step 3: Search for supporting and contradicting evidence
        # Use negation terms to find counterarguments
        all_evidence: dict[str, SearchResult] = {}
        for r in direct:
            all_evidence[r.revision_id] = r

        # Expand via key terms
        for term in key_terms:
            expanded = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
            for r in expanded:
                if r.revision_id not in all_evidence and r.score >= min_relevance:
                    all_evidence[r.revision_id] = r

        # Step 4: Build chains via graph traversal
        chains: list[list[SearchResult]] = []
        if hasattr(self, "_graph") and self._graph is not None:
            for seed_result in direct[:3]:
                chain = [seed_result]
                current_id = seed_result.revision_id
                visited = {current_id}

                for _ in range(max_chain_length - 1):
                    neighbors = self._graph.neighbors(current_id, k=3)
                    best_next = None
                    best_score = -1.0

                    for nid, nscore in neighbors:
                        if nid not in visited and nscore > min_relevance:
                            rev = self.store.revisions.get(nid)
                            if rev and nscore > best_score:
                                best_next = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore,
                                    text=rev.assertion,
                                )
                                best_score = nscore

                    if best_next is None:
                        break

                    chain.append(best_next)
                    visited.add(best_next.revision_id)
                    current_id = best_next.revision_id
                    all_evidence[best_next.revision_id] = best_next

                if len(chain) > 1:
                    chains.append(chain)

        # Step 5: Score each piece of evidence for/against the claim
        supporting: list[SearchResult] = []
        related: list[SearchResult] = []

        for r in sorted(all_evidence.values(), key=lambda x: -x.score):
            if r.revision_id in {d.revision_id for d in direct}:
                supporting.append(r)
            else:
                related.append(r)

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in all_evidence.values():
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return EvidenceChain(
            claim=claim,
            direct_evidence=direct,
            supporting_evidence=supporting,
            related_evidence=related,
            chains=chains,
            sources=sources,
            total_evidence=len(all_evidence),
        )

    def query_deep(
        self,
        question: str,
        *,
        k_per_subquery: int = 5,
        max_subqueries: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> DeepQueryResult:
        """Intelligent query decomposition and targeted retrieval.

        This is the "figure out what we need, then pull it out" capability.

        1. Decompose the question into sub-questions (facets)
        2. Identify which topic clusters are relevant
        3. Retrieve targeted chunks for each sub-question
        4. Follow graph connections to find additional context
        5. Assemble a comprehensive answer context

        Args:
            question: Complex natural language question.
            k_per_subquery: Results per sub-query.
            max_subqueries: Maximum number of sub-queries to generate.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            DeepQueryResult with organized context from across the store.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Decompose question into sub-queries
        subqueries = self._decompose_question(question, max_subqueries)

        # Step 2: Identify relevant topic clusters
        relevant_clusters: dict[int, float] = {}
        if hasattr(self, "_graph") and self._graph is not None:
            for sq in subqueries:
                results = self.query(sq, k=3, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    cluster_id = self._graph.cluster_of(r.revision_id)
                    if cluster_id is not None:
                        current = relevant_clusters.get(cluster_id, 0)
                        relevant_clusters[cluster_id] = max(current, r.score)

        # Step 3: Targeted retrieval for each sub-query
        facets: list[QueryFacet] = []
        all_chunks: dict[str, SearchResult] = {}

        for sq in subqueries:
            results = self.query(sq, k=k_per_subquery, valid_at=valid_at, tx_id=tx_id)
            for r in results:
                all_chunks[r.revision_id] = r

            # Step 4: Follow graph connections for top results
            graph_results: list[SearchResult] = []
            if hasattr(self, "_graph") and self._graph is not None:
                for r in results[:2]:
                    for nid, nscore in self._graph.neighbors(r.revision_id, k=3):
                        if nid not in all_chunks:
                            rev = self.store.revisions.get(nid)
                            if rev:
                                sr = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore * 0.5,  # Discount graph-discovered results
                                    text=rev.assertion,
                                )
                                graph_results.append(sr)
                                all_chunks[nid] = sr

            facets.append(QueryFacet(
                subquery=sq,
                results=results,
                graph_results=graph_results,
            ))

        # Step 5: Re-rank all collected chunks
        final_results = self._rerank_for_question(
            question, list(all_chunks.values())
        )

        # Organize by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        # Build relevant topics info
        topic_info: list[dict[str, Any]] = []
        if hasattr(self, "_graph") and self._graph is not None:
            for cid, score in sorted(relevant_clusters.items(), key=lambda x: -x[1])[:5]:
                labels = self._graph.cluster_label(cid)
                size = len(self._graph.cluster_members(cid))
                topic_info.append({
                    "cluster_id": cid,
                    "relevance": score,
                    "labels": labels,
                    "size": size,
                })

        return DeepQueryResult(
            question=question,
            subqueries=subqueries,
            facets=facets,
            results=final_results,
            sources=sources,
            relevant_topics=topic_info,
        )

    # ---- Answer Synthesis ----

    def synthesize(
        self,
        question: str,
        *,
        k: int = 10,
        context_window: int = 1,
        hops: int = 2,
        max_context_chars: int = 30000,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "SynthesisResult":
        """Full-stack retrieval and synthesis for answering complex questions.

        This is the highest-level reasoning method. It combines:
        1. Multi-hop retrieval (reason) for breadth
        2. Context expansion for depth within documents
        3. Source grouping for cross-document analysis
        4. Evidence chain construction for traceability
        5. Formatted output ready for LLM consumption

        Args:
            question: Complex natural language question.
            k: Number of seed results per retrieval step.
            context_window: Chunks before/after each seed to include.
            hops: Number of multi-hop expansion rounds.
            max_context_chars: Maximum characters in the output context.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        t0_synth = _time.time()
        audit = self._begin_audit("synthesize", question)

        # Step 1: Multi-hop retrieval
        t_step = _time.time()
        reasoning = self.reason(question, k=k, hops=hops, valid_at=valid_at, tx_id=tx_id)
        if audit:
            audit.add("reason", f"Multi-hop retrieval ({hops} hops)",
                      {"k": k, "hops": hops},
                      {"total_chunks": reasoning.total_chunks,
                       "source_count": reasoning.source_count,
                       "hops_completed": reasoning.total_hops},
                      (_time.time() - t_step) * 1000)

        # Step 1b: Diversify seed results for cross-source coverage
        t_step = _time.time()
        diversified = self._diversify_results(reasoning.results, max_per_source=3)
        if audit:
            div_sources = set()
            for r in diversified:
                core = self.store.cores.get(r.core_id)
                div_sources.add(core.slots.get("source", "?") if core else "?")
            audit.add("diversify", "Round-robin source diversification",
                      {"input_count": len(reasoning.results), "max_per_source": 3},
                      {"output_count": len(diversified),
                       "unique_sources": len(div_sources)},
                      (_time.time() - t_step) * 1000)

        # Step 2: Expand context for each seed, grouped by source
        t_step = _time.time()
        seed_groups: dict[str, list[SearchResult]] = {}  # source -> expanded chunks
        seen: set[str] = set()

        for r in diversified:
            if r.revision_id in seen:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            if context_window > 0:
                context = self.expand_context(r, window=context_window)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        seed_groups.setdefault(source, []).append(cr)
            else:
                seen.add(r.revision_id)
                seed_groups.setdefault(source, []).append(r)

        if audit:
            total_expanded = sum(len(v) for v in seed_groups.values())
            audit.add("expand", f"Context expansion (window={context_window})",
                      {"context_window": context_window, "seed_count": len(diversified)},
                      {"expanded_count": total_expanded,
                       "source_groups": len(seed_groups)},
                      (_time.time() - t_step) * 1000)

        # Step 2b: Interleave sources for diversity in final result order
        t_step = _time.time()
        for source in seed_groups:
            seed_groups[source].sort(key=lambda r: -r.score)

        sorted_group_keys = sorted(
            seed_groups.keys(),
            key=lambda s: -seed_groups[s][0].score if seed_groups[s] else 0,
        )

        expanded_results: list[SearchResult] = []
        round_idx = 0
        max_per_source = max(3, context_window * 2 + 1)  # seed + neighbors
        while True:
            added = False
            for source in sorted_group_keys:
                group = seed_groups[source]
                if round_idx < len(group) and round_idx < max_per_source:
                    expanded_results.append(group[round_idx])
                    added = True
            round_idx += 1
            if not added:
                break

        if audit:
            audit.add("interleave", "Source interleaving for final ordering",
                      {"max_per_source": max_per_source,
                       "source_count": len(sorted_group_keys)},
                      {"final_count": len(expanded_results)},
                      (_time.time() - t_step) * 1000)

        # Step 3: Group by source document
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Sort chunks within each source by score (seeds before neighbors)
        for source in by_source:
            by_source[source].sort(key=lambda r: -r.score)

        # Sort sources by relevance (max seed score, not sum — avoids bulk-context bias)
        source_scores: dict[str, float] = {}
        for source, chunks in by_source.items():
            source_scores[source] = max(r.score for r in chunks) if chunks else 0.0
        sorted_sources = sorted(by_source.keys(), key=lambda s: -source_scores[s])

        # Step 4: Build structured context
        context_parts: list[str] = []
        context_parts.append(f"# Research Context: {question}\n")
        context_parts.append(
            f"Retrieved {len(expanded_results)} chunks from "
            f"{len(by_source)} sources via {reasoning.total_hops}-hop retrieval.\n"
        )

        total_chars = 0
        source_summaries: list[dict[str, Any]] = []

        for source in sorted_sources:
            chunks = by_source[source]
            if total_chars >= max_context_chars:
                break

            context_parts.append(f"\n## Source: {source}")
            context_parts.append(f"({len(chunks)} relevant chunks)\n")

            for chunk in chunks:
                remaining = max_context_chars - total_chars
                if remaining <= 0:
                    break
                text = chunk.text[:remaining]
                score_label = f" [relevance: {chunk.score:.3f}]" if chunk.score > 0 else ""
                context_parts.append(f"### Chunk{score_label}")
                context_parts.append(text)
                context_parts.append("")
                total_chars += len(text)

            source_summaries.append({
                "source": source,
                "chunks": len(chunks),
                "relevance": source_scores[source],
            })

        # Step 5: Extract key themes
        t_step = _time.time()
        all_text = " ".join(r.text[:200] for r in expanded_results[:20])
        themes = self._extract_key_terms(all_text, max_terms=8)
        if audit:
            audit.add("themes", "Key theme extraction",
                      {"text_sample_count": min(20, len(expanded_results))},
                      {"themes": themes},
                      (_time.time() - t_step) * 1000)

        if audit:
            audit.add("assemble", "Build structured context",
                      {"max_context_chars": max_context_chars,
                       "sources_included": len(source_summaries)},
                      {"context_chars": total_chars,
                       "source_summaries": [s["source"][:40] for s in source_summaries[:5]]},
                      0.0)  # assembly time already included in above steps
            self._finish_audit(audit, t0_synth)

        return SynthesisResult(
            question=question,
            results=expanded_results,
            sources=by_source,
            source_summaries=source_summaries,
            themes=themes,
            context="\n".join(context_parts),
            reasoning_trace=reasoning.trace,
            total_chunks=len(expanded_results),
        )

    # ---- Adaptive Retrieval ----

    def ask(
        self,
        question: str,
        *,
        k: int = 10,
        strategy: str = "auto",
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Intelligent adaptive retrieval — the single entry point for all queries.

        Automatically classifies the query and selects the best retrieval
        strategy:

        - "factual": Direct search + re-rank for specific fact lookup
        - "comparison": Search both terms, cross-document analysis
        - "exploratory": Multi-hop + graph traversal for open-ended questions
        - "multi-aspect": Decompose and search each aspect independently
        - "auto": Classify automatically (default)

        Args:
            question: Any natural language question.
            k: Maximum seed results.
            strategy: Override the automatic strategy selection.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        t0 = _time.time()
        audit = self._begin_audit("ask", question)

        # Classification
        t_classify = _time.time()
        if strategy == "auto":
            strategy = self._classify_query(question)
        if audit:
            audit.strategy = strategy
            audit.add("classify", f"Query classified as '{strategy}'",
                      {"question": question, "input_strategy": "auto"},
                      {"strategy": strategy},
                      (_time.time() - t_classify) * 1000)

        # Dispatch
        t_dispatch = _time.time()
        if strategy == "factual":
            result = self._retrieve_factual(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "comparison":
            result = self._retrieve_comparison(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "exploratory":
            result = self.synthesize(question, k=k, context_window=1, hops=3, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "multi-aspect":
            result = self._retrieve_multi_aspect(question, k=k, valid_at=valid_at, tx_id=tx_id)
        else:
            result = self.synthesize(question, k=k, context_window=1, hops=2, valid_at=valid_at, tx_id=tx_id)

        if audit:
            # Collect result summary
            top_sources = []
            for r in result.results[:5]:
                core = self.store.cores.get(r.core_id)
                source = core.slots.get("source", "?") if core else "?"
                top_sources.append(f"[{r.score:.3f}] {source[:40]}")

            audit.add("dispatch", f"Retrieved via '{strategy}' strategy",
                      {"strategy": strategy, "k": k,
                       "valid_at": str(valid_at), "tx_id": tx_id},
                      {"total_chunks": result.total_chunks,
                       "source_count": result.source_count,
                       "themes": result.themes,
                       "top_5": top_sources},
                      (_time.time() - t_dispatch) * 1000)
            self._finish_audit(audit, t0)

        return result

    def _classify_query(self, question: str) -> str:
        """Classify a query into a retrieval strategy type.

        Uses heuristic patterns to determine query intent:
        - Comparison: "vs", "compare", "difference between", "better than"
        - Multi-aspect: conjunctions, multiple topics, "and", complex structure
        - Factual: "what is", "define", "how does", short and specific
        - Exploratory: "why", "explain", "how", open-ended
        """
        import re
        q = question.lower().strip()

        # Comparison patterns
        comparison_patterns = [
            r'\bvs\.?\b', r'\bversus\b', r'\bcompare\b', r'\bcompar',
            r'\bdifference\s+between\b', r'\bbetter\s+than\b',
            r'\badvantages?\s+(?:of|over)\b', r'\bpros?\s+and\s+cons?\b',
        ]
        for pat in comparison_patterns:
            if re.search(pat, q):
                return "comparison"

        # Multi-aspect: multiple conjunctions, long queries
        conjunctions = len(re.findall(r'\b(?:and|or|also|additionally)\b', q))
        if conjunctions >= 2 or len(q) > 150:
            return "multi-aspect"

        # Factual: short, specific, "what is"
        factual_patterns = [
            r'^what\s+is\b', r'^define\b', r'^who\s+(?:is|was|are)\b',
            r'^when\s+(?:did|was|is)\b', r'^where\s+(?:is|was|are)\b',
        ]
        for pat in factual_patterns:
            if re.search(pat, q):
                return "factual"

        # Exploratory: open-ended questions (check before short-query fallback)
        exploratory_patterns = [
            r'^why\b', r'^how\s+(?:do|does|can|could|should|have|has|did)\b',
            r'^explain\b', r'\bimpact\b', r'\bimplication',
            r'\bfuture\b', r'\btrend',
            r'^which\b.*\bmost\b', r'^what\b.*\bmost\b',  # superlative questions
            r'\bevolved?\b', r'\bchanged?\b', r'\bsuperseded\b',
            r'\blimitation', r'\bfundamental\b', r'\bpromising\b',
            r'\bconflict', r'\bcontradic',
        ]
        for pat in exploratory_patterns:
            if re.search(pat, q):
                return "exploratory"

        # Short queries are usually factual
        if len(q.split()) <= 4:
            return "factual"

        # Default to exploratory for longer questions
        if len(q.split()) > 8:
            return "exploratory"

        return "factual"

    def _retrieve_factual(
        self,
        question: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Factual retrieval: direct search, high precision."""
        results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)

        # Expand top result for context
        expanded: list[SearchResult] = []
        seen: set[str] = set()

        if results:
            context = self.expand_context(results[0], window=1)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        for r in results[1:]:
            if r.revision_id not in seen:
                seen.add(r.revision_id)
                expanded.append(r)

        # Build synthesis
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Answer Context: {question}\n"]
        for r in expanded[:k]:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            context_parts.append(f"## From: {source}")
            context_parts.append(r.text[:1000])
            context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=self._extract_key_terms(" ".join(r.text[:200] for r in expanded[:5]), max_terms=5),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(results), "new": len(results)}],
            total_chunks=len(expanded),
        )

    def _retrieve_comparison(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Comparison retrieval: search for both sides, cross-reference."""
        import re

        # Extract the two sides of the comparison
        sides = re.split(r'\s+(?:vs\.?|versus|compared?\s+to|or)\s+', question, flags=re.IGNORECASE)

        all_results: dict[str, SearchResult] = {}
        side_results: dict[str, list[SearchResult]] = {}

        for side in sides:
            side = side.strip().rstrip("?.,!")
            if len(side) < 3:
                continue
            results = self.query(side, k=k // 2, valid_at=valid_at, tx_id=tx_id)
            side_results[side] = results
            for r in results:
                all_results[r.revision_id] = r

        # Also search the full question
        full_results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in full_results:
            all_results[r.revision_id] = r

        final = sorted(all_results.values(), key=lambda r: -r.score)

        # Build structured comparison context
        by_source: dict[str, list[SearchResult]] = {}
        for r in final:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Comparison: {question}\n"]
        for side, results in side_results.items():
            context_parts.append(f"## Perspective: {side}")
            for r in results[:k // 2]:
                context_parts.append(r.text[:800])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=final,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=list(side_results.keys()),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(full_results), "new": len(full_results)}],
            total_chunks=len(final),
        )

    def _retrieve_multi_aspect(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Multi-aspect retrieval: decompose and search each aspect."""
        # Use query_deep for decomposition
        deep = self.query_deep(question, k_per_subquery=k // 3, max_subqueries=4, valid_at=valid_at, tx_id=tx_id)

        # Expand top results with context
        expanded: list[SearchResult] = []
        seen: set[str] = set()
        for r in deep.results:
            if r.revision_id not in seen:
                context = self.expand_context(r, window=1)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        expanded.append(cr)

        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Multi-Aspect Analysis: {question}\n"]
        for facet in deep.facets:
            context_parts.append(f"## Aspect: {facet.subquery}")
            for r in facet.results[:3]:
                context_parts.append(r.text[:600])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=deep.subqueries,
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(deep.results), "new": len(deep.results)}],
            total_chunks=len(expanded),
        )

    # ---- Knowledge Timeline ----

    def timeline(
        self,
        topic: str,
        *,
        k: int = 20,
    ) -> list[dict[str, Any]]:
        """Show how knowledge about a topic evolved over time.

        Returns a chronological view of claims related to a topic, ordered
        by transaction time (when the knowledge was recorded). This enables
        questions like "how has our understanding of X changed?"

        Args:
            topic: Topic to trace through time.
            k: Maximum chunks to analyze.

        Returns:
            List of timeline entries, each with:
              - revision_id: str
              - text: str (chunk content)
              - source: str
              - recorded_at: str (ISO timestamp)
              - tx_id: int
              - valid_from: str (ISO timestamp)
              - valid_until: str | None
              - status: str ("asserted" or "retracted")
              - score: float (relevance to topic)
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k)

        entries: list[dict[str, Any]] = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev is None:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            entries.append({
                "revision_id": r.revision_id,
                "text": r.text[:500],
                "source": source,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
                "tx_id": rev.transaction_time.tx_id,
                "valid_from": rev.valid_time.start.isoformat(),
                "valid_until": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
                "status": rev.status,
                "score": r.score,
            })

        # Sort chronologically by transaction time
        entries.sort(key=lambda e: e["recorded_at"])
        return entries

    def timeline_diff(
        self,
        topic: str,
        *,
        tx_id_a: int,
        tx_id_b: int,
        k: int = 20,
    ) -> dict[str, Any]:
        """Compare what was known about a topic at two different points in time.

        Returns chunks that appear in one time but not the other, enabling
        "what changed between version A and version B?" analysis.

        Args:
            topic: Topic to compare.
            tx_id_a: Earlier transaction time.
            tx_id_b: Later transaction time.
            k: Maximum chunks per query.

        Returns:
            Dict with:
              - only_in_a: chunks visible at tx_id_a but not tx_id_b
              - only_in_b: chunks visible at tx_id_b but not tx_id_a
              - in_both: chunks visible at both times
              - summary: human-readable diff summary
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)

        results_a = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_a)
        results_b = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_b)

        ids_a = {r.revision_id for r in results_a}
        ids_b = {r.revision_id for r in results_b}

        only_a = [r for r in results_a if r.revision_id not in ids_b]
        only_b = [r for r in results_b if r.revision_id not in ids_a]
        both = [r for r in results_b if r.revision_id in ids_a]

        summary_parts = [f"Topic: {topic}"]
        summary_parts.append(f"At tx_id={tx_id_a}: {len(results_a)} chunks")
        summary_parts.append(f"At tx_id={tx_id_b}: {len(results_b)} chunks")
        summary_parts.append(f"Added: {len(only_b)}, Removed: {len(only_a)}, Unchanged: {len(both)}")

        return {
            "only_in_a": only_a,
            "only_in_b": only_b,
            "in_both": both,
            "summary": " | ".join(summary_parts),
        }

    # ---- Provenance & Citation ----

    def provenance_of(self, result: SearchResult) -> dict[str, Any]:
        """Get full provenance for a search result.

        Returns structured provenance data including source document,
        page number, chunk position, ingestion time, and confidence.

        Args:
            result: A SearchResult from any query method.

        Returns:
            Dict with source, page, chunk_idx, ingested_at, valid_time,
            confidence_bp, and raw provenance.
        """
        rev = self.store.revisions.get(result.revision_id)
        if rev is None:
            return {"error": "revision not found", "revision_id": result.revision_id}

        core = self.store.cores.get(result.core_id)

        info: dict[str, Any] = {
            "revision_id": result.revision_id,
            "core_id": result.core_id,
            "source": rev.provenance.source if rev.provenance else "unknown",
            "evidence_ref_length": len(rev.provenance.evidence_ref) if rev.provenance and rev.provenance.evidence_ref else 0,
            "confidence_bp": rev.confidence_bp,
            "status": rev.status,
            "valid_time": {
                "start": rev.valid_time.start.isoformat(),
                "end": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
            },
            "transaction_time": {
                "tx_id": rev.transaction_time.tx_id,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
            },
        }

        # Extract structured fields from claim slots
        if core:
            info["claim_type"] = core.claim_type
            if "source" in core.slots:
                info["document"] = core.slots["source"]
            if "page_start" in core.slots:
                info["page"] = int(core.slots["page_start"])
            if "chunk_idx" in core.slots:
                info["chunk_index"] = int(core.slots["chunk_idx"])

        return info

    def cite(
        self,
        result: SearchResult,
        *,
        style: str = "inline",
    ) -> str:
        """Generate a formatted citation for a search result.

        Args:
            result: A SearchResult from any query method.
            style: Citation style — "inline", "full", or "markdown".

        Returns:
            Formatted citation string.
        """
        prov = self.provenance_of(result)
        if "error" in prov:
            return f"[unknown source]"

        source = prov.get("document", prov.get("source", "unknown"))
        page = prov.get("page")
        chunk_idx = prov.get("chunk_index")
        tx_time = prov.get("transaction_time", {}).get("recorded_at", "")

        if style == "inline":
            parts = [source]
            if page is not None:
                parts.append(f"p.{page}")
            return f"[{', '.join(parts)}]"

        elif style == "markdown":
            parts = [f"**{source}**"]
            if page is not None:
                parts.append(f"page {page}")
            if chunk_idx is not None:
                parts.append(f"chunk {chunk_idx}")
            return " | ".join(parts)

        else:  # full
            parts = [f"Source: {source}"]
            if page is not None:
                parts.append(f"Page: {page}")
            if chunk_idx is not None:
                parts.append(f"Chunk: {chunk_idx}")
            parts.append(f"Confidence: {prov.get('confidence_bp', 0)}/10000")
            if tx_time:
                parts.append(f"Ingested: {tx_time[:10]}")
            return " | ".join(parts)

    def cite_results(
        self,
        results: list[SearchResult],
        *,
        style: str = "inline",
        deduplicate: bool = True,
    ) -> list[str]:
        """Generate citations for a list of search results.

        Args:
            results: List of SearchResult from any query method.
            style: Citation style.
            deduplicate: If True, skip duplicate sources.

        Returns:
            List of formatted citation strings.
        """
        citations: list[str] = []
        seen_sources: set[str] = set()

        for r in results:
            citation = self.cite(r, style=style)
            if deduplicate:
                prov = self.provenance_of(r)
                source_key = prov.get("document", prov.get("source", r.revision_id))
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
            citations.append(citation)

        return citations

    def query_by_source(
        self,
        source: str,
        *,
        k: int = 50,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Retrieve all chunks from a specific source document.

        Args:
            source: Source document name (or partial match).
            k: Maximum results.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResult from the specified source.
        """
        results: list[SearchResult] = []
        source_lower = source.lower()

        for rid, rev in self.store.revisions.items():
            if len(results) >= k:
                break

            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            doc_source = core.slots.get("source", "")
            if source_lower not in doc_source.lower():
                continue

            # Apply temporal filter
            if valid_at is not None and tx_id is not None:
                winner = self.store.query_as_of(
                    rev.core_id, valid_at=valid_at, tx_id=tx_id,
                )
                if winner is None or winner.revision_id != rid:
                    continue

            results.append(SearchResult(
                core_id=rev.core_id,
                revision_id=rid,
                score=1.0,
                text=rev.assertion,
            ))

        return results

    def list_sources(self) -> list[dict[str, Any]]:
        """List all unique source documents in the store.

        Returns:
            List of dicts with source name, chunk count, and page range.
        """
        sources: dict[str, dict[str, Any]] = {}

        for rid, rev in self.store.revisions.items():
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            source = core.slots.get("source", "unknown")
            if source not in sources:
                sources[source] = {
                    "source": source,
                    "chunks": 0,
                    "pages": set(),
                    "first_ingested": rev.transaction_time.recorded_at,
                }

            sources[source]["chunks"] += 1
            page = core.slots.get("page_start")
            if page is not None:
                sources[source]["pages"].add(int(page))

            if rev.transaction_time.recorded_at < sources[source]["first_ingested"]:
                sources[source]["first_ingested"] = rev.transaction_time.recorded_at

        result = []
        for info in sorted(sources.values(), key=lambda x: -x["chunks"]):
            pages = sorted(info["pages"])
            result.append({
                "source": info["source"],
                "chunks": info["chunks"],
                "page_range": f"{min(pages)}-{max(pages)}" if pages else "unknown",
                "total_pages": len(pages),
                "first_ingested": info["first_ingested"].isoformat(),
            })

        return result

    # ---- Semantic Deduplication ----

    def deduplicate(
        self,
        *,
        threshold: float = 0.85,
        k: int = 100,
    ) -> list[list[SearchResult]]:
        """Find clusters of near-duplicate chunks across documents.

        Uses TF-IDF pairwise similarity to identify chunks that say
        essentially the same thing. Useful for corpus quality analysis.

        Args:
            threshold: Minimum similarity to consider as duplicate (0-1).
            k: Maximum chunks to analyze. Set high for full corpus scan.

        Returns:
            List of duplicate clusters (each cluster is a list of SearchResult).
            Only returns clusters with 2+ members.
        """
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None or not tfidf._fitted:
            return []

        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return []

        # Use the full TF-IDF matrix
        n = min(len(tfidf._texts), k)
        if n < 2:
            return []

        sim_matrix = cosine_similarity(tfidf._matrix[:n])

        # Union-find for clustering
        parent: dict[int, int] = {i: i for i in range(n)}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if float(sim_matrix[i][j]) >= threshold:
                    union(i, j)

        # Group by cluster
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            clusters.setdefault(root, []).append(i)

        # Build results — only clusters with 2+ members
        result: list[list[SearchResult]] = []
        for members in clusters.values():
            if len(members) < 2:
                continue
            cluster_results = []
            for idx in members:
                rid = tfidf._revision_ids[idx]
                rev = self.store.revisions.get(rid)
                if rev:
                    cluster_results.append(SearchResult(
                        core_id=rev.core_id,
                        revision_id=rid,
                        score=1.0,
                        text=tfidf._texts[idx],
                    ))
            if len(cluster_results) >= 2:
                result.append(cluster_results)

        # Sort by cluster size (largest first)
        result.sort(key=lambda c: -len(c))
        return result

    # ---- Query Explanation ----

    def explain(
        self,
        question: str,
        result: SearchResult,
    ) -> dict[str, Any]:
        """Explain why a specific result was returned for a question.

        Provides feature attribution showing which terms matched,
        the similarity score breakdown, and contextual factors.

        Args:
            question: The original query.
            result: A SearchResult to explain.

        Returns:
            Dict with:
              - question: str
              - result_text: str (first 200 chars)
              - score: float
              - matching_terms: list[str] (shared terms)
              - question_unique_terms: list[str]
              - result_unique_terms: list[str]
              - term_overlap_ratio: float
              - source: str
              - provenance: dict
              - graph_distance: int | None (if graph exists)
        """
        import re

        # Extract terms
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "and", "or", "but", "not", "this", "that", "it", "its",
        }

        q_terms = set(re.findall(r'\b\w{3,}\b', question.lower())) - stop_words
        r_terms = set(re.findall(r'\b\w{3,}\b', result.text.lower())) - stop_words

        matching = q_terms & r_terms
        q_unique = q_terms - r_terms
        r_unique = r_terms - q_terms

        overlap_ratio = len(matching) / max(len(q_terms), 1)

        # Provenance
        prov = self.provenance_of(result)

        # Graph distance
        graph_distance = None
        if hasattr(self, "_graph") and self._graph is not None:
            # Try to find the shortest path from any query result to this result
            query_results = self.query(question, k=3)
            for qr in query_results:
                if qr.revision_id == result.revision_id:
                    graph_distance = 0
                    break
                path = self._graph.path(qr.revision_id, result.revision_id)
                if path is not None:
                    d = len(path) - 1
                    if graph_distance is None or d < graph_distance:
                        graph_distance = d

        return {
            "question": question,
            "result_text": result.text[:200],
            "score": result.score,
            "matching_terms": sorted(matching),
            "question_unique_terms": sorted(q_unique),
            "result_unique_terms": sorted(r_unique)[:20],
            "term_overlap_ratio": round(overlap_ratio, 3),
            "source": prov.get("document", prov.get("source", "unknown")),
            "provenance": prov,
            "graph_distance": graph_distance,
        }

    # ---- Answer Extraction ----

    def extract_answer(
        self,
        question: str,
        results: list[SearchResult] | None = None,
        *,
        k: int = 10,
        max_sentences: int = 5,
        min_relevance: float = 0.1,
    ) -> dict[str, Any]:
        """Extract the most relevant answer sentences from retrieved chunks.

        Performs sentence-level re-ranking against the question to find
        the specific passages that best answer it, without requiring an LLM.

        Args:
            question: The question to answer.
            results: Pre-retrieved results (auto-retrieves if None).
            k: Number of chunks to consider (if auto-retrieving).
            max_sentences: Maximum answer sentences to return.
            min_relevance: Minimum sentence relevance score (0-1).

        Returns:
            Dict with:
              - question: str
              - answer_sentences: list of {text, score, source, chunk_rank}
              - supporting_chunks: list of {text_preview, score, source}
              - confidence: float (0-1, based on answer quality)
              - source_count: int
        """
        import re

        if results is None:
            results = self.query(question, k=k)

        if not results:
            return {
                "question": question,
                "answer_sentences": [],
                "supporting_chunks": [],
                "confidence": 0.0,
                "source_count": 0,
            }

        # Extract question terms for scoring
        import math
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "can", "may", "might", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "and", "or",
            "but", "not", "this", "that", "it", "its", "what", "which",
            "who", "how", "why", "when", "where", "if", "so", "than",
            "about", "between", "into", "through", "during", "each",
        }
        q_terms = [w for w in re.findall(r'\b\w{3,}\b', question.lower())
                    if w not in stop_words]
        q_term_set = set(q_terms)

        # Collect all sentences for IDF computation
        all_sentences: list[tuple[str, str, int]] = []  # (text, source, chunk_rank)
        for chunk_rank, result in enumerate(results[:k]):
            core = self.store.cores.get(result.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sentences = re.split(r'(?<=[.!?])\s+', result.text)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) >= 20:
                    all_sentences.append((sent, source, chunk_rank))

        if not all_sentences:
            return {
                "question": question,
                "answer_sentences": [],
                "supporting_chunks": [],
                "confidence": 0.0,
                "source_count": 0,
            }

        # Compute IDF for query terms across all sentences
        n_docs = len(all_sentences)
        doc_freq: dict[str, int] = {}
        for sent, _, _ in all_sentences:
            s_terms = set(re.findall(r'\b\w{3,}\b', sent.lower())) - stop_words
            for term in q_term_set & s_terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        # BM25 parameters
        bm25_k1 = 1.2
        bm25_b = 0.75
        avg_len = sum(len(s[0].split()) for s in all_sentences) / max(n_docs, 1)

        # Score each sentence with BM25
        scored_sentences: list[dict[str, Any]] = []

        for sent, source, chunk_rank in all_sentences:
            s_words = re.findall(r'\b\w{3,}\b', sent.lower())
            s_terms = set(s_words) - stop_words
            if not s_terms:
                continue

            # BM25 score
            doc_len = len(s_words)
            bm25_score = 0.0
            for term in q_term_set:
                if term not in s_terms:
                    continue
                tf = s_words.count(term)
                df = doc_freq.get(term, 0)
                idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (tf * (bm25_k1 + 1)) / (
                    tf + bm25_k1 * (1 - bm25_b + bm25_b * doc_len / max(avg_len, 1))
                )
                bm25_score += idf * tf_norm

            if bm25_score <= 0:
                continue

            # Normalize to 0-1 range (approximate)
            max_possible = len(q_term_set) * math.log(n_docs + 1) * (bm25_k1 + 1)
            score = min(bm25_score / max(max_possible, 1), 1.0)

            # Informativeness bonus: sentences that add beyond the query
            info_ratio = len(s_terms - q_term_set) / max(len(s_terms), 1)
            score = score * 0.8 + min(info_ratio, 0.8) * 0.2

            # Chunk rank discount (earlier chunks more relevant)
            rank_discount = 1.0 / (1.0 + chunk_rank * 0.1)
            score *= rank_discount

            scored_sentences.append({
                "text": sent,
                "score": round(score, 4),
                "source": source,
                "chunk_rank": chunk_rank,
                "overlap_terms": sorted(q_term_set & s_terms),
            })

        # Sort by score and deduplicate near-identical sentences
        scored_sentences.sort(key=lambda x: -x["score"])

        answer_sentences = []
        seen_text: set[str] = set()

        for s in scored_sentences:
            if s["score"] < min_relevance:
                break
            # Dedup: skip if >60% word overlap with already selected sentence
            s_words = set(s["text"].lower().split())
            is_dup = False
            for existing in answer_sentences:
                e_words = set(existing["text"].lower().split())
                jaccard = len(s_words & e_words) / max(len(s_words | e_words), 1)
                if jaccard > 0.6:
                    is_dup = True
                    break
            if not is_dup:
                answer_sentences.append(s)
            if len(answer_sentences) >= max_sentences:
                break

        # Supporting chunks summary
        supporting = []
        sources = set()
        for result in results[:k]:
            core = self.store.cores.get(result.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.add(source)
            supporting.append({
                "text_preview": result.text[:150],
                "score": round(result.score, 4),
                "source": source,
            })

        # Confidence based on answer quality
        if answer_sentences:
            avg_score = sum(s["score"] for s in answer_sentences) / len(answer_sentences)
            coverage = min(len(answer_sentences) / max_sentences, 1.0)
            source_diversity = min(len(sources) / 3, 1.0)
            confidence = avg_score * 0.5 + coverage * 0.3 + source_diversity * 0.2
        else:
            confidence = 0.0

        return {
            "question": question,
            "answer_sentences": answer_sentences,
            "supporting_chunks": supporting[:5],
            "confidence": round(confidence, 3),
            "source_count": len(sources),
        }

    def answer(
        self,
        question: str,
        *,
        k: int = 10,
        hops: int = 2,
        max_sentences: int = 5,
    ) -> dict[str, Any]:
        """Full pipeline: retrieve + reason + extract answer.

        This is the highest-level answering method. It combines multi-hop
        retrieval with sentence-level answer extraction.

        Args:
            question: Any natural language question.
            k: Number of seed results.
            hops: Multi-hop reasoning depth.
            max_sentences: Maximum answer sentences.

        Returns:
            Dict with question, answer_sentences, supporting_chunks,
            confidence, source_count, strategy, and audit trace (if enabled).
        """
        t0 = _time.time()
        audit = self._begin_audit("answer", question)

        # Step 1: Classify and retrieve
        strategy = self._classify_query(question)
        if audit:
            audit.strategy = strategy
            audit.add("classify", f"Query classified as '{strategy}'",
                      {"question": question}, {"strategy": strategy},
                      (_time.time() - t0) * 1000)

        # Step 2: Retrieve using best strategy
        t_retrieve = _time.time()
        if strategy == "factual":
            results = self.query(question, k=k)
        else:
            reasoning = self.reason(question, k=k, hops=hops)
            results = reasoning.results

        if audit:
            audit.add("retrieve", f"Retrieved {len(results)} chunks",
                      {"strategy": strategy, "k": k},
                      {"chunk_count": len(results)},
                      (_time.time() - t_retrieve) * 1000)

        # Step 3: Extract answer
        t_extract = _time.time()
        answer = self.extract_answer(question, results,
                                     max_sentences=max_sentences)
        if audit:
            audit.add("extract", f"Extracted {len(answer['answer_sentences'])} answer sentences",
                      {"max_sentences": max_sentences},
                      {"sentence_count": len(answer["answer_sentences"]),
                       "confidence": answer["confidence"]},
                      (_time.time() - t_extract) * 1000)
            self._finish_audit(audit, t0)

        answer["strategy"] = strategy
        return answer

    # ---- Contradiction Detection ----

    def contradictions(
        self,
        topic: str,
        *,
        k: int = 20,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Find potential contradictions in the knowledge base about a topic.

        Searches for chunks that are topically similar but come from different
        sources, then applies negation and opposition detection to find conflicts.

        Args:
            topic: Topic to search for contradictions.
            k: Number of chunks to analyze.
            similarity_threshold: Minimum TF-IDF similarity between chunks.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of contradiction dicts, each with:
              - chunk_a: SearchResult
              - chunk_b: SearchResult
              - source_a: str
              - source_b: str
              - similarity: float (topical similarity)
              - conflict_signals: list[str] (what triggered the detection)
              - confidence_bp: int (0-10000, how likely this is a real contradiction)
        """
        import re

        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)
        if len(results) < 2:
            return []

        # Get source for each result
        result_sources: dict[str, str] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            result_sources[r.revision_id] = (
                core.slots.get("source", "unknown") if core else "unknown"
            )

        # Compute pairwise similarity using TF-IDF
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        pairs_with_similarity: list[tuple[int, int, float]] = []

        if tfidf is not None and tfidf._fitted:
            try:
                from sklearn.metrics.pairwise import cosine_similarity
                texts = [r.text for r in results]
                vecs = tfidf._vectorizer.transform(texts)
                sim_matrix = cosine_similarity(vecs)

                for i in range(len(results)):
                    for j in range(i + 1, len(results)):
                        sim = float(sim_matrix[i][j])
                        if sim >= similarity_threshold:
                            # Only consider cross-source pairs
                            if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                                pairs_with_similarity.append((i, j, sim))
            except Exception:
                pass

        if not pairs_with_similarity:
            # Fallback: compare all cross-source pairs
            for i in range(len(results)):
                for j in range(i + 1, len(results)):
                    if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                        pairs_with_similarity.append((i, j, 0.5))

        # Detect contradiction signals
        negation_words = {
            "not", "no", "never", "neither", "nor", "none", "nothing",
            "nowhere", "hardly", "scarcely", "barely", "doesn't", "don't",
            "didn't", "won't", "wouldn't", "couldn't", "shouldn't",
            "isn't", "aren't", "wasn't", "weren't", "cannot", "can't",
        }
        opposition_pairs = [
            ("increase", "decrease"), ("improve", "worsen"), ("better", "worse"),
            ("higher", "lower"), ("more", "less"), ("faster", "slower"),
            ("larger", "smaller"), ("stronger", "weaker"), ("efficient", "inefficient"),
            ("effective", "ineffective"), ("successful", "unsuccessful"),
            ("advantage", "disadvantage"), ("benefit", "drawback"),
            ("outperform", "underperform"), ("superior", "inferior"),
            ("significant", "insignificant"), ("positive", "negative"),
            ("optimal", "suboptimal"), ("accurate", "inaccurate"),
        ]

        contradictions: list[dict[str, Any]] = []

        for i, j, sim in pairs_with_similarity:
            a, b = results[i], results[j]
            a_words = set(re.findall(r'\b\w+\b', a.text.lower()))
            b_words = set(re.findall(r'\b\w+\b', b.text.lower()))

            signals: list[str] = []
            confidence = 0

            # Signal 1: One has negation of shared concept
            a_negations = a_words & negation_words
            b_negations = b_words & negation_words
            if a_negations and not b_negations:
                signals.append(f"negation in A: {', '.join(a_negations)}")
                confidence += 2000
            elif b_negations and not a_negations:
                signals.append(f"negation in B: {', '.join(b_negations)}")
                confidence += 2000

            # Signal 2: Opposition word pairs
            for pos, neg in opposition_pairs:
                if pos in a_words and neg in b_words:
                    signals.append(f"opposition: A='{pos}' vs B='{neg}'")
                    confidence += 3000
                elif neg in a_words and pos in b_words:
                    signals.append(f"opposition: A='{neg}' vs B='{pos}'")
                    confidence += 3000

            # Signal 3: Numerical disagreement on same topic
            a_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', a.text))
            b_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', b.text))
            shared_context = a_words & b_words - negation_words
            if a_nums and b_nums and a_nums != b_nums and len(shared_context) > 5:
                signals.append(f"different numbers: A={a_nums} vs B={b_nums}")
                confidence += 1500

            # Signal 4: High topical similarity + different sources = potential conflict
            if sim > 0.4:
                signals.append(f"high similarity ({sim:.2f}) across sources")
                confidence += 1000

            if signals:
                confidence = min(confidence, 10000)
                contradictions.append({
                    "chunk_a": a,
                    "chunk_b": b,
                    "source_a": result_sources[a.revision_id],
                    "source_b": result_sources[b.revision_id],
                    "similarity": sim,
                    "conflict_signals": signals,
                    "confidence_bp": confidence,
                })

        # Sort by confidence
        contradictions.sort(key=lambda c: -c["confidence_bp"])
        return contradictions

    def confidence(
        self,
        claim: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Assess confidence in a claim based on evidence in the store.

        Scores a claim based on:
        1. Source diversity (more independent sources = higher confidence)
        2. Internal consistency (do sources agree?)
        3. Recency (newer evidence weighted higher)
        4. Evidence density (how many relevant chunks found)

        Args:
            claim: Factual claim to evaluate.
            k: Number of chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            Dict with:
              - confidence_bp: int (0-10000)
              - evidence_count: int
              - source_count: int
              - supporting: int (chunks that support)
              - contradicting: int (chunks with contradiction signals)
              - recency_score: float (0-1, how recent the evidence is)
              - assessment: str ("high", "medium", "low", "insufficient")
        """
        import re

        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        if not results:
            return {
                "confidence_bp": 0,
                "evidence_count": 0,
                "source_count": 0,
                "supporting": 0,
                "contradicting": 0,
                "recency_score": 0.0,
                "assessment": "insufficient",
            }

        # Count unique sources
        sources: set[str] = set()
        for r in results:
            core = self.store.cores.get(r.core_id)
            if core:
                sources.add(core.slots.get("source", "unknown"))

        # Check for negation/contradiction signals vs the claim
        claim_words = set(re.findall(r'\b\w+\b', claim.lower()))
        negation_words = {
            "not", "no", "never", "neither", "nor", "none",
            "doesn't", "don't", "didn't", "won't", "cannot", "can't",
        }
        claim_has_negation = bool(claim_words & negation_words)

        supporting = 0
        contradicting = 0
        for r in results:
            r_words = set(re.findall(r'\b\w+\b', r.text.lower()))
            r_has_negation = bool(r_words & negation_words)

            # If claim is positive and evidence is negative (or vice versa)
            if claim_has_negation != r_has_negation:
                contradicting += 1
            else:
                supporting += 1

        # Recency score: based on transaction times of evidence
        recency_scores = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev:
                tx_recorded = rev.transaction_time.recorded_at
                # Score based on how recent (within last 5 years)
                now = datetime.now(timezone.utc)
                age_days = (now - tx_recorded).days
                recency = max(0.0, 1.0 - age_days / (365 * 5))
                recency_scores.append(recency)
        recency_score = sum(recency_scores) / len(recency_scores) if recency_scores else 0.0

        # Compute overall confidence
        confidence = 0

        # Source diversity (0-3000)
        source_score = min(len(sources) * 1000, 3000)
        confidence += source_score

        # Evidence density (0-2000)
        density_score = min(len(results) * 400, 2000)
        confidence += density_score

        # Consistency (0-3000)
        if supporting > 0:
            consistency = supporting / (supporting + contradicting)
            confidence += int(consistency * 3000)

        # Recency boost (0-2000)
        confidence += int(recency_score * 2000)

        confidence = min(confidence, 10000)

        # Assessment
        if len(results) < 2:
            assessment = "insufficient"
        elif confidence >= 7000:
            assessment = "high"
        elif confidence >= 4000:
            assessment = "medium"
        else:
            assessment = "low"

        return {
            "confidence_bp": confidence,
            "evidence_count": len(results),
            "source_count": len(sources),
            "supporting": supporting,
            "contradicting": contradicting,
            "recency_score": round(recency_score, 3),
            "assessment": assessment,
        }

    def _decompose_question(
        self,
        question: str,
        max_parts: int = 5,
    ) -> list[str]:
        """Decompose a complex question into simpler sub-questions.

        Uses multi-strategy heuristic decomposition:
        1. Clause splitting: "What is X and how does Y?" → two questions
        2. Contrast extraction: "difference between A and B" → A, B, A vs B
        3. Temporal decomposition: "how has X evolved?" → past, present, future
        4. Conjunction splitting: "A and B and C" → separate queries
        5. Entity extraction: pull out key noun phrases
        """
        import re

        q = question.strip().rstrip("?.,!")
        q_lower = q.lower()
        subqueries = [question]  # Always include the original

        # Strategy 1: Question clause splitting
        # "What is X and how does Y work?" → "What is X" + "how does Y work"
        clause_splits = re.split(
            r'[,;]\s*(?:and\s+)?(?:how|what|why|which|where|when|who)\b',
            q, flags=re.IGNORECASE,
        )
        if len(clause_splits) > 1:
            # Re-attach the question word that was consumed by split
            for part in clause_splits:
                part = part.strip().rstrip("?.,!")
                if len(part) > 15:
                    subqueries.append(part)

        # Strategy 2: Contrast/comparison extraction
        # "difference between A and B" → "A", "B", "A vs B"
        contrast_match = re.search(
            r'(?:difference|comparison|compare|contrast|tradeoff|trade-off)\s+'
            r'(?:between\s+)?(.+?)\s+(?:and|vs\.?|versus)\s+(.+)',
            q_lower,
        )
        if contrast_match:
            a_term = contrast_match.group(1).strip().rstrip("?.,!")
            b_term = contrast_match.group(2).strip().rstrip("?.,!")
            if len(a_term) > 3:
                subqueries.append(a_term)
            if len(b_term) > 3:
                subqueries.append(b_term)
            subqueries.append(f"{a_term} vs {b_term}")

        # Strategy 3: Temporal decomposition
        # "how has X evolved?" → "X origins", "X current state"
        temporal_match = re.search(
            r'(?:how\s+has|how\s+have|how\s+did)\s+(.+?)\s+'
            r'(?:evolved?|changed?|developed?|progressed?|grown?)',
            q_lower,
        )
        if temporal_match:
            topic = temporal_match.group(1).strip()
            if len(topic) > 3:
                subqueries.append(f"{topic} origins history")
                subqueries.append(f"{topic} current state recent")

        # Strategy 4: Conjunction splitting (broader than just "and")
        parts = re.split(
            r'\b(?:and|or|but|also|additionally|furthermore|moreover|as\s+well\s+as)\b',
            q, flags=re.IGNORECASE,
        )
        for part in parts:
            part = part.strip().rstrip("?.,!")
            if len(part) > 15 and part.lower() != q_lower:
                subqueries.append(part)

        # Strategy 5: "relate to" / "impact on" extraction
        relate_match = re.search(
            r'(?:relat(?:e|ion|ionship)|impact|effect|influence|connection)\s+'
            r'(?:between|of|on|to)\s+(.+?)\s+(?:and|on|to|with)\s+(.+)',
            q_lower,
        )
        if relate_match:
            a_term = relate_match.group(1).strip().rstrip("?.,!")
            b_term = relate_match.group(2).strip().rstrip("?.,!")
            if len(a_term) > 3:
                subqueries.append(a_term)
            if len(b_term) > 3:
                subqueries.append(b_term)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for sq in subqueries:
            normalized = sq.lower().strip()
            if normalized not in seen and len(normalized) > 5:
                seen.add(normalized)
                unique.append(sq)

        return unique[:max_parts]

    def _extract_expansion_terms(
        self,
        results: list[SearchResult],
        seen: set[str],
        max_terms: int = 3,
    ) -> list[str]:
        """Extract key terms from results for query expansion."""
        all_text = " ".join(r.text for r in results)
        terms = self._extract_key_terms(all_text, max_terms=max_terms * 2)
        # Filter already seen
        novel = [t for t in terms if t.lower().strip() not in seen]
        return novel[:max_terms]

    def _extract_key_terms(
        self,
        text: str,
        max_terms: int = 10,
    ) -> list[str]:
        """Extract key terms from text using TF-IDF or simple frequency."""
        import re
        from collections import Counter

        # Common English stop words + newsletter/boilerplate terms
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "out", "off", "over", "under", "again",
            "further", "then", "once", "here", "there", "when", "where", "why",
            "how", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "because", "but", "and", "or",
            "if", "while", "about", "up", "this", "that", "these", "those",
            "it", "its", "they", "them", "their", "we", "our", "you", "your",
            "he", "him", "his", "she", "her", "i", "me", "my", "what", "which",
            "who", "whom", "also", "many", "much", "any", "well", "like",
            "new", "one", "two", "first", "even", "back", "get", "make",
            "know", "take", "come", "see", "think", "look", "want", "give",
            "use", "find", "tell", "work", "way", "let", "still", "going",
            "don", "didn", "doesn", "won", "ll", "ve", "re", "things",
            # Newsletter/boilerplate terms
            "hey", "subscribe", "newsletter", "email", "post", "writeup",
            "write", "series", "breakdowns", "breakdown", "found", "value",
            "sharing", "share", "appreciate", "link", "links", "click",
            "follow", "join", "sign", "free", "update", "content", "read",
            "reading", "check", "drop", "playlist", "search", "important",
            "always", "people", "time", "really", "great", "amazing",
            "incredible", "interesting", "awesome", "love", "thanks",
            # Generic filler words
            "huge", "believe", "becoming", "become", "thing", "things",
            "look", "looking", "lot", "lots", "make", "making", "made",
            "like", "keep", "still", "well", "much", "many", "also",
            "way", "ways", "new", "use", "using", "used", "need",
            "want", "say", "said", "means", "mean", "take", "step",
            "move", "going", "come", "think", "know", "see", "get",
            "let", "put", "run", "try", "give", "work", "call",
            "long", "able", "different", "good", "best", "even",
            "every", "first", "last", "next", "part", "point",
            "right", "actually", "basically", "simply", "just",
            "world", "today", "google", "source", "image",
            # Commercial/marketing
            "please", "consider", "premium", "subscription", "cost",
            "netflix", "price", "pricing", "buy", "sell", "offer",
            "product", "service", "customer", "company", "business",
            "plan", "trial", "account", "million", "billion",
            # Web/platform terms
            "website", "page", "site", "online", "http", "https",
            "www", "com", "org", "html", "pdf", "file", "files",
            # Filler verbs/adjectives
            "based", "related", "specific", "general", "common",
            "possible", "available", "similar", "across", "within",
            "form", "answer", "question", "questions", "require",
            "understand", "show", "shown", "shows", "mind",
            "require", "required", "requires", "help", "helps",
            "allows", "allow", "called", "known", "given",
            "higher", "lower", "larger", "smaller", "better",
            "result", "results", "example", "examples", "case",
            "however", "therefore", "thus", "hence", "often",
            "typically", "usually", "especially", "particularly",
            # Overly generic ML terms (appear in every chunk)
            "data", "model", "models", "training", "learning",
            "systems", "system", "code", "text", "input", "output",
            "layers", "layer", "process", "method", "methods",
            "approach", "task", "tasks", "problem", "problems",
            "performance", "accuracy", "number", "set", "sets",
            "features", "feature", "information", "function",
            "network", "networks", "algorithm", "algorithms",
            "parameters", "parameter", "weights", "weight",
            # More commercial/filler
            "provide", "various", "consulting", "advisory",
            "services", "impact", "impacts", "batch", "sizes",
            "crippling", "chocolate", "milk", "recipes",
        }

        # Extract words (3+ chars, alphabetic)
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        filtered = [w for w in words if w not in stop_words and len(w) > 3]

        # Count bigrams — both words must pass stop word filter
        bigrams = []
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i+1]
            if w1 not in stop_words and w2 not in stop_words and len(w1) > 3 and len(w2) > 3:
                bigrams.append(f"{w1} {w2}")

        # Combine unigram and bigram counts
        counter = Counter(filtered)
        bigram_counter = Counter(bigrams)

        # Prefer bigrams (more specific), require count >= 2
        terms: list[str] = []
        seen_words: set[str] = set()
        for term, count in bigram_counter.most_common(max_terms * 2):
            if count >= 2 and len(terms) < max_terms:
                # Skip bigrams with very short words or non-alpha chars
                parts = term.split()
                if all(len(p) > 3 and p.isalpha() for p in parts):
                    terms.append(term)
                    seen_words.update(parts)
        for term, count in counter.most_common(max_terms * 3):
            if len(terms) >= max_terms:
                break
            if term.isalpha() and term not in seen_words and term not in " ".join(terms):
                terms.append(term)

        return terms[:max_terms]

    def _diversify_results(
        self,
        results: list[SearchResult],
        *,
        max_per_source: int = 3,
    ) -> list[SearchResult]:
        """Re-order results to maximize source diversity.

        Uses a round-robin approach: take the best result from each source,
        then the second-best from each, etc. This ensures the top results
        come from diverse documents.

        Args:
            results: Results sorted by score.
            max_per_source: Maximum results from any single source.

        Returns:
            Results re-ordered for diversity.
        """
        # Group by source, preserving order within each source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Round-robin selection: best from each source, then second-best, etc.
        diversified: list[SearchResult] = []
        seen: set[str] = set()
        round_num = 0

        while len(diversified) < len(results):
            added_this_round = False
            # Sort sources by their best remaining score
            sorted_sources = sorted(
                by_source.items(),
                key=lambda x: -x[1][0].score if x[1] else 0,
            )
            for source, chunks in sorted_sources:
                if round_num < len(chunks) and round_num < max_per_source:
                    r = chunks[round_num]
                    if r.revision_id not in seen:
                        seen.add(r.revision_id)
                        diversified.append(r)
                        added_this_round = True
            round_num += 1
            if not added_this_round:
                break

        return diversified

    def _rerank_for_question(
        self,
        question: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Re-rank results by relevance to the original question."""
        # Get TF-IDF component for re-ranking
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None:
            return sorted(results, key=lambda r: -r.score)

        # Re-score against original question using TF-IDF
        if not tfidf._fitted:
            tfidf.rebuild()

        try:
            from sklearn.metrics.pairwise import cosine_similarity
            vectorizer = tfidf._vectorizer
            q_vec = vectorizer.transform([question])
            text_vecs = vectorizer.transform([r.text for r in results])
            scores = cosine_similarity(q_vec, text_vecs)[0]

            rescored = []
            for r, score in zip(results, scores):
                rescored.append(SearchResult(
                    core_id=r.core_id,
                    revision_id=r.revision_id,
                    score=float(score),
                    text=r.text,
                ))
            rescored.sort(key=lambda r: -r.score)
            return rescored
        except Exception:
            return sorted(results, key=lambda r: -r.score)


@dataclass
class ReasoningResult:
    """Result of multi-hop reasoning over the knowledge store."""
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    trace: list[dict[str, Any]]
    total_hops: int

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary of reasoning results."""
        lines = [f'Question: "{self.question}"']
        lines.append(f"Found {self.total_chunks} relevant chunks across {self.source_count} documents")
        lines.append(f"Reasoning: {self.total_hops} expansion hops")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        lines.append("")
        lines.append("Top results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")
        return "\n".join(lines)


@dataclass
class QueryFacet:
    """A single facet (sub-question) of a deep query."""
    subquery: str
    results: list[SearchResult]
    graph_results: list[SearchResult]

    @property
    def total_chunks(self) -> int:
        return len(self.results) + len(self.graph_results)


@dataclass
class DeepQueryResult:
    """Result of intelligent query decomposition and targeted retrieval."""
    question: str
    subqueries: list[str]
    facets: list[QueryFacet]
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    relevant_topics: list[dict[str, Any]]

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f'Deep Query: "{self.question}"']
        lines.append(f"Decomposed into {len(self.subqueries)} sub-queries:")
        for sq in self.subqueries:
            lines.append(f"  - {sq}")
        lines.append(f"\nFound {self.total_chunks} chunks across {self.source_count} documents")

        if self.relevant_topics:
            lines.append("\nRelevant topics:")
            for t in self.relevant_topics:
                labels = ", ".join(t["labels"][:3])
                lines.append(f"  [{t['size']} chunks, relevance={t['relevance']:.3f}] {labels}")

        lines.append("\nTop results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")

        lines.append(f"\nSource breakdown:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:55]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 10) -> str:
        """Format results as context suitable for feeding to an LLM.

        Returns a structured text block with source attribution that
        can be used as context for LLM-based reasoning.
        """
        lines = [f"# Context for: {self.question}\n"]

        for i, r in enumerate(self.results[:max_chunks]):
            core_lookup = None
            # We can't access store from here, so use what we have
            lines.append(f"## Chunk {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        return "\n".join(lines)


@dataclass
class EvidenceChain:
    """Cross-document evidence chain supporting or refuting a claim."""
    claim: str
    direct_evidence: list[SearchResult]
    supporting_evidence: list[SearchResult]
    related_evidence: list[SearchResult]
    chains: list[list[SearchResult]]
    sources: dict[str, list[SearchResult]]
    total_evidence: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def chain_count(self) -> int:
        return len(self.chains)

    def summary(self) -> str:
        """Human-readable evidence chain summary."""
        lines = [f'Evidence for: "{self.claim}"']
        lines.append(f"Total evidence: {self.total_evidence} chunks from {self.source_count} sources")
        lines.append(f"Direct evidence: {len(self.direct_evidence)} chunks")
        lines.append(f"Evidence chains: {self.chain_count}")
        lines.append("")

        if self.direct_evidence:
            lines.append("Direct evidence:")
            for r in self.direct_evidence[:5]:
                text_preview = r.text[:120].replace("\n", " ")
                lines.append(f"  [{r.score:.3f}] {text_preview}...")

        if self.chains:
            lines.append("")
            lines.append("Evidence chains:")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"  Chain {i+1} ({len(chain)} links):")
                for j, link in enumerate(chain):
                    text_preview = link.text[:80].replace("\n", " ")
                    lines.append(f"    {j+1}. [{link.score:.3f}] {text_preview}...")

        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 15) -> str:
        """Format evidence as LLM-ready context with source attribution."""
        lines = [f"# Evidence Analysis: {self.claim}\n"]

        lines.append("## Direct Evidence\n")
        for i, r in enumerate(self.direct_evidence[:max_chunks // 2]):
            lines.append(f"### Evidence {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        if self.chains:
            lines.append("## Evidence Chains\n")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"### Chain {i+1}")
                for j, link in enumerate(chain):
                    lines.append(f"Link {j+1}: {link.text[:500]}")
                    lines.append("")

        if self.related_evidence:
            lines.append("## Related Context\n")
            remaining = max_chunks - len(self.direct_evidence[:max_chunks // 2])
            for i, r in enumerate(self.related_evidence[:remaining]):
                lines.append(f"### Related {i+1} (relevance: {r.score:.3f})")
                lines.append(r.text[:500])
                lines.append("")

        return "\n".join(lines)


@dataclass
class SynthesisResult:
    """Full-stack retrieval and synthesis result.

    Contains organized, source-attributed context ready for LLM consumption
    or human review.
    """
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    source_summaries: list[dict[str, Any]]
    themes: list[str]
    context: str
    reasoning_trace: list[dict[str, Any]]
    total_chunks: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def context_length(self) -> int:
        return len(self.context)

    def summary(self) -> str:
        """Human-readable summary of the synthesis."""
        lines = [f'Synthesis: "{self.question}"']
        lines.append(
            f"Retrieved {self.total_chunks} chunks from "
            f"{self.source_count} sources"
        )
        lines.append(f"Context: {self.context_length:,} characters")
        lines.append("")

        if self.themes:
            lines.append("Key themes: " + ", ".join(self.themes))
            lines.append("")

        lines.append("Sources (by relevance):")
        for ss in self.source_summaries[:10]:
            lines.append(
                f"  [{ss['chunks']} chunks, rel={ss['relevance']:.3f}] "
                f"{ss['source'][:55]}"
            )

        lines.append("")
        lines.append("Reasoning trace:")
        for t in self.reasoning_trace:
            if t["hop"] == 0:
                lines.append(f"  Hop 0: {t['results']} initial results")
            else:
                terms = t.get("expansion_terms", [])
                lines.append(
                    f"  Hop {t['hop']}: +{t['new']} new "
                    f"(expanded: {', '.join(terms[:3])})"
                )

        return "\n".join(lines)


@dataclass
class CoverageReport:
    """Analysis of store coverage for a topic."""
    topic: str
    total_chunks: int
    sources: dict[str, list[SearchResult]]
    subtopics: list[str]
    source_count: int

    def summary(self) -> str:
        """Human-readable coverage report."""
        lines = [f'Coverage: "{self.topic}"']
        lines.append(f"Found {self.total_chunks} chunks across {self.source_count} documents")
        lines.append("")
        lines.append("Subtopics discovered:")
        for st in self.subtopics:
            lines.append(f"  - {st}")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        return "\n".join(lines)
