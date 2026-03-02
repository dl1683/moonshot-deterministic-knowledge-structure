# Deterministic Knowledge Structure (DKS)

A deterministic, AI-native data structure for factual memory where paraphrases converge to the same semantic identity without collapsing near-neighbor facts.

## What This Is

DKS is a V1 implementation of a **Deterministic Semantic Fact Graph** — a bitemporal knowledge store with:

- **Canonicalized identity**: SHA-256 hashing of normalized text ensures "the CEO of Apple" and "Apple's CEO" converge to the same `core_id`
- **Bitemporal revision model**: Separate `ValidTime` (when a fact was true) and `TransactionTime` (when it was recorded) for audit-safe historical queries
- **Deterministic merge**: Replica-stable conflict resolution with explicit conflict records (competing revisions, ID collisions, epoch quarantine, orphan relations)
- **Provenance tracking**: Evidence atoms with independence-aware confidence aggregation and cycle-safe inference fixpoints
- **Snapshot persistence**: Full store state serializable to canonical JSON with round-trip validation and checkpoint/restart determinism

## Install

```bash
pip install -e ".[dev]"
```

## Test

```bash
python -m pytest -q
```

475 tests covering identity determinism, bitemporal queries, merge conflict resolution, snapshot round-trips, insertion-order permutation invariance, and checkpoint/restart replay.

## Core API

```python
from dks import ClaimCore, KnowledgeStore, ValidTime, TransactionTime, canonicalize_text

# Create a knowledge store
store = KnowledgeStore()

# Canonicalize text for stable identity
text = canonicalize_text("The CEO of Apple is Tim Cook")

# Create claims with valid-time intervals
claim = ClaimCore(
    claim_type_id="org.ceo_of@v1",
    role_bindings={"subject": "tim_cook", "object": "apple_inc"},
)

# Assert revisions with bitemporal coordinates
vt = ValidTime(start=2011, end=None)
tt = TransactionTime(tx_id=(1, "replica_a", 1))
store.assert_revision(claim, vt, tt)

# Query as-of any point in transaction time
result = store.query_as_of(claim.core_id, valid_at=2023, tx_asof=tt)

# Merge two stores deterministically
other_store = KnowledgeStore()
merge_result = store.merge(other_store)
# merge_result.conflicts contains any CF-01..CF-04 conflict records
```

## Exported Symbols (26)

| Category | Symbols |
|----------|---------|
| **Core types** | `ClaimCore`, `ClaimRevision`, `ValidTime`, `TransactionTime`, `Provenance`, `RelationEdge` |
| **Store** | `KnowledgeStore`, `MergeResult`, `MergeConflict`, `ConflictCode` |
| **Query projections** | `RevisionLifecycleProjection`, `RevisionLifecycleTransition`, `RelationLifecycleProjection`, `RelationLifecycleTransition`, `RelationResolutionProjection`, `RelationResolutionTransition`, `RelationLifecycleSignatureProjection`, `RelationLifecycleSignatureTransition` |
| **Fingerprinting** | `DeterministicStateFingerprint`, `DeterministicStateFingerprintTransition`, `MergeConflictProjection`, `MergeConflictProjectionTransition` |
| **Snapshot** | `SnapshotValidationError`, `SnapshotValidationReport` |
| **Utilities** | `canonicalize_text` |

## Project Structure

```
src/dks/
  __init__.py          26 exported symbols (public API)
  core.py              ~5,100 lines, single-file V1 implementation
tests/                 86 test files, 475 tests
tools/
  post_iter_verify.cmd Test runner script
  function_smoke.py    API smoke test
research/
  DESIGN.md            V1 design targets and core entity definitions
  STATE.md             Implementation completeness tracker
  FAILURE_MODES.md     20 core failure modes and mitigations
  DECISION_LOG.md      Architectural decisions summary
  EXECUTION_GATE.md    Verification checklist
  EVALUATION_RUBRIC.md Design evaluation rubric
```

## Design

See [`research/DESIGN.md`](research/DESIGN.md) for the full V1 design document covering:
- 10 design targets (semantic identity through surgery strategy governance)
- 12 core entity definitions (ClaimCore through ConflictRecord)
- Deterministic invariants and conflict classification

## Background

This project was originally built through an autonomous LLM iteration loop (135+ cycles). The V1 implementation is complete and tested. The repository has been cleaned up to contain only the essential code, tests, and documentation.
