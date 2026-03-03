"""Claim extraction from unstructured text.

This module provides the Extractor protocol and default implementations for
extracting structured ClaimCore instances from text. The commitment boundary
is explicit: ExtractionResult is non-deterministic output. Only when claims
are committed via store.assert_revision() do they become deterministic data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .core import ClaimCore, Provenance, canonicalize_text


@dataclass(frozen=True)
class ExtractionResult:
    """Result of extracting claims from text.

    This is the output of the non-deterministic extraction phase.
    Claims become deterministic only after commitment to a KnowledgeStore.
    """
    claims: tuple[ClaimCore, ...]
    provenance: tuple[Provenance, ...]
    raw_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Extractor(Protocol):
    """Protocol for claim extraction backends.

    Implementations may be deterministic (regex) or non-deterministic (LLM).
    """

    def extract(
        self,
        text: str,
        *,
        claim_types: list[str] | None = None,
    ) -> ExtractionResult:
        """Extract structured claims from text.

        Args:
            text: Unstructured input text.
            claim_types: Optional filter — only extract claims of these types.

        Returns:
            ExtractionResult with extracted claims and provenance.
        """
        ...


class RegexExtractor:
    """Zero-dependency regex-based extractor for structured patterns.

    Extracts claims matching registered patterns. Good for:
    - Dates, numbers, known templates
    - Structured log lines
    - Key-value pairs

    Not suitable for open-domain extraction (use LLMExtractor for that).
    """

    def __init__(self) -> None:
        self._patterns: list[tuple[str, re.Pattern[str], list[str]]] = []

    def register_pattern(
        self,
        claim_type: str,
        pattern: str,
        slot_names: list[str],
    ) -> None:
        """Register a regex pattern for a claim type.

        Named groups in the pattern are mapped to slot_names in order.
        If the pattern uses unnamed groups, they're mapped positionally.
        """
        self._patterns.append((claim_type, re.compile(pattern), slot_names))

    def extract(
        self,
        text: str,
        *,
        claim_types: list[str] | None = None,
    ) -> ExtractionResult:
        claims: list[ClaimCore] = []
        provenances: list[Provenance] = []

        for claim_type, pattern, slot_names in self._patterns:
            if claim_types is not None and claim_type not in claim_types:
                continue

            for match in pattern.finditer(text):
                groups = match.groupdict() if match.groupdict() else {}
                if not groups:
                    # Use positional groups
                    groups = {
                        name: val
                        for name, val in zip(slot_names, match.groups())
                        if val is not None
                    }
                else:
                    # Map named groups to slot_names
                    mapped = {}
                    for name in slot_names:
                        if name in groups and groups[name] is not None:
                            mapped[name] = groups[name]
                    groups = mapped

                if groups:
                    claim = ClaimCore(
                        claim_type=claim_type,
                        slots={k: canonicalize_text(v) for k, v in groups.items()},
                    )
                    claims.append(claim)
                    provenances.append(Provenance(
                        source=f"regex:{claim_type}",
                        evidence_ref=match.group(0),
                    ))

        return ExtractionResult(
            claims=tuple(claims),
            provenance=tuple(provenances),
            raw_text=text,
        )


class LLMExtractor:
    """LLM-backed extractor for open-domain claim extraction.

    Requires an LLM callable that takes a prompt and returns structured JSON.
    The LLM is called outside the deterministic boundary — results are
    non-deterministic until committed to a KnowledgeStore.

    Default model recommendation: Qwen3-0.6B (from model registry)
    for fast iteration. Upgrade to Qwen3-4B for production quality.
    """

    def __init__(
        self,
        llm_fn: Any,
        *,
        system_prompt: str | None = None,
        model_id: str = "Qwen/Qwen3-0.6B",
    ) -> None:
        """
        Args:
            llm_fn: Callable that takes (prompt: str) -> str (JSON response).
            system_prompt: Optional system prompt for the LLM.
            model_id: Model identifier for provenance tracking.
        """
        self._llm_fn = llm_fn
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._model_id = model_id

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "Extract factual claims from the following text. "
            "Return a JSON array where each element has:\n"
            '  {"claim_type": "<type>", "slots": {"<role>": "<value>", ...}}\n'
            "Only extract concrete, verifiable facts. "
            "Use lowercase for all values."
        )

    def extract(
        self,
        text: str,
        *,
        claim_types: list[str] | None = None,
    ) -> ExtractionResult:
        import json

        type_filter = ""
        if claim_types:
            type_filter = f"\nOnly extract these claim types: {', '.join(claim_types)}"

        prompt = f"{self._system_prompt}{type_filter}\n\nText:\n{text}"

        raw_response = self._llm_fn(prompt)

        try:
            parsed = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            return ExtractionResult(
                claims=(),
                provenance=(),
                raw_text=text,
                metadata={"error": "failed to parse LLM response", "raw": str(raw_response)},
            )

        claims: list[ClaimCore] = []
        provenances: list[Provenance] = []

        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            ct = item.get("claim_type", "")
            slots = item.get("slots", {})
            if not ct or not slots:
                continue
            if not isinstance(slots, dict):
                continue

            claim = ClaimCore(
                claim_type=canonicalize_text(ct),
                slots={canonicalize_text(k): canonicalize_text(str(v)) for k, v in slots.items()},
            )
            claims.append(claim)
            provenances.append(Provenance(
                source=f"llm:{self._model_id}",
                evidence_ref=text[:200],
            ))

        return ExtractionResult(
            claims=tuple(claims),
            provenance=tuple(provenances),
            raw_text=text,
            metadata={"model_id": self._model_id},
        )
