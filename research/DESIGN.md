# Design Document

## Canonical Objective

Define a deterministic, AI-native structure for factual memory where paraphrases converge to the same semantic identity without collapsing near-neighbor facts.

Working name: Deterministic Semantic Fact Graph (`DSFG`).

## Design Targets (V1 Scope)

The V1 implementation covers 10 design iterations:

1. **Semantic Identity** — Canonicalized claim identity via SHA-256 hashing of normalized text (`core_id`).
2. **Relation Algebra** — Deterministic relation edges for dependency, derivation, contradiction, and evidence support.
3. **Bitemporal Revision** — Dual-time revision semantics with `ValidTime` (when fact was true) and `TransactionTime` (when recorded), deterministic supersession/rollback, and as-of query behavior.
4. **Provenance & Uncertainty** — Deterministic confidence composition from evidence atoms, rule-based inference with cycle-safe fixpoint evaluation, and lineage explainability.
5. **Distributed Merge** — Replica-stable merge semantics with conflict classification (competing revisions, ID collisions, epoch quarantine, orphan relations) and deterministic resolution precedence.
6. **Interval Surgery** — Deterministic overlap resolution for partial valid-time conflicts with rollback-safe projection semantics.
7. **Cross-Epoch Migration** — Deterministic migration transactions converting quarantined foreign-epoch operations into admitted canonical state.
8. **Witness Independence** — Witness-basis qualifiers for same-rule inference, reducing conservative undercount while preserving anti-inflation guarantees.
9. **Multi-Hop Migration** — Path composition, cutover precedence, and non-destructive compaction for multi-epoch migration chains.
10. **Surgery Strategy Governance** — Policy sequencing and admissibility constraints for interval-surgery strategy selection.

> **Note:** The autonomous Continuum loop continued through iteration 58, adding governance layers (retention, caching, tiering, attestation, federation, etc.) that were never implemented. These were removed during cleanup.

## Core Entities (V1)

### 1. EntityNode
- `entity_id`: stable ID from entity canonicalization layer.
- `aliases`: lexical forms that may map to the same `entity_id`.

### 2. ClaimType
- `claim_type_id`: ontology predicate ID with version (e.g., `org.ceo_of@v3`).
- `roles`: ordered role schema with type constraints (e.g., `subject:Person`, `object:Organization`).

### 3. ClaimCore
- Semantic identity of a proposition independent of provenance and revision events.
- `core_id = H(ns, claim_type_id, role_fingerprint, polarity, quantifier, modality)`.
- `role_fingerprint`: lexicographically sorted `role=value_token` pairs.

### 4. ClaimRevision
- Immutable assertion payload bound to one `core_id` and one normalized valid-time interval.
- `revision_id = H(ns_rev, core_id, valid_interval_fingerprint, assertion_kind, payload_fingerprint)`.
- `assertion_kind`: `observed` | `inferred`.

### 5. RevisionStatusEvent
- Append-only lifecycle event for one `revision_id`.
- `status_event_id = H(ns_rev_evt, revision_id, event_type, cause_fingerprint, tx_id)`.
- `event_type`: `asserted` | `superseded` | `retracted` | `auto_retracted`.

### 6. EvidenceAtom
- `evidence_id`: stable ID for an atomic evidence payload.
- Deterministic quality fields: `source_reliability_bp`, `extraction_quality_bp`, `independence_key` (all `0..10000` basis points).

### 7. RelationRecord
- Canonical, hash-addressed relation instance.
- `relation_id = H(ns_rel, relation_type_id, endpoint_fingerprint, qualifier_fingerprint)`.

### 8. RuleRecord
- `rule_id`: stable identifier of deterministic inference rule implementation + version.
- `rule_reliability_bp`: calibrated reliability prior in basis points.

### 9. TransactionRecord
- `tx_id`: globally comparable tuple `(hlc_ms, replica_id, replica_seq)`.
- `status`: `committed` | `voided`.

### 10. SchemaEpoch
- `schema_epoch_id`: immutable ID for the full canonicalization + invariant bundle.
- Any change to normalization/invariant policy requires a new epoch ID.

### 11. OperationEnvelope
- Replication unit for append-only sync.
- `op_id = H(ns_op, schema_epoch_id, tx_id, op_kind, subject_id, payload_hash)`.
- Core V1 `op_kind` values: `upsert_core`, `assert_revision`, `append_status_event`, `assert_relation`, `upsert_evidence`, `upsert_rule`, `void_tx`, `apply_interval_surgery`, `apply_epoch_migration`, `apply_migration_compaction`.

### 12. ConflictRecord
- Deterministic record for merge/admission conflicts.
- `conflict_id = H(ns_conflict, conflict_class, subject_fingerprint, first_seen_tx_id)`.
- `conflict_class` includes: `CF-01` (competing revisions), `CF-02` (epoch quarantine), `CF-03` (ID collision/poison), `CF-04` (orphan relation), and others.
- Resolution state: `open` | `resolved`, with optional chosen winner.

---

## Design Targets (V2 Scope)

V2 extends DKS from a storage backend to a complete agentic memory system while preserving the deterministic core.

### DT-11: Extraction Protocol

**Module:** `dks.extract`

Protocol-based claim extraction with swappable backends:
- `Extractor` Protocol: `.extract(text, claim_types) -> ExtractionResult`
- `RegexExtractor`: Zero-dependency default for structured patterns
- `LLMExtractor`: LLM-backed extraction for open-domain text

Key design: ExtractionResult is non-deterministic output. Only `store.assert_revision()` crosses the commitment boundary.

### DT-12: Entity Resolution as Data

**Module:** `dks.resolve`

Entity resolution decisions are stored AS CLAIMS in the KnowledgeStore:
- `ClaimCore(claim_type="dks.entity_alias@v1", slots={"surface": mention, "entity": entity_id, "method": method})`
- Resolution decisions are auditable, retractable, and temporally queryable
- `CascadingResolver`: exact → normalized → embedding → LLM (tried in order)

This makes entity resolution a first-class operation in the knowledge graph, not a black box preprocessing step.

### DT-13: Temporal-Aware Search

**Module:** `dks.index`

Embedding-based semantic search filtered through `query_as_of()`:
- `EmbeddingBackend` Protocol: `.embed(texts) -> vectors`
- `SearchIndex`: Combines similarity with bitemporal visibility
- Results honor the same temporal guarantees as direct queries

### DT-14: Pipeline Orchestration

**Module:** `dks.pipeline`

Single canonical execution path: `Pipeline`
- `ingest()`: extract → resolve → commit → index
- `query()`: embed → search → temporal filter
- `merge()`: deterministic store merge
- `rebuild_index()`: reconstruct search index from store

### DT-15: MCP Integration

**Module:** `dks.mcp`

Model Context Protocol server exposing Pipeline as tools:
- `dks_ingest`: Ingest text into the store
- `dks_query`: Semantic search with temporal filtering
- `dks_query_exact`: Direct core_id lookup with bitemporal coordinates
- `dks_snapshot`: Export canonical JSON
- `dks_stats`: Store statistics

## V2 Bug Fixes Applied to V1 Core

- **Merge pending relations transfer**: `merge()` now processes `other._pending_relations`
- **Merge variant/collision history transfer**: `merge()` now transfers `other._relation_variants` and `other._relation_collision_pairs`
- **Retraction splash narrowing**: Retraction of `[2010,2020)` no longer suppresses asserted `[2015,2025)` in the overlap zone (per FM-009/INV-T5)
- **Unicode NFC normalization**: `canonicalize_text()` applies `unicodedata.normalize("NFC")`
- **Zero-width character stripping**: Invisible codepoints (zero-width spaces, BOM, bidi marks) stripped before identity hashing
