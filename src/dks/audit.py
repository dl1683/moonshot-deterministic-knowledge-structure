"""Audit trail for DKS pipeline operations.

Records every decision point during retrieval and ingestion,
providing full transparency into what happened and why.
"""
from __future__ import annotations

import json as _json
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditEvent:
    """A single decision point in the retrieval pipeline."""
    stage: str         # e.g. "classify", "search", "expand", "diversify", "rerank"
    action: str        # What happened
    inputs: dict       # What went in
    outputs: dict      # What came out
    duration_ms: float # How long it took
    metadata: dict = field(default_factory=dict)  # Extra details


@dataclass
class AuditTrace:
    """Complete audit trail for a retrieval operation."""
    operation: str     # "query", "reason", "synthesize", "ask", etc.
    question: str
    strategy: str = ""
    events: list[AuditEvent] = field(default_factory=list)
    started_at: str = ""
    total_duration_ms: float = 0.0

    def add(self, stage: str, action: str, inputs: dict, outputs: dict,
            duration_ms: float, **metadata) -> None:
        self.events.append(AuditEvent(
            stage=stage, action=action, inputs=inputs,
            outputs=outputs, duration_ms=duration_ms, metadata=metadata,
        ))

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "operation": self.operation,
            "question": self.question,
            "strategy": self.strategy,
            "started_at": self.started_at,
            "total_duration_ms": self.total_duration_ms,
            "events": [
                {
                    "stage": e.stage,
                    "action": e.action,
                    "inputs": e.inputs,
                    "outputs": e.outputs,
                    "duration_ms": e.duration_ms,
                    "metadata": e.metadata,
                }
                for e in self.events
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return _json.dumps(self.to_dict(), indent=indent, default=str)


class AuditManager:
    """Manages audit trail lifecycle for pipeline operations."""

    def __init__(self) -> None:
        self._enabled = False
        self._last_trace: AuditTrace | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def last_trace(self) -> AuditTrace | None:
        return self._last_trace

    def begin(self, operation: str, question: str) -> AuditTrace | None:
        """Start a new audit trace if auditing is enabled."""
        if not self._enabled:
            return None
        return AuditTrace(
            operation=operation,
            question=question,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def finish(self, trace: AuditTrace | None, t0: float) -> None:
        """Finalize and store an audit trace."""
        if trace is None:
            return
        trace.total_duration_ms = (_time.time() - t0) * 1000
        self._last_trace = trace

    @staticmethod
    def render(trace: AuditTrace | None) -> str:
        """Render an audit trace as a human-readable markdown report."""
        if trace is None:
            return "No audit trace available."

        lines = []
        lines.append(f"# Audit Report: {trace.operation}")
        lines.append("")
        lines.append(f"**Question:** {trace.question}")
        if trace.strategy:
            lines.append(f"**Strategy:** {trace.strategy}")
        lines.append(f"**Started:** {trace.started_at}")
        lines.append(f"**Total Duration:** {trace.total_duration_ms:.1f}ms")
        lines.append("")

        lines.append("## Decision Pipeline")
        lines.append("")

        for i, event in enumerate(trace.events):
            pct = (event.duration_ms / trace.total_duration_ms * 100
                   if trace.total_duration_ms > 0 else 0)
            lines.append(
                f"### {i+1}. {event.stage.upper()}: {event.action} "
                f"({event.duration_ms:.1f}ms, {pct:.0f}%)"
            )
            lines.append("")

            if event.inputs:
                lines.append("**Inputs:**")
                for k, v in event.inputs.items():
                    if isinstance(v, list) and len(v) > 5:
                        lines.append(f"- {k}: [{len(v)} items]")
                    elif isinstance(v, str) and len(v) > 100:
                        lines.append(f"- {k}: {v[:100]}...")
                    else:
                        lines.append(f"- {k}: {v}")
                lines.append("")

            if event.outputs:
                lines.append("**Outputs:**")
                for k, v in event.outputs.items():
                    if isinstance(v, list) and len(v) > 5:
                        lines.append(f"- {k}: [{len(v)} items]")
                    elif isinstance(v, str) and len(v) > 100:
                        lines.append(f"- {k}: {v[:100]}...")
                    else:
                        lines.append(f"- {k}: {v}")
                lines.append("")

            if event.metadata:
                lines.append("**Details:**")
                for k, v in event.metadata.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")

        lines.append("## Timing Breakdown")
        lines.append("")
        lines.append("| Stage | Action | Duration | % |")
        lines.append("|-------|--------|----------|---|")
        for event in trace.events:
            pct = (event.duration_ms / trace.total_duration_ms * 100
                   if trace.total_duration_ms > 0 else 0)
            lines.append(
                f"| {event.stage} | {event.action} | "
                f"{event.duration_ms:.1f}ms | {pct:.0f}% |"
            )

        return "\n".join(lines)
