from datetime import datetime, timezone

import pytest

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


def _assert_relation_ids_sorted(*buckets: tuple) -> None:
    for bucket in buckets:
        relation_ids = tuple(relation.relation_id for relation in bucket)
        assert relation_ids == tuple(sorted(relation_ids))


def test_query_relation_lifecycle_as_of_tracks_active_and_pending_across_retraction_transition() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    residence_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": "archive-lifecycle-transition"},
    )

    residence_asserted = store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    evidence_revision = store.assert_revision(
        core=evidence_core,
        assertion="Archive A records London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_doc"),
        confidence_bp=9000,
    )
    active_relation = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=residence_asserted.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="supports",
        from_revision_id=residence_asserted.revision_id,
        to_revision_id="missing-revision-z",
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    valid_at = dt(2024, 6, 1)
    projection_tx2 = store.query_relation_lifecycle_as_of(tx_id=2, valid_at=valid_at)
    assert projection_tx2.active == (active_relation,)
    assert projection_tx2.pending == ()

    projection_tx3 = store.query_relation_lifecycle_as_of(tx_id=3, valid_at=valid_at)
    assert projection_tx3.active == (active_relation,)
    assert projection_tx3.pending == (pending_relation,)

    store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_b"),
        confidence_bp=7000,
        status="retracted",
    )

    projection_tx4 = store.query_relation_lifecycle_as_of(tx_id=4, valid_at=valid_at)
    assert projection_tx4.active == ()
    assert projection_tx4.pending == (pending_relation,)


def test_query_relation_lifecycle_as_of_is_deterministically_ordered() -> None:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core_residence = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_doc_a = ClaimCore(claim_type="document", slots={"id": "lifecycle-order-a"})
    core_doc_b = ClaimCore(claim_type="document", slots={"id": "lifecycle-order-b"})

    operation_order = ("active_a", "pending_a", "active_b", "pending_b")

    def build_store(order: tuple[str, ...]) -> KnowledgeStore:
        store = KnowledgeStore()
        residence_revision = store.assert_revision(
            core=core_residence,
            assertion="Ada lives in London",
            valid_time=valid_time,
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="source_residence"),
            confidence_bp=8200,
            status="asserted",
        )
        doc_a_revision = store.assert_revision(
            core=core_doc_a,
            assertion="Lifecycle order doc A",
            valid_time=valid_time,
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="source_doc_a"),
            confidence_bp=9000,
            status="asserted",
        )
        doc_b_revision = store.assert_revision(
            core=core_doc_b,
            assertion="Lifecycle order doc B",
            valid_time=valid_time,
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="source_doc_b"),
            confidence_bp=9000,
            status="asserted",
        )

        for operation in order:
            if operation == "active_a":
                store.attach_relation(
                    relation_type="derived_from",
                    from_revision_id=residence_revision.revision_id,
                    to_revision_id=doc_a_revision.revision_id,
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
                continue
            if operation == "active_b":
                store.attach_relation(
                    relation_type="supports",
                    from_revision_id=residence_revision.revision_id,
                    to_revision_id=doc_b_revision.revision_id,
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
                continue

            orphan_replica = KnowledgeStore()
            if operation == "pending_a":
                relation = RelationEdge(
                    relation_type="depends_on",
                    from_revision_id=residence_revision.revision_id,
                    to_revision_id="missing-lifecycle-order-a",
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
            else:
                relation = RelationEdge(
                    relation_type="supports",
                    from_revision_id=residence_revision.revision_id,
                    to_revision_id="missing-lifecycle-order-b",
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
            orphan_replica.relations[relation.relation_id] = relation
            store = store.merge(orphan_replica).merged
        return store

    forward_store = build_store(operation_order)
    reverse_store = build_store(tuple(reversed(operation_order)))

    forward_projection = forward_store.query_relation_lifecycle_as_of(
        tx_id=5,
        valid_at=dt(2024, 6, 1),
    )
    reverse_projection = reverse_store.query_relation_lifecycle_as_of(
        tx_id=5,
        valid_at=dt(2024, 6, 1),
    )

    assert forward_projection == reverse_projection
    _assert_relation_ids_sorted(forward_projection.active, forward_projection.pending)


def test_query_relation_lifecycle_as_of_supports_revision_filtering() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    target_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_core = ClaimCore(claim_type="document", slots={"id": "lifecycle-filter-evidence"})
    other_from_core = ClaimCore(claim_type="document", slots={"id": "lifecycle-filter-other-from"})
    other_to_core = ClaimCore(claim_type="document", slots={"id": "lifecycle-filter-other-to"})

    target_revision = store.assert_revision(
        core=target_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_target"),
        confidence_bp=8200,
        status="asserted",
    )
    evidence_revision = store.assert_revision(
        core=evidence_core,
        assertion="Archive evidence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_evidence"),
        confidence_bp=9000,
        status="asserted",
    )
    other_from_revision = store.assert_revision(
        core=other_from_core,
        assertion="Other from",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_other_from"),
        confidence_bp=9000,
        status="asserted",
    )
    other_to_revision = store.assert_revision(
        core=other_to_core,
        assertion="Other to",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_other_to"),
        confidence_bp=9000,
        status="asserted",
    )

    other_active = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=other_from_revision.revision_id,
        to_revision_id=other_to_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )

    orphan_replica = KnowledgeStore()
    target_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-lifecycle-filter-target",
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    other_pending = RelationEdge(
        relation_type="supports",
        from_revision_id=other_from_revision.revision_id,
        to_revision_id="missing-lifecycle-filter-other",
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    orphan_replica.relations[target_pending.relation_id] = target_pending
    orphan_replica.relations[other_pending.relation_id] = other_pending
    store = store.merge(orphan_replica).merged

    store.assert_revision(
        core=target_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_target_retracted"),
        confidence_bp=8200,
        status="retracted",
    )

    valid_at = dt(2024, 6, 1)
    target_projection = store.query_relation_lifecycle_as_of(
        tx_id=4,
        valid_at=valid_at,
        revision_id=target_revision.revision_id,
    )
    assert target_projection.active == ()
    assert target_projection.pending == (target_pending,)

    evidence_projection = store.query_relation_lifecycle_as_of(
        tx_id=4,
        valid_at=valid_at,
        revision_id=evidence_revision.revision_id,
    )
    assert evidence_projection.active == ()
    assert evidence_projection.pending == ()

    other_projection = store.query_relation_lifecycle_as_of(
        tx_id=4,
        valid_at=valid_at,
        revision_id=other_from_revision.revision_id,
    )
    assert other_projection.active == (other_active,)
    assert other_projection.pending == (other_pending,)

    missing_projection = store.query_relation_lifecycle_as_of(
        tx_id=4,
        valid_at=valid_at,
        revision_id="missing-revision",
    )
    assert missing_projection.active == ()
    assert missing_projection.pending == ()


def test_query_relation_lifecycle_for_tx_window_matches_as_of_filtered_projection() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    residence_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_primary_core = ClaimCore(claim_type="document", slots={"id": "window-primary"})
    evidence_secondary_core = ClaimCore(claim_type="document", slots={"id": "window-secondary"})

    residence_revision = store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8200,
        status="asserted",
    )
    evidence_primary_revision = store.assert_revision(
        core=evidence_primary_core,
        assertion="Primary archive evidence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_primary"),
        confidence_bp=9000,
        status="asserted",
    )
    evidence_secondary_revision = store.assert_revision(
        core=evidence_secondary_core,
        assertion="Secondary archive evidence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_secondary"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_primary_revision.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    start_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_primary_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    end_active = store.attach_relation(
        relation_type="depends_on",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_secondary_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    pending_mid = RelationEdge(
        relation_type="depends_on",
        from_revision_id=residence_revision.revision_id,
        to_revision_id="missing-window-mid",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    pending_end = RelationEdge(
        relation_type="supports",
        from_revision_id=residence_revision.revision_id,
        to_revision_id="missing-window-end",
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    orphan_replica.relations[pending_mid.relation_id] = pending_mid
    orphan_replica.relations[pending_end.relation_id] = pending_end
    store = store.merge(orphan_replica).merged

    valid_at = dt(2024, 6, 1)
    tx_windows = (
        (4, 4),
        (5, 5),
        (5, 6),
        (6, 7),
        (8, 9),
        (5, 7),
    )
    for tx_start, tx_end in tx_windows:
        projection = store.query_relation_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
        as_of_projection = store.query_relation_lifecycle_as_of(
            tx_id=tx_end,
            valid_at=valid_at,
        )
        assert projection.active == tuple(
            relation
            for relation in as_of_projection.active
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        )
        assert projection.pending == tuple(
            relation
            for relation in as_of_projection.pending
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        )
        _assert_relation_ids_sorted(projection.active, projection.pending)

    full_window_projection = store.query_relation_lifecycle_for_tx_window(
        tx_start=5,
        tx_end=7,
        valid_at=valid_at,
    )
    assert full_window_projection.active == tuple(
        sorted((start_active, end_active), key=lambda relation: relation.relation_id)
    )
    assert full_window_projection.pending == tuple(
        sorted((pending_mid, pending_end), key=lambda relation: relation.relation_id)
    )

    residence_window_projection = store.query_relation_lifecycle_for_tx_window(
        tx_start=6,
        tx_end=7,
        valid_at=valid_at,
        revision_id=residence_revision.revision_id,
    )
    assert residence_window_projection.active == (end_active,)
    assert residence_window_projection.pending == tuple(
        sorted((pending_mid, pending_end), key=lambda relation: relation.relation_id)
    )

    evidence_primary_window_projection = store.query_relation_lifecycle_for_tx_window(
        tx_start=6,
        tx_end=7,
        valid_at=valid_at,
        revision_id=evidence_primary_revision.revision_id,
    )
    assert evidence_primary_window_projection.active == ()
    assert evidence_primary_window_projection.pending == ()


def test_query_relation_lifecycle_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_relation_lifecycle_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=dt(2024, 6, 1),
        )
