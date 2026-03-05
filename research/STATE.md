# State

Last updated: 2026-03-05 (v0.3.7)

## Current Architecture

### V1 Core (`dks.core` — zero external dependencies)

- **Data primitives**: `ClaimCore` (canonicalized identity + stable `core_id`), `ClaimRevision` (bitemporal + provenance + confidence), `RelationEdge` (deterministic `relation_id` + symmetry)
- **Identity**: Unicode NFC normalization, zero-width stripping, SHA-256 canonical hashing
- **Time model**: `ValidTime` half-open interval `[start, end)`, `TransactionTime` with `tx_id` ordering
- **Core operations**: `assert_revision`, `attach_relation`, `query_as_of`, `merge`, `checkpoint`
- **Lifecycle projections**: Revision lifecycle, relation lifecycle, relation resolution, merge conflict, state fingerprint — all with as-of, tx-window, and transition query surfaces
- **Snapshot persistence**: Canonical JSON serialization/deserialization with schema version, checksum, preflight validation, referential integrity checks
- **Merge**: Deterministic CRDT-style merge with conflict classification (competing revisions, ID collisions, orphan relations), deferred pending relation replay, checkpoint-backed snapshots
- **State fingerprint**: Composed deterministic digest from all projection surfaces, with canonical serialization/deserialization round-trip

### V2 Pipeline Layer

| Module | Purpose |
|--------|---------|
| `dks.extract` | Extractor Protocol + RegexExtractor + LLMExtractor + PDFExtractor + DocxExtractor + PptxExtractor |
| `dks.resolve` | Resolver Protocol + ExactResolver + NormalizedResolver + CascadingResolver |
| `dks.index` | TemporalSearchIndex Protocol + TF-IDF + Dense + Hybrid RRF + KnowledgeGraph |
| `dks.search` | SearchEngine: multi-hop reasoning, synthesis, entity linking, deduplication |
| `dks.explore` | Explorer: corpus profiles, quality reports, annotations, insights |
| `dks.ingest` | Ingester: extract → resolve → commit → index (PDF, DOCX, PPTX, text, directory) |
| `dks.pipeline` | Thin facade orchestrator — 50+ public methods |
| `dks.mcp` | MCPToolHandler — 25 tools for AI agent integration |
| `dks.cli` | Click CLI: ingest, query, stats, sources, repl, demo, serve |
| `dks.audit` | AuditEvent / AuditTrace / AuditManager |
| `dks.results` | Result dataclasses for structured output |

### Key Design Properties

- **Commitment boundary**: Non-deterministic extraction/resolution → deterministic storage via `assert_revision()`
- **Protocol-based backends**: Extractor, Resolver, EmbeddingBackend, TemporalSearchIndex — all swappable
- **Zero cross-module private access**: All inter-module communication through public APIs
- **Retraction-aware search**: `retracted_core_ids()` cached, `_ensure_index_fresh()` on all 19 search-facing methods
- **Safe deserialization**: `_safe_pickle_load()` with explicit type allowlist

## Test Inventory

- **1,183 tests** across 115 test files
- V1 core: identity determinism, Unicode convergence, bitemporal queries, retraction semantics, CRDT merge (Hypothesis), snapshot round-trips, permutation invariance
- V2 pipeline: extraction, resolution, indexing, search, MCP, save/load
- V3-V6: stress tests, edge cases, integration, Protocol conformance, security

## Metrics

| Metric | Value |
|--------|-------|
| Version | 0.3.7 |
| Total lines | ~16,000 |
| Modules | 12 |
| Exported symbols | 61 |
| Tests | 1,183 |
| Test files | 115 |
| External deps (core) | 0 |
| Codex grade | A+ (review #15) |
