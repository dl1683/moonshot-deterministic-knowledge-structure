# Research Index

## Implementation

| File | Description |
|------|-------------|
| `src/dks/core.py` | Single-file V1 implementation (~5,100 lines). All 18 classes. |
| `src/dks/__init__.py` | Public API surface — 26 exported symbols. |

## Tests

| File | Description |
|------|-------------|
| `tests/test_v1_core.py` | Core behavior tests (87 tests) — identity, revision, merge, query, conflict. |
| `tests/test_v1_semantics.py` | Semantic determinism tests. |
| `tests/test_v1_*_permutations.py` | Insertion-order permutation invariance tests. |
| `tests/test_v1_*_replay*.py` | Checkpoint/restart replay determinism tests. |
| `tests/test_v1_store_snapshot*.py` | Snapshot persistence round-trip tests. |
| `tests/test_v1_merge_conflict_journal*.py` | Merge conflict journal recording/query tests. |
| `tests/test_v1_relation_lifecycle*.py` | Relation lifecycle projection tests. |
| `tests/test_v1_state_fingerprint*.py` | State fingerprint query tests. |

## Research Documents

| File | Description |
|------|-------------|
| `research/DESIGN.md` | V1 design: canonical objective, design targets, core entities. |
| `research/STATE.md` | Current implementation state and completeness tracker. |
| `research/DECISION_LOG.md` | Architectural decisions summary. |
| `research/FAILURE_MODES.md` | Failure mode catalog (FM-001 through FM-020). |
| `research/EXECUTION_GATE.md` | Execution gate criteria and verification checklist. |
| `research/EVALUATION_RUBRIC.md` | Design evaluation rubric and scoring. |

## Tools

| File | Description |
|------|-------------|
| `tools/post_iter_verify.cmd` | Test runner script for post-change verification. |
| `tools/function_smoke.py` | Smoke test for core API functions. |
