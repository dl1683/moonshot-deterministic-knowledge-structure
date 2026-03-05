"""SearchEngine — all search and reasoning methods for DKS.

Extracted from Pipeline so that the engine can be composed, tested, and
extended independently of the ingestion and persistence machinery.

The SearchEngine owns:
  - Basic search (query, query_multi, query_exact, query_with_context)
  - Context expansion (expand_context, _reconstruct_siblings)
  - Entity linking (link_entities)
  - Reasoning layer (reason, discover, coverage, evidence_chain, query_deep)
  - Answer synthesis (synthesize, ask, and the private strategy helpers)
  - Knowledge timeline (timeline, timeline_diff)
  - Provenance & citation (provenance_of, cite, cite_results, query_by_source)
  - Semantic deduplication (deduplicate)
  - Query explanation (explain)
  - Answer extraction (extract_answer, answer)
  - Contradiction detection (contradictions, confidence)
  - Private helpers (_classify_query, _decompose_question, etc.)
"""
from __future__ import annotations

import math
import re
import time as _time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .audit import AuditManager
from .core import KnowledgeStore, Provenance
from .index import KnowledgeGraph, SearchIndex, SearchResult
from .results import CoverageReport, DeepQueryResult, EvidenceChain, QueryFacet, ReasoningResult, SynthesisResult

# Universal English stop words — minimal set used across all search methods.
# Derived from function words (determiners, prepositions, auxiliaries, pronouns).
# Domain-specific terms should NOT be here — those are handled by IDF filtering.
_STOP_WORDS: frozenset[str] = frozenset({
    # Determiners
    "the", "a", "an", "this", "that", "these", "those",
    # Prepositions
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "up", "about",
    # Conjunctions
    "and", "or", "but", "nor", "so", "if", "while", "than",
    # Auxiliaries / modals
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall", "can",
    # Pronouns
    "it", "its", "they", "them", "their", "we", "our", "you", "your",
    "he", "him", "his", "she", "her", "i", "me", "my",
    # Question words
    "what", "which", "who", "whom", "how", "why", "when", "where",
    # Common adverbs / fillers
    "not", "no", "also", "just", "very", "too", "only", "then",
    "here", "there", "again", "further", "once", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "own",
    "same", "all", "any", "many", "much", "even", "still",
    # Contractions fragments
    "don", "didn", "doesn", "won", "ll", "ve", "re",
})

# Negation words used across contradiction detection and confidence scoring.
_NEGATION_WORDS: frozenset[str] = frozenset({
    "not", "no", "never", "neither", "nor", "none", "nothing",
    "nowhere", "hardly", "scarcely", "barely", "seldom", "rarely",
    "doesn't", "don't", "didn't", "won't", "wouldn't", "couldn't",
    "shouldn't", "isn't", "aren't", "wasn't", "weren't", "cannot", "can't",
    "without", "lack", "fail", "false", "incorrect", "wrong",
    "unlike", "contrary",
})


class SearchEngine:
    """Holds all search and reasoning methods.

    Injectable dependencies allow test doubles and composition.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        index: Any,
        reranker: Any,
        graph_fn: Callable[[], Any],
        audit: AuditManager,
        chunk_siblings: dict[str, list[str]],
        entity_decisions_fn: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.store = store
        self._index = index
        self._reranker = reranker
        self._graph_fn = graph_fn
        self._audit = audit
        self._chunk_siblings = chunk_siblings
        self._entity_decisions_fn = entity_decisions_fn

    @property
    def _graph(self) -> Any:
        """Return the current KnowledgeGraph or None."""
        return self._graph_fn()

    # ---- Basic Search ----

    def query(
        self,
        question: str,
        *,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
        k: int = 5,
    ) -> list[SearchResult]:
        """Search for relevant claims with temporal filtering.

        Args:
            question: Natural language query.
            valid_at: When the facts should be true (for temporal filter).
            tx_id: Transaction time cutoff (for temporal filter).
            k: Maximum number of results.

        Returns:
            List of SearchResult ordered by relevance.
        """
        if self._index is None:
            raise ValueError(
                "No search index configured. "
                "Set embedding_backend or search_index in Pipeline init."
            )
        if not question or not question.strip():
            return []
        if k < 1:
            return []

        # If re-ranker is configured, retrieve more candidates then re-rank
        if self._reranker is not None:
            candidates = self._index.search(
                question,
                k=k * 4,  # Over-retrieve for better re-ranking
                valid_at=valid_at,
                tx_id=tx_id,
            )
            return self._reranker.rerank(question, candidates, top_k=k)

        return self._index.search(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    def query_multi(
        self,
        question: str,
        *,
        k: int = 10,
        group_by_source: bool = True,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> dict[str, list[SearchResult]]:
        """Multi-document retrieval: find relevant chunks across all sources.

        Returns results grouped by source document, enabling cross-document
        reasoning.

        Args:
            question: Natural language query.
            k: Total results to retrieve before grouping.
            group_by_source: If True, group results by source document.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            Dict mapping source filename → list of SearchResult.
        """
        results = self.query(
            question,
            k=k,
            valid_at=valid_at,
            tx_id=tx_id,
        )

        if not group_by_source:
            return {"all": results}

        grouped: dict[str, list[SearchResult]] = {}
        for result in results:
            # Get the source from the claim's slots
            core = self.store.cores.get(result.core_id)
            source = "unknown"
            if core and "source" in core.slots:
                source = core.slots["source"]
            grouped.setdefault(source, []).append(result)

        return grouped

    def query_exact(
        self,
        core_id: str,
        *,
        valid_at: datetime,
        tx_id: int,
    ):
        """Direct query by core_id with bitemporal coordinates.

        This bypasses search and goes straight to the deterministic core.
        """
        return self.store.query_as_of(
            core_id,
            valid_at=valid_at,
            tx_id=tx_id,
        )

    # ---- Context Expansion ----

    def expand_context(
        self,
        result: SearchResult,
        *,
        window: int = 2,
    ) -> list[SearchResult]:
        """Expand a search result to include surrounding chunks from the same document.

        When a relevant chunk is found, this retrieves the N chunks before
        and after it from the same source document, providing full context
        for reasoning.

        Args:
            result: A SearchResult to expand context around.
            window: Number of chunks before/after to include.

        Returns:
            Ordered list of SearchResults (including the original).
        """
        core = self.store.cores.get(result.core_id)
        if core is None:
            return [result]

        source = core.slots.get("source", "")
        if not source:
            return [result]

        # Find sibling chunks for this source
        siblings = self._chunk_siblings.get(source)

        # If siblings not tracked, try to reconstruct from store
        if siblings is None:
            siblings = self._reconstruct_siblings(source)

        if not siblings:
            return [result]

        # Find position of this result in the sibling list
        try:
            pos = siblings.index(result.revision_id)
        except ValueError:
            return [result]

        # Get window of surrounding chunks
        start = max(0, pos - window)
        end = min(len(siblings), pos + window + 1)

        expanded = []
        for rid in siblings[start:end]:
            rev = self.store.revisions.get(rid)
            if rev:
                expanded.append(SearchResult(
                    core_id=rev.core_id,
                    revision_id=rid,
                    score=result.score if rid == result.revision_id else result.score * 0.5,
                    text=rev.assertion,
                ))

        return expanded

    def _reconstruct_siblings(self, source: str) -> list[str]:
        """Reconstruct sibling chunk order from store data."""
        # Find all chunks from this source, excluding retracted
        retracted = self.store.retracted_core_ids()
        chunks: list[tuple[int, str]] = []  # (chunk_idx, revision_id)
        for rev_id, rev in self.store.revisions.items():
            if rev.status != "asserted" or rev.core_id in retracted:
                continue
            core = self.store.cores.get(rev.core_id)
            if core and core.slots.get("source") == source:
                try:
                    idx = int(core.slots.get("chunk_idx", "0"))
                except (ValueError, TypeError):
                    idx = 0
                chunks.append((idx, rev_id))

        if not chunks:
            return []

        chunks.sort()
        siblings = [rid for _, rid in chunks]
        self._chunk_siblings[source] = siblings
        return siblings

    def query_with_context(
        self,
        question: str,
        *,
        k: int = 5,
        context_window: int = 1,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search with automatic context expansion.

        Like query(), but each result includes surrounding chunks from
        the same document for extended context.

        Args:
            question: Natural language query.
            k: Number of seed results.
            context_window: Chunks before/after each result to include.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResults including expanded context, ordered
            by seed result relevance with context chunks adjacent.
        """
        seeds = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        if context_window <= 0:
            return seeds

        seen: set[str] = set()
        expanded: list[SearchResult] = []

        for seed in seeds:
            context = self.expand_context(seed, window=context_window)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        return expanded

    # ---- Entity Linking ----

    def link_entities(
        self,
        *,
        min_entity_length: int = 3,
        min_shared_entities: int = 2,
        max_edges_per_node: int = 10,
    ) -> dict[str, Any]:
        """Create entity-based cross-references between chunks.

        Extracts key noun phrases from each chunk, finds chunks that share
        entities across different documents, and adds explicit edges to
        the knowledge graph. This enables multi-hop reasoning that follows
        actual conceptual links rather than just keyword similarity.

        Must be called AFTER build_graph().

        Args:
            min_entity_length: Minimum character length for an entity.
            min_shared_entities: Minimum shared entities to create a link.
            max_edges_per_node: Maximum entity edges per chunk.

        Returns:
            Dict with:
              - total_entities: int (unique entities found)
              - total_links: int (new graph edges added)
              - top_entities: list of (entity, count) tuples
        """
        import hashlib

        graph = self._graph
        if graph is None:
            raise ValueError("Graph not built. Call build_graph() first.")

        # Step 1: Statistical entity extraction
        #
        # Principled approach — no stopword lists, no hardcoded patterns.
        # The math decides what's noise vs. signal:
        #
        #   0. Detect boilerplate: sentences repeated across many documents
        #      are template text (footers, headers, signatures) — exclude them
        #   1. Tokenize each chunk into words (pure alphabetic only)
        #   2. Extract candidate unigrams and bigrams
        #   3. Compute IDF across all chunks — terms in too many or too few
        #      chunks are automatically excluded
        #   4. For bigrams, use PMI to keep only real collocations
        #   5. Per chunk, keep only the top-K most discriminative terms

        # Filter out retracted revisions once — used throughout this method
        retracted = self.store.retracted_core_ids()
        active_revisions = {
            rid: rev for rid, rev in self.store.revisions.items()
            if rev.status == "asserted" and rev.core_id not in retracted
        }

        n_chunks = len(active_revisions)
        if n_chunks == 0:
            return {"total_entities": 0, "total_links": 0, "top_entities": []}

        # IDF band: only keep terms appearing in [min_df, max_df] fraction of chunks
        # Scale gracefully: small corpus (< 50 chunks) uses min_df=2, large uses 3+
        min_df = 2 if n_chunks < 50 else max(3, int(n_chunks * 0.004))
        max_df_frac = 0.10 if n_chunks > 100 else 0.50  # More lenient for small corpora
        max_df = max(min_df + 1, int(n_chunks * max_df_frac))

        # Step 0: Boilerplate detection
        # Sentences that appear in many different source documents are template
        # text (newsletter footers, author bios, social links). We detect these
        # by hashing normalized sentences and counting source-document frequency.

        sentence_sources: dict[str, set[str]] = {}  # sentence_hash -> source set
        chunk_boilerplate: dict[str, set[str]] = {}  # rev_id -> set of boilerplate hashes

        for rev_id, rev in active_revisions.items():
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", rev_id) if core else rev_id
            # Split into sentences (simple split on . ! ? followed by space/newline)
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            hashes = set()
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.lower().strip())
                if len(normed) < 20:
                    continue  # Too short to be meaningful boilerplate
                h = hashlib.md5(normed.encode()).hexdigest()[:12]
                hashes.add(h)
                sentence_sources.setdefault(h, set()).add(source)
            chunk_boilerplate[rev_id] = hashes

        # A sentence appearing in >5% of source documents is boilerplate
        n_sources = len({
            (self.store.cores.get(r.core_id).slots.get("source", rid)
             if self.store.cores.get(r.core_id) else rid)
            for rid, r in active_revisions.items()
        })
        boilerplate_threshold = max(3, int(n_sources * 0.05))
        boilerplate_hashes = {
            h for h, sources in sentence_sources.items()
            if len(sources) >= boilerplate_threshold
        }

        # For each chunk, build clean text (boilerplate sentences removed)
        chunk_clean_text: dict[str, str] = {}
        for rev_id, rev in active_revisions.items():
            sentences = re.split(r'(?<=[.!?])\s+|\n+', rev.assertion)
            clean_parts = []
            for sent in sentences:
                normed = re.sub(r'\s+', ' ', sent.lower().strip())
                if len(normed) < 20:
                    clean_parts.append(sent)
                    continue
                h = hashlib.md5(normed.encode()).hexdigest()[:12]
                if h not in boilerplate_hashes:
                    clean_parts.append(sent)
            chunk_clean_text[rev_id] = " ".join(clean_parts)

        # Tokenize: pure alphabetic words (3+ chars) — excludes URLs,
        # hashes, codes, mixed alphanumeric noise. Acronyms (2+ uppercase)
        # are extracted separately and kept as-is.
        word_re = re.compile(r'\b([a-z]{3,})\b')
        acronym_re = re.compile(r'\b([A-Z]{2,})\b')

        # Pass 1: Collect document frequencies for unigrams and bigrams
        chunk_tokens: dict[str, list[str]] = {}  # rev_id -> token list
        chunk_acronyms: dict[str, set[str]] = {}  # rev_id -> acronym set
        unigram_df: Counter = Counter()   # term -> num chunks containing it
        bigram_df: Counter = Counter()    # "w1 w2" -> num chunks containing it
        unigram_tf_total: Counter = Counter()  # total corpus frequency
        acronym_df: Counter = Counter()   # ACRONYM -> num chunks containing it

        for rev_id in active_revisions:
            text = chunk_clean_text.get(rev_id, "")
            tokens = word_re.findall(text.lower())
            chunk_tokens[rev_id] = tokens

            # Extract acronyms separately (from clean text)
            acrs = set(acronym_re.findall(text))
            chunk_acronyms[rev_id] = acrs
            for acr in acrs:
                acronym_df[acr] += 1

            # Unique terms in this chunk (for DF counting)
            unique_unigrams = set(tokens)
            for t in unique_unigrams:
                unigram_df[t] += 1
                unigram_tf_total[t] += tokens.count(t)

            # Unique bigrams in this chunk
            unique_bigrams = set()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                unique_bigrams.add(bg)
            for bg in unique_bigrams:
                bigram_df[bg] += 1

        # Filter acronyms by IDF band (same as words)
        good_acronyms: dict[str, float] = {}
        for acr, df in acronym_df.items():
            if df < min_df or df > max_df:
                continue
            if len(acr) < 2:
                continue
            good_acronyms[acr] = math.log(n_chunks / df)

        # Identify function/ubiquitous words from the data: words appearing
        # in >50% of chunks. These are grammar words and corpus boilerplate.
        # Derived entirely from corpus statistics, no hardcoded lists.
        function_threshold = max(n_chunks // 2, 5)
        function_words = {
            term for term, df in unigram_df.items()
            if df > function_threshold
        }

        # Pass 2: Compute IDF scores, filter to informative band
        # IDF = log(N / df) — higher = more discriminative
        good_unigrams: dict[str, float] = {}
        for term, df in unigram_df.items():
            if df < min_df or df > max_df:
                continue
            if len(term) < min_entity_length:
                continue
            if term in function_words:
                continue
            good_unigrams[term] = math.log(n_chunks / df)

        # For bigrams: require IDF band + positive PMI
        # PMI(w1, w2) = log(P(w1,w2) / (P(w1) * P(w2)))
        # Positive PMI means the words co-occur more than chance
        total_tokens = sum(len(t) for t in chunk_tokens.values())
        total_bigrams = max(total_tokens - n_chunks, 1)  # approximate

        # For bigrams, also track source-document frequency
        # (a bigram only from one doc's boilerplate isn't a real entity)
        bigram_sources: dict[str, set[str]] = {}
        for rev_id in active_revisions:
            core = self.store.cores.get(active_revisions[rev_id].core_id)
            source = core.slots.get("source", rev_id) if core else rev_id
            tokens = chunk_tokens.get(rev_id, [])
            seen_bg: set[str] = set()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                if bg not in seen_bg:
                    seen_bg.add(bg)
                    bigram_sources.setdefault(bg, set()).add(source)

        good_bigrams: dict[str, float] = {}
        for bigram, df in bigram_df.items():
            if df < min_df or df > max_df:
                continue
            w1, w2 = bigram.split(" ", 1)
            if len(w1) < 3 or len(w2) < 3:
                continue
            # Cross-source requirement: must appear in 2+ source docs
            # (skip for tiny corpora with <=4 sources)
            min_bg_sources = 2 if n_sources > 4 else 1
            if len(bigram_sources.get(bigram, set())) < min_bg_sources:
                continue
            # Neither component can be a function word
            if w1 in function_words or w2 in function_words:
                continue
            # PMI filter: keep only collocations
            p_bigram = df / max(n_chunks, 1)
            p_w1 = unigram_df.get(w1, 1) / max(n_chunks, 1)
            p_w2 = unigram_df.get(w2, 1) / max(n_chunks, 1)
            pmi = math.log(max(p_bigram, 1e-10) / max(p_w1 * p_w2, 1e-10))
            if pmi <= 0.5:
                continue  # Require meaningful collocation (PMI > 0.5)
            # IDF of the bigram, weighted by source diversity
            idf = math.log(n_chunks / df)
            n_bg_sources = len(bigram_sources.get(bigram, set()))
            # Source ratio: fraction of distinct sources vs chunks containing it
            # High ratio = appears broadly across docs (technical term)
            # Low ratio = concentrated in few docs (single-author boilerplate)
            source_ratio = n_bg_sources / max(df, 1)
            good_bigrams[bigram] = idf * (1 + pmi) * (1 + source_ratio)

        # Pass 3: For each chunk, select top-K discriminative entities
        max_entities_per_chunk = 15

        chunk_entities: dict[str, set[str]] = {}
        entity_chunks: dict[str, set[str]] = {}

        for rev_id, tokens in chunk_tokens.items():
            # Score candidates by TF-IDF
            token_counts = Counter(tokens)
            candidates: list[tuple[str, float]] = []

            # Unigram candidates
            for term, count in token_counts.items():
                if term in good_unigrams:
                    tf = 1 + math.log(count)  # Sublinear TF
                    score = tf * good_unigrams[term]
                    candidates.append((term, score))

            # Bigram candidates
            bigram_counts: Counter = Counter()
            for i in range(len(tokens) - 1):
                bg = f"{tokens[i]} {tokens[i+1]}"
                bigram_counts[bg] += 1

            for bg, count in bigram_counts.items():
                if bg in good_bigrams:
                    tf = 1 + math.log(count)
                    score = tf * good_bigrams[bg]
                    candidates.append((bg, score))

            # Acronym candidates
            for acr in chunk_acronyms.get(rev_id, set()):
                if acr in good_acronyms:
                    candidates.append((acr, good_acronyms[acr]))

            # Take top-K by score
            candidates.sort(key=lambda x: -x[1])
            entities = set()
            for term, _ in candidates[:max_entities_per_chunk]:
                entities.add(term)

            chunk_entities[rev_id] = entities
            for entity in entities:
                entity_chunks.setdefault(entity, set()).add(rev_id)

        # Pass 4: Cluster-spread filter
        # Remove entities that only appear within a single topical cluster.
        # Boilerplate entities ("chocolate milk") appear in many chunks but
        # always alongside the same newsletter content = same cluster.
        # Real technical entities ("neural networks") span diverse topics.
        rev_to_cluster = graph.revision_cluster if graph is not None else None
        if rev_to_cluster and len(rev_to_cluster) > 0 and n_chunks > 50:
            # Only apply cluster filter on large enough corpora where
            # clustering is meaningful. For small corpora (<50 chunks),
            # the clusters are too coarse to be a useful filter.
            n_actual_clusters = len(set(rev_to_cluster.values()))
            min_clusters = 2 if n_actual_clusters >= 5 else 1
            filtered_entity_chunks: dict[str, set[str]] = {}
            for entity, rev_ids in entity_chunks.items():
                clusters = set()
                for rid in rev_ids:
                    cid = rev_to_cluster.get(rid)
                    if cid is not None:
                        clusters.add(cid)
                if len(clusters) >= min_clusters:
                    filtered_entity_chunks[entity] = rev_ids
            entity_chunks = filtered_entity_chunks

            # Rebuild chunk_entities to only include surviving entities
            for rev_id in chunk_entities:
                chunk_entities[rev_id] = {
                    e for e in chunk_entities[rev_id]
                    if e in entity_chunks
                }

        # Pass 5: Apply user entity decisions (reject list)
        if self._entity_decisions_fn is not None:
            decisions = self._entity_decisions_fn()
            rejected = {e for e, d in decisions.items() if d == "rejected"}
            if rejected:
                for rev_id in chunk_entities:
                    chunk_entities[rev_id] -= rejected
                entity_chunks = {
                    e: rids for e, rids in entity_chunks.items()
                    if e not in rejected
                }

        # Step 2: Find cross-document entity links
        # For each pair of chunks from different sources, count shared entities
        total_links = 0

        for rev_id, entities in chunk_entities.items():
            rev = active_revisions.get(rev_id)
            if rev is None:
                continue
            core = self.store.cores.get(rev.core_id)
            source = core.slots.get("source", "") if core else ""

            # Find candidate neighbors via shared entities
            neighbor_scores: dict[str, int] = {}
            for entity in entities:
                for other_id in entity_chunks.get(entity, set()):
                    if other_id == rev_id:
                        continue
                    # Only cross-document links
                    other_rev = active_revisions.get(other_id)
                    if other_rev is None:
                        continue
                    other_core = self.store.cores.get(other_rev.core_id)
                    other_source = other_core.slots.get("source", "") if other_core else ""
                    if other_source == source:
                        continue
                    neighbor_scores[other_id] = neighbor_scores.get(other_id, 0) + 1

            # Add edges for chunks with enough shared entities
            edges_added = 0
            for neighbor_id, shared_count in sorted(
                neighbor_scores.items(), key=lambda x: -x[1]
            ):
                if shared_count < min_shared_entities:
                    break
                if edges_added >= max_edges_per_node:
                    break

                # Add to graph (score = shared entity count / max possible)
                max_shared = min(len(chunk_entities.get(rev_id, set())),
                                 len(chunk_entities.get(neighbor_id, set())))
                edge_score = shared_count / max(max_shared, 1)

                if graph.add_edge(rev_id, neighbor_id, edge_score):
                    total_links += 1
                    edges_added += 1

        # Compute stats
        all_entities = set()
        for entities in chunk_entities.values():
            all_entities.update(entities)

        entity_counts = Counter()
        for entity, chunks in entity_chunks.items():
            if len(chunks) >= 2:  # Only entities appearing in multiple chunks
                entity_counts[entity] = len(chunks)

        return {
            "total_entities": len(all_entities),
            "total_links": total_links,
            "top_entities": entity_counts.most_common(20),
        }

    # ---- Reasoning Layer ----

    def reason(
        self,
        question: str,
        *,
        k: int = 5,
        hops: int = 2,
        expand_k: int = 3,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> ReasoningResult:
        """Multi-hop retrieval: iteratively expand context to answer complex questions.

        Unlike simple query(), reason() performs multiple retrieval rounds:
        1. Initial retrieval: get top-k chunks for the question
        2. Extract key terms from retrieved chunks
        3. Expand: query with extracted terms to find related context
        4. Repeat for `hops` iterations
        5. Deduplicate and rank all found chunks

        Args:
            question: Natural language question.
            k: Results per hop.
            hops: Number of expansion rounds.
            expand_k: Number of expansion queries per hop.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            ReasoningResult with all retrieved chunks, sources, and reasoning trace.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        all_results: dict[str, SearchResult] = {}  # revision_id -> result
        trace: list[dict[str, Any]] = []
        seen_queries: set[str] = set()

        # Hop 0: initial retrieval
        initial = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in initial:
            all_results[r.revision_id] = r
        trace.append({
            "hop": 0,
            "query": question,
            "results": len(initial),
            "new": len(initial),
        })
        seen_queries.add(question.lower().strip())

        # Expansion hops
        for hop in range(1, hops + 1):
            # Extract key terms from current results
            expansion_terms = self._extract_expansion_terms(
                list(all_results.values()),
                seen_queries,
                max_terms=expand_k,
            )

            new_this_hop = 0
            for term in expansion_terms:
                if term.lower().strip() in seen_queries:
                    continue
                seen_queries.add(term.lower().strip())

                hop_results = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in hop_results:
                    if r.revision_id not in all_results:
                        all_results[r.revision_id] = r
                        new_this_hop += 1

            trace.append({
                "hop": hop,
                "expansion_terms": expansion_terms,
                "new": new_this_hop,
                "total": len(all_results),
            })

            if new_this_hop == 0:
                break  # No new information found

        # Rank all results by relevance to original question
        final_results = self._rerank_for_question(
            question, list(all_results.values())
        )

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return ReasoningResult(
            question=question,
            results=final_results,
            sources=sources,
            trace=trace,
            total_hops=len(trace) - 1,
        )

    def discover(
        self,
        seed_query: str,
        *,
        k: int = 5,
        depth: int = 2,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Discover related knowledge by traversing the similarity graph.

        Starting from seed results, find progressively more distant but
        related chunks. Useful for exploratory analysis.

        Args:
            seed_query: Starting query.
            k: Results per expansion.
            depth: How many levels of expansion.
            similarity_threshold: Minimum score to follow.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            All discovered chunks, ordered by discovery path.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        discovered: dict[str, SearchResult] = {}
        frontier: list[str] = []  # queries to explore

        # Start with seed
        seed_results = self.query(seed_query, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in seed_results:
            if r.score >= similarity_threshold:
                discovered[r.revision_id] = r
                # Extract text snippets as new queries
                frontier.append(r.text[:200])

        for level in range(depth):
            new_frontier: list[str] = []
            for text in frontier[:k]:
                # Use first few significant words as expansion query
                words = text.split()[:10]
                expansion = " ".join(words)
                results = self.query(expansion, k=k, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    if r.revision_id not in discovered and r.score >= similarity_threshold:
                        discovered[r.revision_id] = r
                        new_frontier.append(r.text[:200])
            frontier = new_frontier
            if not frontier:
                break

        return list(discovered.values())

    def coverage(
        self,
        topic: str,
        *,
        k: int = 20,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> CoverageReport:
        """Analyze what the store knows about a topic.

        Returns a structured report of all related knowledge, grouped by
        source document and subtopic.

        Args:
            topic: Topic to analyze.
            k: Maximum chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            CoverageReport with sources, subtopics, and gap analysis.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)

        # Group by source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Extract subtopics (key terms from results)
        all_text = " ".join(r.text for r in results)
        subtopics = self._extract_key_terms(all_text, max_terms=10)

        return CoverageReport(
            topic=topic,
            total_chunks=len(results),
            sources=by_source,
            subtopics=subtopics,
            source_count=len(by_source),
        )

    def evidence_chain(
        self,
        claim: str,
        *,
        k: int = 5,
        max_chain_length: int = 5,
        min_relevance: float = 0.05,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "EvidenceChain":
        """Build an evidence chain supporting or refuting a claim.

        Given a claim like "transformers are better than RNNs for NLP",
        this method finds:
        1. Direct evidence (chunks that directly address the claim)
        2. Supporting evidence (chunks that support the direct evidence)
        3. Contradicting evidence (chunks that challenge the claim)
        4. Links between evidence chunks through the knowledge graph

        The chain traces how evidence connects across documents, enabling
        cross-document reasoning.

        Args:
            claim: A factual claim to investigate.
            k: Number of chunks to retrieve per search.
            max_chain_length: Maximum links in a single evidence chain.
            min_relevance: Minimum score threshold.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            EvidenceChain with supporting, contradicting, and linked evidence.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Find direct evidence
        direct = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        direct = [r for r in direct if r.score >= min_relevance]

        # Step 2: Extract the key aspects of the claim for targeted search
        key_terms = self._extract_key_terms(claim, max_terms=5)

        # Step 3: Search for supporting and contradicting evidence
        # Use negation terms to find counterarguments
        all_evidence: dict[str, SearchResult] = {}
        for r in direct:
            all_evidence[r.revision_id] = r

        # Expand via key terms
        for term in key_terms:
            expanded = self.query(term, k=k, valid_at=valid_at, tx_id=tx_id)
            for r in expanded:
                if r.revision_id not in all_evidence and r.score >= min_relevance:
                    all_evidence[r.revision_id] = r

        # Step 4: Build chains via graph traversal
        chains: list[list[SearchResult]] = []
        graph = self._graph
        if graph is not None:
            for seed_result in direct[:3]:
                chain = [seed_result]
                current_id = seed_result.revision_id
                visited = {current_id}

                for _ in range(max_chain_length - 1):
                    neighbors = graph.neighbors(current_id, k=3)
                    best_next = None
                    best_score = -1.0

                    for nid, nscore in neighbors:
                        if nid not in visited and nscore > min_relevance:
                            rev = self.store.revisions.get(nid)
                            if rev and nscore > best_score:
                                best_next = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore,
                                    text=rev.assertion,
                                )
                                best_score = nscore

                    if best_next is None:
                        break

                    chain.append(best_next)
                    visited.add(best_next.revision_id)
                    current_id = best_next.revision_id
                    all_evidence[best_next.revision_id] = best_next

                if len(chain) > 1:
                    chains.append(chain)

        # Step 5: Score each piece of evidence for/against the claim
        supporting: list[SearchResult] = []
        related: list[SearchResult] = []

        for r in sorted(all_evidence.values(), key=lambda x: -x.score):
            if r.revision_id in {d.revision_id for d in direct}:
                supporting.append(r)
            else:
                related.append(r)

        # Group by source
        sources: dict[str, list[SearchResult]] = {}
        for r in all_evidence.values():
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        return EvidenceChain(
            claim=claim,
            direct_evidence=direct,
            supporting_evidence=supporting,
            related_evidence=related,
            chains=chains,
            sources=sources,
            total_evidence=len(all_evidence),
        )

    def query_deep(
        self,
        question: str,
        *,
        k_per_subquery: int = 5,
        max_subqueries: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> DeepQueryResult:
        """Intelligent query decomposition and targeted retrieval.

        This is the "figure out what we need, then pull it out" capability.

        1. Decompose the question into sub-questions (facets)
        2. Identify which topic clusters are relevant
        3. Retrieve targeted chunks for each sub-question
        4. Follow graph connections to find additional context
        5. Assemble a comprehensive answer context

        Args:
            question: Complex natural language question.
            k_per_subquery: Results per sub-query.
            max_subqueries: Maximum number of sub-queries to generate.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            DeepQueryResult with organized context from across the store.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        # Step 1: Decompose question into sub-queries
        subqueries = self._decompose_question(question, max_subqueries)

        # Step 2: Identify relevant topic clusters
        relevant_clusters: dict[int, float] = {}
        graph = self._graph
        if graph is not None:
            for sq in subqueries:
                results = self.query(sq, k=3, valid_at=valid_at, tx_id=tx_id)
                for r in results:
                    cluster_id = graph.cluster_of(r.revision_id)
                    if cluster_id is not None:
                        current = relevant_clusters.get(cluster_id, 0)
                        relevant_clusters[cluster_id] = max(current, r.score)

        # Step 3: Targeted retrieval for each sub-query
        facets: list[QueryFacet] = []
        all_chunks: dict[str, SearchResult] = {}

        for sq in subqueries:
            results = self.query(sq, k=k_per_subquery, valid_at=valid_at, tx_id=tx_id)
            for r in results:
                all_chunks[r.revision_id] = r

            # Step 4: Follow graph connections for top results
            graph_results: list[SearchResult] = []
            if graph is not None:
                for r in results[:2]:
                    for nid, nscore in graph.neighbors(r.revision_id, k=3):
                        if nid not in all_chunks:
                            rev = self.store.revisions.get(nid)
                            if rev:
                                sr = SearchResult(
                                    core_id=rev.core_id,
                                    revision_id=nid,
                                    score=nscore * 0.5,  # Discount graph-discovered results
                                    text=rev.assertion,
                                )
                                graph_results.append(sr)
                                all_chunks[nid] = sr

            facets.append(QueryFacet(
                subquery=sq,
                results=results,
                graph_results=graph_results,
            ))

        # Step 5: Re-rank all collected chunks
        final_results = self._rerank_for_question(
            question, list(all_chunks.values())
        )

        # Organize by source
        sources: dict[str, list[SearchResult]] = {}
        for r in final_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.setdefault(source, []).append(r)

        # Build relevant topics info
        topic_info: list[dict[str, Any]] = []
        if graph is not None:
            for cid, score in sorted(relevant_clusters.items(), key=lambda x: -x[1])[:5]:
                labels = graph.cluster_label(cid)
                size = len(graph.cluster_members(cid))
                topic_info.append({
                    "cluster_id": cid,
                    "relevance": score,
                    "labels": labels,
                    "size": size,
                })

        return DeepQueryResult(
            question=question,
            subqueries=subqueries,
            facets=facets,
            results=final_results,
            sources=sources,
            relevant_topics=topic_info,
        )

    # ---- Answer Synthesis ----

    def synthesize(
        self,
        question: str,
        *,
        k: int = 10,
        context_window: int = 1,
        hops: int = 2,
        max_context_chars: int = 30000,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> "SynthesisResult":
        """Full-stack retrieval and synthesis for answering complex questions.

        This is the highest-level reasoning method. It combines:
        1. Multi-hop retrieval (reason) for breadth
        2. Context expansion for depth within documents
        3. Source grouping for cross-document analysis
        4. Evidence chain construction for traceability
        5. Formatted output ready for LLM consumption

        Args:
            question: Complex natural language question.
            k: Number of seed results per retrieval step.
            context_window: Chunks before/after each seed to include.
            hops: Number of multi-hop expansion rounds.
            max_context_chars: Maximum characters in the output context.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        t0_synth = _time.time()
        audit = self._audit.begin("synthesize", question)

        # Step 1: Multi-hop retrieval
        t_step = _time.time()
        reasoning = self.reason(question, k=k, hops=hops, valid_at=valid_at, tx_id=tx_id)
        if audit:
            audit.add("reason", f"Multi-hop retrieval ({hops} hops)",
                      {"k": k, "hops": hops},
                      {"total_chunks": reasoning.total_chunks,
                       "source_count": reasoning.source_count,
                       "hops_completed": reasoning.total_hops},
                      (_time.time() - t_step) * 1000)

        # Step 1b: Diversify seed results for cross-source coverage
        t_step = _time.time()
        diversified = self._diversify_results(reasoning.results, max_per_source=3)
        if audit:
            div_sources = set()
            for r in diversified:
                core = self.store.cores.get(r.core_id)
                div_sources.add(core.slots.get("source", "?") if core else "?")
            audit.add("diversify", "Round-robin source diversification",
                      {"input_count": len(reasoning.results), "max_per_source": 3},
                      {"output_count": len(diversified),
                       "unique_sources": len(div_sources)},
                      (_time.time() - t_step) * 1000)

        # Step 2: Expand context for each seed, grouped by source
        t_step = _time.time()
        seed_groups: dict[str, list[SearchResult]] = {}  # source -> expanded chunks
        seen: set[str] = set()

        for r in diversified:
            if r.revision_id in seen:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            if context_window > 0:
                context = self.expand_context(r, window=context_window)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        seed_groups.setdefault(source, []).append(cr)
            else:
                seen.add(r.revision_id)
                seed_groups.setdefault(source, []).append(r)

        if audit:
            total_expanded = sum(len(v) for v in seed_groups.values())
            audit.add("expand", f"Context expansion (window={context_window})",
                      {"context_window": context_window, "seed_count": len(diversified)},
                      {"expanded_count": total_expanded,
                       "source_groups": len(seed_groups)},
                      (_time.time() - t_step) * 1000)

        # Step 2b: Interleave sources for diversity in final result order
        t_step = _time.time()
        for source in seed_groups:
            seed_groups[source].sort(key=lambda r: -r.score)

        sorted_group_keys = sorted(
            seed_groups.keys(),
            key=lambda s: -seed_groups[s][0].score if seed_groups[s] else 0,
        )

        expanded_results: list[SearchResult] = []
        round_idx = 0
        max_per_source = max(3, context_window * 2 + 1)  # seed + neighbors
        while True:
            added = False
            for source in sorted_group_keys:
                group = seed_groups[source]
                if round_idx < len(group) and round_idx < max_per_source:
                    expanded_results.append(group[round_idx])
                    added = True
            round_idx += 1
            if not added:
                break

        if audit:
            audit.add("interleave", "Source interleaving for final ordering",
                      {"max_per_source": max_per_source,
                       "source_count": len(sorted_group_keys)},
                      {"final_count": len(expanded_results)},
                      (_time.time() - t_step) * 1000)

        # Step 3: Group by source document
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded_results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Sort chunks within each source by score (seeds before neighbors)
        for source in by_source:
            by_source[source].sort(key=lambda r: -r.score)

        # Sort sources by relevance (max seed score, not sum — avoids bulk-context bias)
        source_scores: dict[str, float] = {}
        for source, chunks in by_source.items():
            source_scores[source] = max(r.score for r in chunks) if chunks else 0.0
        sorted_sources = sorted(by_source.keys(), key=lambda s: -source_scores[s])

        # Step 4: Build structured context
        context_parts: list[str] = []
        context_parts.append(f"# Research Context: {question}\n")
        context_parts.append(
            f"Retrieved {len(expanded_results)} chunks from "
            f"{len(by_source)} sources via {reasoning.total_hops}-hop retrieval.\n"
        )

        total_chars = 0
        source_summaries: list[dict[str, Any]] = []

        for source in sorted_sources:
            chunks = by_source[source]
            if total_chars >= max_context_chars:
                break

            context_parts.append(f"\n## Source: {source}")
            context_parts.append(f"({len(chunks)} relevant chunks)\n")

            for chunk in chunks:
                remaining = max_context_chars - total_chars
                if remaining <= 0:
                    break
                text = chunk.text[:remaining]
                score_label = f" [relevance: {chunk.score:.3f}]" if chunk.score > 0 else ""
                context_parts.append(f"### Chunk{score_label}")
                context_parts.append(text)
                context_parts.append("")
                total_chars += len(text)

            source_summaries.append({
                "source": source,
                "chunks": len(chunks),
                "relevance": source_scores[source],
            })

        # Step 5: Extract key themes
        t_step = _time.time()
        all_text = " ".join(r.text[:200] for r in expanded_results[:20])
        themes = self._extract_key_terms(all_text, max_terms=8)
        if audit:
            audit.add("themes", "Key theme extraction",
                      {"text_sample_count": min(20, len(expanded_results))},
                      {"themes": themes},
                      (_time.time() - t_step) * 1000)

        if audit:
            audit.add("assemble", "Build structured context",
                      {"max_context_chars": max_context_chars,
                       "sources_included": len(source_summaries)},
                      {"context_chars": total_chars,
                       "source_summaries": [s["source"][:40] for s in source_summaries[:5]]},
                      0.0)  # assembly time already included in above steps
            self._audit.finish(audit, t0_synth)

        return SynthesisResult(
            question=question,
            results=expanded_results,
            sources=by_source,
            source_summaries=source_summaries,
            themes=themes,
            context="\n".join(context_parts),
            reasoning_trace=reasoning.trace,
            total_chunks=len(expanded_results),
        )

    # ---- Adaptive Retrieval ----

    def ask(
        self,
        question: str,
        *,
        k: int = 10,
        strategy: str = "auto",
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Intelligent adaptive retrieval — the single entry point for all queries.

        Automatically classifies the query and selects the best retrieval
        strategy:

        - "factual": Direct search + re-rank for specific fact lookup
        - "comparison": Search both terms, cross-document analysis
        - "exploratory": Multi-hop + graph traversal for open-ended questions
        - "multi-aspect": Decompose and search each aspect independently
        - "auto": Classify automatically (default)

        Args:
            question: Any natural language question.
            k: Maximum seed results.
            strategy: Override the automatic strategy selection.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            SynthesisResult with organized, source-attributed context.
        """
        t0 = _time.time()
        audit = self._audit.begin("ask", question)

        # Classification
        t_classify = _time.time()
        if strategy == "auto":
            strategy = self._classify_query(question)
        if audit:
            audit.strategy = strategy
            audit.add("classify", f"Query classified as '{strategy}'",
                      {"question": question, "input_strategy": "auto"},
                      {"strategy": strategy},
                      (_time.time() - t_classify) * 1000)

        # Dispatch
        t_dispatch = _time.time()
        if strategy == "factual":
            result = self._retrieve_factual(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "comparison":
            result = self._retrieve_comparison(question, k=k, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "exploratory":
            result = self.synthesize(question, k=k, context_window=1, hops=3, valid_at=valid_at, tx_id=tx_id)
        elif strategy == "multi-aspect":
            result = self._retrieve_multi_aspect(question, k=k, valid_at=valid_at, tx_id=tx_id)
        else:
            result = self.synthesize(question, k=k, context_window=1, hops=2, valid_at=valid_at, tx_id=tx_id)

        if audit:
            # Collect result summary
            top_sources = []
            for r in result.results[:5]:
                core = self.store.cores.get(r.core_id)
                source = core.slots.get("source", "?") if core else "?"
                top_sources.append(f"[{r.score:.3f}] {source[:40]}")

            audit.add("dispatch", f"Retrieved via '{strategy}' strategy",
                      {"strategy": strategy, "k": k,
                       "valid_at": str(valid_at), "tx_id": tx_id},
                      {"total_chunks": result.total_chunks,
                       "source_count": result.source_count,
                       "themes": result.themes,
                       "top_5": top_sources},
                      (_time.time() - t_dispatch) * 1000)
            self._audit.finish(audit, t0)

        return result

    def _classify_query(self, question: str) -> str:
        """Classify a query into a retrieval strategy type.

        Uses heuristic patterns to determine query intent:
        - Comparison: "vs", "compare", "difference between", "better than"
        - Multi-aspect: conjunctions, multiple topics, "and", complex structure
        - Factual: "what is", "define", "how does", short and specific
        - Exploratory: "why", "explain", "how", open-ended
        """
        q = question.lower().strip()

        # Comparison patterns
        comparison_patterns = [
            r'\bvs\.?\b', r'\bversus\b', r'\bcompare\b', r'\bcompari',
            r'\bdifference\s+between\b', r'\bbetter\s+than\b',
            r'\badvantages?\s+(?:of|over)\b', r'\bpros?\s+and\s+cons?\b',
        ]
        for pat in comparison_patterns:
            if re.search(pat, q):
                return "comparison"

        # Multi-aspect: multiple conjunctions, long queries
        conjunctions = len(re.findall(r'\b(?:and|or|also|additionally)\b', q))
        if conjunctions >= 2 or len(q) > 150:
            return "multi-aspect"

        # Factual: short, specific, "what is"
        factual_patterns = [
            r'^what\s+is\b', r'^define\b', r'^who\s+(?:is|was|are)\b',
            r'^when\s+(?:did|was|is)\b', r'^where\s+(?:is|was|are)\b',
        ]
        for pat in factual_patterns:
            if re.search(pat, q):
                return "factual"

        # Exploratory: open-ended questions (check before short-query fallback)
        exploratory_patterns = [
            r'^why\b', r'^how\s+(?:do|does|can|could|should|have|has|did)\b',
            r'^explain\b', r'\bimpact\b', r'\bimplication',
            r'\bfuture\b', r'\btrend',
            r'^which\b.*\bmost\b', r'^what\b.*\bmost\b',  # superlative questions
            r'\bevolved?\b', r'\bchanged?\b', r'\bsuperseded\b',
            r'\blimitation', r'\bfundamental\b', r'\bpromising\b',
            r'\bconflict', r'\bcontradic',
        ]
        for pat in exploratory_patterns:
            if re.search(pat, q):
                return "exploratory"

        # Short queries are usually factual
        if len(q.split()) <= 4:
            return "factual"

        # Default to exploratory for longer questions
        if len(q.split()) > 8:
            return "exploratory"

        return "factual"

    def _retrieve_factual(
        self,
        question: str,
        *,
        k: int = 5,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Factual retrieval: direct search, high precision."""
        results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)

        # Expand top result for context
        expanded: list[SearchResult] = []
        seen: set[str] = set()

        if results:
            context = self.expand_context(results[0], window=1)
            for r in context:
                if r.revision_id not in seen:
                    seen.add(r.revision_id)
                    expanded.append(r)

        for r in results[1:]:
            if r.revision_id not in seen:
                seen.add(r.revision_id)
                expanded.append(r)

        # Build synthesis
        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Answer Context: {question}\n"]
        for r in expanded[:k]:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "?") if core else "?"
            context_parts.append(f"## From: {source}")
            context_parts.append(r.text[:1000])
            context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=self._extract_key_terms(" ".join(r.text[:200] for r in expanded[:5]), max_terms=5),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(results), "new": len(results)}],
            total_chunks=len(expanded),
        )

    def _retrieve_comparison(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Comparison retrieval: search for both sides, cross-reference."""
        # Extract the two sides of the comparison
        sides = re.split(r'\s+(?:vs\.?|versus|compared?\s+to|or)\s+', question, flags=re.IGNORECASE)

        all_results: dict[str, SearchResult] = {}
        side_results: dict[str, list[SearchResult]] = {}

        for side in sides:
            side = side.strip().rstrip("?.,!")
            if len(side) < 3:
                continue
            results = self.query(side, k=k // 2, valid_at=valid_at, tx_id=tx_id)
            side_results[side] = results
            for r in results:
                all_results[r.revision_id] = r

        # Also search the full question
        full_results = self.query(question, k=k, valid_at=valid_at, tx_id=tx_id)
        for r in full_results:
            all_results[r.revision_id] = r

        final = sorted(all_results.values(), key=lambda r: -r.score)

        # Build structured comparison context
        by_source: dict[str, list[SearchResult]] = {}
        for r in final:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Comparison: {question}\n"]
        for side, results in side_results.items():
            context_parts.append(f"## Perspective: {side}")
            for r in results[:k // 2]:
                context_parts.append(r.text[:800])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=final,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=list(side_results.keys()),
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(full_results), "new": len(full_results)}],
            total_chunks=len(final),
        )

    def _retrieve_multi_aspect(
        self,
        question: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> SynthesisResult:
        """Multi-aspect retrieval: decompose and search each aspect."""
        # Use query_deep for decomposition
        deep = self.query_deep(question, k_per_subquery=k // 3, max_subqueries=4, valid_at=valid_at, tx_id=tx_id)

        # Expand top results with context
        expanded: list[SearchResult] = []
        seen: set[str] = set()
        for r in deep.results:
            if r.revision_id not in seen:
                context = self.expand_context(r, window=1)
                for cr in context:
                    if cr.revision_id not in seen:
                        seen.add(cr.revision_id)
                        expanded.append(cr)

        by_source: dict[str, list[SearchResult]] = {}
        for r in expanded:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        context_parts = [f"# Multi-Aspect Analysis: {question}\n"]
        for facet in deep.facets:
            context_parts.append(f"## Aspect: {facet.subquery}")
            for r in facet.results[:3]:
                context_parts.append(r.text[:600])
                context_parts.append("")

        return SynthesisResult(
            question=question,
            results=expanded,
            sources=by_source,
            source_summaries=[
                {"source": s, "chunks": len(c), "relevance": sum(r.score for r in c)}
                for s, c in by_source.items()
            ],
            themes=deep.subqueries,
            context="\n".join(context_parts),
            reasoning_trace=[{"hop": 0, "results": len(deep.results), "new": len(deep.results)}],
            total_chunks=len(expanded),
        )

    # ---- Knowledge Timeline ----

    def timeline(
        self,
        topic: str,
        *,
        k: int = 20,
    ) -> list[dict[str, Any]]:
        """Show how knowledge about a topic evolved over time.

        Returns a chronological view of claims related to a topic, ordered
        by transaction time (when the knowledge was recorded). This enables
        questions like "how has our understanding of X changed?"

        Args:
            topic: Topic to trace through time.
            k: Maximum chunks to analyze.

        Returns:
            List of timeline entries, each with:
              - revision_id: str
              - text: str (chunk content)
              - source: str
              - recorded_at: str (ISO timestamp)
              - tx_id: int
              - valid_from: str (ISO timestamp)
              - valid_until: str | None
              - status: str ("asserted" or "retracted")
              - score: float (relevance to topic)
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k)

        entries: list[dict[str, Any]] = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev is None:
                continue

            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"

            entries.append({
                "revision_id": r.revision_id,
                "text": r.text[:500],
                "source": source,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
                "tx_id": rev.transaction_time.tx_id,
                "valid_from": rev.valid_time.start.isoformat(),
                "valid_until": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
                "status": rev.status,
                "score": r.score,
            })

        # Sort chronologically by transaction time
        entries.sort(key=lambda e: e["recorded_at"])
        return entries

    def timeline_diff(
        self,
        topic: str,
        *,
        tx_id_a: int,
        tx_id_b: int,
        k: int = 20,
    ) -> dict[str, Any]:
        """Compare what was known about a topic at two different points in time.

        Returns chunks that appear in one time but not the other, enabling
        "what changed between version A and version B?" analysis.

        Args:
            topic: Topic to compare.
            tx_id_a: Earlier transaction time.
            tx_id_b: Later transaction time.
            k: Maximum chunks per query.

        Returns:
            Dict with:
              - only_in_a: chunks visible at tx_id_a but not tx_id_b
              - only_in_b: chunks visible at tx_id_b but not tx_id_a
              - in_both: chunks visible at both times
              - summary: human-readable diff summary
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)

        results_a = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_a)
        results_b = self.query(topic, k=k, valid_at=far_future, tx_id=tx_id_b)

        ids_a = {r.revision_id for r in results_a}
        ids_b = {r.revision_id for r in results_b}

        only_a = [r for r in results_a if r.revision_id not in ids_b]
        only_b = [r for r in results_b if r.revision_id not in ids_a]
        both = [r for r in results_b if r.revision_id in ids_a]

        summary_parts = [f"Topic: {topic}"]
        summary_parts.append(f"At tx_id={tx_id_a}: {len(results_a)} chunks")
        summary_parts.append(f"At tx_id={tx_id_b}: {len(results_b)} chunks")
        summary_parts.append(f"Added: {len(only_b)}, Removed: {len(only_a)}, Unchanged: {len(both)}")

        return {
            "only_in_a": only_a,
            "only_in_b": only_b,
            "in_both": both,
            "summary": " | ".join(summary_parts),
        }

    # ---- Provenance & Citation ----

    def provenance_of(self, result: SearchResult) -> dict[str, Any]:
        """Get full provenance for a search result.

        Returns structured provenance data including source document,
        page number, chunk position, ingestion time, and confidence.

        Args:
            result: A SearchResult from any query method.

        Returns:
            Dict with source, page, chunk_idx, ingested_at, valid_time,
            confidence_bp, and raw provenance.
        """
        rev = self.store.revisions.get(result.revision_id)
        if rev is None:
            return {"error": "revision not found", "revision_id": result.revision_id}

        core = self.store.cores.get(result.core_id)

        info: dict[str, Any] = {
            "revision_id": result.revision_id,
            "core_id": result.core_id,
            "source": rev.provenance.source if rev.provenance else "unknown",
            "evidence_ref_length": len(rev.provenance.evidence_ref) if rev.provenance and rev.provenance.evidence_ref else 0,
            "confidence_bp": rev.confidence_bp,
            "status": rev.status,
            "valid_time": {
                "start": rev.valid_time.start.isoformat(),
                "end": rev.valid_time.end.isoformat() if rev.valid_time.end else None,
            },
            "transaction_time": {
                "tx_id": rev.transaction_time.tx_id,
                "recorded_at": rev.transaction_time.recorded_at.isoformat(),
            },
        }

        # Extract structured fields from claim slots
        if core:
            info["claim_type"] = core.claim_type
            if "source" in core.slots:
                info["document"] = core.slots["source"]
            if "page_start" in core.slots:
                info["page"] = int(core.slots["page_start"])
            if "chunk_idx" in core.slots:
                info["chunk_index"] = int(core.slots["chunk_idx"])

        return info

    def cite(
        self,
        result: SearchResult,
        *,
        style: str = "inline",
    ) -> str:
        """Generate a formatted citation for a search result.

        Args:
            result: A SearchResult from any query method.
            style: Citation style — "inline", "full", or "markdown".

        Returns:
            Formatted citation string.
        """
        prov = self.provenance_of(result)
        if "error" in prov:
            return f"[unknown source]"

        source = prov.get("document", prov.get("source", "unknown"))
        page = prov.get("page")
        chunk_idx = prov.get("chunk_index")
        tx_time = prov.get("transaction_time", {}).get("recorded_at", "")

        if style == "inline":
            parts = [source]
            if page is not None:
                parts.append(f"p.{page}")
            return f"[{', '.join(parts)}]"

        elif style == "markdown":
            parts = [f"**{source}**"]
            if page is not None:
                parts.append(f"page {page}")
            if chunk_idx is not None:
                parts.append(f"chunk {chunk_idx}")
            return " | ".join(parts)

        else:  # full
            parts = [f"Source: {source}"]
            if page is not None:
                parts.append(f"Page: {page}")
            if chunk_idx is not None:
                parts.append(f"Chunk: {chunk_idx}")
            parts.append(f"Confidence: {prov.get('confidence_bp', 0)}/10000")
            if tx_time:
                parts.append(f"Ingested: {tx_time[:10]}")
            return " | ".join(parts)

    def cite_results(
        self,
        results: list[SearchResult],
        *,
        style: str = "inline",
        deduplicate: bool = True,
    ) -> list[str]:
        """Generate citations for a list of search results.

        Args:
            results: List of SearchResult from any query method.
            style: Citation style.
            deduplicate: If True, skip duplicate sources.

        Returns:
            List of formatted citation strings.
        """
        citations: list[str] = []
        seen_sources: set[str] = set()

        for r in results:
            citation = self.cite(r, style=style)
            if deduplicate:
                prov = self.provenance_of(r)
                source_key = prov.get("document", prov.get("source", r.revision_id))
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
            citations.append(citation)

        return citations

    def query_by_source(
        self,
        source: str,
        *,
        k: int = 50,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[SearchResult]:
        """Retrieve all chunks from a specific source document.

        Args:
            source: Source document name (or partial match).
            k: Maximum results.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of SearchResult from the specified source.
        """
        results: list[SearchResult] = []
        source_lower = source.lower()
        retracted_cores = self.store.retracted_core_ids()

        for rid, rev in self.store.revisions.items():
            if len(results) >= k:
                break

            if rev.status != "asserted" or rev.core_id in retracted_cores:
                continue

            core = self.store.cores.get(rev.core_id)
            if core is None:
                continue

            doc_source = core.slots.get("source", "")
            if source_lower not in doc_source.lower():
                continue

            # Apply temporal filter
            if valid_at is not None and tx_id is not None:
                winner = self.store.query_as_of(
                    rev.core_id, valid_at=valid_at, tx_id=tx_id,
                )
                if winner is None or winner.revision_id != rid:
                    continue

            results.append(SearchResult(
                core_id=rev.core_id,
                revision_id=rid,
                score=1.0,
                text=rev.assertion,
            ))

        return results

    # ---- Semantic Deduplication ----

    def deduplicate(
        self,
        *,
        threshold: float = 0.85,
        k: int = 100,
    ) -> list[list[SearchResult]]:
        """Find clusters of near-duplicate chunks across documents.

        Uses TF-IDF pairwise similarity to identify chunks that say
        essentially the same thing. Useful for corpus quality analysis.

        Args:
            threshold: Minimum similarity to consider as duplicate (0-1).
            k: Maximum chunks to analyze. Set high for full corpus scan.

        Returns:
            List of duplicate clusters (each cluster is a list of SearchResult).
            Only returns clusters with 2+ members.
        """
        from .index import TfidfSearchIndex, HybridSearchIndex

        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None or not tfidf._fitted:
            return []

        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return []

        # Use the full TF-IDF matrix
        n = min(len(tfidf._texts), k)
        if n < 2:
            return []

        sim_matrix = cosine_similarity(tfidf._matrix[:n])

        # Union-find for clustering
        parent: dict[int, int] = {i: i for i in range(n)}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if float(sim_matrix[i][j]) >= threshold:
                    union(i, j)

        # Group by cluster
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            clusters.setdefault(root, []).append(i)

        # Build results — only clusters with 2+ active members
        retracted = self.store.retracted_core_ids()
        result: list[list[SearchResult]] = []
        for members in clusters.values():
            if len(members) < 2:
                continue
            cluster_results = []
            for idx in members:
                rid = tfidf._revision_ids[idx]
                rev = self.store.revisions.get(rid)
                if rev and rev.status == "asserted" and rev.core_id not in retracted:
                    cluster_results.append(SearchResult(
                        core_id=rev.core_id,
                        revision_id=rid,
                        score=1.0,
                        text=tfidf._texts[idx],
                    ))
            if len(cluster_results) >= 2:
                result.append(cluster_results)

        # Sort by cluster size (largest first)
        result.sort(key=lambda c: -len(c))
        return result

    # ---- Query Explanation ----

    def explain(
        self,
        question: str,
        result: SearchResult,
    ) -> dict[str, Any]:
        """Explain why a specific result was returned for a question.

        Provides feature attribution showing which terms matched,
        the similarity score breakdown, and contextual factors.

        Args:
            question: The original query.
            result: A SearchResult to explain.

        Returns:
            Dict with:
              - question: str
              - result_text: str (first 200 chars)
              - score: float
              - matching_terms: list[str] (shared terms)
              - question_unique_terms: list[str]
              - result_unique_terms: list[str]
              - term_overlap_ratio: float
              - source: str
              - provenance: dict
              - graph_distance: int | None (if graph exists)
        """
        # Extract terms
        q_terms = set(re.findall(r'\b\w{3,}\b', question.lower())) - _STOP_WORDS
        r_terms = set(re.findall(r'\b\w{3,}\b', result.text.lower())) - _STOP_WORDS

        matching = q_terms & r_terms
        q_unique = q_terms - r_terms
        r_unique = r_terms - q_terms

        overlap_ratio = len(matching) / max(len(q_terms), 1)

        # Provenance
        prov = self.provenance_of(result)

        # Graph distance
        graph_distance = None
        graph = self._graph
        if graph is not None:
            # Try to find the shortest path from any query result to this result
            query_results = self.query(question, k=3)
            for qr in query_results:
                if qr.revision_id == result.revision_id:
                    graph_distance = 0
                    break
                path = graph.path_between(qr.revision_id, result.revision_id)
                if path is not None:
                    d = len(path) - 1
                    if graph_distance is None or d < graph_distance:
                        graph_distance = d

        return {
            "question": question,
            "result_text": result.text[:200],
            "score": result.score,
            "matching_terms": sorted(matching),
            "question_unique_terms": sorted(q_unique),
            "result_unique_terms": sorted(r_unique)[:20],
            "term_overlap_ratio": round(overlap_ratio, 3),
            "source": prov.get("document", prov.get("source", "unknown")),
            "provenance": prov,
            "graph_distance": graph_distance,
        }

    # ---- Answer Extraction ----

    def extract_answer(
        self,
        question: str,
        results: list[SearchResult] | None = None,
        *,
        k: int = 10,
        max_sentences: int = 5,
        min_relevance: float = 0.1,
    ) -> dict[str, Any]:
        """Extract the most relevant answer sentences from retrieved chunks.

        Performs sentence-level re-ranking against the question to find
        the specific passages that best answer it, without requiring an LLM.

        Args:
            question: The question to answer.
            results: Pre-retrieved results (auto-retrieves if None).
            k: Number of chunks to consider (if auto-retrieving).
            max_sentences: Maximum answer sentences to return.
            min_relevance: Minimum sentence relevance score (0-1).

        Returns:
            Dict with:
              - question: str
              - answer_sentences: list of {text, score, source, chunk_rank}
              - supporting_chunks: list of {text_preview, score, source}
              - confidence: float (0-1, based on answer quality)
              - source_count: int
        """
        if results is None:
            results = self.query(question, k=k)

        if not results:
            return {
                "question": question,
                "answer_sentences": [],
                "supporting_chunks": [],
                "confidence": 0.0,
                "source_count": 0,
            }

        # Extract question terms for scoring
        q_terms = [w for w in re.findall(r'\b\w{3,}\b', question.lower())
                    if w not in _STOP_WORDS]
        q_term_set = set(q_terms)

        # Collect all sentences for IDF computation
        all_sentences: list[tuple[str, str, int]] = []  # (text, source, chunk_rank)
        for chunk_rank, result in enumerate(results[:k]):
            core = self.store.cores.get(result.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sentences = re.split(r'(?<=[.!?])\s+', result.text)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) >= 20:
                    all_sentences.append((sent, source, chunk_rank))

        if not all_sentences:
            return {
                "question": question,
                "answer_sentences": [],
                "supporting_chunks": [],
                "confidence": 0.0,
                "source_count": 0,
            }

        # Compute IDF for query terms across all sentences
        n_docs = len(all_sentences)
        doc_freq: dict[str, int] = {}
        for sent, _, _ in all_sentences:
            s_terms = set(re.findall(r'\b\w{3,}\b', sent.lower())) - _STOP_WORDS
            for term in q_term_set & s_terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        # BM25 parameters
        bm25_k1 = 1.2
        bm25_b = 0.75
        avg_len = sum(len(s[0].split()) for s in all_sentences) / max(n_docs, 1)

        # Score each sentence with BM25
        scored_sentences: list[dict[str, Any]] = []

        for sent, source, chunk_rank in all_sentences:
            s_words = re.findall(r'\b\w{3,}\b', sent.lower())
            s_terms = set(s_words) - _STOP_WORDS
            if not s_terms:
                continue

            # BM25 score
            doc_len = len(s_words)
            bm25_score = 0.0
            for term in q_term_set:
                if term not in s_terms:
                    continue
                tf = s_words.count(term)
                df = doc_freq.get(term, 0)
                idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (tf * (bm25_k1 + 1)) / (
                    tf + bm25_k1 * (1 - bm25_b + bm25_b * doc_len / max(avg_len, 1))
                )
                bm25_score += idf * tf_norm

            if bm25_score <= 0:
                continue

            # Normalize to 0-1 range (approximate)
            max_possible = len(q_term_set) * math.log(n_docs + 1) * (bm25_k1 + 1)
            score = min(bm25_score / max(max_possible, 1), 1.0)

            # Informativeness bonus: sentences that add beyond the query
            info_ratio = len(s_terms - q_term_set) / max(len(s_terms), 1)
            score = score * 0.8 + min(info_ratio, 0.8) * 0.2

            # Chunk rank discount (earlier chunks more relevant)
            rank_discount = 1.0 / (1.0 + chunk_rank * 0.1)
            score *= rank_discount

            scored_sentences.append({
                "text": sent,
                "score": round(score, 4),
                "source": source,
                "chunk_rank": chunk_rank,
                "overlap_terms": sorted(q_term_set & s_terms),
            })

        # Sort by score and deduplicate near-identical sentences
        scored_sentences.sort(key=lambda x: -x["score"])

        answer_sentences = []
        seen_text: set[str] = set()

        for s in scored_sentences:
            if s["score"] < min_relevance:
                break
            # Dedup: skip if >60% word overlap with already selected sentence
            s_words = set(s["text"].lower().split())
            is_dup = False
            for existing in answer_sentences:
                e_words = set(existing["text"].lower().split())
                jaccard = len(s_words & e_words) / max(len(s_words | e_words), 1)
                if jaccard > 0.6:
                    is_dup = True
                    break
            if not is_dup:
                answer_sentences.append(s)
            if len(answer_sentences) >= max_sentences:
                break

        # Supporting chunks summary
        supporting = []
        sources = set()
        for result in results[:k]:
            core = self.store.cores.get(result.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            sources.add(source)
            supporting.append({
                "text_preview": result.text[:150],
                "score": round(result.score, 4),
                "source": source,
            })

        # Confidence based on answer quality
        if answer_sentences:
            avg_score = sum(s["score"] for s in answer_sentences) / len(answer_sentences)
            coverage = min(len(answer_sentences) / max_sentences, 1.0)
            source_diversity = min(len(sources) / 3, 1.0)
            confidence = avg_score * 0.5 + coverage * 0.3 + source_diversity * 0.2
        else:
            confidence = 0.0

        return {
            "question": question,
            "answer_sentences": answer_sentences,
            "supporting_chunks": supporting[:5],
            "confidence": round(confidence, 3),
            "source_count": len(sources),
        }

    def answer(
        self,
        question: str,
        *,
        k: int = 10,
        hops: int = 2,
        max_sentences: int = 5,
    ) -> dict[str, Any]:
        """Full pipeline: retrieve + reason + extract answer.

        This is the highest-level answering method. It combines multi-hop
        retrieval with sentence-level answer extraction.

        Args:
            question: Any natural language question.
            k: Number of seed results.
            hops: Multi-hop reasoning depth.
            max_sentences: Maximum answer sentences.

        Returns:
            Dict with question, answer_sentences, supporting_chunks,
            confidence, source_count, strategy, and audit trace (if enabled).
        """
        t0 = _time.time()
        audit = self._audit.begin("answer", question)

        # Step 1: Classify and retrieve
        strategy = self._classify_query(question)
        if audit:
            audit.strategy = strategy
            audit.add("classify", f"Query classified as '{strategy}'",
                      {"question": question}, {"strategy": strategy},
                      (_time.time() - t0) * 1000)

        # Step 2: Retrieve using best strategy
        t_retrieve = _time.time()
        if strategy == "factual":
            results = self.query(question, k=k)
        else:
            reasoning = self.reason(question, k=k, hops=hops)
            results = reasoning.results

        if audit:
            audit.add("retrieve", f"Retrieved {len(results)} chunks",
                      {"strategy": strategy, "k": k},
                      {"chunk_count": len(results)},
                      (_time.time() - t_retrieve) * 1000)

        # Step 3: Extract answer
        t_extract = _time.time()
        answer = self.extract_answer(question, results,
                                     max_sentences=max_sentences)
        if audit:
            audit.add("extract", f"Extracted {len(answer['answer_sentences'])} answer sentences",
                      {"max_sentences": max_sentences},
                      {"sentence_count": len(answer["answer_sentences"]),
                       "confidence": answer["confidence"]},
                      (_time.time() - t_extract) * 1000)
            self._audit.finish(audit, t0)

        answer["strategy"] = strategy
        return answer

    # ---- Contradiction Detection ----

    def contradictions(
        self,
        topic: str,
        *,
        k: int = 20,
        similarity_threshold: float = 0.15,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Find potential contradictions in the knowledge base about a topic.

        Searches for chunks that are topically similar but come from different
        sources, then applies negation and opposition detection to find conflicts.

        Args:
            topic: Topic to search for contradictions.
            k: Number of chunks to analyze.
            similarity_threshold: Minimum TF-IDF similarity between chunks.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.

        Returns:
            List of contradiction dicts, each with:
              - chunk_a: SearchResult
              - chunk_b: SearchResult
              - source_a: str
              - source_b: str
              - similarity: float (topical similarity)
              - conflict_signals: list[str] (what triggered the detection)
              - confidence_bp: int (0-10000, how likely this is a real contradiction)
        """
        from .index import TfidfSearchIndex, HybridSearchIndex

        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(topic, k=k, valid_at=valid_at, tx_id=tx_id)
        if len(results) < 2:
            return []

        # Get source for each result
        result_sources: dict[str, str] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            result_sources[r.revision_id] = (
                core.slots.get("source", "unknown") if core else "unknown"
            )

        # Compute pairwise similarity using TF-IDF
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        pairs_with_similarity: list[tuple[int, int, float]] = []

        if tfidf is not None and tfidf._fitted:
            try:
                from sklearn.metrics.pairwise import cosine_similarity
                texts = [r.text for r in results]
                vecs = tfidf._vectorizer.transform(texts)
                sim_matrix = cosine_similarity(vecs)

                for i in range(len(results)):
                    for j in range(i + 1, len(results)):
                        sim = float(sim_matrix[i][j])
                        if sim >= similarity_threshold:
                            # Only consider cross-source pairs
                            if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                                pairs_with_similarity.append((i, j, sim))
            except (ValueError, ImportError, AttributeError):
                pass

        if not pairs_with_similarity:
            # Fallback: compare all cross-source pairs
            for i in range(len(results)):
                for j in range(i + 1, len(results)):
                    if result_sources[results[i].revision_id] != result_sources[results[j].revision_id]:
                        pairs_with_similarity.append((i, j, 0.5))

        # Detect contradiction signals
        negation_words = _NEGATION_WORDS
        opposition_pairs = [
            ("increase", "decrease"), ("improve", "worsen"), ("better", "worse"),
            ("higher", "lower"), ("more", "less"), ("faster", "slower"),
            ("larger", "smaller"), ("stronger", "weaker"), ("efficient", "inefficient"),
            ("effective", "ineffective"), ("successful", "unsuccessful"),
            ("advantage", "disadvantage"), ("benefit", "drawback"),
            ("outperform", "underperform"), ("superior", "inferior"),
            ("significant", "insignificant"), ("positive", "negative"),
            ("optimal", "suboptimal"), ("accurate", "inaccurate"),
        ]

        contradictions: list[dict[str, Any]] = []

        for i, j, sim in pairs_with_similarity:
            a, b = results[i], results[j]
            a_words = set(re.findall(r'\b\w+\b', a.text.lower()))
            b_words = set(re.findall(r'\b\w+\b', b.text.lower()))

            signals: list[str] = []
            confidence = 0

            # Signal 1: One has negation of shared concept
            a_negations = a_words & negation_words
            b_negations = b_words & negation_words
            if a_negations and not b_negations:
                signals.append(f"negation in A: {', '.join(a_negations)}")
                confidence += 2000
            elif b_negations and not a_negations:
                signals.append(f"negation in B: {', '.join(b_negations)}")
                confidence += 2000

            # Signal 2: Opposition word pairs
            for pos, neg in opposition_pairs:
                if pos in a_words and neg in b_words:
                    signals.append(f"opposition: A='{pos}' vs B='{neg}'")
                    confidence += 3000
                elif neg in a_words and pos in b_words:
                    signals.append(f"opposition: A='{neg}' vs B='{pos}'")
                    confidence += 3000

            # Signal 3: Numerical disagreement on same topic
            a_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', a.text))
            b_nums = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', b.text))
            shared_context = a_words & b_words - negation_words
            if a_nums and b_nums and a_nums != b_nums and len(shared_context) > 5:
                signals.append(f"different numbers: A={a_nums} vs B={b_nums}")
                confidence += 1500

            # Signal 4: High topical similarity + different sources = potential conflict
            if sim > 0.4:
                signals.append(f"high similarity ({sim:.2f}) across sources")
                confidence += 1000

            if signals:
                confidence = min(confidence, 10000)
                contradictions.append({
                    "chunk_a": a,
                    "chunk_b": b,
                    "source_a": result_sources[a.revision_id],
                    "source_b": result_sources[b.revision_id],
                    "similarity": sim,
                    "conflict_signals": signals,
                    "confidence_bp": confidence,
                })

        # Sort by confidence
        contradictions.sort(key=lambda c: -c["confidence_bp"])
        return contradictions

    def confidence(
        self,
        claim: str,
        *,
        k: int = 10,
        valid_at: Optional[datetime] = None,
        tx_id: Optional[int] = None,
        recency_window_years: int = 5,
    ) -> dict[str, Any]:
        """Assess confidence in a claim based on evidence in the store.

        Scores a claim based on:
        1. Source diversity (more independent sources = higher confidence)
        2. Internal consistency (do sources agree?)
        3. Recency (newer evidence weighted higher)
        4. Evidence density (how many relevant chunks found)

        Args:
            claim: Factual claim to evaluate.
            k: Number of chunks to analyze.
            valid_at: Temporal filter.
            tx_id: Transaction time cutoff.
            recency_window_years: Window for recency scoring (default 5).

        Returns:
            Dict with:
              - confidence_bp: int (0-10000)
              - evidence_count: int
              - source_count: int
              - supporting: int (chunks that support)
              - contradicting: int (chunks with contradiction signals)
              - recency_score: float (0-1, how recent the evidence is)
              - assessment: str ("high", "medium", "low", "insufficient")
        """
        if self._index is None:
            raise ValueError("No search index configured.")

        results = self.query(claim, k=k, valid_at=valid_at, tx_id=tx_id)
        if not results:
            return {
                "confidence_bp": 0,
                "evidence_count": 0,
                "source_count": 0,
                "supporting": 0,
                "contradicting": 0,
                "recency_score": 0.0,
                "assessment": "insufficient",
            }

        # Count unique sources
        sources: set[str] = set()
        for r in results:
            core = self.store.cores.get(r.core_id)
            if core:
                sources.add(core.slots.get("source", "unknown"))

        # Check for negation/contradiction signals vs the claim
        claim_words = set(re.findall(r'\b\w+\b', claim.lower()))
        negation_words = _NEGATION_WORDS
        claim_has_negation = bool(claim_words & negation_words)

        supporting = 0
        contradicting = 0
        for r in results:
            r_words = set(re.findall(r'\b\w+\b', r.text.lower()))
            r_has_negation = bool(r_words & negation_words)

            # If claim is positive and evidence is negative (or vice versa)
            if claim_has_negation != r_has_negation:
                contradicting += 1
            else:
                supporting += 1

        # Recency score: based on transaction times of evidence
        recency_scores = []
        for r in results:
            rev = self.store.revisions.get(r.revision_id)
            if rev:
                tx_recorded = rev.transaction_time.recorded_at
                now = datetime.now(timezone.utc)
                age_days = (now - tx_recorded).days
                recency = max(0.0, 1.0 - age_days / (365 * recency_window_years))
                recency_scores.append(recency)
        recency_score = sum(recency_scores) / len(recency_scores) if recency_scores else 0.0

        # Compute overall confidence
        confidence_val = 0

        # Source diversity (0-3000)
        source_score = min(len(sources) * 1000, 3000)
        confidence_val += source_score

        # Evidence density (0-2000)
        density_score = min(len(results) * 400, 2000)
        confidence_val += density_score

        # Consistency (0-3000)
        if supporting > 0:
            consistency = supporting / (supporting + contradicting)
            confidence_val += int(consistency * 3000)

        # Recency boost (0-2000)
        confidence_val += int(recency_score * 2000)

        confidence_val = min(confidence_val, 10000)

        # Assessment
        if len(results) < 2:
            assessment = "insufficient"
        elif confidence_val >= 7000:
            assessment = "high"
        elif confidence_val >= 4000:
            assessment = "medium"
        else:
            assessment = "low"

        return {
            "confidence_bp": confidence_val,
            "evidence_count": len(results),
            "source_count": len(sources),
            "supporting": supporting,
            "contradicting": contradicting,
            "recency_score": round(recency_score, 3),
            "assessment": assessment,
        }

    # ---- Private Helpers ----

    def _decompose_question(
        self,
        question: str,
        max_parts: int = 5,
    ) -> list[str]:
        """Decompose a complex question into simpler sub-questions.

        Uses multi-strategy heuristic decomposition:
        1. Clause splitting: "What is X and how does Y?" → two questions
        2. Contrast extraction: "difference between A and B" → A, B, A vs B
        3. Temporal decomposition: "how has X evolved?" → past, present, future
        4. Conjunction splitting: "A and B and C" → separate queries
        5. Entity extraction: pull out key noun phrases
        """
        q = question.strip().rstrip("?.,!")
        q_lower = q.lower()
        subqueries = [question]  # Always include the original

        # Strategy 1: Question clause splitting
        # "What is X and how does Y work?" → "What is X" + "how does Y work"
        clause_splits = re.split(
            r'[,;]\s*(?:and\s+)?(?:how|what|why|which|where|when|who)\b',
            q, flags=re.IGNORECASE,
        )
        if len(clause_splits) > 1:
            # Re-attach the question word that was consumed by split
            for part in clause_splits:
                part = part.strip().rstrip("?.,!")
                if len(part) > 15:
                    subqueries.append(part)

        # Strategy 2: Contrast/comparison extraction
        # "difference between A and B" → "A", "B", "A vs B"
        contrast_match = re.search(
            r'(?:difference|comparison|compare|contrast|tradeoff|trade-off)\s+'
            r'(?:between\s+)?(.+?)\s+(?:and|vs\.?|versus)\s+(.+)',
            q_lower,
        )
        if contrast_match:
            a_term = contrast_match.group(1).strip().rstrip("?.,!")
            b_term = contrast_match.group(2).strip().rstrip("?.,!")
            if len(a_term) > 3:
                subqueries.append(a_term)
            if len(b_term) > 3:
                subqueries.append(b_term)
            subqueries.append(f"{a_term} vs {b_term}")

        # Strategy 3: Temporal decomposition
        # "how has X evolved?" → "X origins", "X current state"
        temporal_match = re.search(
            r'(?:how\s+has|how\s+have|how\s+did)\s+(.+?)\s+'
            r'(?:evolved?|changed?|developed?|progressed?|grown?)',
            q_lower,
        )
        if temporal_match:
            topic = temporal_match.group(1).strip()
            if len(topic) > 3:
                subqueries.append(f"{topic} origins history")
                subqueries.append(f"{topic} current state recent")

        # Strategy 4: Conjunction splitting (broader than just "and")
        parts = re.split(
            r'\b(?:and|or|but|also|additionally|furthermore|moreover|as\s+well\s+as)\b',
            q, flags=re.IGNORECASE,
        )
        for part in parts:
            part = part.strip().rstrip("?.,!")
            if len(part) > 15 and part.lower() != q_lower:
                subqueries.append(part)

        # Strategy 5: "relate to" / "impact on" extraction
        relate_match = re.search(
            r'(?:relat(?:e|ion|ionship)|impact|effect|influence|connection)\s+'
            r'(?:between|of|on|to)\s+(.+?)\s+(?:and|on|to|with)\s+(.+)',
            q_lower,
        )
        if relate_match:
            a_term = relate_match.group(1).strip().rstrip("?.,!")
            b_term = relate_match.group(2).strip().rstrip("?.,!")
            if len(a_term) > 3:
                subqueries.append(a_term)
            if len(b_term) > 3:
                subqueries.append(b_term)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for sq in subqueries:
            normalized = sq.lower().strip()
            if normalized not in seen and len(normalized) > 5:
                seen.add(normalized)
                unique.append(sq)

        return unique[:max_parts]

    def _extract_expansion_terms(
        self,
        results: list[SearchResult],
        seen: set[str],
        max_terms: int = 3,
    ) -> list[str]:
        """Extract key terms from results for query expansion."""
        all_text = " ".join(r.text for r in results)
        terms = self._extract_key_terms(all_text, max_terms=max_terms * 2)
        # Filter already seen
        novel = [t for t in terms if t.lower().strip() not in seen]
        return novel[:max_terms]

    def _extract_key_terms(
        self,
        text: str,
        max_terms: int = 10,
    ) -> list[str]:
        """Extract key terms from text using TF-IDF or simple frequency."""
        # Use universal stop words plus additional common verbs/fillers
        # that are not discriminative for key term extraction.
        # NOTE: Domain-specific terms (ML, commercial, etc.) are intentionally
        # NOT included here — IDF filtering should handle corpus-specific noise.
        stop_words = _STOP_WORDS | {
            # Common verbs that rarely carry domain meaning
            "get", "make", "take", "come", "see", "think", "look", "want",
            "give", "use", "find", "tell", "work", "let", "put", "run",
            "try", "call", "say", "said", "know", "keep", "going", "need",
            "like", "back", "way", "new", "one", "two", "first",
            # Common filler adjectives/adverbs
            "good", "best", "great", "long", "able", "different", "right",
            "actually", "basically", "simply", "really", "well",
            "last", "next", "part", "point", "thing", "things",
            # Discourse connectives
            "however", "therefore", "thus", "hence", "often",
            "typically", "usually", "especially", "particularly", "because",
            # Generic relational
            "based", "related", "specific", "general", "common",
            "similar", "across", "within", "available", "possible",
            "called", "known", "given", "shown", "required",
            "higher", "lower", "larger", "smaller", "better",
            "result", "results", "example", "examples", "case",
        }

        # Extract words (3+ chars, alphabetic)
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        filtered = [w for w in words if w not in stop_words and len(w) > 3]

        # Count bigrams — both words must pass stop word filter
        bigrams = []
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i+1]
            if w1 not in stop_words and w2 not in stop_words and len(w1) > 3 and len(w2) > 3:
                bigrams.append(f"{w1} {w2}")

        # Combine unigram and bigram counts
        counter = Counter(filtered)
        bigram_counter = Counter(bigrams)

        # Prefer bigrams (more specific), require count >= 2
        terms: list[str] = []
        seen_words: set[str] = set()
        for term, count in bigram_counter.most_common(max_terms * 2):
            if count >= 2 and len(terms) < max_terms:
                # Skip bigrams with very short words or non-alpha chars
                parts = term.split()
                if all(len(p) > 3 and p.isalpha() for p in parts):
                    terms.append(term)
                    seen_words.update(parts)
        for term, count in counter.most_common(max_terms * 3):
            if len(terms) >= max_terms:
                break
            if term.isalpha() and term not in seen_words and term not in " ".join(terms):
                terms.append(term)

        return terms[:max_terms]

    def _diversify_results(
        self,
        results: list[SearchResult],
        *,
        max_per_source: int = 3,
    ) -> list[SearchResult]:
        """Re-order results to maximize source diversity.

        Uses a round-robin approach: take the best result from each source,
        then the second-best from each, etc. This ensures the top results
        come from diverse documents.

        Args:
            results: Results sorted by score.
            max_per_source: Maximum results from any single source.

        Returns:
            Results re-ordered for diversity.
        """
        # Group by source, preserving order within each source
        by_source: dict[str, list[SearchResult]] = {}
        for r in results:
            core = self.store.cores.get(r.core_id)
            source = core.slots.get("source", "unknown") if core else "unknown"
            by_source.setdefault(source, []).append(r)

        # Round-robin selection: best from each source, then second-best, etc.
        diversified: list[SearchResult] = []
        seen: set[str] = set()
        round_num = 0

        while len(diversified) < len(results):
            added_this_round = False
            # Sort sources by their best remaining score
            sorted_sources = sorted(
                by_source.items(),
                key=lambda x: -x[1][0].score if x[1] else 0,
            )
            for source, chunks in sorted_sources:
                if round_num < len(chunks) and round_num < max_per_source:
                    r = chunks[round_num]
                    if r.revision_id not in seen:
                        seen.add(r.revision_id)
                        diversified.append(r)
                        added_this_round = True
            round_num += 1
            if not added_this_round:
                break

        return diversified

    def _rerank_for_question(
        self,
        question: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Re-rank results by relevance to the original question."""
        from .index import TfidfSearchIndex, HybridSearchIndex

        # Get TF-IDF component for re-ranking
        tfidf = None
        if isinstance(self._index, TfidfSearchIndex):
            tfidf = self._index._tfidf
        elif isinstance(self._index, HybridSearchIndex):
            tfidf = self._index._tfidf

        if tfidf is None:
            return sorted(results, key=lambda r: -r.score)

        # Re-score against original question using TF-IDF
        if not tfidf._fitted:
            tfidf.rebuild()

        try:
            from sklearn.metrics.pairwise import cosine_similarity
            vectorizer = tfidf._vectorizer
            q_vec = vectorizer.transform([question])
            text_vecs = vectorizer.transform([r.text for r in results])
            scores = cosine_similarity(q_vec, text_vecs)[0]

            rescored = []
            for r, score in zip(results, scores):
                rescored.append(SearchResult(
                    core_id=r.core_id,
                    revision_id=r.revision_id,
                    score=float(score),
                    text=r.text,
                ))
            rescored.sort(key=lambda r: -r.score)
            return rescored
        except (ValueError, ImportError, AttributeError):
            return sorted(results, key=lambda r: -r.score)
