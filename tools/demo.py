"""DKS Full Capability Demo — Ingest, Search, Explore, Reason.

Usage:
    python tools/demo.py <pdf_directory> [--save <dir>] [--load <dir>]
    python tools/demo.py --load ./dks_state --interactive

Examples:
    # Ingest all PDFs and run demo queries
    python tools/demo.py "C:/path/to/pdfs"

    # Ingest and save state for fast reload
    python tools/demo.py "C:/path/to/pdfs" --save ./dks_state

    # Load saved state and enter interactive REPL
    python tools/demo.py --load ./dks_state --interactive
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
    """Run the automated demo battery."""
    store = pipeline.store

    # ---- Section 1: Corpus Profile ----
    print("\n" + "=" * 70)
    print("  SECTION 1: CORPUS PROFILE")
    print("=" * 70)
    print(pipeline.render_profile())

    # ---- Section 2: Quality Report ----
    print("\n" + "=" * 70)
    print("  SECTION 2: QUALITY REPORT")
    print("=" * 70)
    print(pipeline.render_quality_report())

    # ---- Section 3: Ingestion Timeline ----
    print("\n" + "=" * 70)
    print("  SECTION 3: INGESTION TIMELINE")
    print("=" * 70)
    print(pipeline.render_timeline())

    # ---- Section 4: Basic Retrieval ----
    print("\n" + "=" * 70)
    print("  SECTION 4: BASIC RETRIEVAL")
    print("=" * 70)

    queries = [
        "why do large language models hallucinate",
        "prompt engineering techniques for AI safety",
        "tree-based models vs deep learning",
    ]

    for q in queries:
        print(f'\n  Q: "{q}"')
        results = pipeline.query(q, k=3)
        for i, r in enumerate(results):
            core = store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            print(f"    {i+1}. [{r.score:.3f}] {source[:50]}")
            print(f"       {r.text[:100].replace(chr(10), ' ')}...")

    # ---- Section 5: Multi-Hop Reasoning ----
    print("\n" + "=" * 70)
    print("  SECTION 5: MULTI-HOP REASONING")
    print("=" * 70)

    q = "What are the fundamental limitations of current AI systems and how can they be addressed?"
    print(f'\n  Q: "{q}"')
    t0 = time.time()
    result = pipeline.reason(q, k=5, hops=2, expand_k=3)
    elapsed = time.time() - t0
    print(f"    Found {result.total_chunks} chunks across {result.source_count} documents ({elapsed:.2f}s)")
    for trace in result.trace:
        if trace["hop"] == 0:
            print(f"    Hop 0 (initial): {trace['results']} results")
        else:
            terms = trace.get("expansion_terms", [])
            print(f"    Hop {trace['hop']} (expanded with: {', '.join(terms[:3])}): +{trace['new']} new")

    # ---- Section 6: Topic Evolution ----
    print("\n" + "=" * 70)
    print("  SECTION 6: TOPIC EVOLUTION")
    print("=" * 70)

    evo = pipeline.evolution("neural networks", k=10)
    print(pipeline.render_evolution(evo))

    # ---- Section 7: Source Comparison ----
    print("\n" + "=" * 70)
    print("  SECTION 7: SOURCE COMPARISON")
    print("=" * 70)

    sources = pipeline.list_sources()
    if len(sources) >= 2:
        cmp = pipeline.compare_sources(sources[0]["source"], sources[1]["source"])
        print(pipeline.render_comparison(cmp))
    else:
        print("  Need at least 2 sources for comparison.")

    # ---- Section 8: Corpus Insights ----
    print("\n" + "=" * 70)
    print("  SECTION 8: CORPUS INSIGHTS")
    print("=" * 70)
    print(pipeline.render_insights())

    # ---- Section 9: Suggested Queries ----
    print("\n" + "=" * 70)
    print("  SECTION 9: SUGGESTED QUERIES")
    print("=" * 70)
    suggestions = pipeline.suggest_queries(n=5)
    for s in suggestions:
        print(f"  [{s['type']:<12s}] {s['query']}")
        print(f"    {s['rationale']}")
    print()

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


def interactive_repl(pipeline: Pipeline) -> None:
    """Interactive REPL for exploring the knowledge base."""
    print("\n" + "=" * 70)
    print("  DKS INTERACTIVE EXPLORER")
    print("=" * 70)
    print("""
  Commands:
    query <text>          Search the knowledge base
    reason <text>         Multi-hop reasoning query
    profile               Show corpus profile
    quality               Show quality report
    timeline              Show ingestion timeline
    sources               List all sources
    source <name>         Show source details
    browse source <name>  Browse chunks from a source
    browse cluster <id>   Browse chunks in a cluster
    chunk <revision_id>   Show full chunk details
    evolve <topic>        Show topic evolution
    compare <a> <b>       Compare two sources
    contradictions        Scan for contradictions
    staleness             Show staleness report
    entities              Review entity quality
    insights              Corpus health + recommendations
    suggest               Suggest interesting queries
    help                  Show this help
    quit                  Exit
""")

    while True:
        try:
            line = input("  dks> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd == "quit" or cmd == "exit":
                print("  Goodbye.")
                break

            elif cmd == "help":
                interactive_repl.__doc__  # Re-print help
                print("  Type a command above.")

            elif cmd == "query":
                if not arg:
                    print("  Usage: query <search text>")
                    continue
                results = pipeline.query(arg, k=5)
                for i, r in enumerate(results):
                    core = pipeline.store.cores.get(r.core_id)
                    source = core.slots.get("source", "?") if core else "?"
                    print(f"  {i+1}. [{r.score:.3f}] {source[:50]}")
                    print(f"     {r.text[:150].replace(chr(10), ' ')}...")

            elif cmd == "reason":
                if not arg:
                    print("  Usage: reason <question>")
                    continue
                t0 = time.time()
                result = pipeline.reason(arg, k=5, hops=2, expand_k=3)
                elapsed = time.time() - t0
                print(f"  {result.total_chunks} chunks, {result.source_count} sources ({elapsed:.2f}s)")
                for r in result.results[:5]:
                    core = pipeline.store.cores.get(r.core_id)
                    source = core.slots.get("source", "?") if core else "?"
                    print(f"  [{r.score:.3f}] {source[:45]}")
                    print(f"    {r.text[:120].replace(chr(10), ' ')}...")

            elif cmd == "profile":
                print(pipeline.render_profile())

            elif cmd == "quality":
                print(pipeline.render_quality_report())

            elif cmd == "timeline":
                print(pipeline.render_timeline())

            elif cmd == "sources":
                for s in pipeline.list_sources():
                    print(f"  {s['source'][:50]:<50s} {s['chunks']:>5d} chunks  {s.get('total_pages', '?')} pages")

            elif cmd == "source":
                if not arg:
                    print("  Usage: source <name>")
                    continue
                detail = pipeline.source_detail(arg)
                if not detail.get("found"):
                    print(f"  Source '{arg}' not found.")
                else:
                    print(f"  Source: {detail['source']}")
                    print(f"  Chunks: {detail['chunk_count']}")
                    print(f"  Pages: {detail.get('page_range', 'N/A')}")
                    print(f"  Avg length: {detail['avg_chunk_length']} chars")
                    if detail.get("quality_flags"):
                        print(f"  Flags: {', '.join(detail['quality_flags'])}")

            elif cmd == "browse":
                sub_parts = arg.split(maxsplit=1)
                if len(sub_parts) < 2:
                    print("  Usage: browse source <name> | browse cluster <id>")
                    continue
                sub_cmd, sub_arg = sub_parts
                if sub_cmd == "source":
                    result = pipeline.browse_source(sub_arg, limit=10)
                    print(pipeline.render_browse(result))
                elif sub_cmd == "cluster":
                    try:
                        cid = int(sub_arg)
                    except ValueError:
                        print("  Cluster ID must be a number.")
                        continue
                    result = pipeline.browse_cluster(cid, limit=10)
                    print(pipeline.render_browse(result))

            elif cmd == "chunk":
                if not arg:
                    print("  Usage: chunk <revision_id>")
                    continue
                detail = pipeline.chunk_detail(arg)
                print(pipeline.render_chunk_detail(detail))

            elif cmd == "evolve":
                if not arg:
                    print("  Usage: evolve <topic>")
                    continue
                result = pipeline.evolution(arg, k=10)
                print(pipeline.render_evolution(result))

            elif cmd == "compare":
                cmp_parts = arg.split(maxsplit=1)
                if len(cmp_parts) < 2:
                    print("  Usage: compare <source_a> <source_b>")
                    continue
                result = pipeline.compare_sources(cmp_parts[0], cmp_parts[1])
                print(pipeline.render_comparison(result))

            elif cmd == "contradictions":
                print("  Scanning for contradictions...")
                pairs = pipeline.scan_contradictions(k=10, threshold=0.4)
                print(pipeline.render_contradictions(pairs))

            elif cmd == "staleness":
                report = pipeline.staleness_report()
                print(f"  {report['stale_count']} stale chunks (>{report['threshold_days']} days)")
                for source, count in sorted(report["by_source"].items(), key=lambda x: -x[1]):
                    print(f"    {source[:45]}: {count}")
                if report["oldest"]:
                    print(f"\n  Oldest chunks:")
                    for entry in report["oldest"][:5]:
                        print(f"    [{entry['age_days']}d] {entry['source'][:40]}")
                        print(f"      {entry['preview'][:100]}...")

            elif cmd == "entities":
                print("  Analyzing entities...")
                review = pipeline.review_entities(top_k=20)
                print(f"  Total analyzed: {review['total_analyzed']}")
                if review["high"]:
                    print(f"\n  High quality ({len(review['high'])}):")
                    for e in review["high"][:10]:
                        print(f"    {e['entity']:<30s} score={e['score']:.2f}  sources={e['source_count']}")
                if review["flagged"]:
                    print(f"\n  Flagged ({len(review['flagged'])}):")
                    for e in review["flagged"][:10]:
                        print(f"    {e['entity']:<30s} score={e['score']:.2f}")

            elif cmd == "insights":
                print(pipeline.render_insights())

            elif cmd == "suggest":
                suggestions = pipeline.suggest_queries(n=5)
                for s in suggestions:
                    print(f"  [{s['type']:<12s}] {s['query']}")
                    print(f"    {s['rationale']}")

            else:
                print(f"  Unknown command: {cmd}. Type 'help' for options.")

        except Exception as e:
            print(f"  Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="DKS Full Capability Demo")
    parser.add_argument("pdf_dir", nargs="?", help="Directory containing PDF files")
    parser.add_argument("--save", help="Save pipeline state to this directory")
    parser.add_argument("--load", help="Load pipeline state from this directory")
    parser.add_argument("--interactive", "-i", action="store_true", help="Enter interactive REPL after demo")
    args = parser.parse_args()

    pipeline = build_pipeline(args.pdf_dir, args.save, args.load)

    if args.interactive:
        interactive_repl(pipeline)
    else:
        run_demo(pipeline)


if __name__ == "__main__":
    main()
