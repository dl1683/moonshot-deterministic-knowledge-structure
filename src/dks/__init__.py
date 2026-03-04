"""Deterministic Knowledge Structure — agentic AI memory with deterministic core."""

__version__ = "0.3.3"

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
    PDFExtractor,
    RegexExtractor,
    TextChunker,
)

from .resolve import (
    CascadingResolver,
    ExactResolver,
    NormalizedResolver,
    ResolutionDecision,
    Resolver,
)

from .index import (
    CrossEncoderReranker,
    DenseSearchIndex,
    EmbeddingBackend,
    HybridSearchIndex,
    KnowledgeGraph,
    NumpyIndex,
    SearchIndex,
    SearchResult,
    SentenceTransformerIndex,
    TfidfIndex,
    TfidfSearchIndex,
)

from .audit import (
    AuditEvent,
    AuditManager,
    AuditTrace,
)

from .results import (
    CoverageReport,
    DeepQueryResult,
    EvidenceChain,
    QueryFacet,
    ReasoningResult,
    SynthesisResult,
)

from .pipeline import Pipeline

from .mcp import MCPToolHandler

__all__ = [
    # V1 core (26 symbols)
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
    "PDFExtractor",
    "RegexExtractor",
    "TextChunker",
    # V2 resolution
    "CascadingResolver",
    "ExactResolver",
    "NormalizedResolver",
    "ResolutionDecision",
    "Resolver",
    # V2 search
    "CrossEncoderReranker",
    "DenseSearchIndex",
    "EmbeddingBackend",
    "HybridSearchIndex",
    "KnowledgeGraph",
    "NumpyIndex",
    "SearchIndex",
    "SearchResult",
    "SentenceTransformerIndex",
    "TfidfIndex",
    "TfidfSearchIndex",
    # V2 audit
    "AuditEvent",
    "AuditManager",
    "AuditTrace",
    # V2 pipeline
    "CoverageReport",
    "DeepQueryResult",
    "EvidenceChain",
    "Pipeline",
    "QueryFacet",
    "ReasoningResult",
    "SynthesisResult",
    # V2 MCP
    "MCPToolHandler",
]
