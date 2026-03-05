"""DKS Command-Line Interface.

Usage:
    dks ingest <path>          Ingest PDF, Word, PowerPoint, text, or directory
    dks query <question>       Search the knowledge base
    dks stats                  Show store statistics
    dks sources                List all ingested sources
    dks repl                   Interactive REPL explorer
    dks save <path>            Save pipeline state
    dks demo [pdf_dir]         Run automated demo battery
    dks serve                  Start MCP server (stdio)

Global option --store sets the state directory (default: ./dks_state).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from .core import KnowledgeStore
from .index import TfidfSearchIndex
from .pipeline import Pipeline


def _load_pipeline(store_path: str) -> Pipeline:
    """Load pipeline from saved state, or create empty one."""
    p = Path(store_path)
    if p.exists() and (p / "store.json").exists():
        click.echo(f"Loading state from {store_path}...")
        return Pipeline.load(store_path)
    store = KnowledgeStore()
    return Pipeline(store=store, search_index=TfidfSearchIndex(store))


def _save_pipeline(pipeline: Pipeline, store_path: str) -> None:
    """Save pipeline state to directory."""
    pipeline.save(store_path)
    click.echo(f"State saved to {store_path}")


@click.group()
@click.option("--store", default="./dks_state", envvar="DKS_STORE",
              help="Pipeline state directory (default: ./dks_state)")
@click.version_option(package_name="dks")
@click.pass_context
def cli(ctx: click.Context, store: str) -> None:
    """DKS — Deterministic Knowledge Structure CLI.

    Agentic AI memory with deterministic core. Ingest documents,
    search with temporal awareness, and explore your knowledge base.
    """
    ctx.ensure_object(dict)
    ctx.obj["store"] = store


# ---- ingest ----


@cli.command()
@click.argument("path")
@click.option("--source", default=None, help="Source name (default: filename)")
@click.option("--pattern", default="**/*", help="Glob pattern for directories (default: recursive)")
@click.option("--chunk-size", default=800, help="Characters per chunk")
@click.option("--chunk-overlap", default=150, help="Overlap between chunks")
@click.option("--no-graph", is_flag=True, help="Skip building knowledge graph")
@click.pass_context
def ingest(ctx: click.Context, path: str, source: str | None,
           pattern: str, chunk_size: int, chunk_overlap: int, no_graph: bool) -> None:
    """Ingest a file or directory into the knowledge base.

    Supported formats: PDF, Word (.docx), PowerPoint (.pptx), and 60+ text formats.
    For directories, recursively ingests all supported files.
    Binary files and unrecognized extensions are automatically skipped.
    """
    store_path = ctx.obj["store"]
    pipeline = _load_pipeline(store_path)
    p = Path(path)

    if not p.exists():
        click.echo(f"Error: {path} does not exist.", err=True)
        sys.exit(1)

    t0 = time.time()

    needs_rebuild = True

    if p.is_dir():
        click.echo(f"Ingesting directory: {path} (pattern: {pattern})")
        results = pipeline.ingest_directory(
            p, pattern=pattern, progress=True,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )
        total_chunks = sum(len(v) for v in results.values())
        click.echo(f"\n{len(results)} files, {total_chunks} chunks in {time.time() - t0:.1f}s")
        needs_rebuild = False  # ingest_directory rebuilds internally

    elif p.suffix.lower() == ".pdf":
        click.echo(f"Ingesting PDF: {p.name}")
        from .extract import TextChunker
        chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)
        rev_ids = pipeline.ingest_pdf(p, chunker=chunker)
        click.echo(f"{len(rev_ids)} chunks in {time.time() - t0:.1f}s")

    elif p.suffix.lower() == ".docx":
        click.echo(f"Ingesting Word document: {p.name}")
        from .extract import TextChunker
        chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)
        rev_ids = pipeline.ingest_docx(p, chunker=chunker)
        click.echo(f"{len(rev_ids)} chunks in {time.time() - t0:.1f}s")

    elif p.suffix.lower() == ".pptx":
        click.echo(f"Ingesting PowerPoint: {p.name}")
        from .extract import TextChunker
        chunker = TextChunker(chunk_size=chunk_size, overlap=chunk_overlap)
        rev_ids = pipeline.ingest_pptx(p, chunker=chunker)
        click.echo(f"{len(rev_ids)} chunks in {time.time() - t0:.1f}s")

    else:
        # Treat as text file
        text = p.read_text(encoding="utf-8")
        src = source or p.name
        click.echo(f"Ingesting text: {p.name} (source: {src})")
        rev_ids = pipeline.ingest_text(text, source=src,
                                       chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        click.echo(f"{len(rev_ids)} chunks in {time.time() - t0:.1f}s")

    if needs_rebuild:
        pipeline.rebuild_index()

    if not no_graph:
        click.echo("Building knowledge graph...")
        pipeline.build_graph()

    _save_pipeline(pipeline, store_path)


# ---- query ----


@cli.command()
@click.argument("question")
@click.option("-k", "--top-k", default=5, help="Number of results")
@click.option("--reason", is_flag=True, help="Use multi-hop reasoning")
@click.pass_context
def query(ctx: click.Context, question: str, top_k: int, reason: bool) -> None:
    """Search the knowledge base."""
    store_path = ctx.obj["store"]
    pipeline = _load_pipeline(store_path)

    if pipeline.stats()["revisions"] == 0:
        click.echo("Knowledge base is empty. Ingest some documents first.")
        return

    t0 = time.time()

    if reason:
        result = pipeline.reason(question, k=top_k, hops=2, expand_k=3)
        elapsed = time.time() - t0
        click.echo(f"{result.total_chunks} chunks, {result.source_count} sources ({elapsed:.2f}s)\n")
        for i, r in enumerate(result.results[:top_k]):
            core = pipeline.store.cores.get(r.core_id)
            src = core.slots.get("source", "?") if core else "?"
            click.echo(f"  {i+1}. [{r.score:.3f}] {src[:50]}")
            click.echo(f"     {r.text[:150].replace(chr(10), ' ')}...")
    else:
        results = pipeline.query(question, k=top_k)
        elapsed = time.time() - t0
        click.echo(f"{len(results)} results ({elapsed:.2f}s)\n")
        for i, r in enumerate(results):
            core = pipeline.store.cores.get(r.core_id)
            src = core.slots.get("source", "?") if core else "?"
            click.echo(f"  {i+1}. [{r.score:.3f}] {src[:50]}")
            click.echo(f"     {r.text[:150].replace(chr(10), ' ')}...")


# ---- stats ----


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show store and index statistics."""
    pipeline = _load_pipeline(ctx.obj["store"])
    s = pipeline.stats()
    click.echo(f"Cores:     {s['cores']:,}")
    click.echo(f"Revisions: {s['revisions']:,}")
    click.echo(f"Relations: {s.get('relations', 0):,}")
    click.echo(f"Indexed:   {s.get('indexed', 0):,}")

    graph = pipeline.graph
    if graph:
        click.echo(f"\nKnowledge Graph:")
        click.echo(f"  Nodes:    {graph.total_nodes:,}")
        click.echo(f"  Edges:    {graph.total_edges:,}")
        click.echo(f"  Clusters: {graph.total_clusters}")


# ---- sources ----


@cli.command()
@click.pass_context
def sources(ctx: click.Context) -> None:
    """List all ingested sources."""
    pipeline = _load_pipeline(ctx.obj["store"])
    source_list = pipeline.list_sources()
    if not source_list:
        click.echo("No sources found.")
        return
    for s in source_list:
        click.echo(f"  {s['source'][:55]:<55s} {s['chunks']:>5d} chunks")


# ---- save ----


@cli.command()
@click.argument("path")
@click.pass_context
def save(ctx: click.Context, path: str) -> None:
    """Save pipeline state to a directory."""
    pipeline = _load_pipeline(ctx.obj["store"])
    _save_pipeline(pipeline, path)


# ---- repl ----


@cli.command()
@click.pass_context
def repl(ctx: click.Context) -> None:
    """Launch interactive REPL explorer."""
    pipeline = _load_pipeline(ctx.obj["store"])

    if pipeline.graph is None and pipeline.stats()["revisions"] > 0:
        click.echo("Building graph for exploration...")
        pipeline.build_graph()

    click.echo("\n" + "=" * 60)
    click.echo("  DKS INTERACTIVE EXPLORER")
    click.echo("=" * 60)
    click.echo("""
  Commands:
    query <text>          Search the knowledge base
    reason <text>         Multi-hop reasoning query
    profile               Corpus profile
    quality               Quality report
    timeline              Ingestion timeline
    sources               List all sources
    source <name>         Source details
    browse source <name>  Browse chunks from a source
    browse cluster <id>   Browse chunks in a cluster
    chunk <revision_id>   Full chunk details
    evolve <topic>        Topic evolution
    compare <a> <b>       Compare two sources
    contradictions        Scan for contradictions
    staleness             Staleness report
    entities              Review entity quality
    insights              Corpus health + recommendations
    suggest               Suggested queries
    annotate <id> <tags>  Tag a chunk (comma-separated)
    annotations [tag]     List annotations
    summary               Auto-generated corpus summary
    stats                 Store statistics
    save                  Save current state
    help                  Show this help
    quit                  Exit
""")

    store_path = ctx.obj["store"]

    while True:
        try:
            line = input("  dks> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\n  Goodbye.")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("quit", "exit"):
                click.echo("  Goodbye.")
                break

            elif cmd == "help":
                click.echo("  Type a command from the list above.")

            elif cmd == "query":
                if not arg:
                    click.echo("  Usage: query <text>")
                    continue
                results = pipeline.query(arg, k=5)
                for i, r in enumerate(results):
                    core = pipeline.store.cores.get(r.core_id)
                    src = core.slots.get("source", "?") if core else "?"
                    click.echo(f"  {i+1}. [{r.score:.3f}] {src[:50]}")
                    click.echo(f"     {r.text[:150].replace(chr(10), ' ')}...")

            elif cmd == "reason":
                if not arg:
                    click.echo("  Usage: reason <question>")
                    continue
                t0 = time.time()
                result = pipeline.reason(arg, k=5, hops=2, expand_k=3)
                elapsed = time.time() - t0
                click.echo(f"  {result.total_chunks} chunks, {result.source_count} sources ({elapsed:.2f}s)")
                for r in result.results[:5]:
                    core = pipeline.store.cores.get(r.core_id)
                    src = core.slots.get("source", "?") if core else "?"
                    click.echo(f"  [{r.score:.3f}] {src[:45]}")
                    click.echo(f"    {r.text[:120].replace(chr(10), ' ')}...")

            elif cmd == "profile":
                click.echo(pipeline.render_profile())

            elif cmd == "quality":
                click.echo(pipeline.render_quality_report())

            elif cmd == "timeline":
                click.echo(pipeline.render_timeline())

            elif cmd == "sources":
                for s in pipeline.list_sources():
                    click.echo(f"  {s['source'][:55]:<55s} {s['chunks']:>5d} chunks")

            elif cmd == "source":
                if not arg:
                    click.echo("  Usage: source <name>")
                    continue
                detail = pipeline.source_detail(arg)
                if not detail.get("found"):
                    click.echo(f"  Source '{arg}' not found.")
                else:
                    click.echo(f"  Source: {detail['source']}")
                    click.echo(f"  Chunks: {detail['chunk_count']}")
                    click.echo(f"  Avg length: {detail['avg_chunk_length']} chars")

            elif cmd == "browse":
                sub_parts = arg.split(maxsplit=1)
                if len(sub_parts) < 2:
                    click.echo("  Usage: browse source <name> | browse cluster <id>")
                    continue
                sub_cmd, sub_arg = sub_parts
                if sub_cmd == "source":
                    result = pipeline.browse_source(sub_arg, limit=10)
                    click.echo(pipeline.render_browse(result))
                elif sub_cmd == "cluster":
                    try:
                        cid = int(sub_arg)
                    except ValueError:
                        click.echo("  Cluster ID must be a number.")
                        continue
                    result = pipeline.browse_cluster(cid, limit=10)
                    click.echo(pipeline.render_browse(result))

            elif cmd == "chunk":
                if not arg:
                    click.echo("  Usage: chunk <revision_id>")
                    continue
                detail = pipeline.chunk_detail(arg)
                click.echo(pipeline.render_chunk_detail(detail))

            elif cmd == "evolve":
                if not arg:
                    click.echo("  Usage: evolve <topic>")
                    continue
                result = pipeline.evolution(arg, k=10)
                click.echo(pipeline.render_evolution(result))

            elif cmd == "compare":
                cmp_parts = arg.split(maxsplit=1)
                if len(cmp_parts) < 2:
                    click.echo("  Usage: compare <source_a> <source_b>")
                    continue
                result = pipeline.compare_sources(cmp_parts[0], cmp_parts[1])
                click.echo(pipeline.render_comparison(result))

            elif cmd == "contradictions":
                click.echo("  Scanning...")
                pairs = pipeline.scan_contradictions(k=10, threshold=0.4)
                click.echo(pipeline.render_contradictions(pairs))

            elif cmd == "staleness":
                report = pipeline.staleness_report()
                click.echo(f"  {report['stale_count']} stale chunks (>{report['threshold_days']} days)")
                for source, count in sorted(report["by_source"].items(), key=lambda x: -x[1]):
                    click.echo(f"    {source[:45]}: {count}")

            elif cmd == "entities":
                click.echo("  Analyzing...")
                review = pipeline.review_entities(top_k=20)
                click.echo(f"  Total analyzed: {review['total_analyzed']}")
                if review["high"]:
                    click.echo(f"\n  High quality ({len(review['high'])}):")
                    for e in review["high"][:10]:
                        click.echo(f"    {e['entity']:<30s} score={e['score']:.2f}")
                if review["flagged"]:
                    click.echo(f"\n  Flagged ({len(review['flagged'])}):")
                    for e in review["flagged"][:10]:
                        click.echo(f"    {e['entity']:<30s} score={e['score']:.2f}")

            elif cmd == "insights":
                click.echo(pipeline.render_insights())

            elif cmd == "suggest":
                suggestions = pipeline.suggest_queries(n=5)
                for s in suggestions:
                    click.echo(f"  [{s['type']:<12s}] {s['query']}")
                    click.echo(f"    {s['rationale']}")

            elif cmd == "annotate":
                parts_ann = arg.split(maxsplit=1)
                if len(parts_ann) < 2:
                    click.echo("  Usage: annotate <revision_id> <tag1,tag2,...>")
                    continue
                rid_ann, tags_str = parts_ann
                tags_list = [t.strip() for t in tags_str.split(",")]
                ann_id = pipeline.annotate_chunk(rid_ann, tags=tags_list)
                click.echo(f"  Annotated. ID: {ann_id[:30]}...")

            elif cmd == "annotations":
                tag_filter = arg.strip() if arg.strip() else None
                anns = pipeline.list_annotations(tag=tag_filter)
                if not anns:
                    click.echo("  No annotations found.")
                for a in anns:
                    click.echo(f"  [{', '.join(a['tags'])}] -> {a['target_revision'][:30]}...")
                    if a["note"]:
                        click.echo(f"    Note: {a['note']}")

            elif cmd == "summary":
                click.echo(pipeline.summarize_corpus())

            elif cmd == "stats":
                s = pipeline.stats()
                click.echo(f"  Cores: {s['cores']:,}  Revisions: {s['revisions']:,}  Indexed: {s.get('indexed', 0):,}")

            elif cmd == "save":
                _save_pipeline(pipeline, store_path)

            else:
                click.echo(f"  Unknown command: {cmd}. Type 'help' for options.")

        except Exception as e:
            click.echo(f"  Error: {e}", err=True)


# ---- demo ----


@cli.command()
@click.argument("pdf_dir", required=False)
@click.option("--save-to", default=None, help="Save state after ingestion")
@click.pass_context
def demo(ctx: click.Context, pdf_dir: str | None, save_to: str | None) -> None:
    """Run the automated demo battery.

    If PDF_DIR is given, ingests from that directory first.
    Otherwise loads from --store.
    """
    store_path = ctx.obj["store"]

    if pdf_dir:
        from .extract import PDFExtractor, TextChunker
        store = KnowledgeStore()
        search = TfidfSearchIndex(store)
        pipeline = Pipeline(
            store=store,
            extractor=PDFExtractor(TextChunker(chunk_size=800, overlap=150)),
            search_index=search,
        )
        click.echo(f"Ingesting PDFs from {pdf_dir}...")
        t0 = time.time()
        results = pipeline.ingest_directory(pdf_dir, progress=True)
        total = sum(len(v) for v in results.values())
        click.echo(f"\n{len(results)} files, {total} chunks in {time.time() - t0:.1f}s")

        click.echo("Building knowledge graph...")
        pipeline.build_graph(n_clusters=50)

        if save_to:
            _save_pipeline(pipeline, save_to)
    else:
        pipeline = _load_pipeline(store_path)
        if pipeline.stats()["revisions"] == 0:
            click.echo("No data loaded. Provide a PDF directory or use --store with saved state.")
            return
        if pipeline.graph is None:
            click.echo("Building graph...")
            pipeline.build_graph(n_clusters=50)

    # Run demo battery
    click.echo("\n" + "=" * 60)
    click.echo("  CORPUS PROFILE")
    click.echo("=" * 60)
    click.echo(pipeline.render_profile())

    click.echo("\n" + "=" * 60)
    click.echo("  QUALITY REPORT")
    click.echo("=" * 60)
    click.echo(pipeline.render_quality_report())

    click.echo("\n" + "=" * 60)
    click.echo("  CORPUS INSIGHTS")
    click.echo("=" * 60)
    click.echo(pipeline.render_insights())

    click.echo("\n" + "=" * 60)
    click.echo("  SUGGESTED QUERIES")
    click.echo("=" * 60)
    suggestions = pipeline.suggest_queries(n=5)
    for s in suggestions:
        click.echo(f"  [{s['type']:<12s}] {s['query']}")

    s = pipeline.stats()
    click.echo(f"\nSummary: {s['cores']:,} cores, {s['revisions']:,} revisions, {s.get('indexed', 0):,} indexed")


# ---- serve ----


@cli.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start MCP server over stdio.

    Exposes 25 DKS tools via the Model Context Protocol.
    Requires: pip install dks[mcp]
    """
    try:
        from .mcp import MCPToolHandler
    except ImportError:
        click.echo("MCP support requires: pip install dks[mcp]", err=True)
        sys.exit(1)

    pipeline = _load_pipeline(ctx.obj["store"])
    handler = MCPToolHandler(pipeline)

    click.echo(f"DKS MCP server started ({len(handler.list_tools())} tools)", err=True)
    click.echo("Listening on stdio...", err=True)

    # Read JSON-RPC from stdin, write to stdout
    import json
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            method = request.get("method", "")
            params = request.get("params", {})

            if method == "tools/list":
                tools = handler.list_tools()
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": tools}}
            elif method == "tools/call":
                name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = handler.handle_tool_call(name, arguments)
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
            else:
                response = {"jsonrpc": "2.0", "id": request.get("id"),
                            "error": {"code": -32601, "message": f"Unknown method: {method}"}}

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            err = {"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "Parse error"}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
