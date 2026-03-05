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
from .extract import DocxExtractor, Extractor, PDFExtractor, PptxExtractor, TextChunker
from .index import TemporalSearchIndex
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
        return self._ingest_document(
            extraction, path, "pdf",
            valid_time=valid_time, transaction_time=transaction_time,
            confidence_bp=confidence_bp,
        )

    def _ingest_document(
        self,
        extraction: "ExtractionResult",
        path: str | Path,
        format_prefix: str,
        *,
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
    ) -> list[str]:
        """Shared logic for ingesting document extraction results (PDF, DOCX, PPTX)."""
        if not extraction.claims:
            return []

        vt = valid_time or ValidTime(start=datetime.now(timezone.utc), end=None)
        tt = transaction_time or self._tx_factory()

        revision_ids: list[str] = []
        for i, claim in enumerate(extraction.claims):
            prov = extraction.provenance[i] if i < len(extraction.provenance) else Provenance(
                source=f"{format_prefix}:{Path(path).name}",
            )
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

            if self._index is not None:
                self._index.add(revision.revision_id, assertion)

        # Use full path string as sibling key to avoid collisions from same-name files
        source_name = canonicalize_text(str(Path(path)))
        self._chunk_siblings[source_name] = revision_ids
        return revision_ids

    def ingest_docx(
        self,
        path: str | Path,
        *,
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
    ) -> list[str]:
        """Ingest a Word (.docx) document: extract text, chunk, commit, index.

        Requires: pip install python-docx

        Args:
            path: Path to the .docx file.
            valid_time: When the facts are true.
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker.

        Returns:
            List of revision_ids for all committed chunks.
        """
        extractor = DocxExtractor(chunker=chunker)
        extraction = extractor.extract_docx(path)
        return self._ingest_document(
            extraction, path, "docx",
            valid_time=valid_time, transaction_time=transaction_time,
            confidence_bp=confidence_bp,
        )

    def ingest_pptx(
        self,
        path: str | Path,
        *,
        valid_time: ValidTime | None = None,
        transaction_time: TransactionTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
    ) -> list[str]:
        """Ingest a PowerPoint (.pptx) presentation: extract text, chunk, commit, index.

        Requires: pip install python-pptx

        Args:
            path: Path to the .pptx file.
            valid_time: When the facts are true.
            transaction_time: When ingested (auto-generated if None).
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker.

        Returns:
            List of revision_ids for all committed chunks.
        """
        extractor = PptxExtractor(chunker=chunker)
        extraction = extractor.extract_pptx(path)
        return self._ingest_document(
            extraction, path, "pptx",
            valid_time=valid_time, transaction_time=transaction_time,
            confidence_bp=confidence_bp,
        )

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

    # File extensions treated as text (read with UTF-8, chunked, indexed).
    _TEXT_EXTENSIONS: frozenset[str] = frozenset({
        ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl",
        ".xml", ".html", ".htm", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
        ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
        ".scala", ".r", ".jl", ".lua", ".sh", ".bash", ".zsh", ".ps1",
        ".bat", ".sql", ".graphql", ".proto", ".tf", ".dockerfile",
        ".makefile", ".cmake", ".gradle", ".sbt",
        ".css", ".scss", ".less", ".sass",
        ".tex", ".bib", ".org", ".adoc",
        ".env", ".gitignore", ".dockerignore", ".editorconfig",
        ".log", ".diff", ".patch",
    })

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        pattern: str = "**/*",
        valid_time: ValidTime | None = None,
        confidence_bp: int = 5000,
        chunker: TextChunker | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        progress: bool = True,
    ) -> dict[str, list[str]]:
        """Ingest files from a directory, recursively by default.

        Supports PDFs, Word (.docx), PowerPoint (.pptx), and text files.
        File type is detected by extension. Binary files and unrecognized
        extensions are skipped.

        Args:
            directory: Path to directory.
            pattern: Glob pattern (default: '**/*' for recursive).
                     Use '*.pdf' for top-level PDFs only.
            valid_time: When the facts are true.
            confidence_bp: Confidence for extracted claims.
            chunker: Optional custom chunker (for PDFs).
            chunk_size: Characters per chunk (for text files).
            chunk_overlap: Overlap between chunks (for text files).
            progress: Print progress to stderr.

        Returns:
            Dict mapping relative path -> list of revision_ids.
        """
        directory = Path(directory)
        all_files = sorted(f for f in directory.glob(pattern) if f.is_file())

        if not all_files:
            return {}

        results: dict[str, list[str]] = {}
        errors: dict[str, str] = {}
        skipped = 0

        for i, file_path in enumerate(all_files):
            suffix = file_path.suffix.lower()
            # Compute relative path for display and source tracking
            try:
                rel_path = str(file_path.relative_to(directory))
            except ValueError:
                rel_path = file_path.name

            if progress:
                print(
                    f"\r  [{i+1}/{len(all_files)}] {rel_path[:60]}...",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

            try:
                if suffix == ".pdf":
                    revision_ids = self.ingest_pdf(
                        file_path,
                        valid_time=valid_time,
                        confidence_bp=confidence_bp,
                        chunker=chunker,
                    )
                    results[rel_path] = revision_ids
                elif suffix == ".docx":
                    revision_ids = self.ingest_docx(
                        file_path,
                        valid_time=valid_time,
                        confidence_bp=confidence_bp,
                        chunker=chunker,
                    )
                    results[rel_path] = revision_ids
                elif suffix == ".pptx":
                    revision_ids = self.ingest_pptx(
                        file_path,
                        valid_time=valid_time,
                        confidence_bp=confidence_bp,
                        chunker=chunker,
                    )
                    results[rel_path] = revision_ids
                elif suffix in self._TEXT_EXTENSIONS or suffix == "":
                    # Read as text, skip files that fail UTF-8 decode
                    try:
                        text = file_path.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, PermissionError):
                        skipped += 1
                        continue
                    if not text.strip():
                        skipped += 1
                        continue
                    revision_ids = self.ingest_text(
                        text,
                        source=rel_path,
                        valid_time=valid_time,
                        confidence_bp=confidence_bp,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                    results[rel_path] = revision_ids
                else:
                    skipped += 1
                    continue
            except (ValueError, OSError, RuntimeError, ImportError) as e:
                errors[rel_path] = str(e)
                if progress:
                    print(
                        f"\n  ERROR: {rel_path}: {e}",
                        file=sys.stderr,
                    )

        if progress:
            total_chunks = sum(len(v) for v in results.values())
            print(
                f"\n  Done: {len(results)} files, {total_chunks} chunks, "
                f"{skipped} skipped, {len(errors)} errors",
                file=sys.stderr,
            )

        # Rebuild search index after batch ingestion.
        # All TemporalSearchIndex types implement rebuild() — it's a no-op for
        # SearchIndex (which embeds eagerly on add()) and triggers matrix/embedding
        # rebuild for TF-IDF and dense types.
        if self._index is not None:
            self._index.rebuild()

        return results
