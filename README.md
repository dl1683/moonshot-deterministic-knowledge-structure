# DKS — Deterministic Knowledge Structure

**The SQLite for agent memory.** A deterministic, bitemporal knowledge store for AI agents that need reliable, auditable, mergeable memory.

```
pip install dks           # zero-dependency core
pip install dks[pipeline] # + numpy for embedding search
pip install dks[all]      # + LLM + MCP integration
```

## Quick Start

```python
from dks import Pipeline, KnowledgeStore

# Create pipeline
pipeline = Pipeline(store=KnowledgeStore())

# Ingest text (automatically chunked and indexed)
pipeline.ingest_text("Einstein developed the theory of relativity in 1905.", source="physics.txt")
pipeline.ingest_text("Newton published Principia Mathematica in 1687.", source="physics.txt")
pipeline.rebuild_index()

# Search
results = pipeline.query("who developed relativity")
print(results[0].text)  # Einstein developed the theory of relativity...

# Save and load
pipeline.save("my_knowledge.dks")
loaded = Pipeline.load("my_knowledge.dks")
```

### Advanced: Structured Extraction

```python
from dks import Pipeline, RegexExtractor, NumpyIndex, ValidTime, TransactionTime
from datetime import datetime, timezone

# Configure with custom extractor
extractor = RegexExtractor()
extractor.register_pattern("residence", r"(?P<subject>\w+) lives in (?P<city>\w+)", ["subject", "city"])
pipeline = Pipeline(extractor=extractor, embedding_backend=NumpyIndex(dimension=64))

# Ingest with explicit temporal context
pipeline.ingest(
    "Alice lives in London",
    valid_time=ValidTime(start=datetime(2024, 1, 1, tzinfo=timezone.utc), end=None),
    transaction_time=TransactionTime(tx_id=1, recorded_at=datetime.now(timezone.utc)),
)

# Query with temporal awareness
results = pipeline.query("who lives where", k=5)
```

## What DKS Does

DKS is a **complete agentic memory system** built on a deterministic core:

| Layer | Module | Purpose |
|-------|--------|---------|
| **Extract** | `dks.extract` | Extract structured claims from text (regex or LLM) |
| **Resolve** | `dks.resolve` | Map surface mentions to canonical entity IDs |
| **Store** | `dks.core` | Deterministic bitemporal knowledge store |
| **Search** | `dks.index` | TF-IDF + Dense + Hybrid RRF search with temporal filtering |
| **Reason** | `dks.search` | SearchEngine: answer synthesis, entity linking, deduplication |
| **Explore** | `dks.explore` | Explorer: profiles, annotations, quality reports, insights |
| **Orchestrate** | `dks.pipeline` | Single canonical execution path |
| **Integrate** | `dks.mcp` | MCP server (25 tools) for AI agent integration |

### The Commitment Boundary

```
                NON-DETERMINISTIC              DETERMINISTIC
              ┌──────────────────┐  ┌─────────────────────────────┐
  text ──────►│  Extract claims  │  │                             │
              │  Resolve entities│──►  store.assert_revision()   │
              │  Embed for search│  │                             │
              └──────────────────┘  │  SHA-256 identity           │
                                    │  Bitemporal visibility      │
                                    │  Deterministic merge        │
                                    │  Conflict classification    │
                                    └─────────────────────────────┘
```

**Determinism is a property of DATA, not CODE.** LLM extraction and embedding search are non-deterministic, but once committed to the store, everything becomes deterministic data with SHA-256 identity, bitemporal visibility, and CRDT-style merge.

## Core Properties

- **Canonicalized identity**: Unicode NFC normalization + zero-width stripping + SHA-256 hashing. Same semantic content = same `core_id`.
- **Bitemporal model**: `ValidTime` (when a fact was true) + `TransactionTime` (when it was recorded). Query any point in both dimensions.
- **Deterministic merge**: CRDT-style merge with proven commutativity, associativity, and idempotency. Conflict classification (competing revisions, ID collisions, orphan relations).
- **Entity resolution as data**: Resolution decisions stored as regular claims — auditable, retractable, temporally queryable.
- **Protocol-based backends**: Swap LLM extractors, embedding models, or resolution strategies without changing the pipeline.

## Architecture

```
dks/
  core.py      Deterministic bitemporal store (~5,200 lines, zero deps)
  pipeline.py  Thin facade orchestrator (~900 lines)
  search.py    SearchEngine: search, reasoning, synthesis (~2,930 lines)
  explore.py   Explorer: profiles, annotations, quality, insights (~2,250 lines)
  ingest.py    Ingester: extract → resolve → commit → index (~335 lines)
  index.py     TF-IDF + Dense + Hybrid RRF + KnowledgeGraph (~1,230 lines)
  extract.py   Extractor Protocol + RegexExtractor + LLMExtractor + PDFExtractor (~515 lines)
  resolve.py   Resolver Protocol + cascading resolution (~165 lines)
  mcp.py       MCPToolHandler (25 tools) (~615 lines)
  audit.py     AuditEvent / AuditTrace / AuditManager (~175 lines)
  results.py   Result dataclasses (~275 lines)
```

**58 exported symbols** (26 V1 core + 32 V2/V3 modules). All V1 symbols unchanged.

## Entity Resolution as Data

Resolution decisions are stored as regular claims:

```python
from dks import ExactResolver, ResolutionDecision

resolver = ExactResolver()
resolver.register("Tim Cook", "entity:tim_cook")

decision = resolver.resolve("Tim Cook")
# ResolutionDecision(surface_form='Tim Cook', resolved_entity_id='entity:tim_cook', confidence_bp=10000, method='exact')

# Store the decision as an auditable claim
alias_claim = decision.as_alias_claim()
# ClaimCore(claim_type='dks.entity_alias@v1', slots={'surface': 'tim cook', 'entity': 'entity:tim_cook', 'method': 'exact'})
```

Wrong resolutions can be explicitly retracted. Resolution history is temporally queryable.

## MCP Integration

```python
from dks import Pipeline, MCPToolHandler, RegexExtractor, NumpyIndex

pipeline = Pipeline(extractor=RegexExtractor(), embedding_backend=NumpyIndex(64))
handler = MCPToolHandler(pipeline)

# Tools: dks_ingest, dks_query, dks_query_exact, dks_snapshot, dks_stats
tools = handler.list_tools()
result = handler.handle_tool_call("dks_ingest", {"text": "Alice lives in London"})
```

## Testing

```bash
pip install -e ".[dev]"
python -m pytest -q
```

1179 tests covering:
- Identity determinism and Unicode convergence
- Bitemporal queries and retraction semantics
- Merge CRDT properties (commutativity, associativity, idempotency) via Hypothesis
- Snapshot round-trips and permutation invariance
- End-to-end pipeline: ingest, query, merge, resolution
- MCP tool handler operations
- Retraction-aware filtering across all subsystems
- Property-based stress tests with Hypothesis
- Full lifecycle tests: multi-source merge, temporal progression, save/load round-trip

## Known Limitations

- **Not thread-safe**: `KnowledgeStore` mutations are not synchronized. Callers must synchronize externally in multi-threaded deployments.
- **Interval surgery**: DESIGN.md target 6 (overlap resolution for partial valid-time conflicts) is unimplemented.
- **NumpyIndex**: Brute-force cosine similarity, good for <100K vectors. Swap in FAISS/Annoy for scale.
- **LLMExtractor**: Requires user-provided `llm_fn` callable. No built-in model inference.
- **Search index persistence**: Index state is saved/loaded with `Pipeline.save()`/`Pipeline.load()`, but must be rebuilt after `merge()`.
- **Graph must be rebuilt after merge**: `build_graph()` required after `merge()` for graph-dependent operations.

## Design Documents

- [`research/DESIGN.md`](research/DESIGN.md) — V1+V2 design targets and core entity definitions
- [`research/FAILURE_MODES.md`](research/FAILURE_MODES.md) — 20 core failure modes and mitigations
- [`research/DECISION_LOG.md`](research/DECISION_LOG.md) — Architectural decision log

## Model Recommendations

From the project model registry:
- **Extraction**: Qwen3-0.6B (600M params, agent-friendly, full precision ~700MB)
- **Embeddings**: Qwen3-Embedding-0.6B (best <1B, 32-1024 dims, 100+ languages)
- **Production**: Qwen3-4B (extraction) + Qwen3-Embedding-4B (embeddings)
