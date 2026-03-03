"""Deterministic Knowledge Structure — agentic AI memory with deterministic core."""

from .core import (
    ClaimCore,
    ClaimRevision,
    ConflictCode,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeConflictProjection,
    MergeConflictProjectionTransition,
    MergeConflict,
    MergeResult,
    Provenance,
    RevisionLifecycleProjection,
    RevisionLifecycleTransition,
    RelationLifecycleProjection,
    RelationLifecycleTransition,
    RelationResolutionProjection,
    RelationResolutionTransition,
    RelationLifecycleSignatureProjection,
    RelationLifecycleSignatureTransition,
    RelationEdge,
    SnapshotValidationError,
    SnapshotValidationReport,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)

from .extract import (
    ExtractionResult,
    Extractor,
    LLMExtractor,
    RegexExtractor,
)

from .resolve import (
    CascadingResolver,
    ExactResolver,
    NormalizedResolver,
    ResolutionDecision,
    Resolver,
)

from .index import (
    EmbeddingBackend,
    NumpyIndex,
    SearchIndex,
    SearchResult,
)

from .pipeline import Pipeline

from .mcp import MCPToolHandler

__all__ = [
    # V1 core (26 symbols — unchanged)
    "ClaimCore",
    "ClaimRevision",
    "ConflictCode",
    "DeterministicStateFingerprint",
    "DeterministicStateFingerprintTransition",
    "KnowledgeStore",
    "MergeConflictProjection",
    "MergeConflictProjectionTransition",
    "MergeConflict",
    "MergeResult",
    "Provenance",
    "RevisionLifecycleProjection",
    "RevisionLifecycleTransition",
    "RelationLifecycleProjection",
    "RelationLifecycleTransition",
    "RelationResolutionProjection",
    "RelationResolutionTransition",
    "RelationLifecycleSignatureProjection",
    "RelationLifecycleSignatureTransition",
    "RelationEdge",
    "SnapshotValidationError",
    "SnapshotValidationReport",
    "TransactionTime",
    "ValidTime",
    "canonicalize_text",
    # V2 extraction
    "ExtractionResult",
    "Extractor",
    "LLMExtractor",
    "RegexExtractor",
    # V2 resolution
    "CascadingResolver",
    "ExactResolver",
    "NormalizedResolver",
    "ResolutionDecision",
    "Resolver",
    # V2 search
    "EmbeddingBackend",
    "NumpyIndex",
    "SearchIndex",
    "SearchResult",
    # V2 pipeline
    "Pipeline",
    # V2 MCP
    "MCPToolHandler",
]
