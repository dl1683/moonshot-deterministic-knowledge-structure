"""Regression tests for merge pending relations transfer (P1/P2/P3 bugs).

P1: merge() must process other._pending_relations, not just other.relations.
P2: merge() must transfer other._relation_variants into merged store.
P3: merge() must transfer other._relation_collision_pairs into merged store.
"""
from datetime import datetime, timezone

from dks import (
    ClaimCore,
    KnowledgeStore,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_store_with_pending_relation() -> tuple[KnowledgeStore, str, str, str]:
    """Create a store where a relation is pending because one endpoint is missing."""
    store_a = KnowledgeStore()
    core1 = ClaimCore(claim_type="fact", slots={"subject": "alpha"})
    core2 = ClaimCore(claim_type="fact", slots={"subject": "beta"})

    rev1 = store_a.assert_revision(
        core=core1,
        assertion="Alpha fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )
    rev2 = store_a.assert_revision(
        core=core2,
        assertion="Beta fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="src_b"),
        confidence_bp=8000,
        status="asserted",
    )

    # Create a relation between rev1 and rev2
    relation = RelationEdge(
        relation_type="supports",
        from_revision_id=rev1.revision_id,
        to_revision_id=rev2.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 3)),
    )

    # Build store_b with only rev1 and the relation — rev2 is missing,
    # so the relation will be pending
    store_b = KnowledgeStore()
    store_b.assert_revision(
        core=core1,
        assertion="Alpha fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )
    # Manually place relation into store_b active relations (simulate partial state)
    store_b.relations[relation.relation_id] = relation

    # Now build store_c that has ONLY rev1 — merging store_b into store_c
    # will move the relation to pending (rev2 endpoint missing)
    store_c = KnowledgeStore()
    store_c.assert_revision(
        core=core1,
        assertion="Alpha fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    result = store_c.merge(store_b)
    merged = result.merged

    # The relation should be pending in merged (rev2 endpoint missing)
    assert relation.relation_id in merged._pending_relations
    assert relation.relation_id not in merged.relations

    return merged, rev1.revision_id, rev2.revision_id, relation.relation_id


def test_merge_transfers_pending_relations_from_other() -> None:
    """P1: Pending relations from the right operand must be transferred during merge."""
    merged_with_pending, rev1_id, rev2_id, relation_id = _make_store_with_pending_relation()

    # Create store_d with rev2 — merging should promote the pending relation
    core2 = ClaimCore(claim_type="fact", slots={"subject": "beta"})
    store_d = KnowledgeStore()
    store_d.assert_revision(
        core=core2,
        assertion="Beta fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="src_b"),
        confidence_bp=8000,
        status="asserted",
    )

    # Merge: merged_with_pending (has pending relation) + store_d (has rev2)
    result = merged_with_pending.merge(store_d)
    final = result.merged

    # The relation should now be active (both endpoints present)
    assert relation_id in final.relations
    assert relation_id not in final._pending_relations


def test_merge_pending_to_pending_survives() -> None:
    """P1: Pending relations from other must survive even if they stay pending in merged."""
    merged_with_pending, rev1_id, rev2_id, relation_id = _make_store_with_pending_relation()

    # Create empty store — pending relation should survive in merged
    empty = KnowledgeStore()
    result = merged_with_pending.merge(empty)
    final = result.merged

    # Pending relation must still be present
    assert relation_id in final._pending_relations


def test_merge_pending_from_right_operand_not_lost() -> None:
    """P1: If the RIGHT operand has pending relations, they must appear in merged."""
    core1 = ClaimCore(claim_type="fact", slots={"subject": "gamma"})
    core2 = ClaimCore(claim_type="fact", slots={"subject": "delta"})

    # Store A has rev1 only
    store_a = KnowledgeStore()
    rev1 = store_a.assert_revision(
        core=core1,
        assertion="Gamma fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Store B has rev1 and a relation to non-existent rev2 (pending)
    store_b = KnowledgeStore()
    store_b.assert_revision(
        core=core1,
        assertion="Gamma fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )
    rev2 = store_b.assert_revision(
        core=core2,
        assertion="Delta fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="src_b"),
        confidence_bp=8000,
        status="asserted",
    )
    relation = RelationEdge(
        relation_type="supports",
        from_revision_id=rev1.revision_id,
        to_revision_id=rev2.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 3)),
    )
    # Place relation as pending in store_b (simulating endpoint missing scenario)
    store_b._pending_relations[relation.relation_id] = relation

    # Merge: store_a (no relation) + store_b (has pending relation)
    result = store_a.merge(store_b)
    final = result.merged

    # The pending relation from store_b MUST appear in merged
    assert relation.relation_id in final._pending_relations or relation.relation_id in final.relations


def test_merge_relation_variants_transferred() -> None:
    """P2: Relation variant history from other must be transferred during merge."""
    store_a = KnowledgeStore()
    core = ClaimCore(claim_type="fact", slots={"subject": "epsilon"})

    rev = store_a.assert_revision(
        core=core,
        assertion="Epsilon fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Manually populate _relation_variants on store_a
    fake_relation = RelationEdge(
        relation_type="supports",
        from_revision_id=rev.revision_id,
        to_revision_id=rev.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 2)),
    )
    variant_key = KnowledgeStore._relation_payload_sort_key(fake_relation)
    store_a._relation_variants[fake_relation.relation_id] = {variant_key: fake_relation}

    # Merge into empty store
    empty = KnowledgeStore()
    result = empty.merge(store_a)
    final = result.merged

    # Variant history must survive
    assert fake_relation.relation_id in final._relation_variants
    assert variant_key in final._relation_variants[fake_relation.relation_id]


def test_merge_relation_collision_pairs_transferred() -> None:
    """P3: Relation collision pair history from other must be transferred during merge."""
    store_a = KnowledgeStore()
    core = ClaimCore(claim_type="fact", slots={"subject": "zeta"})

    rev = store_a.assert_revision(
        core=core,
        assertion="Zeta fact",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 1)),
        provenance=Provenance(source="src_a"),
        confidence_bp=8000,
        status="asserted",
    )

    # Manually populate _relation_collision_pairs
    fake_relation_id = "fake_relation_id_for_test"
    fake_pair = (("a", "b", "c", 1, "d"), ("e", "f", "g", 2, "h"))
    store_a._relation_collision_pairs[fake_relation_id] = {fake_pair}

    # Merge into empty store
    empty = KnowledgeStore()
    result = empty.merge(store_a)
    final = result.merged

    # Collision pair history must survive
    assert fake_relation_id in final._relation_collision_pairs
    assert fake_pair in final._relation_collision_pairs[fake_relation_id]
