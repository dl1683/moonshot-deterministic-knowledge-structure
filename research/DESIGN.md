# Design Document

Last updated: 2026-03-05 (v0.3.7)

## Canonical Objective

Define a deterministic, AI-native structure for factual memory where paraphrases converge to the same semantic identity without collapsing near-neighbor facts.

Working name: Deterministic Knowledge Structure (`DKS`).

## Design Targets (V1 Scope)

1. **Semantic Identity** — Canonicalized claim identity via SHA-256 hashing of normalized text (`core_id`). Unicode NFC normalization + zero-width character stripping.
2. **Relation Algebra** — Deterministic relation edges (`relation_id`) for typed relationships between revisions, with symmetric endpoint handling.
3. **Bitemporal Revision** — Dual-time revision semantics with `ValidTime` (when fact was true) and `TransactionTime` (when recorded). Deterministic supersession, retraction, and as-of/tx-window/transition query surfaces.
4. **Provenance & Confidence** — Source tracking via `Provenance` (source + evidence_ref). Confidence in basis points (0-10000). Both survive serialization round-trips.
5. **Deterministic Merge** — CRDT-style merge with conflict classification (competing revisions, ID collisions, orphan relations). Pending relation transfer, deferred orphan replay, variant/collision history transfer. Proven commutative, associative, and idempotent via Hypothesis.
6. **Snapshot Persistence** — Canonical JSON serialization with schema version, integrity checksum, preflight validation, referential integrity checks, and fail-closed deserialization.
7. **State Fingerprint** — Composed deterministic digest from all projection surfaces (as-of, tx-window, transition), with canonical serialization/deserialization round-trip.

> **Note:** The autonomous Continuum loop (iterations 11-58) added speculative governance layers (interval surgery, epoch migration, witness independence, retention GC, federation, attestation) that were never implemented. These were removed during cleanup.

## Core Entities (V1)

### 1. ClaimCore
- Semantic identity of a proposition.
- `core_id = SHA-256(canonical(claim_type + sorted(slots)))`.
- Fields: `claim_type: str`, `slots: dict[str, str]`.

### 2. ClaimRevision
- Immutable assertion payload bound to one `core_id` and one `ValidTime` interval.
- `revision_id = SHA-256(core_id + assertion + valid_time + transaction_time + provenance + confidence_bp + status)`.
- Fields: `core_id: str`, `assertion: str`, `valid_time: ValidTime`, `transaction_time: TransactionTime`, `provenance: Provenance`, `confidence_bp: int`, `status: "asserted" | "retracted"`.

### 3. RelationEdge
- Deterministic typed edge between two revisions.
- `relation_id = SHA-256(relation_type + from_revision_id + to_revision_id + transaction_time)`. Endpoints are lexicographically sorted for symmetric types (`contradicts`); ordered for directional types (`supports`, `depends_on`, `derived_from`).
- Fields: `relation_type: str`, `from_revision_id: str`, `to_revision_id: str`, `transaction_time: TransactionTime`.

### 4. ValidTime
- Half-open interval `[start, end)` representing when a fact was true in the real world.
- Fields: `start: datetime`, `end: datetime | None`.

### 5. TransactionTime
- When an operation was recorded in the store.
- Fields: `tx_id: int`, `recorded_at: datetime`.

### 6. Provenance
- Source attribution for a revision.
- Fields: `source: str`, `evidence_ref: str | None`.

### 7. ConflictCode (Enum)
- Classification of merge conflicts: `CORE_ID_COLLISION`, `REVISION_ID_COLLISION`, `RELATION_ID_COLLISION`, `COMPETING_REVISION_SAME_SLOT`, `COMPETING_LIFECYCLE_SAME_SLOT`, `ORPHAN_RELATION_ENDPOINT`.

### 8. MergeConflict
- Record of a single merge conflict with `code: ConflictCode`, `entity_id: str`, and `details: str`.

### 9. MergeResult
- Outcome of `store.merge()`: a merged `KnowledgeStore` plus a list of `MergeConflict` entries.

### 10. KnowledgeStore
- The core bitemporal store. Holds all claims, revisions, relations, and merge history.
- Key operations: `assert_revision()`, `attach_relation()`, `query_as_of()`, `merge()`, `checkpoint()`.
- Projection surfaces: revision lifecycle, relation lifecycle, relation resolution, merge conflict, state fingerprint — all with as-of, tx-window, and transition variants.

---

## Design Targets (V2 Scope)

V2 extends DKS from a storage backend to a complete agentic memory system while preserving the deterministic core.

### DT-11: Extraction Protocol

**Module:** `dks.extract`

Protocol-based claim extraction with swappable backends:
- `Extractor` Protocol: `.extract(text, claim_types) -> ExtractionResult`
- `RegexExtractor`: Zero-dependency default for structured patterns
- `LLMExtractor`: LLM-backed extraction for open-domain text
- `PDFExtractor`: PyMuPDF text extraction + chunking
- `DocxExtractor`: python-docx paragraphs + tables + metadata
- `PptxExtractor`: python-pptx slides + shapes + tables + notes
- `TextChunker`: Smart splitting with overlap

Key design: ExtractionResult is non-deterministic output. Only `store.assert_revision()` crosses the commitment boundary.

### DT-12: Entity Resolution as Data

**Module:** `dks.resolve`

Entity resolution decisions are stored AS CLAIMS in the KnowledgeStore:
- `ClaimCore(claim_type="dks.entity_alias@v1", slots={"surface": mention, "entity": entity_id, "method": method})`
- Resolution decisions are auditable, retractable, and temporally queryable
- `CascadingResolver`: chains user-provided resolvers (built-in: exact → normalized; embedding/LLM are extension points)

### DT-13: Temporal-Aware Search

**Module:** `dks.index`

Search index implementations filtered through `query_as_of()`:
- `TemporalSearchIndex` Protocol with 4 conforming implementations
- `TfidfSearchIndex`: TF-IDF with temporal filtering
- `DenseSearchIndex`: Sentence-transformer embeddings
- `HybridSearchIndex`: Reciprocal rank fusion (RRF)
- `KnowledgeGraph`: Entity co-occurrence graph with traversal

### DT-14: Pipeline Orchestration

**Module:** `dks.pipeline`

Single canonical execution path: `Pipeline` (50+ public methods)
- `ingest_text()`, `ingest_pdf()`, `ingest_docx()`, `ingest_pptx()`, `ingest_directory()`
- `query()`, `reason()`, `query_deep()`, `synthesize()`
- `merge()`, `rebuild_index()`, `build_graph()`
- `save()` / `load()`: Full state persistence (store + index + graph)

### DT-15: MCP Integration

**Module:** `dks.mcp`

Model Context Protocol server exposing Pipeline as 25 tools for AI agent integration.

### DT-16: CLI

**Module:** `dks.cli`

Click-based CLI: `ingest`, `query`, `stats`, `sources`, `repl`, `demo`, `serve`.

## V2 Bug Fixes Applied to V1 Core

- **Merge pending relations transfer**: `merge()` now processes `other._pending_relations`
- **Merge variant/collision history transfer**: `merge()` now transfers `other._relation_variants` and `other._relation_collision_pairs`
- **Retraction splash narrowing**: Retraction of `[2010,2020)` no longer suppresses asserted `[2015,2025)` in the overlap zone (per FM-009/INV-T5)
- **Unicode NFC normalization**: `canonicalize_text()` applies `unicodedata.normalize("NFC")`
- **Zero-width character stripping**: Invisible codepoints (zero-width spaces, BOM, bidi marks) stripped before identity hashing
