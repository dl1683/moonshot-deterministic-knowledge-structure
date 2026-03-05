# Research Index

## Implementation

| Module | Description | Lines |
|--------|-------------|-------|
| `src/dks/core.py` | Deterministic bitemporal store (zero external deps) | ~5,200 |
| `src/dks/search.py` | SearchEngine: multi-hop reasoning, synthesis, entity linking | ~2,930 |
| `src/dks/explore.py` | Explorer: profiles, annotations, quality reports, insights | ~2,250 |
| `src/dks/index.py` | TF-IDF + Dense + Hybrid RRF + KnowledgeGraph + TemporalSearchIndex Protocol | ~1,340 |
| `src/dks/pipeline.py` | Thin facade orchestrator — 50+ public methods | ~890 |
| `src/dks/extract.py` | Extractor Protocol + Regex + LLM + PDF + DOCX + PPTX | ~835 |
| `src/dks/mcp.py` | MCPToolHandler — 25 tools for AI agent integration | ~615 |
| `src/dks/cli.py` | Click-based CLI — ingest, query, explore, serve | ~575 |
| `src/dks/ingest.py` | Ingester: extract → resolve → commit → index | ~490 |
| `src/dks/results.py` | Result dataclasses for structured output | ~275 |
| `src/dks/audit.py` | AuditEvent / AuditTrace / AuditManager | ~175 |
| `src/dks/resolve.py` | Resolver Protocol + cascading resolution | ~165 |
| `src/dks/__init__.py` | Public API surface — 61 exported symbols | ~155 |

**Total: ~16,000 lines across 12 modules (excluding `__init__.py`).**

## Tests

115 test files, 1,183 tests. Naming convention: `test_v{N}_{feature}.py`.

| Pattern | Description |
|---------|-------------|
| `test_v1_core.py` | Core behavior tests — identity, revision, merge, query, conflict |
| `test_v1_semantics.py` | Semantic determinism tests |
| `test_v1_*_permutations.py` | Insertion-order permutation invariance |
| `test_v1_*_replay*.py` | Checkpoint/restart replay determinism |
| `test_v1_store_snapshot*.py` | Snapshot persistence round-trip tests |
| `test_v1_merge_conflict_journal*.py` | Merge conflict journal recording/query |
| `test_v1_relation_lifecycle*.py` | Relation lifecycle projection tests |
| `test_v1_state_fingerprint*.py` | State fingerprint query tests |
| `test_v2_*.py` | Pipeline, extraction, indexing, search, MCP, save/load |
| `test_v3_*.py` | Advanced stress, edge cases, integration, robustness |
| `test_v4_*.py` | Codex-mandated tests, error handling, quality benchmarks |
| `test_v5_*.py` | Index dirty flag, pickle security, Codex review tests |
| `test_v6_*.py` | Protocol conformance, functional fixes |
| `test_acceptance_gate.py` | End-to-end acceptance gate |

## Research Documents

| File | Description |
|------|-------------|
| `research/DESIGN.md` | V1 + V2 design targets, core entities, bug fixes |
| `research/STATE.md` | Current implementation state summary |
| `research/DECISION_LOG.md` | Architectural decisions (10 core decisions) |
| `research/FAILURE_MODES.md` | Failure mode catalog (FM-001 through FM-020) |
| `research/EXECUTION_GATE.md` | Gate checklist — what is implemented |
| `research/EVALUATION_RUBRIC.md` | Design evaluation rubric and scoring criteria |

## Tools

| File | Description |
|------|-------------|
| `tools/demo.py` | Interactive demo + automated capability battery |
| `tools/function_smoke.py` | Smoke test for core API functions |
| `tools/post_iter_verify.cmd` | Test runner script for post-change verification |
