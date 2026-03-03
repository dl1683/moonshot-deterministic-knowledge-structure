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
        ]

    def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle an MCP tool call.

        Args:
            name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tool result as a dict.
        """
        if name == "dks_ingest":
            return self._handle_ingest(arguments)
        elif name == "dks_query":
            return self._handle_query(arguments)
        elif name == "dks_query_exact":
            return self._handle_query_exact(arguments)
        elif name == "dks_snapshot":
            return self._handle_snapshot(arguments)
        elif name == "dks_stats":
            return self._handle_stats(arguments)
        else:
            return {"error": f"Unknown tool: {name}"}

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
