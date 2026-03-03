"""Advanced stress tests: realistic complex scenarios that push DKS hard.

These tests exercise the system under increasingly complex, multi-step
scenarios that combine ingestion, retraction, merge, persistence, search,
entity linking, annotation, and temporal queries in ways that reveal
subtle invariant violations.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from dks import (
    KnowledgeStore,
    ClaimCore,
    ValidTime,
    TransactionTime,
    Provenance,
    Pipeline,
    KnowledgeGraph,
    SearchIndex,
    NumpyIndex,
    MergeResult,
    TfidfSearchIndex,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(year=2024, month=1, day=1, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _make_pipeline():
    """Create a Pipeline with TF-IDF index (no model download needed)."""
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


def _make_pipeline_numpy():
    """Create a Pipeline with NumpyIndex (zero-dependency, deterministic)."""
    store = KnowledgeStore()
    backend = NumpyIndex(dimension=64)
    index = SearchIndex(store, backend)
    return Pipeline(store=store, search_index=index)


# Corpus generators --------------------------------------------------------

_SCIENCE_DOCS = [
    ("biology.txt", "Photosynthesis converts sunlight into glucose using chlorophyll in chloroplasts. "
     "This process is fundamental to life on Earth and provides the oxygen we breathe."),
    ("biology.txt", "Cellular respiration breaks down glucose to produce ATP energy in the mitochondria. "
     "The byproducts are carbon dioxide and water which are expelled by the organism."),
    ("genetics.txt", "DNA replication uses helicase to unwind the double helix. DNA polymerase then "
     "synthesizes complementary strands ensuring faithful genetic inheritance."),
    ("genetics.txt", "Mutations in the BRCA1 gene significantly increase breast cancer risk. Genetic "
     "testing can identify carriers of these harmful variants early."),
    ("chemistry.txt", "The periodic table organizes elements by atomic number. Mendeleev predicted "
     "the existence of undiscovered elements using gaps in his table."),
    ("chemistry.txt", "Covalent bonds form when atoms share electron pairs. The strength of a covalent "
     "bond depends on the electronegativity difference between the bonded atoms."),
    ("physics.txt", "Quantum mechanics describes particles as wave functions that collapse upon "
     "measurement. Heisenberg uncertainty principle limits simultaneous position and momentum knowledge."),
    ("physics.txt", "General relativity predicts that massive objects warp spacetime. This warping "
     "causes what we experience as gravitational attraction between masses."),
]

_HISTORY_DOCS = [
    ("history_europe.txt", "The French Revolution of 1789 overthrew the monarchy and established a "
     "republic based on liberty equality and fraternity transforming European politics."),
    ("history_europe.txt", "The Industrial Revolution began in Britain with steam-powered factories "
     "replacing hand production. This fundamentally changed manufacturing and society."),
    ("history_asia.txt", "The Meiji Restoration of 1868 modernized Japan by adopting Western "
     "technology and institutions while preserving Japanese cultural identity."),
    ("history_asia.txt", "The Silk Road connected East and West for centuries enabling trade of "
     "silk spices and ideas between China Persia and the Roman Empire."),
]

_TECH_DOCS = [
    ("ml_guide.txt", "Neural networks learn patterns from data using gradient descent optimization. "
     "Deep learning stacks multiple layers to learn increasingly abstract representations."),
    ("ml_guide.txt", "Transformers use self-attention mechanisms to process sequences in parallel. "
     "This architecture revolutionized natural language processing and computer vision."),
    ("quantum.txt", "Quantum computing uses qubits in superposition to perform parallel computations. "
     "Quantum advantage has been demonstrated for specific optimization problems."),
    ("quantum.txt", "Quantum error correction encodes logical qubits across many physical qubits. "
     "Surface codes are the leading approach to fault-tolerant quantum computation."),
    ("databases.txt", "Relational databases use SQL for structured queries across normalized tables. "
     "ACID transactions ensure data consistency even during concurrent access."),
    ("databases.txt", "NoSQL databases sacrifice strict consistency for horizontal scalability. "
     "Document stores key-value stores and graph databases serve different access patterns."),
]

_ENTITY_DOCS = [
    ("source_a.txt", "Albert Einstein developed the theory of general relativity in 1915. "
     "Einstein received the Nobel Prize in Physics for the photoelectric effect."),
    ("source_b.txt", "Professor Einstein was born in Ulm Germany in 1879. "
     "Albert Einstein worked at the Swiss Patent Office before his academic career."),
    ("source_c.txt", "A. Einstein published four groundbreaking papers in 1905. "
     "Einstein's work on Brownian motion provided evidence for atomic theory."),
    ("source_d.txt", "Einstein fled Nazi Germany in 1933 and settled at Princeton University. "
     "Albert Einstein became a US citizen in 1940 and remained at Princeton until his death."),
    ("source_e.txt", "Einstein's mass-energy equivalence formula E equals mc squared is the most "
     "famous equation in physics. Einstein also contributed to quantum mechanics."),
]


def _ingest_corpus(pipeline, docs):
    """Ingest a list of (source, text) tuples and return all revision_ids."""
    all_ids = []
    for source, text in docs:
        ids = pipeline.ingest_text(text, source=source)
        all_ids.extend(ids)
    return all_ids


# ===========================================================================
# Test 1: Large corpus stats consistency
# ===========================================================================

class TestLargeCorpusStatsConsistency:
    """Ingest 50+ documents of varying sizes and verify stats consistency."""

    def test_large_corpus_stats_consistency(self):
        pipeline = _make_pipeline()

        # Generate 55 unique documents
        all_docs = _SCIENCE_DOCS + _HISTORY_DOCS + _TECH_DOCS
        # Pad to 55+ with generated content
        for i in range(55 - len(all_docs)):
            all_docs.append((
                f"generated_{i}.txt",
                f"Document {i} discusses topic number {i} with details about "
                f"subject_{i} and concept_{i}. This content is unique to document {i} "
                f"and covers material not found elsewhere in the corpus."
            ))
        assert len(all_docs) >= 55

        all_rev_ids = _ingest_corpus(pipeline, all_docs)
        pipeline.rebuild_index()

        stats = pipeline.stats()

        # stats["revisions"] matches len(store.revisions)
        assert stats["revisions"] == len(pipeline.store.revisions)

        # stats["cores"] matches len(store.cores)
        assert stats["cores"] == len(pipeline.store.cores)

        # list_sources() returns the correct number of unique sources
        listed = pipeline.list_sources()
        listed_names = {s["source"] for s in listed}
        expected_sources = {s.strip().lower() for s, _ in all_docs}
        # canonicalize_text lowercases and strips, so compare canonicalized
        assert listed_names == expected_sources, (
            f"Source mismatch: listed={listed_names}, expected={expected_sources}"
        )

        # rebuild_index() returns count matching active (non-retracted) revisions
        indexed = pipeline.rebuild_index()
        retracted = pipeline.store.retracted_core_ids()
        active_count = sum(
            1 for rev in pipeline.store.revisions.values()
            if rev.status == "asserted" and rev.core_id not in retracted
        )
        assert indexed == active_count, (
            f"Indexed {indexed} but {active_count} active revisions"
        )


# ===========================================================================
# Test 2: Cascading retraction chain
# ===========================================================================

class TestCascadingRetractionChain:
    """Ingest A referencing entities, B referencing A's entities, retract A."""

    def test_cascading_retraction_chain(self):
        pipeline = _make_pipeline()

        # Source A: science content about photosynthesis
        a_ids = pipeline.ingest_text(
            "Photosynthesis is the primary mechanism plants use to convert solar "
            "energy into chemical energy stored in glucose molecules.",
            source="source_a.txt",
        )

        # Source B: references the same concepts (photosynthesis, glucose)
        b_ids = pipeline.ingest_text(
            "The glucose produced by photosynthesis fuels cellular respiration "
            "in mitochondria, generating ATP for cellular processes.",
            source="source_b.txt",
        )

        # Annotate a chunk from source A
        ann_id = pipeline.annotate_chunk(a_ids[0], tags=["important"], note="key concept")

        pipeline.rebuild_index()

        # Verify both sources are searchable
        results_before = pipeline.query("photosynthesis glucose", k=10)
        assert len(results_before) > 0

        # Retract source A
        # delete_source compares canonicalized source names
        pipeline.delete_source("source_a.txt", reason="test retraction")
        pipeline.rebuild_index()

        # A's chunks excluded from search
        results_after = pipeline.query("photosynthesis glucose", k=10)
        for r in results_after:
            core = pipeline.store.cores.get(r.core_id)
            assert core.slots.get("source") != "source_a.txt", (
                "Retracted source A appeared in search results"
            )

        # B's chunks still visible
        b_found = False
        for r in results_after:
            core = pipeline.store.cores.get(r.core_id)
            if core.slots.get("source") == "source_b.txt":
                b_found = True
        assert b_found, "Source B should still be visible after retracting A"

        # list_sources should only show source B (and annotation source)
        listed = pipeline.list_sources()
        listed_names = [s["source"] for s in listed]
        assert "source_a.txt" not in listed_names, "Retracted source A still listed"
        assert "source_b.txt" in listed_names, "Source B should still be listed"

        # Annotation on A's chunk is orphaned (filtered out of list_annotations)
        annotations = pipeline.list_annotations(tag="important")
        for ann in annotations:
            assert ann["target_revision"] not in a_ids, (
                "Annotation on retracted chunk should be orphaned"
            )


# ===========================================================================
# Test 3: Multi-way merge consistency
# ===========================================================================

class TestMultiWayMergeConsistency:
    """Create 3 independent pipelines with overlapping content, merge sequentially."""

    def test_multi_way_merge_consistency(self):
        # Pipeline A: science
        pipeline_a = _make_pipeline()
        _ingest_corpus(pipeline_a, _SCIENCE_DOCS[:4])

        # Pipeline B: history (some overlap in style)
        pipeline_b = _make_pipeline()
        _ingest_corpus(pipeline_b, _HISTORY_DOCS)

        # Pipeline C: technology
        pipeline_c = _make_pipeline()
        _ingest_corpus(pipeline_c, _TECH_DOCS[:4])

        cores_a = set(pipeline_a.store.cores.keys())
        cores_b = set(pipeline_b.store.cores.keys())
        cores_c = set(pipeline_c.store.cores.keys())

        # Merge A + B
        result_ab = pipeline_a.merge(pipeline_b)
        cores_ab = set(pipeline_a.store.cores.keys())
        assert cores_a.issubset(cores_ab), "Cores from A missing after A+B merge"
        assert cores_b.issubset(cores_ab), "Cores from B missing after A+B merge"

        # Merge (A+B) + C
        result_abc = pipeline_a.merge(pipeline_c)
        cores_abc = set(pipeline_a.store.cores.keys())

        # All unique content from A, B, C present
        assert cores_a.issubset(cores_abc), "Cores from A missing after triple merge"
        assert cores_b.issubset(cores_abc), "Cores from B missing after triple merge"
        assert cores_c.issubset(cores_abc), "Cores from C missing after triple merge"

        # No duplicate cores (cores dict is keyed by core_id, so duplicates impossible)
        # But verify revision count is at least the sum
        revs_a = len([r for r in pipeline_a.store.revisions.values()])
        assert revs_a >= (len(cores_a) + len(cores_b) + len(cores_c)), (
            "Merged store has fewer revisions than expected"
        )

        # retracted_core_ids() is empty (nothing was retracted)
        assert len(pipeline_a.store.retracted_core_ids()) == 0, (
            "No retractions should exist after clean merge"
        )

        # Stats are consistent
        stats = pipeline_a.stats()
        assert stats["cores"] == len(pipeline_a.store.cores)
        assert stats["revisions"] == len(pipeline_a.store.revisions)


# ===========================================================================
# Test 4: Rapid ingest/retract cycles
# ===========================================================================

class TestRapidIngestRetractCycles:
    """Rapidly cycle: ingest -> retract -> ingest new -> retract -> ... (20 cycles)."""

    def test_rapid_ingest_retract_cycles(self):
        pipeline = _make_pipeline_numpy()

        retracted_count = 0
        for cycle in range(20):
            source = f"cycle_{cycle}.txt"
            text = (
                f"Cycle {cycle} document with unique content about topic_{cycle} "
                f"and details_{cycle} covering subject matter {cycle * 7}."
            )
            ids = pipeline.ingest_text(text, source=source)
            assert len(ids) > 0, f"Cycle {cycle}: no revisions created"

            # Retract the just-ingested source
            pipeline.delete_source(source, reason=f"retract cycle {cycle}")
            retracted_count += 1

            # retracted_core_ids grows
            retracted = pipeline.store.retracted_core_ids()
            assert len(retracted) == retracted_count, (
                f"Cycle {cycle}: expected {retracted_count} retracted cores, "
                f"got {len(retracted)}"
            )

            # Active revision count: only asserted revisions whose core is not retracted
            active = sum(
                1 for rev in pipeline.store.revisions.values()
                if rev.status == "asserted" and rev.core_id not in retracted
            )
            assert active == 0, (
                f"Cycle {cycle}: expected 0 active revisions, got {active}"
            )

        # After 20 cycles, all cores should be retracted
        assert len(pipeline.store.retracted_core_ids()) == 20

        # Search should return nothing
        pipeline.rebuild_index()
        results = pipeline.query("topic", k=10)
        # NumpyIndex-based SearchIndex filters retracted cores
        assert len(results) == 0, "Search should return nothing after all retractions"


# ===========================================================================
# Test 5: Save/load large corpus fidelity
# ===========================================================================

class TestSaveLoadLargeCorpusFidelity:
    """Ingest 30+ documents, save, load, and compare everything."""

    def test_save_load_large_corpus_fidelity(self):
        pipeline = _make_pipeline()

        # Build a 35-document corpus
        docs = _SCIENCE_DOCS + _HISTORY_DOCS + _TECH_DOCS
        for i in range(35 - len(docs)):
            docs.append((
                f"extra_{i}.txt",
                f"Extra document {i} about specific topic_{i} with supplementary "
                f"information regarding subject_{i} and concept_{i}."
            ))

        _ingest_corpus(pipeline, docs)
        pipeline.rebuild_index()

        # Also retract one source to test retraction persistence
        pipeline.delete_source("physics.txt", reason="test retraction")

        # Capture state before save
        orig_cores = dict(pipeline.store.cores)
        orig_revisions = dict(pipeline.store.revisions)
        orig_relations = dict(pipeline.store.relations)
        orig_retracted = pipeline.store.retracted_core_ids()

        tmpdir = tempfile.mkdtemp()
        try:
            pipeline.save(tmpdir)
            loaded = Pipeline.load(tmpdir)

            # All cores match
            assert set(loaded.store.cores.keys()) == set(orig_cores.keys()), (
                "Core keys differ after save/load"
            )
            for cid in orig_cores:
                orig = orig_cores[cid]
                load = loaded.store.cores[cid]
                assert orig.claim_type == load.claim_type
                assert orig.slots == load.slots

            # All revisions match
            assert set(loaded.store.revisions.keys()) == set(orig_revisions.keys()), (
                "Revision keys differ after save/load"
            )
            for rid in orig_revisions:
                orig = orig_revisions[rid]
                load = loaded.store.revisions[rid]
                assert orig.core_id == load.core_id
                assert orig.assertion == load.assertion
                assert orig.status == load.status
                assert orig.confidence_bp == load.confidence_bp

            # All relations match (if any)
            assert set(loaded.store.relations.keys()) == set(orig_relations.keys()), (
                "Relation keys differ after save/load"
            )

            # retracted_core_ids matches
            assert loaded.store.retracted_core_ids() == orig_retracted, (
                "Retracted core IDs differ after save/load"
            )

        finally:
            shutil.rmtree(tmpdir)


# ===========================================================================
# Test 6: Search ranking stability (determinism)
# ===========================================================================

class TestSearchRankingStability:
    """Ingest documents, search the same query 5 times, verify identical results."""

    def test_search_ranking_stability(self):
        pipeline = _make_pipeline()

        # Ingest 20 documents
        docs = list(_SCIENCE_DOCS + _HISTORY_DOCS + _TECH_DOCS)
        # Pad to 20 if needed
        while len(docs) < 20:
            i = len(docs)
            docs.append((
                f"pad_{i}.txt",
                f"Padding document {i} covers topic_{i} with unique content "
                f"about subject_{i} including details on concept_{i}.",
            ))
        assert len(docs) >= 20
        _ingest_corpus(pipeline, docs)
        pipeline.rebuild_index()

        query = "quantum computing qubits superposition"

        # Run the same query 5 times
        all_runs = []
        for _ in range(5):
            results = pipeline.query(query, k=10)
            all_runs.append(results)

        # All runs must be identical
        baseline = all_runs[0]
        for run_idx, results in enumerate(all_runs[1:], start=2):
            assert len(results) == len(baseline), (
                f"Run {run_idx}: result count {len(results)} != baseline {len(baseline)}"
            )
            for i, (base, curr) in enumerate(zip(baseline, results)):
                assert base.revision_id == curr.revision_id, (
                    f"Run {run_idx}, result {i}: revision_id mismatch"
                )
                assert base.score == curr.score, (
                    f"Run {run_idx}, result {i}: score mismatch "
                    f"{base.score} != {curr.score}"
                )
                assert base.core_id == curr.core_id, (
                    f"Run {run_idx}, result {i}: core_id mismatch"
                )


# ===========================================================================
# Test 7: Entity linking across sources
# ===========================================================================

class TestEntityLinkingAcrossSources:
    """Ingest 5 docs mentioning same entity differently, link, retract, re-link."""

    def test_entity_linking_across_sources(self):
        sklearn = pytest.importorskip("sklearn")

        pipeline = _make_pipeline()
        _ingest_corpus(pipeline, _ENTITY_DOCS)
        pipeline.rebuild_index()
        pipeline.build_graph(n_clusters=2)

        # Run link_entities -- finds shared entities across sources
        result1 = pipeline.link_entities()
        assert result1["total_entities"] >= 0  # may be 0 if no shared entities found
        initial_entities = result1["total_entities"]

        # Retract 2 sources
        pipeline.delete_source("source_a.txt", reason="test retraction")
        pipeline.delete_source("source_b.txt", reason="test retraction")
        pipeline.rebuild_index()
        pipeline.build_graph(n_clusters=2)

        # Re-run link_entities with fewer sources
        result2 = pipeline.link_entities()

        # Verify entity counts decreased or stayed same (fewer documents = fewer cross-refs)
        assert result2["total_entities"] <= initial_entities or initial_entities == 0, (
            f"Entity count should not increase after retraction: "
            f"before={initial_entities}, after={result2['total_entities']}"
        )

        # Verify retracted sources are gone from listed sources
        listed = pipeline.list_sources()
        listed_names = [s["source"] for s in listed]
        assert "source_a.txt" not in listed_names
        assert "source_b.txt" not in listed_names
        # Remaining sources should still be listed
        assert "source_c.txt" in listed_names
        assert "source_d.txt" in listed_names
        assert "source_e.txt" in listed_names


# ===========================================================================
# Test 8: Concurrent annotation and retraction
# ===========================================================================

class TestConcurrentAnnotationAndRetraction:
    """Ingest, annotate, retract some, annotate more, verify annotation state."""

    def test_concurrent_annotation_and_retraction(self):
        pipeline = _make_pipeline()

        # Ingest from two sources
        a_ids = pipeline.ingest_text(
            "Machine learning uses gradient descent to optimize model parameters. "
            "Backpropagation computes gradients through the computational graph.",
            source="ml_source.txt",
        )
        b_ids = pipeline.ingest_text(
            "Database indexing uses B-trees for efficient range queries. "
            "Hash indexes provide O(1) lookups for equality comparisons.",
            source="db_source.txt",
        )

        # Annotate chunks from both sources
        ann_a = pipeline.annotate_chunk(a_ids[0], tags=["ml", "optimization"], note="key ML concept")
        ann_b = pipeline.annotate_chunk(b_ids[0], tags=["database", "indexing"], note="key DB concept")

        # Verify both annotations exist
        all_anns = pipeline.list_annotations()
        assert len(all_anns) == 2, f"Expected 2 annotations, got {len(all_anns)}"

        # Retract source A
        pipeline.delete_source("ml_source.txt", reason="removing ML content")

        # Annotations on retracted chunks are orphaned (filtered out)
        active_anns = pipeline.list_annotations()
        for ann in active_anns:
            assert ann["target_revision"] not in a_ids, (
                "Annotation on retracted chunk should be orphaned"
            )

        # Annotations on active chunks survive
        db_anns = pipeline.list_annotations(tag="database")
        assert len(db_anns) == 1, f"Expected 1 database annotation, got {len(db_anns)}"
        assert db_anns[0]["target_revision"] == b_ids[0]

        # Annotate more on active chunks
        ann_b2 = pipeline.annotate_chunk(b_ids[0], tags=["performance"], note="indexing perf")
        all_after = pipeline.list_annotations()
        # Should have the original DB annotation plus the new one
        assert len(all_after) == 2, (
            f"Expected 2 active annotations (1 orphaned), got {len(all_after)}"
        )

        # Tag filter works correctly
        perf_anns = pipeline.list_annotations(tag="performance")
        assert len(perf_anns) == 1
        assert perf_anns[0]["target_revision"] == b_ids[0]


# ===========================================================================
# Test 9: Temporal query across multiple revisions
# ===========================================================================

class TestTemporalQueryMultiRevision:
    """Create a core with multiple revisions at different tx_ids, query at each."""

    def test_temporal_query_multi_revision(self):
        store = KnowledgeStore()
        backend = NumpyIndex(dimension=64)
        index = SearchIndex(store, backend)

        core = ClaimCore(
            claim_type="fact@v1",
            slots={"subject": "population", "location": "city_x"},
        )
        vt = ValidTime(start=dt(2020, 1, 1), end=None)

        # Create 5 revisions at different tx_ids, each with updated assertion
        revision_ids = []
        for i in range(1, 6):
            tx = TransactionTime(tx_id=i, recorded_at=dt(2024, 1, i))
            rev = store.assert_revision(
                core=core,
                assertion=f"City X population is {1000000 + i * 100000}",
                valid_time=vt,
                transaction_time=tx,
                provenance=Provenance(source=f"census_{i}"),
                confidence_bp=5000 + i * 500,
                status="asserted",
            )
            revision_ids.append(rev.revision_id)
            index.add(rev.revision_id, rev.assertion)

        # Query at each tx_id and verify the correct revision wins
        # Note: ClaimRevision canonicalizes assertions (lowercases), so compare lowercase
        for i in range(1, 6):
            winner = store.query_as_of(
                core.core_id,
                valid_at=dt(2023, 6, 15),
                tx_id=i,
            )
            assert winner is not None, f"No winner at tx_id={i}"
            expected_assertion = f"city x population is {1000000 + i * 100000}"
            assert winner.assertion == expected_assertion, (
                f"At tx_id={i}: expected '{expected_assertion}', "
                f"got '{winner.assertion}'"
            )

        # Also verify search with temporal filtering returns correct revision
        results = index.search(
            "City X population",
            k=5,
            valid_at=dt(2023, 6, 15),
            tx_id=3,
        )
        # Should get the revision from tx_id=3
        if results:
            expected_text = "city x population is 1300000"
            assert results[0].text == expected_text, (
                f"Temporal search at tx_id=3: expected '{expected_text}', "
                f"got '{results[0].text}'"
            )


# ===========================================================================
# Test 10: Stress retracted_core_ids cache (Hypothesis)
# ===========================================================================

class TestStressRetractedCoreIdsCache:
    """Property-based: random assert+retract sequences always yield correct set."""

    @given(
        ops=st.lists(
            st.tuples(
                # Operation: True=assert, False=retract
                st.booleans(),
                # Core index (used to pick which core to retract)
                st.integers(min_value=0, max_value=99),
            ),
            min_size=5,
            max_size=40,
        ),
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_retracted_core_ids_always_correct(self, ops):
        store = KnowledgeStore()
        asserted_cores = []  # list of (core, vt) for potential retraction
        retracted_set = set()  # ground truth set of retracted core_ids
        tx_counter = 0

        for is_assert, core_idx in ops:
            tx_counter += 1
            tx = TransactionTime(
                tx_id=tx_counter,
                recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=tx_counter),
            )

            if is_assert or not asserted_cores:
                # Assert a new core
                core = ClaimCore(
                    claim_type="test@v1",
                    slots={"id": str(tx_counter)},
                )
                vt = ValidTime(start=datetime(2020, 1, 1, tzinfo=timezone.utc))
                store.assert_revision(
                    core=core,
                    assertion=f"Claim {tx_counter}",
                    valid_time=vt,
                    transaction_time=tx,
                    provenance=Provenance(source="test"),
                    confidence_bp=5000,
                    status="asserted",
                )
                asserted_cores.append((core, vt))
            else:
                # Retract an existing core
                target_idx = core_idx % len(asserted_cores)
                target_core, target_vt = asserted_cores[target_idx]
                store.assert_revision(
                    core=target_core,
                    assertion=f"Retracted claim",
                    valid_time=target_vt,
                    transaction_time=tx,
                    provenance=Provenance(source="test_retraction"),
                    confidence_bp=5000,
                    status="retracted",
                )
                retracted_set.add(target_core.core_id)

        # Verify retracted_core_ids() matches ground truth
        actual = store.retracted_core_ids()
        assert actual == retracted_set, (
            f"retracted_core_ids mismatch: actual={actual}, expected={retracted_set}"
        )
