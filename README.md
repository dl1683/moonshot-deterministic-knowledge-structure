# DKS — Deterministic Knowledge Structure

**The SQLite for agent memory.** Every AI agent needs memory. Most solutions are a vector database with a prayer. DKS is different: a deterministic, bitemporal, CRDT-mergeable knowledge store where every fact has an identity, a timestamp, a provenance trail, and a cryptographic fingerprint. Once data enters the store, it's *mathematically guaranteed* to be consistent — across time, across agents, across merges.

```
pip install dks               # zero-dependency core
pip install dks[cli]           # + CLI tool
pip install dks[pipeline]      # + search (numpy, scikit-learn, PDF extraction)
pip install dks[all]           # everything (pipeline + embeddings + LLM + MCP + CLI)
```

## 30 Seconds to Your First Knowledge Base

```python
from dks import Pipeline

pipeline = Pipeline()

# Ingest anything — text, PDFs, entire directories
pipeline.ingest_text("Einstein developed relativity in 1905.", source="physics")
pipeline.ingest_text("Newton published Principia in 1687.", source="physics")
pipeline.rebuild_index()

# Search with temporal awareness
results = pipeline.query("who developed relativity")
print(results[0].text)  # Einstein developed relativity in 1905.

# Persistent — save and reload instantly
pipeline.save("my_knowledge")
loaded = Pipeline.load("my_knowledge")
```

## CLI — Your Knowledge Base from the Terminal

```bash
# Ingest an entire repository (recursive, 60+ file types)
dks ingest ./my-project/

# Ingest specific files
dks ingest paper.pdf
dks ingest notes.txt --source "research notes"

# Search
dks query "how does authentication work"
dks query "database schema" -k 10
dks query "system architecture" --reason    # multi-hop reasoning

# Explore
dks stats                    # cores, revisions, indexed count
dks sources                  # list all documents
dks repl                     # interactive explorer (25+ commands)
dks demo ./papers/           # automated capability demo

# AI agent integration
dks serve                    # MCP server over stdio (25 tools)
```

### Ingest Anything

DKS auto-detects file types and handles them appropriately:

| Input | What happens |
|-------|-------------|
| **Directory** | Recursively walks all subfolders, ingests every supported file |
| **PDF** | Text extraction via PyMuPDF, intelligent chunking |
| **Code** (.py, .js, .rs, .go, .java, .cpp, ...) | Read as text, chunked, fully searchable |
| **Docs** (.md, .rst, .txt, .tex, .org) | Read as text, chunked |
| **Config** (.yaml, .toml, .json, .ini, .env) | Read as text, chunked |
| **Data** (.csv, .sql, .graphql, .proto) | Read as text, chunked |

Binary files and unrecognized extensions are automatically skipped.

```bash
# Ingest a full monorepo — code, docs, configs, everything
dks ingest ./my-company-monorepo/

# Only PDFs, non-recursive
dks ingest ./papers/ --pattern "*.pdf"
```

## Why DKS?

Every agent memory system faces the same problems: how do you know what's true? When did it become true? What if two agents disagree? What if you need to undo something?

Most systems punt on these questions. DKS answers them with mathematics.

### The Commitment Boundary

```
              NON-DETERMINISTIC              DETERMINISTIC
            ┌──────────────────┐  ┌─────────────────────────────┐
  text ────►│  Extract claims  │  │                             │
            │  Resolve entities│──►  store.assert_revision()   │
            │  Embed for search│  │                             │
            └──────────────────┘  │  SHA-256 content identity   │
                                  │  Bitemporal visibility      │
                                  │  CRDT-style merge           │
                                  │  Conflict classification    │
                                  └─────────────────────────────┘
```

**Determinism is a property of DATA, not CODE.** LLM extraction and embedding search are non-deterministic — that's fine. But once committed to the store, everything becomes deterministic data with SHA-256 identity, bitemporal visibility, and CRDT-style merge. Two agents ingesting the same facts produce *identical* store states, regardless of order.

### Core Guarantees

| Property | What it means | Why it matters |
|----------|--------------|----------------|
| **Canonicalized identity** | Unicode NFC + zero-width stripping + SHA-256. Same content = same ID, always. | No duplicate facts, no phantom conflicts |
| **Bitemporal model** | `ValidTime` (when true) + `TransactionTime` (when recorded). Query any point in both. | Time-travel queries, full audit trail |
| **CRDT merge** | Commutative, associative, idempotent. Proven via Hypothesis. | Agents merge without coordination |
| **Conflict classification** | Competing revisions, ID collisions, orphan relations — all detected and reported. | No silent data corruption |
| **Entity resolution as data** | Resolution decisions are regular claims. Auditable, retractable, queryable. | Fix mistakes, track provenance |

## What DKS Does

DKS is a **complete agentic memory system** — not just storage, but the full pipeline from raw text to searchable, mergeable, auditable knowledge:

| Layer | Module | What it does |
|-------|--------|-------------|
| **Extract** | `dks.extract` | Structured claim extraction (regex patterns, LLM, PDF) |
| **Resolve** | `dks.resolve` | Entity resolution — map mentions to canonical IDs |
| **Store** | `dks.core` | Deterministic bitemporal knowledge store (zero deps) |
| **Search** | `dks.index` | TF-IDF + Dense + Hybrid RRF with temporal filtering |
| **Reason** | `dks.search` | Multi-hop reasoning, synthesis, entity linking, deduplication |
| **Explore** | `dks.explore` | Corpus profiles, quality reports, annotations, insights |
| **Orchestrate** | `dks.pipeline` | Single canonical execution path (50+ methods) |
| **Integrate** | `dks.mcp` | MCP server — 25 tools for AI agent integration |
| **CLI** | `dks.cli` | Terminal interface — ingest, query, explore, serve |

## Python API

### Ingest

```python
from dks import Pipeline

pipeline = Pipeline()

# Text (automatically chunked)
pipeline.ingest_text("Your text here...", source="notes.txt")

# PDF
pipeline.ingest_pdf("paper.pdf")

# Entire directory (recursive, all file types)
pipeline.ingest_directory("./my-project/")

# Always rebuild after batch ingestion
pipeline.rebuild_index()
```

### Search & Reason

```python
# Basic search
results = pipeline.query("how does caching work", k=5)
for r in results:
    print(f"[{r.score:.3f}] {r.text[:100]}")

# Multi-hop reasoning (follows connections across documents)
result = pipeline.reason("what are the tradeoffs of microservices", k=5, hops=2)
print(f"{result.total_chunks} chunks from {result.source_count} sources")

# Deep query (question decomposition + targeted retrieval)
deep = pipeline.query_deep("Compare REST vs GraphQL for mobile apps")
```

### Explore & Analyze

```python
# Build knowledge graph (connects related chunks)
pipeline.build_graph()

# Corpus overview
print(pipeline.render_profile())
print(pipeline.render_quality_report())

# Find contradictions
contradictions = pipeline.scan_contradictions()

# Track how understanding evolves
evolution = pipeline.evolution("machine learning", k=10)

# Compare documents
comparison = pipeline.compare_sources("paper_a.pdf", "paper_b.pdf")

# Get AI-generated suggestions
suggestions = pipeline.suggest_queries(n=5)
```

### Merge Knowledge Bases

```python
# Two agents working independently
agent_a = Pipeline()
agent_a.ingest_text("Alice is CEO.", source="hr.txt")

agent_b = Pipeline()
agent_b.ingest_text("Bob is CTO.", source="hr.txt")

# Deterministic merge — order doesn't matter
result = agent_a.merge(agent_b)
print(f"Conflicts: {len(result.conflicts)}")
# merge(A, B) == merge(B, A) — guaranteed by CRDT properties
```

### Structured Extraction

```python
from dks import Pipeline, RegexExtractor, NumpyIndex, ValidTime, TransactionTime
from datetime import datetime, timezone

extractor = RegexExtractor()
extractor.register_pattern(
    "residence",
    r"(?P<subject>\w+) lives in (?P<city>\w+)",
    ["subject", "city"],
)
pipeline = Pipeline(extractor=extractor, embedding_backend=NumpyIndex(dimension=64))

pipeline.ingest(
    "Alice lives in London",
    valid_time=ValidTime(start=datetime(2024, 1, 1, tzinfo=timezone.utc)),
    transaction_time=TransactionTime(tx_id=1, recorded_at=datetime.now(timezone.utc)),
)
```

### Entity Resolution

```python
from dks import ExactResolver, ResolutionDecision

resolver = ExactResolver()
resolver.register("Tim Cook", "entity:tim_cook")

decision = resolver.resolve("Tim Cook")
# ResolutionDecision(surface_form='Tim Cook', resolved_entity_id='entity:tim_cook', ...)

# Resolution decisions are stored as auditable claims
alias_claim = decision.as_alias_claim()
# Wrong resolutions can be retracted. Resolution history is temporally queryable.
```

### MCP Integration (for AI Agents)

```python
from dks import Pipeline, MCPToolHandler

pipeline = Pipeline()
handler = MCPToolHandler(pipeline)

# 25 tools: ingest, query, reason, profile, annotate, compare, ...
tools = handler.list_tools()
result = handler.handle_tool_call("dks_ingest", {"text": "Alice lives in London"})
```

Or from the CLI:

```bash
dks serve    # Starts MCP server on stdio — plug into any MCP-compatible agent
```

### Save & Load

```python
pipeline.save("./my_knowledge")     # Persists store + index + graph
loaded = Pipeline.load("./my_knowledge")  # Instant reload
```

### Interactive REPL

```bash
dks repl
```

```
  dks> query how does authentication work
  1. [0.832] auth.py
     The authentication module uses JWT tokens with...
  2. [0.756] security.md
     All API endpoints require Bearer token...

  dks> reason what are the security implications
  12 chunks, 4 sources (0.34s)

  dks> profile
  dks> quality
  dks> evolve "machine learning"
  dks> contradictions
  dks> insights
  dks> suggest
```

25+ commands: `query`, `reason`, `profile`, `quality`, `timeline`, `sources`, `browse`, `chunk`, `evolve`, `compare`, `contradictions`, `staleness`, `entities`, `insights`, `suggest`, `annotate`, `annotations`, `summary`, `stats`, `save`.

## Architecture

```
15,400 lines of Python across 12 modules:

dks/
  core.py      Deterministic bitemporal store (~5,200 lines, zero external deps)
  search.py    SearchEngine: multi-hop reasoning, synthesis, entity linking (~2,930 lines)
  explore.py   Explorer: profiles, annotations, quality reports, insights (~2,250 lines)
  index.py     TF-IDF + Dense + Hybrid RRF + KnowledgeGraph (~1,340 lines)
  pipeline.py  Thin facade orchestrator — 50+ public methods (~890 lines)
  mcp.py       MCPToolHandler — 25 tools for AI agent integration (~615 lines)
  cli.py       Click-based CLI — ingest, query, explore, serve (~560 lines)
  extract.py   Extractor Protocol + Regex + LLM + PDF backends (~510 lines)
  ingest.py    Ingester: extract → resolve → commit → index (~400 lines)
  results.py   Result dataclasses for structured output (~275 lines)
  audit.py     AuditEvent / AuditTrace / AuditManager (~175 lines)
  resolve.py   Resolver Protocol + cascading resolution (~165 lines)
```

**59 exported symbols.** Protocol-based backends throughout — swap extractors, embedding models, or resolution strategies without changing a line of pipeline code.

## Testing

```bash
pip install -e ".[dev]"
python -m pytest -q
```

**1,183 tests** across 115 test files:
- Identity determinism and Unicode convergence
- Bitemporal queries and retraction semantics
- CRDT merge properties (commutativity, associativity, idempotency) via Hypothesis
- Snapshot round-trips and permutation invariance
- End-to-end pipeline: ingest, query, merge, resolution, save/load
- Protocol conformance for all search index types
- MCP tool handler operations (25 tools)
- Retraction-aware filtering across all subsystems
- Property-based stress tests with Hypothesis
- Full lifecycle: multi-source merge, temporal progression, recursive ingestion

## Known Limitations

- **Not thread-safe**: `KnowledgeStore` mutations are not synchronized. Callers must synchronize externally.
- **NumpyIndex**: Brute-force cosine similarity, suitable for <100K vectors. Swap in FAISS/Annoy for scale.
- **LLMExtractor**: Requires user-provided `llm_fn` callable. No built-in model inference.
- **Index rebuild after merge**: `rebuild_index()` and `build_graph()` required after `merge()`.

## Design Documents

- [`research/DESIGN.md`](research/DESIGN.md) — Core design targets and entity definitions
- [`research/FAILURE_MODES.md`](research/FAILURE_MODES.md) — 20 failure modes and mitigations
- [`research/DECISION_LOG.md`](research/DECISION_LOG.md) — Architectural decision log

## Model Recommendations

| Use Case | Model | Notes |
|----------|-------|-------|
| **Extraction** | Qwen3-0.6B | 600M params, agent-friendly, ~700MB |
| **Embeddings** | Qwen3-Embedding-0.6B | Best <1B, 32-1024 dims, 100+ languages |
| **Production** | Qwen3-4B + Qwen3-Embedding-4B | Higher quality, fits on consumer GPU |
