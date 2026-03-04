"""Explorer — browse, annotate, and analyze the knowledge corpus.

Contains all explore/browse/annotation/entity/temporal/comparison/insights
methods extracted from Pipeline, as a cohesive Explorer class with injectable
dependencies.
"""
from __future__ import annotations
import re
import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .core import ClaimCore, KnowledgeStore, Provenance, TransactionTime, ValidTime


class Explorer:
    """Browse, annotate, and analyze the knowledge corpus.

    All explore/browse/annotation/entity/temporal/comparison/insights
    operations live here, leaving Pipeline as a thin ingest+query facade.

    Args:
        store: The deterministic bitemporal KnowledgeStore.
        graph_fn: Callable that returns the current KnowledgeGraph or None.
        tx_factory: Callable that generates the next TransactionTime.
        query_fn: Callable matching Pipeline.query() signature.
        stats_fn: Callable matching Pipeline.stats() signature.
        topics_fn: Callable matching Pipeline.topics() signature.
        link_entities_fn: Callable matching Pipeline.link_entities() signature.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        graph_fn: Callable[[], Any],
        tx_factory: Callable[[], TransactionTime],
        query_fn: Callable,
        stats_fn: Callable[[], dict],
        topics_fn: Callable[[], list],
        link_entities_fn: Callable,
    ) -> None:
        self.store = store
        self._graph_fn = graph_fn
        self._tx_factory = tx_factory
        self._query_fn = query_fn
        self._stats_fn = stats_fn
        self._topics_fn = topics_fn
        self._link_entities_fn = link_entities_fn

    @property
    def _graph(self) -> Any:
        """Return the current KnowledgeGraph (or None if not built)."""
        return self._graph_fn()

    def _retracted_cores(self) -> set[str]:
        """Return set of core_ids that have been retracted by a later revision."""
        return self.store.retracted_core_ids()

    # ---- Data Exploration & Interactive Review ----

    def profile(self) -> dict[str, Any]:
        """Generate a comprehensive corpus profile for interactive exploration.

        Returns a structured overview of the corpus that lets users understand
        their data: what topics exist, how sources distribute, where potential
        quality issues are, and what entities were discovered.

        Must be called AFTER build_graph().

        Returns:
            Dict with:
              - summary: basic stats (chunks, sources, clusters, edges)
              - clusters: list of cluster profiles (id, size, labels, sources, samples)
              - sources: per-source stats (chunk count, clusters covered, topics)
              - boilerplate: detected boilerplate patterns and their frequency
              - quality_flags: list of potential quality issues detected
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        retracted_cores = self._retracted_cores()
        n_chunks = sum(1 for rev in self.store.revisions.values()
                       if rev.status == "asserted" and rev.core_id not in retracted_cores)
        rev_to_cluster = getattr(self._graph, '_revision_cluster', {})

        # ---- Source analysis ----
        source_chunks: dict[str, list[str]] = {}  # source -> [revision_ids]
        source_clusters: dict[str, set[int]] = {}  # source -> {cluster_ids}
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            source_chunks.setdefault(source, []).append(rid)
            cid = rev_to_cluster.get(rid)
            if cid is not None:
                source_clusters.setdefault(source, set()).add(cid)

        n_sources = len(source_chunks)

        # ---- Cluster profiles ----
        cluster_profiles = []
        clusters = getattr(self._graph, '_clusters', {})
        cluster_labels = getattr(self._graph, '_cluster_labels', {})

        for cid, members in sorted(clusters.items()):
            # Filter to active members only
            active_members = [
                rid for rid in members
                if (rev := self.store.revisions.get(rid)) is not None
                and rev.core_id not in retracted_cores
            ]

            # Source distribution within this cluster
            cluster_sources: Counter = Counter()
            for rid in active_members:
                core = self.store.cores.get(
                    self.store.revisions[rid].core_id
                )
                source = core.slots.get("source", "?") if core else "?"
                cluster_sources[source] += 1

            # Sample chunks (first 3)
            samples = []
            for rid in active_members[:3]:
                rev = self.store.revisions.get(rid)
                if rev:
                    samples.append({
                        "revision_id": rid,
                        "text": rev.assertion[:200],
                    })

            # Quality flags for this cluster
            flags = []
            if len(cluster_sources) == 1:
                flags.append("single_source")
            if cluster_sources:
                dominant_source, dominant_count = cluster_sources.most_common(1)[0]
                if dominant_count / max(len(active_members), 1) > 0.8:
                    flags.append(f"dominated_by:{dominant_source[:30]}")

            cluster_profiles.append({
                "cluster_id": cid,
                "size": len(active_members),
                "labels": cluster_labels.get(cid, [])[:6],
                "source_count": len(cluster_sources),
                "top_sources": cluster_sources.most_common(3),
                "samples": samples,
                "flags": flags,
            })

        # Sort by size descending
        cluster_profiles.sort(key=lambda c: -c["size"])

        # ---- Boilerplate detection ----
        sentence_doc_freq: Counter = Counter()
        sentence_text: dict[str, str] = {}  # hash -> sentence text
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", rid) if core else rid
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            seen_hashes: set[str] = set()
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.strip())
                if len(normed) < 20:
                    continue
                h = hashlib.md5(normed.lower().encode()).hexdigest()[:16]
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    sentence_doc_freq[h] += 1
                    if h not in sentence_text:
                        sentence_text[h] = normed[:120]

        # Top repeated sentences (likely boilerplate)
        boilerplate_candidates = [
            {"text": sentence_text[h], "frequency": freq, "hash": h}
            for h, freq in sentence_doc_freq.most_common(20)
            if freq >= max(3, n_sources // 10)
        ]

        # ---- Quality flags ----
        quality_flags = []
        if n_sources < 3:
            quality_flags.append({
                "type": "low_source_diversity",
                "message": f"Only {n_sources} source documents. Cross-document linking may be limited.",
            })

        # Check for source dominance
        source_sizes = [(s, len(rids)) for s, rids in source_chunks.items()]
        source_sizes.sort(key=lambda x: -x[1])
        if source_sizes:
            top_source, top_count = source_sizes[0]
            if top_count / max(n_chunks, 1) > 0.3:
                quality_flags.append({
                    "type": "source_dominance",
                    "message": f"Source '{top_source[:40]}' contains {top_count}/{n_chunks} chunks ({top_count*100//n_chunks}%). Consider balancing.",
                })

        # Check for boilerplate prevalence
        if len(boilerplate_candidates) > 5:
            total_bp_freq = sum(b["frequency"] for b in boilerplate_candidates)
            quality_flags.append({
                "type": "high_boilerplate",
                "message": f"{len(boilerplate_candidates)} repeated sentences detected (total {total_bp_freq} occurrences). Consider reviewing.",
            })

        # Check for single-source clusters
        single_source_clusters = sum(1 for c in cluster_profiles if "single_source" in c["flags"])
        if single_source_clusters > len(cluster_profiles) // 3:
            quality_flags.append({
                "type": "isolated_clusters",
                "message": f"{single_source_clusters}/{len(cluster_profiles)} clusters have content from a single source.",
            })

        # ---- Source stats ----
        source_stats = []
        for source, rids in sorted(source_chunks.items(), key=lambda x: -len(x[1])):
            source_stats.append({
                "source": source,
                "chunks": len(rids),
                "clusters": len(source_clusters.get(source, set())),
                "fraction": len(rids) / max(n_chunks, 1),
            })

        return {
            "summary": {
                "chunks": n_chunks,
                "sources": n_sources,
                "clusters": len(clusters),
                "edges": sum(len(adj) for adj in self._graph._adjacency.values()),
            },
            "clusters": cluster_profiles,
            "sources": source_stats[:20],  # Top 20 sources
            "boilerplate": boilerplate_candidates,
            "quality_flags": quality_flags,
        }

    def render_profile(self, profile: dict[str, Any] | None = None) -> str:
        """Render a corpus profile as readable text.

        Args:
            profile: Output from profile(). If None, calls profile().

        Returns:
            Formatted text summary.
        """
        if profile is None:
            profile = self.profile()

        lines: list[str] = []
        s = profile["summary"]
        lines.append(f"=== Corpus Profile ===")
        lines.append(f"Chunks: {s['chunks']:,}  |  Sources: {s['sources']}  |  "
                     f"Clusters: {s['clusters']}  |  Edges: {s['edges']:,}")

        # Quality flags
        flags = profile.get("quality_flags", [])
        if flags:
            lines.append(f"\n--- Quality Flags ({len(flags)}) ---")
            for f in flags:
                lines.append(f"  [{f['type']}] {f['message']}")

        # Top clusters
        lines.append(f"\n--- Top Clusters ---")
        for c in profile["clusters"][:10]:
            labels = ", ".join(c["labels"][:4])
            flags_str = f"  [{', '.join(c['flags'])}]" if c["flags"] else ""
            lines.append(f"  Cluster {c['cluster_id']}: {c['size']} chunks, "
                        f"{c['source_count']} sources  |  {labels}{flags_str}")

        # Top sources
        lines.append(f"\n--- Top Sources ---")
        for src in profile["sources"][:10]:
            lines.append(f"  {src['source'][:50]:50s}  {src['chunks']:4d} chunks  "
                        f"{src['clusters']:2d} clusters  ({src['fraction']*100:.1f}%)")

        # Boilerplate
        bp = profile.get("boilerplate", [])
        if bp:
            lines.append(f"\n--- Detected Boilerplate ({len(bp)} patterns) ---")
            for b in bp[:5]:
                lines.append(f"  [{b['frequency']}x] {b['text'][:80]}...")

        return "\n".join(lines)

    def delete_cluster(
        self,
        cluster_id: int,
        *,
        reason: str = "User deleted cluster via interactive review",
    ) -> dict[str, Any]:
        """Delete all chunks in a cluster by retracting their revisions.

        This is a soft delete — the data remains in the store as retracted
        revisions, preserving the full audit trail. The chunks will no longer
        appear in search results or entity linking.

        Note: After calling this method, you should call ``rebuild_index()``
        on the Pipeline to ensure the search index reflects the retracted
        content. The graph is updated automatically via ``remove_cluster()``.

        Args:
            cluster_id: The cluster to delete.
            reason: Reason for deletion (stored in retraction metadata).

        Returns:
            Dict with retracted_count and affected_sources.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        clusters = getattr(self._graph, '_clusters', {})
        members = clusters.get(cluster_id, [])
        if not members:
            return {"retracted_count": 0, "affected_sources": []}

        # Retract each revision in the cluster
        retracted = 0
        affected_sources: set[str] = set()
        tx_time = self._tx_factory()

        from .core import Provenance as _P

        for rid in members:
            rev = self.store.revisions.get(rid)
            if rev and rev.status == "asserted":
                core = self.store.cores.get(rev.core_id)
                source = core.slots.get("source", "?") if core else "?"
                affected_sources.add(source)

                self.store.assert_revision(
                    core=core,
                    assertion=rev.assertion,
                    valid_time=rev.valid_time,
                    transaction_time=tx_time,
                    provenance=_P(source="cluster_delete", evidence_ref=reason),
                    confidence_bp=rev.confidence_bp,
                    status="retracted",
                )
                retracted += 1

        # Remove from graph via public API
        self._graph.remove_cluster(cluster_id)

        return {
            "retracted_count": retracted,
            "affected_sources": sorted(affected_sources),
            "reason": reason,
        }

    def review_entities(
        self,
        *,
        top_k: int = 50,
    ) -> dict[str, Any]:
        """Analyze entities for interactive review.

        Runs entity extraction (same method as link_entities) and categorizes
        entities into quality tiers based on source diversity and cluster spread:
        - high: appears across many sources and clusters (likely real domain term)
        - medium: moderate spread, may need review
        - flagged: concentrated in few sources or clusters (likely boilerplate)

        Must be called AFTER build_graph().

        Args:
            top_k: Number of top entities to analyze.

        Returns:
            Dict with high/medium/flagged entity lists, each entry containing
            the entity text, frequency, source count, cluster count, and
            a quality_score (0-100).
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        # Run link_entities to get the statistically-filtered entities
        link_result = self._link_entities_fn(min_shared_entities=1)
        top_entities = link_result.get("top_entities", [])

        retracted_cores = self._retracted_cores()
        rev_to_cluster = getattr(self._graph, '_revision_cluster', {})
        n_chunks = sum(1 for rev in self.store.revisions.values()
                       if rev.status == "asserted" and rev.core_id not in retracted_cores)

        # Compute total sources
        all_sources: set[str] = set()
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            all_sources.add(source)
        n_sources_total = len(all_sources)
        n_clusters_total = len(set(rev_to_cluster.values())) if rev_to_cluster else 1

        # For each top entity, compute quality metrics
        word_re = re.compile(r'\b([a-z]{3,})\b')

        # Build entity -> revisions map using same approach as link_entities
        entity_revisions: dict[str, set[str]] = {}
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            tokens = word_re.findall(rev.assertion.lower())
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                entity_revisions.setdefault(bg, set()).add(rid)
            for t in set(tokens):
                entity_revisions.setdefault(t, set()).add(rid)

        entities_analyzed = []
        for entity, freq in top_entities[:top_k]:
            rids = entity_revisions.get(entity, set())

            # Source and cluster diversity
            sources: set[str] = set()
            clusters: set[int] = set()
            for rid in rids:
                rev = self.store.revisions.get(rid)
                if rev:
                    core = self.store.cores.get(rev.core_id)
                    source = core.slots.get("source", "?") if core else "?"
                    sources.add(source)
                cid = rev_to_cluster.get(rid)
                if cid is not None:
                    clusters.add(cid)

            # Quality score (0-100):
            # Source diversity (0-40): % of total sources containing entity
            source_frac = len(sources) / max(n_sources_total, 1)
            source_score = min(40, int(40 * min(source_frac / 0.05, 1)))

            # Cluster diversity (0-40): % of total clusters containing entity
            cluster_frac = len(clusters) / max(n_clusters_total, 1)
            cluster_score = min(40, int(40 * min(cluster_frac / 0.1, 1)))

            # Frequency (0-20): moderate frequency is optimal (~0.5-3% of corpus)
            freq_ratio = len(rids) / max(n_chunks, 1)
            if freq_ratio < 0.002:
                freq_score = 10
            elif freq_ratio <= 0.03:
                freq_score = 20  # Sweet spot
            elif freq_ratio <= 0.05:
                freq_score = 10
            elif freq_ratio <= 0.10:
                freq_score = 0
            else:
                freq_score = -20  # Very ubiquitous = penalty

            quality = source_score + cluster_score + freq_score

            entities_analyzed.append({
                "entity": entity,
                "frequency": freq,
                "source_count": len(sources),
                "cluster_count": len(clusters),
                "quality_score": quality,
            })

        # Categorize
        high = [e for e in entities_analyzed if e["quality_score"] >= 60]
        medium = [e for e in entities_analyzed if 30 <= e["quality_score"] < 60]
        flagged = [e for e in entities_analyzed if e["quality_score"] < 30]

        return {
            "high": high,
            "medium": medium,
            "flagged": flagged,
            "total_analyzed": len(entities_analyzed),
        }

    def accept_entities(
        self,
        entities: list[str],
        *,
        reason: str = "User accepted via interactive review",
    ) -> int:
        """Accept entities as valid domain terms.

        Stores acceptance decisions as claims in the KnowledgeStore,
        making them persistent and auditable.

        Args:
            entities: List of entity strings to accept.
            reason: Reason for acceptance.

        Returns:
            Number of entity decisions stored.
        """
        from .core import ClaimCore as _CC, Provenance as _P
        from .core import ValidTime as _VT
        from datetime import datetime as _dt

        now = _dt.now(timezone.utc)
        tx = self._tx_factory()
        count = 0

        for entity in entities:
            core = _CC(
                claim_type="dks.entity_review@v1",
                slots={"entity": entity, "decision": "accepted"},
            )
            self.store.assert_revision(
                core=core,
                assertion=f"Entity '{entity}' accepted: {reason}",
                valid_time=_VT(start=now, end=None),
                transaction_time=tx,
                provenance=_P(source="interactive_review"),
                confidence_bp=9000,
            )
            count += 1

        return count

    def reject_entities(
        self,
        entities: list[str],
        *,
        reason: str = "User rejected via interactive review",
    ) -> int:
        """Reject entities as noise/boilerplate.

        Stores rejection decisions as claims in the KnowledgeStore,
        making them persistent and auditable. Rejected entities will
        be excluded from future entity linking.

        Args:
            entities: List of entity strings to reject.
            reason: Reason for rejection.

        Returns:
            Number of entity decisions stored.
        """
        from .core import ClaimCore as _CC, Provenance as _P
        from .core import ValidTime as _VT
        from datetime import datetime as _dt

        now = _dt.now(timezone.utc)
        tx = self._tx_factory()
        count = 0

        for entity in entities:
            core = _CC(
                claim_type="dks.entity_review@v1",
                slots={"entity": entity, "decision": "rejected"},
            )
            self.store.assert_revision(
                core=core,
                assertion=f"Entity '{entity}' rejected: {reason}",
                valid_time=_VT(start=now, end=None),
                transaction_time=tx,
                provenance=_P(source="interactive_review"),
                confidence_bp=9000,
            )
            count += 1

        return count

    def get_entity_decisions(self) -> dict[str, str]:
        """Retrieve all entity review decisions.

        Returns:
            Dict mapping entity -> "accepted" or "rejected".
        """
        retracted = self.store.retracted_core_ids()
        decisions: dict[str, str] = {}
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted" or rev.core_id in retracted:
                continue
            core = self.store.cores.get(rev.core_id)
            if core and core.claim_type == "dks.entity_review@v1":
                entity = core.slots.get("entity", "")
                decision = core.slots.get("decision", "")
                if entity and decision:
                    decisions[entity] = decision
        return decisions

    # ---- Source Management ----

    def source_detail(self, source: str) -> dict[str, Any]:
        """Get detailed statistics for a specific source document.

        Args:
            source: The source identifier (e.g. filename).

        Returns:
            Dict with chunk_count, clusters (with sizes), entities found,
            page_range, avg_chunk_length, and quality_flags.
        """
        retracted_cores = self._retracted_cores()
        chunks: list[dict[str, Any]] = []
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.slots.get("source") != source:
                continue
            chunks.append({
                "revision_id": rid,
                "core_id": rev.core_id,
                "text": rev.assertion,
                "page": core.slots.get("page_start"),
                "confidence_bp": rev.confidence_bp,
            })

        if not chunks:
            return {"source": source, "chunk_count": 0, "found": False}

        # Cluster distribution
        cluster_dist: dict[int, int] = {}
        rev_cluster = {}
        if self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})
        for c in chunks:
            cid = rev_cluster.get(c["revision_id"])
            if cid is not None:
                cluster_dist[cid] = cluster_dist.get(cid, 0) + 1

        # Text stats
        lengths = [len(c["text"]) for c in chunks]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
        pages = sorted({c["page"] for c in chunks if c["page"] is not None})

        # Quality flags
        quality_flags: list[str] = []
        short_chunks = sum(1 for l in lengths if l < 100)
        if short_chunks > len(chunks) * 0.3:
            quality_flags.append("many_short_chunks")
        if len(cluster_dist) == 1:
            quality_flags.append("single_cluster")

        return {
            "source": source,
            "found": True,
            "chunk_count": len(chunks),
            "cluster_distribution": cluster_dist,
            "page_range": f"{min(pages)}-{max(pages)}" if pages else None,
            "total_pages": len(pages),
            "avg_chunk_length": round(avg_len),
            "shortest_chunk": min(lengths) if lengths else 0,
            "longest_chunk": max(lengths) if lengths else 0,
            "quality_flags": quality_flags,
        }

    def delete_source(
        self,
        source: str,
        *,
        reason: str = "User deleted source via interactive review",
    ) -> dict[str, Any]:
        """Delete all chunks from a source by retracting their revisions.

        Soft delete — data remains as retracted revisions for audit trail.

        Args:
            source: The source identifier to delete.
            reason: Reason for deletion.

        Returns:
            Dict with retracted_count.
        """
        from .core import Provenance as _P

        tx_time = self._tx_factory()
        retracted = 0

        for rid, rev in list(self.store.revisions.items()):
            if rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.slots.get("source") != source:
                continue

            self.store.assert_revision(
                core=core,
                assertion=rev.assertion,
                valid_time=rev.valid_time,
                transaction_time=tx_time,
                provenance=_P(source="source_delete", evidence_ref=reason),
                confidence_bp=rev.confidence_bp,
                status="retracted",
            )
            retracted += 1

        return {
            "source": source,
            "retracted_count": retracted,
            "reason": reason,
        }

    # ---- Chunk Browsing ----

    def browse_cluster(
        self,
        cluster_id: int,
        *,
        limit: int = 20,
        preview_length: int = 200,
    ) -> dict[str, Any]:
        """Browse chunks within a specific cluster.

        Args:
            cluster_id: The cluster to browse.
            limit: Max chunks to return.
            preview_length: Text preview truncation length.

        Returns:
            Dict with cluster_id, chunk_count, and list of chunk previews.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        clusters = getattr(self._graph, '_clusters', {})
        members = clusters.get(cluster_id, [])
        retracted_cores = self._retracted_cores()

        chunks: list[dict[str, Any]] = []
        for rid in members[:limit]:
            rev = self.store.revisions.get(rid)
            if rev is None:
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            text = rev.assertion
            chunks.append({
                "revision_id": rid,
                "source": source,
                "preview": text[:preview_length] + ("..." if len(text) > preview_length else ""),
                "length": len(text),
                "status": rev.status,
            })

        # Count active members (excluding retracted) for accurate total
        active_count = sum(
            1 for rid in members
            if (rev := self.store.revisions.get(rid)) is not None
            and rev.core_id not in retracted_cores
        )

        return {
            "cluster_id": cluster_id,
            "total_members": active_count,
            "showing": len(chunks),
            "chunks": chunks,
        }

    def browse_source(
        self,
        source: str,
        *,
        limit: int = 20,
        preview_length: int = 200,
    ) -> dict[str, Any]:
        """Browse chunks from a specific source document.

        Args:
            source: The source identifier.
            limit: Max chunks to return.
            preview_length: Text preview truncation length.

        Returns:
            Dict with source, chunk_count, and list of chunk previews.
        """
        retracted_cores = self._retracted_cores()
        chunks: list[dict[str, Any]] = []
        rev_cluster = {}
        if self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None or core.slots.get("source") != source:
                continue

            text = rev.assertion
            page = core.slots.get("page_start")
            chunks.append({
                "revision_id": rid,
                "page": page,
                "cluster_id": rev_cluster.get(rid),
                "preview": text[:preview_length] + ("..." if len(text) > preview_length else ""),
                "length": len(text),
            })

            if len(chunks) >= limit:
                break

        total = sum(
            1 for rid, rev in self.store.revisions.items()
            if rev.status == "asserted"
            and rev.core_id not in retracted_cores
            and self.store.cores.get(rev.core_id)
            and self.store.cores.get(rev.core_id).slots.get("source") == source
        )

        return {
            "source": source,
            "total_chunks": total,
            "showing": len(chunks),
            "chunks": chunks,
        }

    def chunk_detail(self, revision_id: str) -> dict[str, Any]:
        """Get full details of a single chunk.

        Args:
            revision_id: The revision ID to inspect.

        Returns:
            Dict with full text, metadata, cluster info, and neighbors.
        """
        rev = self.store.revisions.get(revision_id)
        if rev is None:
            return {"revision_id": revision_id, "found": False}

        core = self.store.cores.get(rev.core_id)
        source = core.slots.get("source", "?") if core else "?"

        # Cluster info
        cluster_id = None
        if self._graph is not None:
            rev_cluster = getattr(self._graph, '_revision_cluster', {})
            cluster_id = rev_cluster.get(revision_id)

        # Neighbors from graph
        neighbor_previews: list[dict[str, Any]] = []
        if self._graph is not None:
            adj = self._graph._adjacency.get(revision_id, [])
            for nid, weight in sorted(adj, key=lambda x: -x[1])[:5]:
                n_rev = self.store.revisions.get(nid)
                if n_rev is None:
                    continue
                n_core = self.store.cores.get(n_rev.core_id)
                n_source = n_core.slots.get("source", "?") if n_core else "?"
                neighbor_previews.append({
                    "revision_id": nid,
                    "source": n_source,
                    "weight": round(weight, 4),
                    "preview": n_rev.assertion[:150],
                })

        return {
            "revision_id": revision_id,
            "found": True,
            "core_id": rev.core_id,
            "source": source,
            "text": rev.assertion,
            "length": len(rev.assertion),
            "status": rev.status,
            "confidence_bp": rev.confidence_bp,
            "cluster_id": cluster_id,
            "page": core.slots.get("page_start") if core else None,
            "slots": dict(core.slots) if core else {},
            "neighbors": neighbor_previews,
            "valid_time": {
                "start": rev.valid_time.start.isoformat() if rev.valid_time.start else None,
                "end": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
            },
        }

    # ---- Quality Report ----

    def quality_report(self) -> dict[str, Any]:
        """Generate a comprehensive corpus quality report with automated issue detection.

        Scans the entire corpus for quality issues and returns a structured
        report with actionable suggestions. No external dependencies required.

        Returns:
            Dict with sections: summary, issues (list), per_source stats,
            and recommendations.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        issues: list[dict[str, Any]] = []
        rev_cluster = getattr(self._graph, '_revision_cluster', {})
        clusters = getattr(self._graph, '_clusters', {})
        retracted_cores = self._retracted_cores()

        # Collect per-source and per-chunk data
        source_chunks: dict[str, list[str]] = {}
        chunk_lengths: dict[str, int] = {}
        orphan_chunks: list[str] = []

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            ct = core.claim_type
            if ct != "document.chunk@v1" and not ct.startswith("dks."):
                continue
            if ct.startswith("dks."):
                continue  # Skip internal claims (entity reviews, etc.)

            source = core.slots.get("source", "unknown")
            source_chunks.setdefault(source, []).append(rid)
            chunk_lengths[rid] = len(rev.assertion)

            if rid not in rev_cluster:
                orphan_chunks.append(rid)

        total_chunks = len(chunk_lengths)
        if total_chunks == 0:
            return {
                "summary": {"total_chunks": 0, "total_sources": 0, "issues": 0},
                "issues": [],
                "per_source": {},
                "recommendations": [],
            }

        # Issue 1: Very short chunks (< 50 chars)
        short_threshold = 50
        short_chunks = [
            rid for rid, l in chunk_lengths.items() if l < short_threshold
        ]
        if short_chunks:
            issues.append({
                "type": "short_chunks",
                "severity": "warning",
                "count": len(short_chunks),
                "description": f"{len(short_chunks)} chunks under {short_threshold} characters",
                "suggestion": "Review short chunks — they may be headers, footers, or incomplete extractions",
                "examples": short_chunks[:5],
            })

        # Issue 2: Very long chunks (> 2000 chars)
        long_threshold = 2000
        long_chunks = [
            rid for rid, l in chunk_lengths.items() if l > long_threshold
        ]
        if long_chunks:
            issues.append({
                "type": "long_chunks",
                "severity": "info",
                "count": len(long_chunks),
                "description": f"{len(long_chunks)} chunks over {long_threshold} characters",
                "suggestion": "Long chunks may reduce search precision — consider re-chunking",
                "examples": long_chunks[:5],
            })

        # Issue 3: Orphan chunks (not assigned to any cluster)
        if orphan_chunks:
            issues.append({
                "type": "orphan_chunks",
                "severity": "info",
                "count": len(orphan_chunks),
                "description": f"{len(orphan_chunks)} chunks not assigned to any cluster",
                "suggestion": "Rebuild graph or inspect orphan content",
                "examples": orphan_chunks[:5],
            })

        # Issue 4: Single-source clusters
        single_source_clusters: list[int] = []
        for cid, members in clusters.items():
            sources_in_cluster = set()
            for rid in members:
                rev = self.store.revisions.get(rid)
                if rev is None or rev.core_id in retracted_cores:
                    continue
                core = self.store.cores.get(rev.core_id)
                if core:
                    sources_in_cluster.add(core.slots.get("source", "?"))
            if len(sources_in_cluster) == 1:
                single_source_clusters.append(cid)

        if single_source_clusters:
            issues.append({
                "type": "single_source_clusters",
                "severity": "info",
                "count": len(single_source_clusters),
                "description": f"{len(single_source_clusters)}/{len(clusters)} clusters draw from only one source",
                "suggestion": "Single-source clusters may indicate unique content or poor inter-document linking",
                "cluster_ids": single_source_clusters,
            })

        # Issue 5: Source imbalance (one source has > 50% of chunks)
        for source, rids in source_chunks.items():
            fraction = len(rids) / total_chunks
            if fraction > 0.5 and len(source_chunks) > 1:
                issues.append({
                    "type": "source_imbalance",
                    "severity": "warning",
                    "source": source,
                    "fraction": round(fraction, 3),
                    "description": f"'{source}' contains {fraction:.0%} of all chunks",
                    "suggestion": "Dominant source may bias search results — consider balancing corpus",
                })

        # Issue 6: Low-confidence chunks
        low_conf_threshold = 3000
        low_conf = [
            rid for rid in chunk_lengths
            if self.store.revisions[rid].confidence_bp < low_conf_threshold
        ]
        if low_conf:
            issues.append({
                "type": "low_confidence",
                "severity": "warning",
                "count": len(low_conf),
                "description": f"{len(low_conf)} chunks with confidence below {low_conf_threshold}bp",
                "suggestion": "Review low-confidence chunks for extraction quality",
                "examples": low_conf[:5],
            })

        # Per-source stats
        per_source: dict[str, dict[str, Any]] = {}
        for source, rids in source_chunks.items():
            lengths = [chunk_lengths[r] for r in rids]
            per_source[source] = {
                "chunks": len(rids),
                "avg_length": round(sum(lengths) / len(lengths)),
                "min_length": min(lengths),
                "max_length": max(lengths),
                "clusters": len({rev_cluster.get(r) for r in rids if r in rev_cluster}),
            }

        # Generate recommendations
        recommendations: list[str] = []
        severity_counts = {"warning": 0, "info": 0}
        for issue in issues:
            severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1

        if severity_counts["warning"] == 0:
            recommendations.append("Corpus quality looks good — no warnings detected")
        if severity_counts["warning"] > 3:
            recommendations.append("Multiple warnings — consider a cleanup pass before querying")
        if len(source_chunks) == 1:
            recommendations.append("Single-source corpus — consider adding more sources for richer cross-referencing")

        return {
            "summary": {
                "total_chunks": total_chunks,
                "total_sources": len(source_chunks),
                "total_clusters": len(clusters),
                "issues": len(issues),
                "warnings": severity_counts.get("warning", 0),
            },
            "issues": issues,
            "per_source": per_source,
            "recommendations": recommendations,
        }

    def render_quality_report(self, report: dict[str, Any] | None = None) -> str:
        """Render a quality report as human-readable text.

        Args:
            report: Output from quality_report(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if report is None:
            report = self.quality_report()

        lines: list[str] = []
        s = report["summary"]
        lines.append("=" * 60)
        lines.append("  CORPUS QUALITY REPORT")
        lines.append("=" * 60)
        lines.append(f"  Chunks: {s['total_chunks']}  |  Sources: {s['total_sources']}  |  Clusters: {s['total_clusters']}")
        lines.append(f"  Issues: {s['issues']} ({s['warnings']} warnings)")
        lines.append("")

        if report["issues"]:
            lines.append("  ISSUES:")
            lines.append("-" * 60)
            for issue in report["issues"]:
                icon = "!!" if issue["severity"] == "warning" else ".."
                lines.append(f"  [{icon}] {issue['description']}")
                lines.append(f"       -> {issue['suggestion']}")
                lines.append("")
        else:
            lines.append("  No issues detected.")
            lines.append("")

        if report["per_source"]:
            lines.append("  PER-SOURCE STATS:")
            lines.append("-" * 60)
            for source, stats in sorted(
                report["per_source"].items(), key=lambda x: -x[1]["chunks"]
            ):
                name = source[:45]
                lines.append(
                    f"  {name:<45s} {stats['chunks']:4d} chunks  "
                    f"avg {stats['avg_length']:4d} chars  "
                    f"{stats['clusters']} clusters"
                )
            lines.append("")

        if report["recommendations"]:
            lines.append("  RECOMMENDATIONS:")
            lines.append("-" * 60)
            for rec in report["recommendations"]:
                lines.append(f"  - {rec}")
            lines.append("")

        return "\n".join(lines)

    def render_browse(self, result: dict[str, Any]) -> str:
        """Render browse_cluster or browse_source result as human-readable text.

        Args:
            result: Output from browse_cluster() or browse_source().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []

        if "cluster_id" in result:
            lines.append(f"  Cluster {result['cluster_id']}: {result['total_members']} chunks (showing {result['showing']})")
        else:
            lines.append(f"  Source: {result['source']} — {result['total_chunks']} chunks (showing {result['showing']})")

        lines.append("-" * 60)

        for i, chunk in enumerate(result.get("chunks", []), 1):
            source = chunk.get("source", "")
            page = chunk.get("page", "")
            page_str = f" p.{page}" if page else ""
            cluster = chunk.get("cluster_id")
            cluster_str = f" [c{cluster}]" if cluster is not None else ""
            lines.append(f"  {i}. {source}{page_str}{cluster_str} ({chunk['length']} chars)")
            lines.append(f"     {chunk['preview']}")
            lines.append("")

        return "\n".join(lines)

    def render_chunk_detail(self, detail: dict[str, Any]) -> str:
        """Render chunk_detail result as human-readable text.

        Args:
            detail: Output from chunk_detail().

        Returns:
            Formatted text string.
        """
        if not detail.get("found"):
            return f"  Chunk {detail['revision_id']}: not found"

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"  CHUNK DETAIL: {detail['revision_id'][:40]}")
        lines.append("=" * 60)
        lines.append(f"  Source:     {detail['source']}")
        lines.append(f"  Status:    {detail['status']}")
        lines.append(f"  Length:    {detail['length']} chars")
        lines.append(f"  Cluster:   {detail.get('cluster_id', 'N/A')}")
        lines.append(f"  Confidence: {detail['confidence_bp']}bp")

        if detail.get("page"):
            lines.append(f"  Page:      {detail['page']}")

        lines.append("")
        lines.append("  TEXT:")
        lines.append("-" * 60)
        lines.append(f"  {detail['text']}")
        lines.append("")

        if detail.get("neighbors"):
            lines.append(f"  NEIGHBORS ({len(detail['neighbors'])}):")
            lines.append("-" * 60)
            for n in detail["neighbors"]:
                lines.append(f"  [{n['weight']:.4f}] {n['source']}")
                lines.append(f"    {n['preview'][:120]}...")
                lines.append("")

        return "\n".join(lines)

    # ---- Temporal Analysis ----

    def ingestion_timeline(self) -> list[dict[str, Any]]:
        """Show when knowledge was added over time (ingestion timeline).

        Returns a chronological list of ingestion events grouped by
        transaction time, showing what was added and from which source.

        Returns:
            List of dicts with tx_id, timestamp, source, chunk_count.
        """
        tx_groups: dict[int, dict[str, Any]] = {}
        retracted_cores = self._retracted_cores()

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            ct = core.claim_type
            if ct.startswith("dks."):
                continue  # Skip internal claims

            tx_id = rev.transaction_time.tx_id
            if tx_id not in tx_groups:
                tx_groups[tx_id] = {
                    "tx_id": tx_id,
                    "timestamp": rev.transaction_time.recorded_at,
                    "sources": {},
                    "chunk_count": 0,
                }

            source = core.slots.get("source", "unknown")
            tx_groups[tx_id]["sources"][source] = (
                tx_groups[tx_id]["sources"].get(source, 0) + 1
            )
            tx_groups[tx_id]["chunk_count"] += 1

        result = []
        for info in sorted(tx_groups.values(), key=lambda x: x["timestamp"]):
            result.append({
                "tx_id": info["tx_id"],
                "timestamp": info["timestamp"].isoformat(),
                "sources": dict(info["sources"]),
                "chunk_count": info["chunk_count"],
            })

        return result

    def scan_contradictions(self, *, k: int = 10, threshold: float = 0.6) -> list[dict[str, Any]]:
        """Scan entire corpus for claims that potentially contradict each other.

        Unlike contradictions(topic), this scans all chunks without a topic filter.
        Uses search similarity to find related chunks, then checks for
        negation patterns and opposing assertions. Works purely with
        text heuristics (no LLM required).

        Args:
            k: Number of candidate pairs to evaluate.
            threshold: Minimum similarity to consider as related.

        Returns:
            List of contradiction pairs with evidence.
        """
        # Negation signals that suggest contradiction
        negation_markers = {
            "not", "no", "never", "neither", "nor", "cannot", "can't",
            "don't", "doesn't", "didn't", "won't", "wouldn't", "isn't",
            "aren't", "wasn't", "weren't", "hardly", "rarely", "seldom",
            "without", "lack", "fail", "false", "incorrect", "wrong",
            "unlike", "contrary", "however", "but", "although", "despite",
            "rather than", "instead of", "on the other hand",
        }

        contrast_phrases = {
            "in contrast", "on the contrary", "conversely", "whereas",
            "while others", "some argue", "critics", "challenged",
            "disputed", "debated", "controversial", "disagree",
        }

        results: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        retracted_cores = self._retracted_cores()

        # Get all asserted document chunks
        doc_revisions = []
        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.claim_type.startswith("dks."):
                continue
            doc_revisions.append((rid, rev))

        # For each chunk, search for related chunks from different sources
        for rid, rev in doc_revisions:
            if len(results) >= k:
                break

            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "") if core else ""

            # Search for similar content
            search_results = self._query_fn(rev.assertion[:200], k=5)

            for sr in search_results:
                if sr.revision_id == rid:
                    continue
                if sr.score < threshold:
                    continue

                # Get candidate
                cand_rev = self.store.revisions.get(sr.revision_id)
                if cand_rev is None:
                    continue
                cand_core = self.store.cores.get(cand_rev.core_id)
                cand_source = cand_core.slots.get("source", "") if cand_core else ""

                # Skip same-source pairs
                if source == cand_source:
                    continue

                pair_key = tuple(sorted([rid, sr.revision_id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Check for negation asymmetry
                text_a = rev.assertion.lower()
                text_b = cand_rev.assertion.lower()

                neg_a = sum(1 for m in negation_markers if m in text_a)
                neg_b = sum(1 for m in negation_markers if m in text_b)
                negation_diff = abs(neg_a - neg_b)

                contrast_a = sum(1 for p in contrast_phrases if p in text_a)
                contrast_b = sum(1 for p in contrast_phrases if p in text_b)

                # Score the contradiction likelihood
                score = 0.0
                evidence: list[str] = []

                if negation_diff >= 2:
                    score += 0.4
                    evidence.append(f"Negation asymmetry ({neg_a} vs {neg_b})")
                elif negation_diff == 1:
                    score += 0.2
                    evidence.append("Mild negation difference")

                if contrast_a + contrast_b > 0:
                    score += 0.3
                    evidence.append("Contains contrast language")

                # Different temporal context can indicate evolving understanding
                if rev.valid_time.start and cand_rev.valid_time.start:
                    time_gap = abs(
                        (rev.valid_time.start - cand_rev.valid_time.start).days
                    )
                    if time_gap > 365:
                        score += 0.1
                        evidence.append(f"Published {time_gap // 365}+ years apart")

                if score >= 0.2:
                    results.append({
                        "chunk_a": {
                            "revision_id": rid,
                            "source": source,
                            "text": rev.assertion[:300],
                        },
                        "chunk_b": {
                            "revision_id": sr.revision_id,
                            "source": cand_source,
                            "text": cand_rev.assertion[:300],
                        },
                        "similarity": round(sr.score, 4),
                        "contradiction_score": round(score, 3),
                        "evidence": evidence,
                    })

        # Sort by contradiction score
        results.sort(key=lambda x: -x["contradiction_score"])
        return results[:k]

    def evolution(self, topic: str, *, k: int = 20) -> dict[str, Any]:
        """Show how understanding of a topic has changed across documents.

        Retrieves chunks related to the topic and organizes them by
        temporal order, showing the progression of knowledge.

        Args:
            topic: The topic to trace evolution for.
            k: Max chunks to retrieve.

        Returns:
            Dict with topic, timeline of chunks ordered by valid_time,
            and source diversity info.
        """
        search_results = self._query_fn(topic, k=k)

        entries: list[dict[str, Any]] = []
        sources_seen: set[str] = set()

        for sr in search_results:
            rev = self.store.revisions.get(sr.revision_id)
            if rev is None or rev.status != "asserted":
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"
            sources_seen.add(source)

            entries.append({
                "revision_id": sr.revision_id,
                "source": source,
                "text": rev.assertion[:400],
                "score": round(sr.score, 4),
                "valid_start": rev.valid_time.start.isoformat() if rev.valid_time.start else None,
                "ingested_at": rev.transaction_time.recorded_at.isoformat(),
            })

        # Sort by valid_time (earliest first)
        entries.sort(
            key=lambda x: x["valid_start"] or "9999"
        )

        return {
            "topic": topic,
            "total_chunks": len(entries),
            "source_count": len(sources_seen),
            "sources": sorted(sources_seen),
            "timeline": entries,
        }

    def staleness_report(self, *, age_days: int = 365) -> dict[str, Any]:
        """Identify old claims that may need updating.

        Flags chunks whose valid_time start is older than the threshold,
        grouped by source.

        Args:
            age_days: Chunks older than this are flagged as stale.

        Returns:
            Dict with stale_count, by_source breakdown, and oldest chunks.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
        retracted_cores = self._retracted_cores()

        stale: list[dict[str, Any]] = []
        by_source: dict[str, int] = {}

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            if core.claim_type.startswith("dks."):
                continue

            vt_start = rev.valid_time.start
            if vt_start and vt_start.tzinfo is None:
                vt_start = vt_start.replace(tzinfo=timezone.utc)

            if vt_start and vt_start < cutoff:
                source = core.slots.get("source", "unknown")
                by_source[source] = by_source.get(source, 0) + 1
                stale.append({
                    "revision_id": rid,
                    "source": source,
                    "valid_start": vt_start.isoformat(),
                    "age_days": (datetime.now(timezone.utc) - vt_start).days,
                    "preview": rev.assertion[:150],
                })

        # Sort by age (oldest first)
        stale.sort(key=lambda x: -x["age_days"])

        return {
            "stale_count": len(stale),
            "threshold_days": age_days,
            "by_source": by_source,
            "oldest": stale[:20],
        }

    def render_timeline(self, timeline: list[dict[str, Any]] | None = None) -> str:
        """Render ingestion_timeline() output as human-readable text.

        Args:
            timeline: Output from ingestion_timeline(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if timeline is None:
            timeline = self.ingestion_timeline()

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  INGESTION TIMELINE")
        lines.append("=" * 60)

        for event in timeline:
            ts = event["timestamp"][:19]  # Trim to seconds
            sources = ", ".join(
                f"{s} ({c})" for s, c in event["sources"].items()
            )
            lines.append(f"  [{ts}] TX-{event['tx_id']}: {event['chunk_count']} chunks")
            lines.append(f"    Sources: {sources}")
            lines.append("")

        if not timeline:
            lines.append("  No ingestion events recorded.")

        return "\n".join(lines)

    def render_evolution(self, result: dict[str, Any]) -> str:
        """Render evolution() output as human-readable text.

        Args:
            result: Output from evolution().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"  TOPIC EVOLUTION: {result['topic']}")
        lines.append("=" * 60)
        lines.append(f"  {result['total_chunks']} chunks across {result['source_count']} sources")
        lines.append("")

        for entry in result["timeline"]:
            date = entry["valid_start"][:10] if entry["valid_start"] else "unknown"
            lines.append(f"  [{date}] {entry['source'][:40]} (score: {entry['score']})")
            lines.append(f"    {entry['text'][:150].replace(chr(10), ' ')}...")
            lines.append("")

        return "\n".join(lines)

    def render_contradictions(self, pairs: list[dict[str, Any]]) -> str:
        """Render contradictions() output as human-readable text.

        Args:
            pairs: Output from contradictions().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  POTENTIAL CONTRADICTIONS")
        lines.append("=" * 60)

        if not pairs:
            lines.append("  No contradictions detected.")
            return "\n".join(lines)

        for i, pair in enumerate(pairs, 1):
            lines.append(f"  #{i} (score: {pair['contradiction_score']}, similarity: {pair['similarity']})")
            lines.append(f"    Evidence: {', '.join(pair['evidence'])}")
            lines.append(f"    A [{pair['chunk_a']['source'][:30]}]:")
            lines.append(f"      {pair['chunk_a']['text'][:150].replace(chr(10), ' ')}...")
            lines.append(f"    B [{pair['chunk_b']['source'][:30]}]:")
            lines.append(f"      {pair['chunk_b']['text'][:150].replace(chr(10), ' ')}...")
            lines.append("")

        return "\n".join(lines)

    # ---- Source Comparison ----

    def compare_sources(
        self,
        source_a: str,
        source_b: str,
        *,
        similarity_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Compare two source documents for overlap and divergence.

        Analyzes shared topics, unique content, overlapping chunks,
        and potential contradictions between two sources.

        Args:
            source_a: First source identifier.
            source_b: Second source identifier.
            similarity_threshold: Min similarity to consider overlap.

        Returns:
            Dict with overlap_pairs, unique_to_a, unique_to_b,
            shared_topics, and comparison summary.
        """
        # Collect chunks per source
        retracted_cores = self._retracted_cores()
        chunks_a: list[tuple[str, str]] = []  # (rid, text)
        chunks_b: list[tuple[str, str]] = []

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue
            source = core.slots.get("source", "")
            if source == source_a:
                chunks_a.append((rid, rev.assertion))
            elif source == source_b:
                chunks_b.append((rid, rev.assertion))

        if not chunks_a or not chunks_b:
            return {
                "source_a": source_a,
                "source_b": source_b,
                "found_a": bool(chunks_a),
                "found_b": bool(chunks_b),
                "overlap_pairs": [],
                "unique_to_a": len(chunks_a),
                "unique_to_b": len(chunks_b),
                "similarity_summary": "Cannot compare — one or both sources empty",
            }

        # Find overlapping chunks using search
        overlap_pairs: list[dict[str, Any]] = []
        matched_a: set[str] = set()
        matched_b: set[str] = set()

        for rid_a, text_a in chunks_a:
            results = self._query_fn(text_a[:200], k=5)
            for sr in results:
                if sr.revision_id == rid_a:
                    continue
                if sr.score < similarity_threshold:
                    continue
                # Check if this result is from source_b
                cand_rev = self.store.revisions.get(sr.revision_id)
                if cand_rev is None:
                    continue
                cand_core = self.store.cores.get(cand_rev.core_id)
                if cand_core and cand_core.slots.get("source") == source_b:
                    pair_key = tuple(sorted([rid_a, sr.revision_id]))
                    if pair_key not in {tuple(sorted([p["rid_a"], p["rid_b"]])) for p in overlap_pairs}:
                        overlap_pairs.append({
                            "rid_a": rid_a,
                            "rid_b": sr.revision_id,
                            "similarity": round(sr.score, 4),
                            "text_a": text_a[:200],
                            "text_b": cand_rev.assertion[:200],
                        })
                        matched_a.add(rid_a)
                        matched_b.add(sr.revision_id)

        # Sort by similarity
        overlap_pairs.sort(key=lambda x: -x["similarity"])

        # Extract topic words from overlapping chunks
        shared_words: dict[str, int] = {}
        for pair in overlap_pairs:
            words = set(pair["text_a"].lower().split()) & set(pair["text_b"].lower().split())
            for w in words:
                if len(w) > 3:
                    shared_words[w] = shared_words.get(w, 0) + 1

        shared_topics = sorted(shared_words, key=lambda w: -shared_words[w])[:10]

        unique_a = len(chunks_a) - len(matched_a)
        unique_b = len(chunks_b) - len(matched_b)

        # Generate summary
        overlap_pct_a = len(matched_a) / len(chunks_a) * 100 if chunks_a else 0
        overlap_pct_b = len(matched_b) / len(chunks_b) * 100 if chunks_b else 0

        return {
            "source_a": source_a,
            "source_b": source_b,
            "found_a": True,
            "found_b": True,
            "chunks_a": len(chunks_a),
            "chunks_b": len(chunks_b),
            "overlap_pairs": overlap_pairs[:20],
            "overlap_count": len(overlap_pairs),
            "unique_to_a": unique_a,
            "unique_to_b": unique_b,
            "shared_topics": shared_topics,
            "overlap_pct_a": round(overlap_pct_a, 1),
            "overlap_pct_b": round(overlap_pct_b, 1),
        }

    def render_comparison(self, result: dict[str, Any]) -> str:
        """Render compare_sources() result as human-readable text.

        Args:
            result: Output from compare_sources().

        Returns:
            Formatted text string.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  SOURCE COMPARISON")
        lines.append("=" * 60)
        lines.append(f"  A: {result['source_a']}")
        lines.append(f"  B: {result['source_b']}")

        if not result.get("found_a") or not result.get("found_b"):
            lines.append(f"  {result.get('similarity_summary', 'Missing source(s)')}")
            return "\n".join(lines)

        lines.append(f"  A chunks: {result['chunks_a']}  |  B chunks: {result['chunks_b']}")
        lines.append(f"  Overlapping pairs: {result['overlap_count']}")
        lines.append(f"  A overlap: {result['overlap_pct_a']}%  |  B overlap: {result['overlap_pct_b']}%")
        lines.append(f"  Unique to A: {result['unique_to_a']}  |  Unique to B: {result['unique_to_b']}")
        lines.append("")

        if result.get("shared_topics"):
            lines.append(f"  Shared topics: {', '.join(result['shared_topics'][:8])}")
            lines.append("")

        if result.get("overlap_pairs"):
            lines.append("  TOP OVERLAPPING PAIRS:")
            lines.append("-" * 60)
            for pair in result["overlap_pairs"][:5]:
                lines.append(f"  [{pair['similarity']:.3f}]")
                lines.append(f"    A: {pair['text_a'][:120].replace(chr(10), ' ')}...")
                lines.append(f"    B: {pair['text_b'][:120].replace(chr(10), ' ')}...")
                lines.append("")

        return "\n".join(lines)

    # ---- Corpus Insights ----

    def insights(self) -> dict[str, Any]:
        """Generate proactive insights and recommendations for corpus improvement.

        Combines quality report, staleness, contradiction scanning, and
        corpus statistics into a prioritized list of actionable suggestions.

        Returns:
            Dict with prioritized actions, corpus health score, and suggestions.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        actions: list[dict[str, Any]] = []

        # 1. Quality issues
        qr = self.quality_report()
        for issue in qr["issues"]:
            priority = 1 if issue["severity"] == "warning" else 2
            actions.append({
                "priority": priority,
                "category": "quality",
                "action": issue["suggestion"],
                "detail": issue["description"],
            })

        # 2. Staleness
        stale = self.staleness_report(age_days=365)
        if stale["stale_count"] > 0:
            pct = stale["stale_count"] / max(qr["summary"]["total_chunks"], 1) * 100
            actions.append({
                "priority": 2 if pct < 30 else 1,
                "category": "freshness",
                "action": f"Review {stale['stale_count']} stale chunks ({pct:.0f}% of corpus)",
                "detail": f"Chunks older than 365 days across {len(stale['by_source'])} sources",
            })

        # 3. Source coverage gaps
        sources = self.list_sources()
        if len(sources) == 1:
            actions.append({
                "priority": 1,
                "category": "coverage",
                "action": "Add more sources for richer cross-referencing",
                "detail": "Single-source corpus limits search and contradiction detection",
            })
        elif len(sources) >= 2:
            biggest = sources[0]["chunks"]
            total = sum(s["chunks"] for s in sources)
            if biggest / total > 0.5:
                actions.append({
                    "priority": 2,
                    "category": "balance",
                    "action": f"Corpus dominated by '{sources[0]['source'][:40]}' ({biggest}/{total} chunks)",
                    "detail": "Consider adding more sources on underrepresented topics",
                })

        # 4. Entity review suggestions
        try:
            review = self.review_entities(top_k=20)
            if review["flagged"]:
                actions.append({
                    "priority": 2,
                    "category": "entities",
                    "action": f"Review {len(review['flagged'])} flagged entities for quality",
                    "detail": "Use accept_entities/reject_entities to curate",
                })
        except (KeyError, ValueError, TypeError):
            pass

        # Sort by priority
        actions.sort(key=lambda x: x["priority"])

        # Health score (0-100)
        warning_count = qr["summary"].get("warnings", 0)
        health = max(0, 100 - warning_count * 15 - min(stale["stale_count"], 10) * 3)

        return {
            "health_score": health,
            "total_actions": len(actions),
            "actions": actions,
            "summary": {
                "chunks": qr["summary"]["total_chunks"],
                "sources": qr["summary"]["total_sources"],
                "clusters": qr["summary"]["total_clusters"],
                "stale": stale["stale_count"],
                "warnings": warning_count,
            },
        }

    def suggest_queries(self, *, n: int = 5) -> list[dict[str, str]]:
        """Suggest interesting queries to explore based on corpus content.

        Analyzes cluster labels and source topics to generate query
        suggestions that would exercise different parts of the knowledge base.

        Args:
            n: Number of suggestions to generate.

        Returns:
            List of dicts with query text and rationale.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        suggestions: list[dict[str, str]] = []

        # Get cluster labels
        topics = self._topics_fn()
        top_clusters = sorted(topics, key=lambda x: -x["size"])

        # 1. Suggest queries from largest clusters (what corpus is ABOUT)
        for cluster in top_clusters[:min(2, len(top_clusters))]:
            labels = cluster.get("labels", [])
            if labels:
                q = " ".join(labels[:3])
                suggestions.append({
                    "query": q,
                    "rationale": f"Core topic ({cluster['size']} chunks)",
                    "type": "exploratory",
                })

        # 2. Cross-cluster queries (bridge different topics)
        if len(top_clusters) >= 2:
            labels_a = top_clusters[0].get("labels", [])[:2]
            labels_b = top_clusters[1].get("labels", [])[:2]
            if labels_a and labels_b:
                suggestions.append({
                    "query": f"How does {' '.join(labels_a)} relate to {' '.join(labels_b)}?",
                    "rationale": "Cross-topic bridge query",
                    "type": "reasoning",
                })

        # 3. Contradiction-probing queries
        if len(top_clusters) >= 1:
            labels = top_clusters[0].get("labels", [])
            if labels:
                suggestions.append({
                    "query": f"What are the debates about {labels[0]}?",
                    "rationale": "Probe for contradictory claims",
                    "type": "analytical",
                })

        # 4. Coverage gap query
        sources = self.list_sources()
        if sources:
            smallest = sources[-1]
            suggestions.append({
                "query": f"What does {smallest['source'][:40]} cover?",
                "rationale": f"Least-represented source ({smallest['chunks']} chunks)",
                "type": "coverage",
            })

        return suggestions[:n]

    def render_insights(self, result: dict[str, Any] | None = None) -> str:
        """Render insights() output as human-readable text.

        Args:
            result: Output from insights(). If None, generates one.

        Returns:
            Formatted text string.
        """
        if result is None:
            result = self.insights()

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  CORPUS INSIGHTS")
        lines.append("=" * 60)

        health = result["health_score"]
        bar = "#" * (health // 5) + "-" * (20 - health // 5)
        lines.append(f"  Health: [{bar}] {health}/100")

        s = result["summary"]
        lines.append(f"  {s['chunks']} chunks | {s['sources']} sources | {s['clusters']} clusters")
        lines.append(f"  {s['stale']} stale | {s['warnings']} warnings")
        lines.append("")

        if result["actions"]:
            lines.append("  RECOMMENDED ACTIONS:")
            lines.append("-" * 60)
            for i, action in enumerate(result["actions"], 1):
                icon = "!!" if action["priority"] == 1 else ".."
                lines.append(f"  {i}. [{icon}] [{action['category']}] {action['action']}")
                lines.append(f"       {action['detail']}")
            lines.append("")
        else:
            lines.append("  No actions needed — corpus looks healthy!")
            lines.append("")

        return "\n".join(lines)

    # ---- Chunk Annotation ----

    def annotate_chunk(
        self,
        revision_id: str,
        *,
        tags: list[str] | None = None,
        note: str = "",
    ) -> str:
        """Add user-defined tags and notes to a chunk.

        Annotations are stored as deterministic claims (dks.annotation@v1),
        making them auditable, retractable, and temporally queryable.

        Args:
            revision_id: The chunk to annotate.
            tags: List of tag strings.
            note: Free-text note.

        Returns:
            The annotation revision_id.
        """
        from .core import ClaimCore as _CC, Provenance as _P, ValidTime as _VT
        from datetime import datetime as _dt

        rev = self.store.revisions.get(revision_id)
        if rev is None:
            raise ValueError(f"Revision {revision_id} not found")

        # Reject annotation on retracted chunks to prevent orphaned annotations
        retracted = self.store.retracted_core_ids()
        if rev.core_id in retracted:
            raise ValueError(
                f"Cannot annotate retracted revision {revision_id}. "
                "The target chunk has been retracted."
            )

        slots: dict[str, str] = {
            "target_revision": revision_id,
        }
        if tags:
            slots["tags"] = ",".join(tags)
        if note:
            slots["note"] = note

        core = _CC(
            claim_type="dks.annotation@v1",
            slots=slots,
        )

        now = _dt.now(timezone.utc)
        tx = self._tx_factory()

        result = self.store.assert_revision(
            core=core,
            assertion=f"Annotation on {revision_id}: tags={tags or []}, note={note[:100]}",
            valid_time=_VT(start=now, end=None),
            transaction_time=tx,
            provenance=_P(source="user_annotation"),
            confidence_bp=9000,
        )
        return result.revision_id

    def list_annotations(
        self,
        *,
        revision_id: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """List annotations, optionally filtered by target chunk or tag.

        Args:
            revision_id: Filter to annotations on this specific chunk.
            tag: Filter to annotations containing this tag.

        Returns:
            List of annotation dicts with target, tags, note, and timestamp.
        """
        retracted = self.store.retracted_core_ids()

        # Build set of active target revision_ids (to filter orphaned annotations)
        active_targets: set[str] = set()
        for rid, rev in self.store.revisions.items():
            if rev.status == "asserted" and rev.core_id not in retracted:
                active_targets.add(rid)

        annotations: list[dict[str, Any]] = []

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted" or rev.core_id in retracted:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None or core.claim_type != "dks.annotation@v1":
                continue

            target = core.slots.get("target_revision", "")
            # Skip orphaned annotations (target chunk was retracted)
            if target and target not in active_targets:
                continue

            tags_str = core.slots.get("tags", "")
            note = core.slots.get("note", "")
            tag_list = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

            # Apply filters
            if revision_id and target != revision_id:
                continue
            if tag and tag not in tag_list:
                continue

            annotations.append({
                "annotation_id": rid,
                "target_revision": target,
                "tags": tag_list,
                "note": note,
                "created_at": rev.transaction_time.recorded_at.isoformat(),
            })

        return annotations

    def search_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """Find all chunks that have been annotated with a specific tag.

        Args:
            tag: The tag to search for.

        Returns:
            List of chunk dicts with revision_id, source, and preview text.
        """
        annotations = self.list_annotations(tag=tag)
        results: list[dict[str, Any]] = []

        for ann in annotations:
            target_rid = ann["target_revision"]
            rev = self.store.revisions.get(target_rid)
            if rev is None:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "?") if core else "?"

            results.append({
                "revision_id": target_rid,
                "source": source,
                "text": rev.assertion[:300],
                "tags": ann["tags"],
                "note": ann["note"],
                "annotation_id": ann["annotation_id"],
            })

        return results

    def remove_annotation(self, annotation_id: str) -> bool:
        """Remove an annotation by retracting it.

        Args:
            annotation_id: The revision_id of the annotation to remove.

        Returns:
            True if retracted, False if not found.
        """
        from .core import Provenance as _P

        rev = self.store.revisions.get(annotation_id)
        if rev is None:
            return False

        core = self.store.cores.get(rev.core_id)
        if core is None or core.claim_type != "dks.annotation@v1":
            return False

        tx = self._tx_factory()
        self.store.assert_revision(
            core=core,
            assertion=rev.assertion,
            valid_time=rev.valid_time,
            transaction_time=tx,
            provenance=_P(source="annotation_removal"),
            confidence_bp=rev.confidence_bp,
            status="retracted",
        )
        return True

    # ---- Corpus Summary ----

    def summarize_corpus(self) -> str:
        """Generate a text summary of what the corpus contains.

        Uses cluster labels, source stats, temporal range, and corpus
        metrics to produce a human-readable description. No LLM required.

        Returns:
            Multi-paragraph text summary.
        """
        if self._graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        stats = self._stats_fn()
        sources = self.list_sources()
        topics = self._topics_fn()
        tl = self.ingestion_timeline()

        lines: list[str] = []

        # Opening — count only active, non-retracted document chunks
        retracted = self._retracted_cores()
        n_chunks = sum(
            1 for rev in self.store.revisions.values()
            if rev.status == "asserted" and rev.core_id not in retracted
        )
        n_sources = len(sources)
        lines.append(f"This knowledge base contains {n_chunks:,} chunks from {n_sources} source documents.")

        # Temporal range
        if tl:
            first_ts = tl[0]["timestamp"][:10]
            last_ts = tl[-1]["timestamp"][:10]
            if first_ts != last_ts:
                lines.append(f"Data spans from {first_ts} to {last_ts}.")
            else:
                lines.append(f"All data was ingested on {first_ts}.")

        # Source overview
        if sources:
            top_sources = sources[:min(5, len(sources))]
            source_list = ", ".join(
                f"{s['source'][:35]} ({s['chunks']} chunks)" for s in top_sources
            )
            lines.append(f"\nTop sources: {source_list}.")

        # Topic overview
        if topics:
            top_topics = sorted(topics, key=lambda x: -x["size"])[:min(6, len(topics))]
            topic_descriptions: list[str] = []
            for t in top_topics:
                labels = ", ".join(t["labels"][:3])
                topic_descriptions.append(f"{labels} ({t['size']} chunks)")
            lines.append(f"\nMain topics: {'; '.join(topic_descriptions)}.")

        # Annotations and entity decisions
        n_annotations = len(self.list_annotations())
        decisions = self.get_entity_decisions()
        if n_annotations > 0 or decisions:
            curation_parts: list[str] = []
            if n_annotations > 0:
                curation_parts.append(f"{n_annotations} annotations")
            if decisions:
                n_accepted = sum(1 for v in decisions.values() if v == "accepted")
                n_rejected = sum(1 for v in decisions.values() if v == "rejected")
                if n_accepted:
                    curation_parts.append(f"{n_accepted} accepted entities")
                if n_rejected:
                    curation_parts.append(f"{n_rejected} rejected entities")
            lines.append(f"\nUser curation: {', '.join(curation_parts)}.")

        return "\n".join(lines)

    # ---- Source Listing ----

    def list_sources(self) -> list[dict[str, Any]]:
        """List all unique source documents in the store.

        Returns:
            List of dicts with source name, chunk count, and page range.
        """
        retracted_cores = self._retracted_cores()
        sources: dict[str, dict[str, Any]] = {}

        for rid, rev in self.store.revisions.items():
            if rev.status != "asserted":
                continue
            if rev.core_id in retracted_cores:
                continue
            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            source = core.slots.get("source", "unknown")
            if source not in sources:
                sources[source] = {
                    "source": source,
                    "chunks": 0,
                    "pages": set(),
                    "first_ingested": rev.transaction_time.recorded_at,
                }

            sources[source]["chunks"] += 1
            page = core.slots.get("page_start")
            if page is not None:
                try:
                    sources[source]["pages"].add(int(page))
                except (ValueError, TypeError):
                    pass

            if rev.transaction_time.recorded_at < sources[source]["first_ingested"]:
                sources[source]["first_ingested"] = rev.transaction_time.recorded_at

        result = []
        for info in sorted(sources.values(), key=lambda x: -x["chunks"]):
            pages = sorted(info["pages"])
            result.append({
                "source": info["source"],
                "chunks": info["chunks"],
                "page_range": f"{min(pages)}-{max(pages)}" if pages else "unknown",
                "total_pages": len(pages),
                "first_ingested": info["first_ingested"].isoformat(),
            })

        return result
