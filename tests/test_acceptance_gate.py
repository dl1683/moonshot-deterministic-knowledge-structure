"""Acceptance gate tests — must ALL pass before any session is complete.

40 tests across 8 categories, designed by Codex as a tough session-end gate.
Each test verifies a critical invariant with explicit expected values.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
    Pipeline,
    Provenance,
    TfidfSearchIndex,
    TransactionTime,
    ValidTime,
    canonicalize_text,
)

# ---- Shared helpers ----


def dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _tx(tx_id: int) -> TransactionTime:
    return TransactionTime(tx_id=tx_id, recorded_at=dt(2024))


def _vt(start_year: int = 2024, end_year: int | None = None) -> ValidTime:
    return ValidTime(
        start=dt(start_year),
        end=dt(end_year) if end_year else None,
    )


def _prov(source: str = "test") -> Provenance:
    return Provenance(source=source)


def _make_pipeline() -> Pipeline:
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


def _assert_claim(store, claim_type, slots, vt=None, tx=None, prov=None,
                  confidence=5000, status="asserted"):
    """Helper to assert a claim and return (core, revision)."""
    core = ClaimCore(claim_type=claim_type, slots=slots)
    rev = store.assert_revision(
        core=core,
        assertion=str(slots),
        valid_time=vt or _vt(),
        transaction_time=tx or _tx(1),
        provenance=prov or _prov(),
        confidence_bp=confidence,
        status=status,
    )
    return core, rev


# ============================================================
# Category 1: DETERMINISM INVARIANTS
# ============================================================

class TestDeterminismInvariants:

    def test_core_id_deterministic_exact_hex(self):
        """Same input produces same core_id, always."""
        core_a = ClaimCore(claim_type="residence", slots={"subject": "alice", "city": "london"})
        core_b = ClaimCore(claim_type="residence", slots={"subject": "alice", "city": "london"})
        assert core_a.core_id == core_b.core_id
        assert len(core_a.core_id) == 64  # SHA-256 hex

    def test_core_id_stable_across_slot_ordering(self):
        """Dict key insertion order doesn't affect core_id."""
        core_a = ClaimCore(claim_type="fact", slots={"b": "2", "a": "1"})
        core_b = ClaimCore(claim_type="fact", slots={"a": "1", "b": "2"})
        assert core_a.core_id == core_b.core_id

    def test_core_id_stable_across_case_variation(self):
        """Canonicalization normalizes case."""
        core_a = ClaimCore(claim_type="Fact", slots={"Subject": "Alice"})
        core_b = ClaimCore(claim_type="fact", slots={"subject": "alice"})
        assert core_a.core_id == core_b.core_id

    def test_revision_id_deterministic(self):
        """Identical revision inputs produce identical revision_id."""
        store = KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        vt, tx, prov = _vt(), _tx(1), _prov()
        rev_a = store.assert_revision(
            core=core, assertion="hello", valid_time=vt,
            transaction_time=tx, provenance=prov, confidence_bp=5000,
        )
        # Create a second store, assert same content
        store2 = KnowledgeStore()
        rev_b = store2.assert_revision(
            core=core, assertion="hello", valid_time=vt,
            transaction_time=tx, provenance=prov, confidence_bp=5000,
        )
        assert rev_a.revision_id == rev_b.revision_id
        assert len(rev_a.revision_id) == 64

    def test_revision_id_differs_when_tx_id_differs(self):
        """Different tx_id produces different revision_id."""
        store_a, store_b = KnowledgeStore(), KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        vt, prov = _vt(), _prov()
        rev_a = store_a.assert_revision(
            core=core, assertion="hello", valid_time=vt,
            transaction_time=_tx(1), provenance=prov, confidence_bp=5000,
        )
        rev_b = store_b.assert_revision(
            core=core, assertion="hello", valid_time=vt,
            transaction_time=_tx(2), provenance=prov, confidence_bp=5000,
        )
        assert rev_a.revision_id != rev_b.revision_id

    def test_store_canonical_json_deterministic(self):
        """as_canonical_json() produces identical output on repeated calls."""
        store = KnowledgeStore()
        _assert_claim(store, "a", {"x": "1"})
        _assert_claim(store, "b", {"y": "2"}, tx=_tx(2))
        _assert_claim(store, "c", {"z": "3"}, tx=_tx(3))
        json_a = store.as_canonical_json()
        json_b = store.as_canonical_json()
        assert json_a == json_b

    def test_save_load_byte_identical_store(self):
        """Save → load produces byte-identical canonical JSON."""
        store = KnowledgeStore()
        _assert_claim(store, "fact1", {"a": "1"})
        _assert_claim(store, "fact2", {"b": "2"}, tx=_tx(2))
        original_json = store.as_canonical_json()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "store.json"
            store.to_canonical_json_file(path)
            loaded = KnowledgeStore.from_canonical_json_file(path)

        assert loaded.as_canonical_json() == original_json


# ============================================================
# Category 2: BITEMPORAL CORRECTNESS
# ============================================================

class TestBitemporalCorrectness:

    def _setup_store(self):
        store = KnowledgeStore()
        core = ClaimCore(claim_type="location", slots={"person": "alice", "city": "london"})
        rev = store.assert_revision(
            core=core, assertion="Alice lives in London",
            valid_time=ValidTime(start=dt(2024), end=dt(2025)),
            transaction_time=_tx(5),
            provenance=_prov(), confidence_bp=8000,
        )
        return store, core, rev

    def test_query_before_assertion_tx_returns_none(self):
        store, core, _ = self._setup_store()
        result = store.query_as_of(core.core_id, valid_at=dt(2024, 6, 1), tx_id=4)
        assert result is None

    def test_query_at_assertion_tx_returns_revision(self):
        store, core, rev = self._setup_store()
        result = store.query_as_of(core.core_id, valid_at=dt(2024, 6, 1), tx_id=5)
        assert result is not None
        assert result.revision_id == rev.revision_id

    def test_query_outside_valid_time_range_returns_none(self):
        store, core, _ = self._setup_store()
        result = store.query_as_of(core.core_id, valid_at=dt(2026, 1, 1), tx_id=10)
        assert result is None

    def test_query_between_assertion_and_retraction_returns_asserted(self):
        store, core, rev = self._setup_store()
        # Retract at tx_id=8
        store.assert_revision(
            core=core, assertion="Retracted",
            valid_time=ValidTime(start=dt(2024), end=dt(2025)),
            transaction_time=_tx(8),
            provenance=_prov("retraction"), confidence_bp=8000,
            status="retracted",
        )
        # Query between assertion (5) and retraction (8)
        result = store.query_as_of(core.core_id, valid_at=dt(2024, 6, 1), tx_id=6)
        assert result is not None
        assert result.status == "asserted"

    def test_query_after_retraction_returns_none(self):
        store, core, _ = self._setup_store()
        store.assert_revision(
            core=core, assertion="Retracted",
            valid_time=ValidTime(start=dt(2024), end=dt(2025)),
            transaction_time=_tx(8),
            provenance=_prov("retraction"), confidence_bp=8000,
            status="retracted",
        )
        result = store.query_as_of(core.core_id, valid_at=dt(2024, 6, 1), tx_id=8)
        assert result is None


# ============================================================
# Category 3: MERGE/CRDT PROPERTIES
# ============================================================

class TestMergeCRDTProperties:

    def _make_store_with_claim(self, claim_type, slots, tx_id=1):
        store = KnowledgeStore()
        core = ClaimCore(claim_type=claim_type, slots=slots)
        store.assert_revision(
            core=core, assertion=str(slots),
            valid_time=_vt(), transaction_time=_tx(tx_id),
            provenance=_prov(), confidence_bp=5000,
        )
        return store

    def test_merge_commutativity_concrete(self):
        store_a = self._make_store_with_claim("loc", {"person": "alice", "city": "london"})
        store_b = self._make_store_with_claim("loc", {"person": "bob", "city": "paris"}, tx_id=2)
        merge_ab = store_a.merge(store_b).merged
        merge_ba = store_b.merge(store_a).merged
        assert merge_ab.as_canonical_json() == merge_ba.as_canonical_json()

    def test_merge_idempotency_concrete(self):
        store = self._make_store_with_claim("fact", {"k": "v"})
        original_json = store.as_canonical_json()
        merged = store.merge(store).merged
        assert merged.as_canonical_json() == original_json

    def test_merge_with_empty_is_identity(self):
        store = self._make_store_with_claim("fact", {"k": "v"})
        original_json = store.as_canonical_json()
        merged = store.merge(KnowledgeStore()).merged
        assert merged.as_canonical_json() == original_json

    def test_merge_superset_property(self):
        store_a = self._make_store_with_claim("a", {"x": "1"})
        store_b = self._make_store_with_claim("b", {"y": "2"}, tx_id=2)
        a_cores = set(store_a.cores.keys())
        b_cores = set(store_b.cores.keys())
        merged = store_a.merge(store_b).merged
        assert a_cores | b_cores == set(merged.cores.keys())

    def test_merge_chunk_siblings_transferred(self):
        """Pipeline merge propagates _chunk_siblings from other."""
        pipe_a = _make_pipeline()
        pipe_b = _make_pipeline()
        rids_b = pipe_b.ingest_text("Quantum computing uses qubits", source="doc_b")
        assert "doc_b" in pipe_b._chunk_siblings
        pipe_a.merge(pipe_b)
        assert "doc_b" in pipe_a._chunk_siblings
        # Verify the revision IDs are transferred
        assert len(pipe_a._chunk_siblings["doc_b"]) > 0


# ============================================================
# Category 4: RETRACTION INTEGRITY
# ============================================================

class TestRetractionIntegrity:

    def test_retracted_core_ids_returns_frozenset(self):
        store = KnowledgeStore()
        core, _ = _assert_claim(store, "test", {"k": "v"})
        store.assert_revision(
            core=core, assertion="retracted",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000, status="retracted",
        )
        result = store.retracted_core_ids()
        assert isinstance(result, frozenset)

    def test_retracted_core_ids_immutable_no_cache_corruption(self):
        store = KnowledgeStore()
        core, _ = _assert_claim(store, "test", {"k": "v"})
        store.assert_revision(
            core=core, assertion="retracted",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000, status="retracted",
        )
        ids = store.retracted_core_ids()
        original_len = len(ids)
        # frozenset is immutable — cannot add to it
        with pytest.raises(AttributeError):
            ids.add("fake")  # type: ignore[attr-defined]
        # Verify cache wasn't corrupted
        assert len(store.retracted_core_ids()) == original_len

    def test_retraction_cache_invalidated_on_new_assertion(self):
        store = KnowledgeStore()
        # Cache empty set
        assert store.retracted_core_ids() == frozenset()
        # Now add a retracted revision
        core, _ = _assert_claim(store, "test", {"k": "v"})
        store.assert_revision(
            core=core, assertion="retracted",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000, status="retracted",
        )
        # Cache should be invalidated — new core_id visible
        assert core.core_id in store.retracted_core_ids()

    def test_retraction_original_revision_unchanged(self):
        store = KnowledgeStore()
        core, original_rev = _assert_claim(store, "test", {"k": "v"})
        store.assert_revision(
            core=core, assertion="retracted",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000, status="retracted",
        )
        # Original revision still has status "asserted"
        assert store.revisions[original_rev.revision_id].status == "asserted"

    def test_retraction_creates_new_revision(self):
        store = KnowledgeStore()
        core, _ = _assert_claim(store, "test", {"k": "v"})
        store.assert_revision(
            core=core, assertion="retracted",
            valid_time=_vt(), transaction_time=_tx(2),
            provenance=_prov(), confidence_bp=5000, status="retracted",
        )
        assert len(store.revisions) == 2
        statuses = {rev.status for rev in store.revisions.values()}
        assert statuses == {"asserted", "retracted"}

    def test_invalid_status_raises_valueerror(self):
        store = KnowledgeStore()
        core = ClaimCore(claim_type="test", slots={"k": "v"})
        with pytest.raises(ValueError, match="Invalid status"):
            store.assert_revision(
                core=core, assertion="oops",
                valid_time=_vt(), transaction_time=_tx(1),
                provenance=_prov(), confidence_bp=5000,
                status="invalid",  # type: ignore[arg-type]
            )


# ============================================================
# Category 5: PIPELINE END-TO-END
# ============================================================

class TestPipelineEndToEnd:

    def test_ingest_text_then_search_finds_it(self):
        pipe = _make_pipeline()
        pipe.ingest_text("Neural networks are powerful machine learning models")
        pipe.rebuild_index()
        results = pipe.query("neural networks")
        assert len(results) >= 1

    def test_ingest_text_retract_then_search_excludes(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Quantum entanglement is spooky", source="quantum")
        # Retract all chunks
        for rid in rids:
            rev = pipe.store.revisions[rid]
            core = pipe.store.cores[rev.core_id]
            pipe.store.assert_revision(
                core=core, assertion="retracted",
                valid_time=rev.valid_time,
                transaction_time=_tx(999),
                provenance=_prov("retraction"), confidence_bp=5000,
                status="retracted",
            )
        pipe.rebuild_index()
        results = pipe.query("quantum entanglement")
        assert len(results) == 0

    def test_ingest_on_pipeline_b_merge_into_a_search_on_a(self):
        pipe_a = _make_pipeline()
        pipe_b = _make_pipeline()
        pipe_b.ingest_text("Quantum computing uses qubits for computation", source="qc")
        pipe_a.merge(pipe_b)
        pipe_a.rebuild_index()
        results = pipe_a.query("quantum computing")
        assert len(results) >= 1

    def test_rebuild_index_after_merge_correct_count(self):
        pipe_a = _make_pipeline()
        pipe_b = _make_pipeline()
        pipe_a.ingest_text("Document about cats", source="cats")
        pipe_b.ingest_text("Document about dogs", source="dogs")
        pipe_a.merge(pipe_b)
        count = pipe_a.rebuild_index()
        active_count = len([
            r for r in pipe_a.store.revisions.values()
            if r.status == "asserted" and r.core_id not in pipe_a.store.retracted_core_ids()
        ])
        assert count == active_count

    def test_ingest_text_returns_valid_revision_ids(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Some interesting text about science")
        assert len(rids) >= 1
        for rid in rids:
            assert rid in pipe.store.revisions

    def test_stats_after_ingest(self):
        pipe = _make_pipeline()
        pipe.ingest_text("Hello world document")
        s = pipe.stats()
        assert s["cores"] >= 1
        assert s["revisions"] >= 1
        assert s["indexed"] >= 1


# ============================================================
# Category 6: SEARCH QUALITY
# ============================================================

class TestSearchQuality:

    def _ingest_docs(self, pipe, docs):
        for i, doc in enumerate(docs):
            pipe.ingest_text(doc, source=f"doc_{i}")
        pipe.rebuild_index()

    def test_tfidf_search_relevance_ranking(self):
        pipe = _make_pipeline()
        self._ingest_docs(pipe, [
            "Neural networks use backpropagation for learning",
            "Quantum physics studies subatomic particles and waves",
            "Neural network training process with gradient descent",
        ])
        results = pipe.query("neural networks")
        assert len(results) >= 2
        # At least one neural network result should rank above quantum physics
        scores = {r.text[:10]: r.score for r in results}
        neural_scores = [r.score for r in results if "neural" in r.text.lower()]
        quantum_scores = [r.score for r in results if "quantum" in r.text.lower()]
        if neural_scores and quantum_scores:
            assert max(neural_scores) > max(quantum_scores)

    def test_search_k_1_returns_single_result(self):
        pipe = _make_pipeline()
        self._ingest_docs(pipe, [
            "Alpha document about testing",
            "Beta document about coding",
            "Gamma document about testing",
        ])
        results = pipe.query("testing", k=1)
        assert len(results) == 1

    def test_empty_index_search_returns_empty(self):
        pipe = _make_pipeline()
        results = pipe.query("anything")
        assert results == []

    def test_search_results_descending_scores(self):
        pipe = _make_pipeline()
        self._ingest_docs(pipe, [
            "Machine learning algorithms for classification",
            "Deep learning with neural networks and GPUs",
            "Statistical learning theory and bounds",
            "Reinforcement learning in game playing",
            "Transfer learning across domains",
        ])
        results = pipe.query("learning")
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score


# ============================================================
# Category 7: ANNOTATIONS & ENTITY DECISIONS
# ============================================================

class TestAnnotationsAndEntities:

    def test_annotate_chunk_creates_annotation(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Important finding about proteins", source="bio")
        ann_id = pipe.annotate_chunk(rids[0], tags=["important"], note="key finding")
        assert ann_id is not None
        annotations = pipe.list_annotations()
        assert len(annotations) == 1
        assert "important" in annotations[0]["tags"]

    def test_retracted_annotation_excluded_from_list(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Some text", source="test")
        ann_id = pipe.annotate_chunk(rids[0], tags=["temp"], note="temp note")
        assert len(pipe.list_annotations()) == 1
        pipe.remove_annotation(ann_id)
        assert len(pipe.list_annotations()) == 0

    def test_accept_reject_entities_stored_as_claims(self):
        pipe = _make_pipeline()
        pipe.ingest_text("Machine learning is a field of AI", source="ai")
        pipe.accept_entities(["machine learning"])
        pipe.reject_entities(["boilerplate"])
        decisions = pipe.get_entity_decisions()
        assert decisions.get("machine learning") == "accepted"
        assert decisions.get("boilerplate") == "rejected"

    def test_annotation_on_retracted_chunk_excluded(self):
        pipe = _make_pipeline()
        rids = pipe.ingest_text("Temporary data", source="temp")
        pipe.annotate_chunk(rids[0], tags=["marked"], note="will retract")
        # Retract the chunk
        rev = pipe.store.revisions[rids[0]]
        core = pipe.store.cores[rev.core_id]
        pipe.store.assert_revision(
            core=core, assertion="retracted",
            valid_time=rev.valid_time,
            transaction_time=_tx(999),
            provenance=_prov("retraction"), confidence_bp=5000,
            status="retracted",
        )
        # Annotation should be orphaned (target retracted)
        annotations = pipe.list_annotations()
        assert len(annotations) == 0


# ============================================================
# Category 8: EDGE CASES & ERROR HANDLING
# ============================================================

class TestEdgeCasesAndErrorHandling:

    def test_unicode_nfc_convergence(self):
        """Precomposed and decomposed forms produce identical output."""
        a = canonicalize_text("caf\u00e9")  # precomposed
        b = canonicalize_text("cafe\u0301")  # combining accent
        assert a == b

    def test_zero_width_character_stripping(self):
        a = canonicalize_text("he\u200bllo")  # zero-width space
        b = canonicalize_text("hello")
        assert a == b

    def test_empty_store_operations_no_crash(self):
        store = KnowledgeStore()
        assert store.retracted_core_ids() == frozenset()
        json_out = store.as_canonical_json()
        assert isinstance(json_out, str)
        merged = store.merge(KnowledgeStore()).merged
        assert len(merged.cores) == 0
        result = store.query_as_of("nonexistent", valid_at=dt(2024), tx_id=1)
        assert result is None
