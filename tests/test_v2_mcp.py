"""Tests for dks.mcp — MCP tool handler."""
from datetime import datetime, timezone

from dks import (
    MCPToolHandler,
    NumpyIndex,
    Pipeline,
    RegexExtractor,
    ExactResolver,
    CascadingResolver,
)


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_mcp_handler() -> MCPToolHandler:
    extractor = RegexExtractor()
    extractor.register_pattern(
        "residence",
        r"(?P<subject>\w+) lives in (?P<city>\w+)",
        ["subject", "city"],
    )

    resolver = ExactResolver()
    resolver.register("alice", "entity:alice")
    resolver.register("london", "entity:london")

    pipeline = Pipeline(
        extractor=extractor,
        resolver=CascadingResolver([resolver]),
        embedding_backend=NumpyIndex(dimension=64),
    )
    return MCPToolHandler(pipeline)


class TestMCPToolListing:
    def test_list_tools_returns_tools(self) -> None:
        handler = _make_mcp_handler()
        tools = handler.list_tools()
        assert len(tools) == 5

        names = {t["name"] for t in tools}
        assert "dks_ingest" in names
        assert "dks_query" in names
        assert "dks_query_exact" in names
        assert "dks_snapshot" in names
        assert "dks_stats" in names

    def test_tools_have_schemas(self) -> None:
        handler = _make_mcp_handler()
        tools = handler.list_tools()
        for tool in tools:
            assert "inputSchema" in tool
            assert "description" in tool


class TestMCPIngest:
    def test_ingest_text(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_ingest", {
            "text": "Alice lives in London",
        })
        assert "revision_ids" in result
        assert result["count"] == 1

    def test_ingest_with_valid_time(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_ingest", {
            "text": "Alice lives in London",
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2025-01-01T00:00:00Z",
        })
        assert result["count"] == 1

    def test_ingest_empty_text_errors(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_ingest", {"text": ""})
        assert "error" in result


class TestMCPQuery:
    def test_query_after_ingest(self) -> None:
        handler = _make_mcp_handler()
        handler.handle_tool_call("dks_ingest", {"text": "Alice lives in London"})

        result = handler.handle_tool_call("dks_query", {"question": "lives in"})
        assert "results" in result
        assert result["count"] >= 1

    def test_query_empty_store(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_query", {"question": "anything"})
        assert result["count"] == 0


class TestMCPQueryExact:
    def test_exact_query(self) -> None:
        handler = _make_mcp_handler()
        handler.handle_tool_call("dks_ingest", {
            "text": "Alice lives in London",
            "valid_from": "2024-01-01T00:00:00Z",
        })

        # Get the core_id from snapshot
        snapshot = handler.handle_tool_call("dks_snapshot", {})
        cores = snapshot["snapshot"]["cores"]
        core_id = cores[0]["core_id"]

        result = handler.handle_tool_call("dks_query_exact", {
            "core_id": core_id,
            "valid_at": "2024-06-01T00:00:00Z",
            "tx_id": 1,
        })
        assert "result" in result
        assert result["result"] is not None

    def test_exact_query_missing(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_query_exact", {
            "core_id": "nonexistent",
            "valid_at": "2024-06-01T00:00:00Z",
            "tx_id": 1,
        })
        assert result["result"] is None


class TestMCPStats:
    def test_stats_empty(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("dks_stats", {})
        assert result["cores"] == 0
        assert result["revisions"] == 0

    def test_stats_after_ingest(self) -> None:
        handler = _make_mcp_handler()
        handler.handle_tool_call("dks_ingest", {"text": "Alice lives in London"})

        result = handler.handle_tool_call("dks_stats", {})
        assert result["cores"] == 1
        assert result["revisions"] == 1


class TestMCPSnapshot:
    def test_snapshot(self) -> None:
        handler = _make_mcp_handler()
        handler.handle_tool_call("dks_ingest", {"text": "Alice lives in London"})

        result = handler.handle_tool_call("dks_snapshot", {})
        assert "snapshot" in result
        assert "cores" in result["snapshot"]
        assert "revisions" in result["snapshot"]


class TestMCPUnknownTool:
    def test_unknown_tool(self) -> None:
        handler = _make_mcp_handler()
        result = handler.handle_tool_call("nonexistent_tool", {})
        assert "error" in result
