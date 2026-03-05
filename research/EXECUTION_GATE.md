# Execution Gate

Last updated: 2026-03-05 (v0.3.7)

## V1 Core Gate (all passing)

- [x] Minimal project scaffold (`pyproject.toml`, `src/`, `tests/`)
- [x] V1 primitives (`ClaimCore`, `ClaimRevision`, `RelationEdge`)
- [x] Deterministic identity (canonicalization + stable IDs via SHA-256)
- [x] Unicode NFC normalization + zero-width character stripping
- [x] Dual-time model (`ValidTime`, `TransactionTime`)
- [x] Core operations (`assert_revision`, `attach_relation`, `query_as_of`, `merge`)
- [x] Provenance and confidence representation
- [x] Lifecycle-aware active-endpoint relation filtering
- [x] Pending relation visibility with tx-cutoff filtering
- [x] Revision lifecycle projection (as-of, tx-window, transition)
- [x] Relation lifecycle projection (as-of, tx-window, transition)
- [x] Relation resolution projection (as-of, tx-window, transition)
- [x] Relation lifecycle signature projection (as-of, tx-window, transition)
- [x] Merge conflict projection (as-of, tx-window, transition)
- [x] State fingerprint (as-of, tx-window, transition) with optional conflict-aware input
- [x] Canonical ordering/transition/tx-window/as-of helper routing
- [x] Deterministic state fingerprint serialization/deserialization round-trip
- [x] KnowledgeStore snapshot serialization/deserialization
- [x] Snapshot file I/O with lock-contention retry
- [x] Snapshot schema version compatibility checks
- [x] Strict snapshot deserialization (key-set validation, malformed input rejection)
- [x] Snapshot validation errors (deterministic code/path/message)
- [x] Snapshot integrity checksum (emission + fail-closed validation)
- [x] Snapshot preflight validation (report contracts + load-vs-validate parity)
- [x] Snapshot referential integrity (dangling reference detection)
- [x] Snapshot full-surface restore parity (as-of, window, transition APIs)
- [x] Conflict-aware snapshot restore parity
- [x] Merge-conflict input-aware snapshot restore parity
- [x] Merge conflict journal tx-integrity (fail-closed unknown tx rejection)
- [x] Replay/permutation stress testing (insertion order invariance)
- [x] Checkpoint segmentation determinism (unsplit vs segmented equivalence)
- [x] Duplicate replay idempotence
- [x] Cross-surface consistency (as-of / tx-window / transition parity)
- [x] Mixed orphan+collision+lifecycle checkpoint replay equivalence
- [x] Golden regression baselines for fingerprints and snapshots
- [x] Merge pending relation transfer
- [x] Merge variant/collision history transfer
- [x] Retraction splash narrowing (FM-009/INV-T5)
- [x] Deferred orphan relation replay with idempotent promotion
- [x] CRDT merge properties proven via Hypothesis (commutativity, associativity, idempotency)

## V2 Pipeline Gate (all passing)

- [x] Extractor Protocol + RegexExtractor + LLMExtractor
- [x] PDFExtractor (PyMuPDF text extraction + chunking)
- [x] DocxExtractor (python-docx paragraphs + tables + metadata)
- [x] PptxExtractor (python-pptx slides + shapes + tables + notes)
- [x] TextChunker (smart splitting with overlap)
- [x] Resolver Protocol + ExactResolver + NormalizedResolver + CascadingResolver
- [x] TemporalSearchIndex Protocol (4 conforming implementations)
- [x] TF-IDF search index with temporal filtering
- [x] Dense embedding search index
- [x] Hybrid RRF (reciprocal rank fusion)
- [x] KnowledgeGraph (entity co-occurrence + traversal)
- [x] SearchEngine: multi-hop reasoning, synthesis, entity linking
- [x] Explorer: corpus profiles, quality reports, annotations, insights
- [x] Ingester: extract → resolve → commit → index (all document formats)
- [x] Recursive directory ingestion (60+ file types)
- [x] Pipeline orchestrator (50+ public methods)
- [x] Pipeline save/load (store + index + graph state)
- [x] MCPToolHandler (25 tools for AI agent integration)
- [x] Click CLI: ingest, query, stats, sources, repl, demo, serve
- [x] AuditManager with trace-level event tracking
- [x] Retraction-aware search filtering across all subsystems
- [x] Protocol conformance tests for all search index types
- [x] Safe pickle deserialization with type allowlist

## Verification

```bash
pip install -e ".[dev]"
python -m pytest -q          # 1,183 tests, all passing
tools/post_iter_verify.cmd   # Full verification battery
```
