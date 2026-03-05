# Evaluation Rubric

Last updated: 2026-03-05 (v0.3.7)

This rubric defines pass/fail quality thresholds for the DKS implementation.
All criteria below are tested in the current suite (1,183 tests).

## Category A: Representation Quality

### A1: Paraphrase Robustness

- **Pass**: Curated paraphrase pairs (voice swap, alias substitution, unit rewrite) produce identical `core_id` after canonicalization (Unicode NFC + zero-width stripping + SHA-256).
- **Fail**: Any systematic paraphrase class has less than 90% convergence.

### A2: Distinction Preservation

- **Pass**: Near-neighbor fact pairs (same entities, different predicate/roles/polarity) produce different `core_id`. At least 99% separation.
- **Fail**: Any collision cluster caused by wildcarding or omitted identity fields.

### A3: Relation Semantics

- **Pass**: All relation assertions satisfy typed signatures. `contradicts(A,B) == contradicts(B,A)`. Reordered derivation premises produce stable `relation_id`.
- **Fail**: Endpoint order or duplicate premises change relation identity.

## Category B: Temporal and Provenance Integrity

### B1: Dual-Time Support

- **Pass**: `query_as_of(core, valid_at, tx_asof)` returns only revisions visible at `tx_asof`. Historical replay is stable before and after rollback boundaries.
- **Fail**: Any query result includes a revision from non-visible transaction state (retroactive ghost fact).

### B2: Revision History and Supersession

- **Pass**: Supersession only occurs for exact `(core_id, valid_interval)` matches. Retraction propagates to related revisions deterministically.
- **Fail**: Supersession is non-deterministic or affects unrelated intervals.

### B3: Provenance Trace

- **Pass**: Every revision carries `source`, `provenance`, and `metadata` fields. Provenance survives serialization round-trips.
- **Fail**: Any revision lacks provenance after snapshot restore.

### B4: Confidence Determinism

- **Pass**: `confidence_bp` (basis points, 0-10000) is deterministic for identical inputs. Confidence survives merge and serialization.
- **Fail**: Confidence values differ across replicas or after snapshot round-trip.

## Category C: Merge and Conflict Resolution

### C1: CRDT Properties

- **Pass**: Merge is commutative, associative, and idempotent (proven via Hypothesis property-based tests).
- **Fail**: Any merge property violation.

### C2: Conflict Classification

- **Pass**: Competing revisions, ID collisions, and orphan relations are classified deterministically. Conflict journal records all merge conflicts with tx-integrity.
- **Fail**: Any unclassified conflict or journal corruption.

### C3: Pending Relation Transfer

- **Pass**: Pending relations in source store transfer correctly during merge. Deferred orphan relations replay idempotently when endpoints arrive.
- **Fail**: Pending relations lost or duplicated during merge.

## Category D: Persistence and Snapshot Integrity

### D1: Serialization Round-Trip

- **Pass**: `KnowledgeStore` snapshot serialization/deserialization produces byte-identical state. All projection surfaces (as-of, tx-window, transition) produce identical results before and after restore.
- **Fail**: Any projection surface diverges after restore.

### D2: Schema and Checksum

- **Pass**: Snapshot includes schema version, integrity checksum, and preflight validation. Malformed/incompatible snapshots are rejected fail-closed.
- **Fail**: Corrupted snapshot loads without error.

### D3: Referential Integrity

- **Pass**: Dangling references (relations pointing to non-existent claims) are detected during snapshot validation.
- **Fail**: Dangling references pass validation silently.

## Category E: Insertion Order Invariance

### E1: Permutation Determinism

- **Pass**: All permutations of the same operations produce identical state fingerprints. Replay/permutation stress tests confirm.
- **Fail**: Any permutation changes the resulting state fingerprint.

### E2: Checkpoint Segmentation

- **Pass**: Unsplit replay and segmented checkpoint replay produce identical state.
- **Fail**: Checkpoint boundaries affect final state.

## Verification

All criteria are exercised by:

```bash
python -m pytest -q                    # 1,183 tests
python -m pytest tests/test_v1_*.py    # V1 core criteria (A-E)
python -m pytest tests/test_v2_*.py    # V2 pipeline criteria
```
