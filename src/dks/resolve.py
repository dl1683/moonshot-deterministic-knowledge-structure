"""Entity resolution — map surface mentions to canonical entity IDs.

Resolution decisions are stored AS CLAIMS in the KnowledgeStore, making them
auditable, retractable, and temporally queryable. This is the key innovation:
entity resolution is not a black box — it's first-class data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .core import ClaimCore, canonicalize_text


ALIAS_CLAIM_TYPE = "dks.entity_alias@v1"


@dataclass(frozen=True)
class ResolutionDecision:
    """Result of resolving a surface mention to a canonical entity ID."""
    surface_form: str
    resolved_entity_id: str
    confidence_bp: int  # 0-10000 basis points
    method: str  # "exact" | "normalized" | "embedding" | "llm"

    def as_alias_claim(self) -> ClaimCore:
        """Convert this resolution decision to a ClaimCore for storage.

        Storing resolution decisions as claims makes them:
        - Auditable: who resolved what, when
        - Retractable: wrong resolutions can be explicitly retracted
        - Temporal: resolutions can change over time
        - Queryable: "what was X resolved to at time T?"
        """
        return ClaimCore(
            claim_type=ALIAS_CLAIM_TYPE,
            slots={
                "surface": canonicalize_text(self.surface_form),
                "entity": self.resolved_entity_id,
                "method": self.method,
            },
        )


@runtime_checkable
class Resolver(Protocol):
    """Protocol for entity resolution backends."""

    def resolve(
        self,
        mention: str,
        candidates: list[str] | None = None,
    ) -> ResolutionDecision | None:
        """Resolve a surface mention to a canonical entity ID.

        Args:
            mention: The surface form to resolve (e.g., "Tim Cook").
            candidates: Optional list of known entity IDs to match against.

        Returns:
            ResolutionDecision if resolved, None if no match found.
        """
        ...


class ExactResolver:
    """Exact string match resolver (case-insensitive after canonicalization)."""

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}  # canonical_form -> entity_id

    def register(self, surface_form: str, entity_id: str) -> None:
        """Register an alias mapping."""
        self._aliases[canonicalize_text(surface_form)] = entity_id

    def resolve(
        self,
        mention: str,
        candidates: list[str] | None = None,
    ) -> ResolutionDecision | None:
        canonical = canonicalize_text(mention)
        entity_id = self._aliases.get(canonical)
        if entity_id is None:
            return None
        if candidates is not None and entity_id not in candidates:
            return None
        return ResolutionDecision(
            surface_form=mention,
            resolved_entity_id=entity_id,
            confidence_bp=10000,
            method="exact",
        )


class NormalizedResolver:
    """Normalized string matching with basic text normalization."""

    def __init__(self) -> None:
        self._entities: dict[str, str] = {}  # canonical_name -> entity_id

    def register(self, name: str, entity_id: str) -> None:
        """Register an entity with its canonical name."""
        self._entities[canonicalize_text(name)] = entity_id

    def resolve(
        self,
        mention: str,
        candidates: list[str] | None = None,
    ) -> ResolutionDecision | None:
        canonical = canonicalize_text(mention)

        # Direct match
        entity_id = self._entities.get(canonical)
        if entity_id is not None:
            if candidates is None or entity_id in candidates:
                return ResolutionDecision(
                    surface_form=mention,
                    resolved_entity_id=entity_id,
                    confidence_bp=9500,
                    method="normalized",
                )

        # Substring match (mention is a word-boundary subset of a known entity)
        for name, eid in sorted(self._entities.items()):
            if candidates is not None and eid not in candidates:
                continue
            # Require substring to be a full word (avoid "art" matching "smart")
            canonical_words = set(canonical.split())
            name_words = set(name.split())
            if not canonical_words or not name_words:
                continue
            if canonical_words <= name_words or name_words <= canonical_words:
                return ResolutionDecision(
                    surface_form=mention,
                    resolved_entity_id=eid,
                    confidence_bp=7000,
                    method="normalized",
                )

        return None


class CascadingResolver:
    """Try resolvers in order, return first confident match.

    Default cascade: exact → normalized → (embedding → LLM if configured).
    """

    def __init__(self, resolvers: list[Resolver] | None = None) -> None:
        self._resolvers: list[Resolver] = resolvers or []

    def add_resolver(self, resolver: Resolver) -> None:
        self._resolvers.append(resolver)

    def resolve(
        self,
        mention: str,
        candidates: list[str] | None = None,
    ) -> ResolutionDecision | None:
        for resolver in self._resolvers:
            result = resolver.resolve(mention, candidates)
            if result is not None:
                return result
        return None
