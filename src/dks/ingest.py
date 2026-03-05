"""Ingestion module — extract, resolve, commit, index.

Handles the pipeline from unstructured text to deterministic claims.
The commitment boundary runs through this module: extraction and resolution
are non-deterministic, but once committed to the KnowledgeStore, everything
becomes deterministic data.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .core import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)
from .extract import Extractor, PDFExtractor, TextChunker
from .index import DenseSearchIndex, HybridSearchIndex, SearchIndex, TemporalSearchIndex, TfidfSearchIndex
from .resolve import Resolver


class Ingester:
    """Handles all ingestion operations for the pipeline.

    This class owns the extract → resolve → commit → index flow.
    It receives shared pipeline state via constructor injection.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        extractor: Extractor | None,
        resolver: Resolver | None,
        index: TemporalSearchIndex | None,
        tx_factory: Callable[[], TransactionTime],
        chunk_siblings: dict[str, list[str]],
    ) -> None:
        self.store = store
        self._extractor = extractor
        self._resolver = resolver
        self._index = index
        self._tx_factory = tx_factory
        self._chunk_siblings = chunk_siblings

    @property
    def chunk_siblings(self) -> dict[str, list[str]]:
        return self._chunk_siblings

    @chunk_siblings.setter
    def chunk_siblings(self, value: dict[str, list[str]]) -> None:
        self._chunk_siblings = value

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
        non-deterministic extraction -> deterministic storage.

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

        # Phase 3: Commit to store (COMMITMENT BOUNDARY -- deterministic from here)
        revision_ids: list[str] = []
        prov = provenance or Provenance(source="pipeline:ingest")

        for i, claim in enumerate(resolved_claims):
            extraction_prov = extraction.provenance[i] if i < len(extraction.provenance) else prov

            # For document chunks, use evidence_ref (the original chunk text)
            # as both the assertion and the indexed text to keep them consistent.
            assertion = extraction_prov.evidence_ref or text[:500]

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

            # Phase 4: Index for search (same text as assertion)
            if self._index is not None:
                self._index.add(revision.revision_id, assertion)

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
            start=datetime.now(timezone.utc),
            end=None,
        )
        tt = transaction_time or self._tx_factory()

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

        # Track chunk siblings for context expansion (key must match canonicalized slot value)
        source_name = canonicalize_text(Path(path).name)
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

        vt = valid_time or ValidTime(start=datetime.now(timezone.utc))
        tt = transaction_time or self._tx_factory()

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

        # Track siblings for context expansion (key must match canonicalized slot value)
        self._chunk_siblings[canonicalize_text(source)] = revision_ids

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
            Dict mapping filename -> list of revision_ids.
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
            except (ValueError, OSError, RuntimeError) as e:
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

        # Rebuild search index after batch ingestion.
        # SearchIndex embeds on add(), so rebuild is only needed for deferred-build types.
        if isinstance(self._index, (TfidfSearchIndex, DenseSearchIndex, HybridSearchIndex)):
            self._index.rebuild()

        return results
