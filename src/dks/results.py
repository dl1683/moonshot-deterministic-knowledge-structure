"""Result dataclasses for DKS pipeline operations.

These are returned by Pipeline.reason(), Pipeline.query_deep(),
Pipeline.evidence_chain(), Pipeline.synthesize(), and Pipeline.coverage().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .index import SearchResult


@dataclass
class ReasoningResult:
    """Result of multi-hop reasoning over the knowledge store."""
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    trace: list[dict[str, Any]]
    total_hops: int

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary of reasoning results."""
        lines = [f'Question: "{self.question}"']
        lines.append(f"Found {self.total_chunks} relevant chunks across {self.source_count} documents")
        lines.append(f"Reasoning: {self.total_hops} expansion hops")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        lines.append("")
        lines.append("Top results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")
        return "\n".join(lines)


@dataclass
class QueryFacet:
    """A single facet (sub-question) of a deep query."""
    subquery: str
    results: list[SearchResult]
    graph_results: list[SearchResult]

    @property
    def total_chunks(self) -> int:
        return len(self.results) + len(self.graph_results)


@dataclass
class DeepQueryResult:
    """Result of intelligent query decomposition and targeted retrieval."""
    question: str
    subqueries: list[str]
    facets: list[QueryFacet]
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    relevant_topics: list[dict[str, Any]]

    @property
    def total_chunks(self) -> int:
        return len(self.results)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f'Deep Query: "{self.question}"']
        lines.append(f"Decomposed into {len(self.subqueries)} sub-queries:")
        for sq in self.subqueries:
            lines.append(f"  - {sq}")
        lines.append(f"\nFound {self.total_chunks} chunks across {self.source_count} documents")

        if self.relevant_topics:
            lines.append("\nRelevant topics:")
            for t in self.relevant_topics:
                labels = ", ".join(t["labels"][:3])
                lines.append(f"  [{t['size']} chunks, relevance={t['relevance']:.3f}] {labels}")

        lines.append("\nTop results:")
        for r in self.results[:5]:
            text_preview = r.text[:120].replace("\n", " ")
            lines.append(f"  [{r.score:.3f}] {text_preview}...")

        lines.append(f"\nSource breakdown:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:55]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 10) -> str:
        """Format results as context suitable for feeding to an LLM."""
        lines = [f"# Context for: {self.question}\n"]

        for i, r in enumerate(self.results[:max_chunks]):
            lines.append(f"## Chunk {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        return "\n".join(lines)


@dataclass
class EvidenceChain:
    """Cross-document evidence chain supporting or refuting a claim."""
    claim: str
    direct_evidence: list[SearchResult]
    supporting_evidence: list[SearchResult]
    related_evidence: list[SearchResult]
    chains: list[list[SearchResult]]
    sources: dict[str, list[SearchResult]]
    total_evidence: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def chain_count(self) -> int:
        return len(self.chains)

    def summary(self) -> str:
        """Human-readable evidence chain summary."""
        lines = [f'Evidence for: "{self.claim}"']
        lines.append(f"Total evidence: {self.total_evidence} chunks from {self.source_count} sources")
        lines.append(f"Direct evidence: {len(self.direct_evidence)} chunks")
        lines.append(f"Evidence chains: {self.chain_count}")
        lines.append("")

        if self.direct_evidence:
            lines.append("Direct evidence:")
            for r in self.direct_evidence[:5]:
                text_preview = r.text[:120].replace("\n", " ")
                lines.append(f"  [{r.score:.3f}] {text_preview}...")

        if self.chains:
            lines.append("")
            lines.append("Evidence chains:")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"  Chain {i+1} ({len(chain)} links):")
                for j, link in enumerate(chain):
                    text_preview = link.text[:80].replace("\n", " ")
                    lines.append(f"    {j+1}. [{link.score:.3f}] {text_preview}...")

        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1]))[:8]:
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")

        return "\n".join(lines)

    def context_for_llm(self, max_chunks: int = 15) -> str:
        """Format evidence as LLM-ready context with source attribution."""
        lines = [f"# Evidence Analysis: {self.claim}\n"]

        lines.append("## Direct Evidence\n")
        for i, r in enumerate(self.direct_evidence[:max_chunks // 2]):
            lines.append(f"### Evidence {i+1} (relevance: {r.score:.3f})")
            lines.append(r.text[:1000])
            lines.append("")

        if self.chains:
            lines.append("## Evidence Chains\n")
            for i, chain in enumerate(self.chains[:3]):
                lines.append(f"### Chain {i+1}")
                for j, link in enumerate(chain):
                    lines.append(f"Link {j+1}: {link.text[:500]}")
                    lines.append("")

        if self.related_evidence:
            lines.append("## Related Context\n")
            remaining = max_chunks - len(self.direct_evidence[:max_chunks // 2])
            for i, r in enumerate(self.related_evidence[:remaining]):
                lines.append(f"### Related {i+1} (relevance: {r.score:.3f})")
                lines.append(r.text[:500])
                lines.append("")

        return "\n".join(lines)


@dataclass
class SynthesisResult:
    """Full-stack retrieval and synthesis result.

    Contains organized, source-attributed context ready for LLM consumption
    or human review.
    """
    question: str
    results: list[SearchResult]
    sources: dict[str, list[SearchResult]]
    source_summaries: list[dict[str, Any]]
    themes: list[str]
    context: str
    reasoning_trace: list[dict[str, Any]]
    total_chunks: int

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def context_length(self) -> int:
        return len(self.context)

    def summary(self) -> str:
        """Human-readable summary of the synthesis."""
        lines = [f'Synthesis: "{self.question}"']
        lines.append(
            f"Retrieved {self.total_chunks} chunks from "
            f"{self.source_count} sources"
        )
        lines.append(f"Context: {self.context_length:,} characters")
        lines.append("")

        if self.themes:
            lines.append("Key themes: " + ", ".join(self.themes))
            lines.append("")

        lines.append("Sources (by relevance):")
        for ss in self.source_summaries[:10]:
            lines.append(
                f"  [{ss['chunks']} chunks, rel={ss['relevance']:.3f}] "
                f"{ss['source'][:55]}"
            )

        lines.append("")
        lines.append("Reasoning trace:")
        for t in self.reasoning_trace:
            if t["hop"] == 0:
                lines.append(f"  Hop 0: {t['results']} initial results")
            else:
                terms = t.get("expansion_terms", [])
                lines.append(
                    f"  Hop {t['hop']}: +{t['new']} new "
                    f"(expanded: {', '.join(terms[:3])})"
                )

        return "\n".join(lines)


@dataclass
class CoverageReport:
    """Analysis of store coverage for a topic."""
    topic: str
    total_chunks: int
    sources: dict[str, list[SearchResult]]
    subtopics: list[str]
    source_count: int

    def summary(self) -> str:
        """Human-readable coverage report."""
        lines = [f'Coverage: "{self.topic}"']
        lines.append(f"Found {self.total_chunks} chunks across {self.source_count} documents")
        lines.append("")
        lines.append("Subtopics discovered:")
        for st in self.subtopics:
            lines.append(f"  - {st}")
        lines.append("")
        lines.append("Sources:")
        for source, chunks in sorted(self.sources.items(), key=lambda x: -len(x[1])):
            lines.append(f"  [{len(chunks)} chunks] {source[:60]}")
        return "\n".join(lines)
