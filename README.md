# DKS — Deterministic Knowledge Structure

**The SQLite for agent memory.** A deterministic, bitemporal knowledge store for AI agents that need reliable, auditable, mergeable memory.

```
pip install dks           # zero-dependency core
pip install dks[pipeline] # + numpy for embedding search
pip install dks[all]      # + LLM + MCP integration
```

## 5-Line Quick Start

```python
from dks import Pipeline, RegexExtractor, NumpyIndex, ValidTime, TransactionTime
from datetime import datetime, timezone

# Configure pipeline
extractor = RegexExtractor()
extractor.register_pattern("residence", r"(?P<subject>\w+) lives in (?P<city>\w+)", ["subject", "city"])
pipeline = Pipeline(extractor=extractor, embedding_backend=NumpyIndex(dimension=64))

# Ingest (non-deterministic extraction → deterministic storage)
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
| **Search** | `dks.index` | Embedding-based semantic search with temporal filtering |
| **Orchestrate** | `dks.pipeline` | Single canonical execution path |
| **Integrate** | `dks.mcp` | MCP server for AI agent integration |

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
  core.py      Deterministic store (~5,400 lines, zero deps)
  extract.py   Extractor Protocol + RegexExtractor + LLMExtractor
  resolve.py   Resolver Protocol + ExactResolver + NormalizedResolver + CascadingResolver
  index.py     EmbeddingBackend Protocol + SearchIndex + NumpyIndex
  pipeline.py  Pipeline orchestrator
  mcp.py       MCP tool handler
```

**40 exported symbols** (26 V1 core + 14 V2 modules). All V1 symbols unchanged.

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

564 tests covering:
- Identity determinism and Unicode convergence
- Bitemporal queries and retraction semantics
- Merge CRDT properties (commutativity, associativity, idempotency) via Hypothesis
- Snapshot round-trips and permutation invariance
- End-to-end pipeline: ingest, query, merge, resolution
- MCP tool handler operations

## Known Limitations

- **Interval surgery**: DESIGN.md target 6 (overlap resolution for partial valid-time conflicts) is unimplemented.
- **NumpyIndex**: Brute-force cosine similarity, good for <100K vectors. Swap in FAISS/Annoy for scale.
- **LLMExtractor**: Requires user-provided `llm_fn` callable. No built-in model inference.
- **No persistence for search index**: Index is in-memory only. Rebuild after load/merge.

## Design Documents

- [`research/DESIGN.md`](research/DESIGN.md) — V1+V2 design targets and core entity definitions
- [`research/FAILURE_MODES.md`](research/FAILURE_MODES.md) — 20 core failure modes and mitigations
- [`research/DECISION_LOG.md`](research/DECISION_LOG.md) — Architectural decision log

## Model Recommendations

From the project model registry:
- **Extraction**: Qwen3-0.6B (600M params, agent-friendly, full precision ~700MB)
- **Embeddings**: Qwen3-Embedding-0.6B (best <1B, 32-1024 dims, 100+ languages)
- **Production**: Qwen3-4B (extraction) + Qwen3-Embedding-4B (embeddings)
