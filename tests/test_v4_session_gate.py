"""Session gate tests — Codex-mandated acceptance tests for next session.

Tests designed by Codex to verify bug fixes and integration improvements.
"""
from __future__ import annotations

import json
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


def dt(year=2024, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _tx(tx_id=1):
    return TransactionTime(tx_id=tx_id, recorded_at=dt())


def _vt(start_year=2024, end_year=None):
    return ValidTime(start=dt(start_year), end=dt(end_year) if end_year else None)


def _prov(source="test"):
    return Provenance(source=source)


def _make_pipeline():
    store = KnowledgeStore()
    index = TfidfSearchIndex(store)
    return Pipeline(store=store, search_index=index)


# ============================================================
# Test 1: BUG-11 — delete_source case insensitive
# ============================================================

class TestSourceCanonicalization:

    def test_delete_source_case_insensitive(self):
        """delete_source('MyFile.PDF') deletes chunks ingested as 'MyFile.PDF'."""
        pipe = _make_pipeline()
        pipe.ingest_text("Alpha beta gamma content", source="MyFile.PDF")
        pipe.ingest_text("Delta epsilon zeta content", source="other")
        pipe.rebuild_index()

        result = pipe.delete_source("MyFile.PDF")
        assert result["retracted_count"] >= 1

        pipe.rebuild_index()
        results = pipe.query("alpha beta gamma")
        assert len(results) == 0
        # Other source still searchable
        results = pipe.query("delta epsilon zeta")
        assert len(results) >= 1

    def test_browse_source_case_insensitive(self):
        """browse_source works regardless of case."""
        pipe = _make_pipeline()
        pipe.ingest_text("Some content about testing", source="MyDoc.TXT")
        result = pipe.browse_source("MyDoc.TXT")
        assert result["total_chunks"] >= 1


# ============================================================
# Test 3: Version consistency
# ============================================================

class TestVersionConsistency:

    def test_dks_version_exists(self):
        import dks
        assert hasattr(dks, '__version__')
        assert isinstance(dks.__version__, str)
        assert len(dks.__version__) > 0

    def test_version_matches_save_metadata(self):
        import dks
        pipe = _make_pipeline()
        pipe.ingest_text("Some content")
        with tempfile.TemporaryDirectory() as tmp:
            pipe.save(tmp)
            with open(Path(tmp) / "meta.json") as f:
                meta = json.load(f)
        assert meta["version"] == dks.__version__


# ============================================================
# Test 5: Retraction cache invalidation after merge
# ============================================================

class TestRetractionCacheAfterMerge:

    def test_retracted_core_ids_correct_after_merge(self):
        """Merged store reflects retracted core_ids from both inputs."""
        store_a = KnowledgeStore()
        core_a = ClaimCore(claim_type="a", slots={"k": "v1"})
        store_a.assert_revision(
            core=core_a, assertion="assert", valid_time=_vt(),
            transaction_time=_tx(1), provenance=_prov(), confidence_bp=5000,
        )
        store_a.assert_revision(
            core=core_a, assertion="retract", valid_time=_vt(),
            transaction_time=_tx(2), provenance=_prov(), confidence_bp=5000,
            status="retracted",
        )

        store_b = KnowledgeStore()
        core_b = ClaimCore(claim_type="b", slots={"k": "v2"})
        store_b.assert_revision(
            core=core_b, assertion="assert", valid_time=_vt(),
            transaction_time=_tx(3), provenance=_prov(), confidence_bp=5000,
        )

        merged = store_a.merge(store_b).merged
        retracted = merged.retracted_core_ids()
        assert core_a.core_id in retracted
        assert core_b.core_id not in retracted


# ============================================================
# Test 6: Overlapping valid_time with mixed retraction
# ============================================================

class TestOverlappingValidTimeRetraction:

    def test_overlapping_intervals_mixed_retraction(self):
        """Retraction of one interval shouldn't suppress overlapping asserted intervals."""
        store = KnowledgeStore()
        core = ClaimCore(claim_type="fact", slots={"topic": "test"})

        # Interval 1: [2020, 2025) — will retract
        rev1 = store.assert_revision(
            core=core, assertion="Fact v1",
            valid_time=ValidTime(start=dt(2020), end=dt(2025)),
            transaction_time=_tx(1), provenance=_prov(), confidence_bp=5000,
        )
        # Interval 2: [2022, 2028) — asserted
        rev2 = store.assert_revision(
            core=core, assertion="Fact v2",
            valid_time=ValidTime(start=dt(2022), end=dt(2028)),
            transaction_time=_tx(2), provenance=_prov(), confidence_bp=5000,
        )
        # Retract interval 1
        store.assert_revision(
            core=core, assertion="Retract v1",
            valid_time=ValidTime(start=dt(2020), end=dt(2025)),
            transaction_time=_tx(3), provenance=_prov(), confidence_bp=5000,
            status="retracted",
        )

        # At 2023 (overlap zone), should see asserted rev2 (interval 2)
        result = store.query_as_of(core.core_id, valid_at=dt(2023), tx_id=3)
        assert result is not None
        assert result.status == "asserted"
        assert result.revision_id == rev2.revision_id


# ============================================================
# Test 8: save/load preserves tx_counter
# ============================================================

class TestSaveLoadTxCounter:

    def test_tx_counter_preserved_after_reload(self):
        """After save/load, next tx_id > previous max."""
        pipe = _make_pipeline()
        pipe.ingest_text("Document one", source="a")
        pipe.ingest_text("Document two", source="b")
        max_tx_before = max(r.transaction_time.tx_id for r in pipe.store.revisions.values())

        with tempfile.TemporaryDirectory() as tmp:
            pipe.save(tmp)
            loaded = Pipeline.load(tmp)

        # Ingest on loaded pipeline should use higher tx_ids
        rids = loaded.ingest_text("Document three", source="c")
        new_tx = loaded.store.revisions[rids[0]].transaction_time.tx_id
        assert new_tx > max_tx_before


# ============================================================
# Test 10: Pipeline.load with missing files
# ============================================================

class TestLoadMissingFiles:

    def test_load_missing_directory_raises(self):
        """Loading from nonexistent path raises clear error."""
        with pytest.raises((FileNotFoundError, ValueError, OSError)):
            Pipeline.load("/nonexistent/path/that/doesnt/exist")

    def test_load_empty_directory_raises(self):
        """Loading from empty directory raises clear error."""
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises((FileNotFoundError, ValueError, KeyError, OSError)):
                Pipeline.load(tmp)
