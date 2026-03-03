"""MCP (Model Context Protocol) server for DKS.

Exposes Pipeline operations as MCP tools that any MCP-compatible
AI agent can call. This is DKS's integration surface.

Usage:
    from dks.mcp import create_mcp_server
    server = create_mcp_server(pipeline)
    server.run()

Requires: pip install dks[mcp]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .core import KnowledgeStore, Provenance, TransactionTime, ValidTime
from .pipeline import Pipeline


class MCPToolHandler:
    """Handles MCP tool calls by delegating to a Pipeline.

    This is a framework-agnostic handler. It can be wrapped by any
    MCP server implementation (e.g., the `mcp` Python package).
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._tx_counter = 0

    def _next_tx(self) -> TransactionTime:
        self._tx_counter += 1
        return TransactionTime(
            tx_id=self._tx_counter,
            recorded_at=datetime.now(timezone.utc),
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions."""
        return [
            {
                "name": "dks_ingest",
                "description": "Ingest text into the knowledge store. Extracts claims, resolves entities, and commits them.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to ingest"},
                        "valid_from": {"type": "string", "description": "ISO datetime when facts became true"},
                        "valid_to": {"type": "string", "description": "ISO datetime when facts stopped being true (optional)"},
                        "confidence": {"type": "integer", "description": "Confidence in basis points (0-10000)", "default": 5000},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "dks_query",
                "description": "Search the knowledge store for claims similar to a question.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Natural language question"},
                        "k": {"type": "integer", "description": "Max results", "default": 5},
                        "valid_at": {"type": "string", "description": "ISO datetime for temporal filter (optional)"},
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "dks_query_exact",
                "description": "Look up a specific claim by its core_id with temporal coordinates.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "core_id": {"type": "string", "description": "The core_id to look up"},
                        "valid_at": {"type": "string", "description": "ISO datetime for valid time"},
                        "tx_id": {"type": "integer", "description": "Transaction ID cutoff"},
                    },
                    "required": ["core_id", "valid_at", "tx_id"],
                },
            },
            {
                "name": "dks_snapshot",
                "description": "Export the current knowledge store state as canonical JSON.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_stats",
                "description": "Get statistics about the knowledge store.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_reason",
                "description": "Multi-hop reasoning query that expands search iteratively.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Natural language question"},
                        "k": {"type": "integer", "description": "Max results per hop", "default": 5},
                        "hops": {"type": "integer", "description": "Number of expansion hops", "default": 2},
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "dks_profile",
                "description": "Get a comprehensive corpus profile with cluster overview, source stats, and quality flags.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_quality_report",
                "description": "Generate an automated quality report scanning for issues in the corpus.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_sources",
                "description": "List all source documents with chunk counts and page ranges.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_source_detail",
                "description": "Get detailed statistics for a specific source document.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Source name/filename"},
                    },
                    "required": ["source"],
                },
            },
            {
                "name": "dks_browse_cluster",
                "description": "Browse chunks within a specific topic cluster.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "integer", "description": "Cluster ID to browse"},
                        "limit": {"type": "integer", "description": "Max chunks to return", "default": 20},
                    },
                    "required": ["cluster_id"],
                },
            },
            {
                "name": "dks_browse_source",
                "description": "Browse chunks from a specific source document.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Source name/filename"},
                        "limit": {"type": "integer", "description": "Max chunks to return", "default": 20},
                    },
                    "required": ["source"],
                },
            },
            {
                "name": "dks_chunk_detail",
                "description": "Get full details of a specific chunk including text, metadata, and neighbors.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "revision_id": {"type": "string", "description": "The revision ID to inspect"},
                    },
                    "required": ["revision_id"],
                },
            },
            {
                "name": "dks_evolution",
                "description": "Show how understanding of a topic has evolved across documents over time.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Topic to trace evolution for"},
                        "k": {"type": "integer", "description": "Max chunks to retrieve", "default": 20},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "dks_compare_sources",
                "description": "Compare two source documents for overlap, divergence, and shared topics.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_a": {"type": "string", "description": "First source name"},
                        "source_b": {"type": "string", "description": "Second source name"},
                    },
                    "required": ["source_a", "source_b"],
                },
            },
            {
                "name": "dks_contradictions",
                "description": "Scan the corpus for potential contradictions between claims.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "k": {"type": "integer", "description": "Max contradiction pairs to find", "default": 10},
                    },
                },
            },
            {
                "name": "dks_staleness",
                "description": "Identify claims that may be outdated based on their age.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "age_days": {"type": "integer", "description": "Flag chunks older than this many days", "default": 365},
                    },
                },
            },
            {
                "name": "dks_delete_source",
                "description": "Soft-delete all chunks from a source (retract, preserving audit trail).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Source name to delete"},
                        "reason": {"type": "string", "description": "Reason for deletion"},
                    },
                    "required": ["source"],
                },
            },
            {
                "name": "dks_delete_cluster",
                "description": "Soft-delete all chunks in a cluster (retract, preserving audit trail).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "integer", "description": "Cluster ID to delete"},
                        "reason": {"type": "string", "description": "Reason for deletion"},
                    },
                    "required": ["cluster_id"],
                },
            },
            {
                "name": "dks_insights",
                "description": "Get proactive corpus insights with prioritized improvement recommendations and health score.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "dks_suggest_queries",
                "description": "Get suggested queries to explore the knowledge base based on corpus content.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "description": "Number of suggestions", "default": 5},
                    },
                },
            },
        ]

    def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle an MCP tool call.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result as a dict.
        """
        handlers = {
            "dks_ingest": self._handle_ingest,
            "dks_query": self._handle_query,
            "dks_query_exact": self._handle_query_exact,
            "dks_snapshot": self._handle_snapshot,
            "dks_stats": self._handle_stats,
            "dks_reason": self._handle_reason,
            "dks_profile": self._handle_profile,
            "dks_quality_report": self._handle_quality_report,
            "dks_sources": self._handle_sources,
            "dks_source_detail": self._handle_source_detail,
            "dks_browse_cluster": self._handle_browse_cluster,
            "dks_browse_source": self._handle_browse_source,
            "dks_chunk_detail": self._handle_chunk_detail,
            "dks_evolution": self._handle_evolution,
            "dks_compare_sources": self._handle_compare_sources,
            "dks_contradictions": self._handle_contradictions,
            "dks_staleness": self._handle_staleness,
            "dks_delete_source": self._handle_delete_source,
            "dks_delete_cluster": self._handle_delete_cluster,
            "dks_insights": self._handle_insights,
            "dks_suggest_queries": self._handle_suggest_queries,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}
        return handler(arguments)

    def _handle_ingest(self, args: dict[str, Any]) -> dict[str, Any]:
        text = args.get("text", "")
        if not text:
            return {"error": "text is required"}

        valid_from = _parse_datetime(args.get("valid_from")) or datetime.now(timezone.utc)
        valid_to = _parse_datetime(args.get("valid_to"))
        confidence = args.get("confidence", 5000)

        valid_time = ValidTime(start=valid_from, end=valid_to)
        tx_time = self._next_tx()

        try:
            revision_ids = self._pipeline.ingest(
                text,
                valid_time=valid_time,
                transaction_time=tx_time,
                confidence_bp=confidence,
            )
            return {
                "revision_ids": revision_ids,
                "count": len(revision_ids),
                "tx_id": tx_time.tx_id,
            }
        except ValueError as e:
            return {"error": str(e)}

    def _handle_query(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args.get("question", "")
        if not question:
            return {"error": "question is required"}

        k = args.get("k", 5)
        valid_at = _parse_datetime(args.get("valid_at"))
        tx_id = self._tx_counter if valid_at else None

        try:
            results = self._pipeline.query(
                question,
                k=k,
                valid_at=valid_at,
                tx_id=tx_id,
            )
            return {
                "results": [
                    {
                        "core_id": r.core_id,
                        "revision_id": r.revision_id,
                        "score": round(r.score, 4),
                        "text": r.text[:500],
                    }
                    for r in results
                ],
                "count": len(results),
            }
        except ValueError as e:
            return {"error": str(e)}

    def _handle_query_exact(self, args: dict[str, Any]) -> dict[str, Any]:
        core_id = args.get("core_id", "")
        valid_at = _parse_datetime(args.get("valid_at"))
        tx_id = args.get("tx_id")

        if not core_id or valid_at is None or tx_id is None:
            return {"error": "core_id, valid_at, and tx_id are required"}

        result = self._pipeline.query_exact(
            core_id,
            valid_at=valid_at,
            tx_id=tx_id,
        )
        if result is None:
            return {"result": None}

        return {
            "result": {
                "revision_id": result.revision_id,
                "core_id": result.core_id,
                "assertion": result.assertion,
                "status": result.status,
                "confidence_bp": result.confidence_bp,
            }
        }

    def _handle_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = self._pipeline.store.as_canonical_payload()
        return {"snapshot": payload}

    def _handle_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        store = self._pipeline.store
        return {
            "cores": len(store.cores),
            "revisions": len(store.revisions),
            "relations": len(store.relations),
            "pending_relations": len(store._pending_relations),
        }

    def _handle_reason(self, args: dict[str, Any]) -> dict[str, Any]:
        question = args.get("question", "")
        if not question:
            return {"error": "question is required"}
        k = args.get("k", 5)
        hops = args.get("hops", 2)
        result = self._pipeline.reason(question, k=k, hops=hops, expand_k=3)
        return {
            "total_chunks": result.total_chunks,
            "source_count": result.source_count,
            "hops": result.total_hops,
            "results": [
                {"core_id": r.core_id, "revision_id": r.revision_id,
                 "score": round(r.score, 4), "text": r.text[:500]}
                for r in result.results[:10]
            ],
        }

    def _handle_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._pipeline.profile()
        except ValueError as e:
            return {"error": str(e)}

    def _handle_quality_report(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._pipeline.quality_report()
        except ValueError as e:
            return {"error": str(e)}

    def _handle_sources(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"sources": self._pipeline.list_sources()}

    def _handle_source_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        source = args.get("source", "")
        if not source:
            return {"error": "source is required"}
        return self._pipeline.source_detail(source)

    def _handle_browse_cluster(self, args: dict[str, Any]) -> dict[str, Any]:
        cluster_id = args.get("cluster_id")
        if cluster_id is None:
            return {"error": "cluster_id is required"}
        limit = args.get("limit", 20)
        try:
            return self._pipeline.browse_cluster(int(cluster_id), limit=limit)
        except ValueError as e:
            return {"error": str(e)}

    def _handle_browse_source(self, args: dict[str, Any]) -> dict[str, Any]:
        source = args.get("source", "")
        if not source:
            return {"error": "source is required"}
        limit = args.get("limit", 20)
        return self._pipeline.browse_source(source, limit=limit)

    def _handle_chunk_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        revision_id = args.get("revision_id", "")
        if not revision_id:
            return {"error": "revision_id is required"}
        return self._pipeline.chunk_detail(revision_id)

    def _handle_evolution(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = args.get("topic", "")
        if not topic:
            return {"error": "topic is required"}
        k = args.get("k", 20)
        return self._pipeline.evolution(topic, k=k)

    def _handle_compare_sources(self, args: dict[str, Any]) -> dict[str, Any]:
        source_a = args.get("source_a", "")
        source_b = args.get("source_b", "")
        if not source_a or not source_b:
            return {"error": "source_a and source_b are required"}
        return self._pipeline.compare_sources(source_a, source_b)

    def _handle_contradictions(self, args: dict[str, Any]) -> dict[str, Any]:
        k = args.get("k", 10)
        return {"contradictions": self._pipeline.scan_contradictions(k=k)}

    def _handle_staleness(self, args: dict[str, Any]) -> dict[str, Any]:
        age_days = args.get("age_days", 365)
        return self._pipeline.staleness_report(age_days=age_days)

    def _handle_delete_source(self, args: dict[str, Any]) -> dict[str, Any]:
        source = args.get("source", "")
        if not source:
            return {"error": "source is required"}
        reason = args.get("reason", "Deleted via MCP tool")
        return self._pipeline.delete_source(source, reason=reason)

    def _handle_delete_cluster(self, args: dict[str, Any]) -> dict[str, Any]:
        cluster_id = args.get("cluster_id")
        if cluster_id is None:
            return {"error": "cluster_id is required"}
        reason = args.get("reason", "Deleted via MCP tool")
        try:
            return self._pipeline.delete_cluster(int(cluster_id), reason=reason)
        except ValueError as e:
            return {"error": str(e)}

    def _handle_insights(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._pipeline.insights()
        except ValueError as e:
            return {"error": str(e)}

    def _handle_suggest_queries(self, args: dict[str, Any]) -> dict[str, Any]:
        n = args.get("n", 5)
        try:
            return {"suggestions": self._pipeline.suggest_queries(n=n)}
        except ValueError as e:
            return {"error": str(e)}


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
