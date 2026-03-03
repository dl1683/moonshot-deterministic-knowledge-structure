"""DKS Full Capability Demo — Ingest, Search, Reason, Navigate.

Usage:
    python tools/demo.py <pdf_directory> [--save <dir>] [--load <dir>]

Examples:
    # Ingest all PDFs and run demo queries
    python tools/demo.py "C:/path/to/pdfs"

    # Ingest and save state for fast reload
    python tools/demo.py "C:/path/to/pdfs" --save ./dks_state

    # Load saved state and run queries (skips ingestion)
    python tools/demo.py --load ./dks_state
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dks import (
    KnowledgeStore,
    PDFExtractor,
    Pipeline,
    TextChunker,
    TfidfSearchIndex,
)


def build_pipeline(pdf_dir: str | None, save_dir: str | None, load_dir: str | None) -> Pipeline:
    """Build or load a pipeline."""
    if load_dir:
        print(f"\n[1] Loading saved state from {load_dir}...")
        t0 = time.time()
        pipeline = Pipeline.load(load_dir)
        print(f"    Loaded in {time.time() - t0:.1f}s")
        print(f"    Store: {pipeline.stats()}")
        if pipeline.graph is None:
            print("    Building graph...")
            pipeline.build_graph(n_clusters=50)
        return pipeline

    if not pdf_dir:
        print("ERROR: Provide --load <dir> or a PDF directory.")
        sys.exit(1)

    # Full ingestion pipeline
    store = KnowledgeStore()
    search = TfidfSearchIndex(store)
    pipeline = Pipeline(
        store=store,
        extractor=PDFExtractor(TextChunker(chunk_size=800, overlap=150)),
        search_index=search,
    )

    print(f"\n[1] Ingesting PDFs from {pdf_dir}...")
    t0 = time.time()
    results = pipeline.ingest_directory(pdf_dir, progress=True)
    ingest_time = time.time() - t0
    total_chunks = sum(len(v) for v in results.values())
    print(f"    {len(results)} files, {total_chunks} chunks in {ingest_time:.1f}s")

    print(f"\n[2] Building knowledge graph...")
    t0 = time.time()
    graph = pipeline.build_graph(n_clusters=50)
    print(f"    {graph.total_nodes} nodes, {graph.total_edges} edges, {graph.total_clusters} clusters in {time.time() - t0:.1f}s")

    if save_dir:
        print(f"\n[3] Saving state to {save_dir}...")
        t0 = time.time()
        pipeline.save(save_dir)
        print(f"    Saved in {time.time() - t0:.1f}s")

    return pipeline


def run_demo(pipeline: Pipeline) -> None:
    """Run the full demo battery."""
    store = pipeline.store

    # ---- Section 1: Basic Retrieval ----
    print("\n" + "=" * 70)
    print("  SECTION 1: BASIC RETRIEVAL")
    print("=" * 70)

    queries = [
        "differential evolution optimization algorithm",
        "why do large language models hallucinate",
        "tree-based models vs deep learning",
        "prompt engineering techniques for AI safety",
        "self-assembling neural networks",
    ]

    for q in queries:
        print(f'\n  Q: "{q}"')
        results = pipeline.query(q, k=3)
        for i, r in enumerate(results):
            core = store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            print(f"    {i+1}. [{r.score:.3f}] {source[:50]}")
            print(f"       {r.text[:100].replace(chr(10), ' ')}...")

    # ---- Section 2: Multi-Hop Reasoning ----
    print("\n" + "=" * 70)
    print("  SECTION 2: MULTI-HOP REASONING")
    print("=" * 70)

    reasoning_queries = [
        "What are the fundamental limitations of current AI systems and how can they be addressed?",
        "How do neural network architectures compare to traditional methods for different tasks?",
    ]

    for q in reasoning_queries:
        print(f'\n  Q: "{q}"')
        t0 = time.time()
        result = pipeline.reason(q, k=5, hops=2, expand_k=3)
        elapsed = time.time() - t0
        print(f"    Found {result.total_chunks} chunks across {result.source_count} documents ({elapsed:.2f}s)")
        print(f"    Hops: {result.total_hops}")

        # Show trace
        for trace in result.trace:
            if trace["hop"] == 0:
                print(f"    Hop 0 (initial): {trace['results']} results")
            else:
                terms = trace.get("expansion_terms", [])
                print(f"    Hop {trace['hop']} (expanded with: {', '.join(terms[:3])}): +{trace['new']} new")

        # Show top results
        print("    Top results:")
        for r in result.results[:3]:
            core = store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            print(f"      [{r.score:.3f}] {source[:45]}")
            print(f"        {r.text[:100].replace(chr(10), ' ')}...")

    # ---- Section 3: Topic Discovery ----
    print("\n" + "=" * 70)
    print("  SECTION 3: TOPIC DISCOVERY")
    print("=" * 70)

    topics = pipeline.topics()
    print(f"\n  {len(topics)} topics discovered from corpus:")
    for t in sorted(topics, key=lambda x: -x["size"])[:10]:
        labels = ", ".join(t["labels"][:4])
        print(f"    [{t['size']:4d} chunks] {labels}")

    # ---- Section 4: Graph Navigation ----
    print("\n" + "=" * 70)
    print("  SECTION 4: GRAPH NAVIGATION")
    print("=" * 70)

    nav_queries = ["Kolmogorov-Arnold networks", "reinforcement learning"]
    for q in nav_queries:
        results = pipeline.query(q, k=1)
        if not results:
            continue
        seed = results[0]
        core = store.cores.get(seed.core_id)
        source = core.slots.get("source", "?") if core else "?"
        print(f'\n  Seed: "{q}" -> {source[:45]}')
        neighbors = pipeline.neighbors(seed.revision_id, k=5)
        for n in neighbors:
            n_core = store.cores.get(n.core_id)
            n_source = n_core.slots.get("source", "?") if n_core else "?"
            print(f"    -> [{n.score:.3f}] {n_source[:45]}")

    # ---- Section 5: Coverage Analysis ----
    print("\n" + "=" * 70)
    print("  SECTION 5: COVERAGE ANALYSIS")
    print("=" * 70)

    coverage_topics = ["AI safety and ethics", "deep learning optimization"]
    for topic in coverage_topics:
        report = pipeline.coverage(topic, k=15)
        print(f'\n  Topic: "{topic}"')
        print(f"    Chunks: {report.total_chunks}")
        print(f"    Sources: {report.source_count}")
        print(f"    Subtopics: {', '.join(report.subtopics[:6])}")

    # ---- Section 6: Multi-Document Retrieval ----
    print("\n" + "=" * 70)
    print("  SECTION 6: MULTI-DOCUMENT RETRIEVAL")
    print("=" * 70)

    md_query = "How do companies like Google and Meta approach large scale AI systems?"
    print(f'\n  Q: "{md_query}"')
    grouped = pipeline.query_multi(md_query, k=10)
    for source, chunks in sorted(grouped.items(), key=lambda x: -len(x[1]))[:5]:
        print(f"    [{len(chunks)} chunks] {source[:55]}")
        for c in chunks[:1]:
            print(f"      {c.text[:80].replace(chr(10), ' ')}...")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    stats = pipeline.stats()
    graph = pipeline.graph
    print(f"\n  Knowledge Store:")
    print(f"    Cores:     {stats['cores']:,}")
    print(f"    Revisions: {stats['revisions']:,}")
    print(f"    Indexed:   {stats.get('indexed', 0):,}")
    if graph:
        print(f"  Knowledge Graph:")
        print(f"    Nodes:    {graph.total_nodes:,}")
        print(f"    Edges:    {graph.total_edges:,}")
        print(f"    Clusters: {graph.total_clusters}")
    print()


def main():
    parser = argparse.ArgumentParser(description="DKS Full Capability Demo")
    parser.add_argument("pdf_dir", nargs="?", help="Directory containing PDF files")
    parser.add_argument("--save", help="Save pipeline state to this directory")
    parser.add_argument("--load", help="Load pipeline state from this directory")
    args = parser.parse_args()

    pipeline = build_pipeline(args.pdf_dir, args.save, args.load)
    run_demo(pipeline)


if __name__ == "__main__":
    main()
