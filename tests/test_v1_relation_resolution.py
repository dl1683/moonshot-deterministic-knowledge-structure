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


def test_query_relation_resolution_as_of_buckets_track_pending_promotion() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    residence_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_core = ClaimCore(claim_type="document", slots={"id": "archive-resolution-promotion"})

    residence_revision = store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8200,
        status="asserted",
    )

    endpoint_replica = KnowledgeStore()
    evidence_revision = endpoint_replica.assert_revision(
        core=evidence_core,
        assertion="Archive A records London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_archive"),
        confidence_bp=9000,
        status="asserted",
    )

    orphan_replica = KnowledgeStore()
    promoted_relation = RelationEdge(
        relation_type="derived_from",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    orphan_replica.relations[promoted_relation.relation_id] = promoted_relation
    store = store.merge(orphan_replica).merged

    pre_promotion = store.query_relation_resolution_as_of(
        tx_id=2,
        valid_at=dt(2024, 6, 1),
    )
    assert pre_promotion.active == ()
    assert pre_promotion.pending == (promoted_relation,)

    store = store.merge(endpoint_replica).merged
    post_promotion = store.query_relation_resolution_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
    )
    assert post_promotion.active == (promoted_relation,)
    assert post_promotion.pending == ()


def test_query_relation_resolution_as_of_is_deterministically_ordered() -> None:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    core_residence = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    core_doc_a = ClaimCore(claim_type="document", slots={"id": "archive-a"})
    core_doc_b = ClaimCore(claim_type="document", slots={"id": "archive-b"})

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
            assertion="Archive A records London residence",
            valid_time=valid_time,
            transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="source_doc_a"),
            confidence_bp=9000,
            status="asserted",
        )
        doc_b_revision = store.assert_revision(
            core=core_doc_b,
            assertion="Archive B records London residence",
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
                    to_revision_id="missing-revision-z",
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
            else:
                relation = RelationEdge(
                    relation_type="supports",
                    from_revision_id=residence_revision.revision_id,
                    to_revision_id="missing-revision-a",
                    transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
                )
            orphan_replica.relations[relation.relation_id] = relation
            store = store.merge(orphan_replica).merged
        return store

    forward_store = build_store(operation_order)
    reverse_store = build_store(tuple(reversed(operation_order)))

    forward_projection = forward_store.query_relation_resolution_as_of(
        tx_id=5,
        valid_at=dt(2024, 6, 1),
    )
    reverse_projection = reverse_store.query_relation_resolution_as_of(
        tx_id=5,
        valid_at=dt(2024, 6, 1),
    )

    assert forward_projection == reverse_projection
    assert tuple(
        relation.relation_id for relation in forward_projection.active
    ) == tuple(sorted(relation.relation_id for relation in forward_projection.active))
    assert tuple(
        relation.relation_id for relation in forward_projection.pending
    ) == tuple(sorted(relation.relation_id for relation in forward_projection.pending))


def test_query_relation_resolution_as_of_supports_core_filtering() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    target_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    linked_core = ClaimCore(claim_type="document", slots={"id": "archive-linked"})
    unrelated_core = ClaimCore(claim_type="document", slots={"id": "archive-unrelated"})

    target_revision = store.assert_revision(
        core=target_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_target"),
        confidence_bp=8200,
        status="asserted",
    )
    linked_revision = store.assert_revision(
        core=linked_core,
        assertion="Archive linked to London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked"),
        confidence_bp=9000,
        status="asserted",
    )
    unrelated_revision = store.assert_revision(
        core=unrelated_core,
        assertion="Archive unrelated to London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_unrelated"),
        confidence_bp=9000,
        status="asserted",
    )

    target_active = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    unrelated_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=linked_revision.revision_id,
        to_revision_id=unrelated_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    orphan_replica = KnowledgeStore()
    target_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-revision-target",
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    orphan_replica.relations[target_pending.relation_id] = target_pending
    store = store.merge(orphan_replica).merged

    target_projection = store.query_relation_resolution_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id=target_core.core_id,
    )
    assert target_projection.active == (target_active,)
    assert target_projection.pending == (target_pending,)

    linked_projection = store.query_relation_resolution_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id=linked_core.core_id,
    )
    assert linked_projection.active == tuple(
        sorted((target_active, unrelated_active), key=lambda relation: relation.relation_id)
    )
    assert linked_projection.pending == ()

    missing_projection = store.query_relation_resolution_as_of(
        tx_id=3,
        valid_at=dt(2024, 6, 1),
        core_id="missing-core",
    )
    assert missing_projection.active == ()
    assert missing_projection.pending == ()


def test_query_relation_resolution_as_of_active_bucket_matches_query_relations_as_of() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    residence_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    evidence_core = ClaimCore(claim_type="document", slots={"id": "archive-parity"})

    residence_asserted = store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_residence"),
        confidence_bp=8200,
        status="asserted",
    )
    evidence_revision = store.assert_revision(
        core=evidence_core,
        assertion="Archive records London residence",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_archive"),
        confidence_bp=9000,
        status="asserted",
    )
    active_relation = store.attach_relation(
        relation_type="derived_from",
        from_revision_id=residence_asserted.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=residence_asserted.revision_id,
        to_revision_id="missing-revision-parity",
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    store.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_residence_retracted"),
        confidence_bp=8200,
        status="retracted",
    )

    valid_at = dt(2024, 6, 1)
    projection_tx2 = store.query_relation_resolution_as_of(tx_id=2, valid_at=valid_at)
    assert projection_tx2.active == (active_relation,)
    assert projection_tx2.pending == ()

    projection_tx3 = store.query_relation_resolution_as_of(tx_id=3, valid_at=valid_at)
    assert projection_tx3.active == (active_relation,)
    assert projection_tx3.pending == (pending_relation,)

    projection_tx4 = store.query_relation_resolution_as_of(tx_id=4, valid_at=valid_at)
    assert projection_tx4.active == ()
    assert projection_tx4.pending == (pending_relation,)

    for tx_id in (2, 3, 4):
        projection = store.query_relation_resolution_as_of(tx_id=tx_id, valid_at=valid_at)
        assert projection.active == store.query_relations_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            active_only=True,
        )


def test_query_relation_resolution_for_tx_window_matches_as_of_filtered_projection() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    target_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    linked_core_a = ClaimCore(claim_type="document", slots={"id": "window-link-a"})
    linked_core_b = ClaimCore(claim_type="document", slots={"id": "window-link-b"})

    target_revision = store.assert_revision(
        core=target_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_target"),
        confidence_bp=8300,
        status="asserted",
    )
    linked_revision_a = store.assert_revision(
        core=linked_core_a,
        assertion="Window link A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked_a"),
        confidence_bp=9000,
        status="asserted",
    )
    linked_revision_b = store.assert_revision(
        core=linked_core_b,
        assertion="Window link B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked_b"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision_a.revision_id,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    start_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision_b.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    end_active = store.attach_relation(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision_a.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    orphan_replica = KnowledgeStore()
    pending_mid = RelationEdge(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-window-mid",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    pending_end = RelationEdge(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-window-end",
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    orphan_replica.relations[pending_mid.relation_id] = pending_mid
    orphan_replica.relations[pending_end.relation_id] = pending_end
    store = store.merge(orphan_replica).merged

    tx_windows = (
        (4, 4),
        (5, 5),
        (5, 6),
        (6, 7),
        (4, 7),
    )
    for tx_start, tx_end in tx_windows:
        projection = store.query_relation_resolution_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=dt(2024, 6, 1),
        )
        as_of_projection = store.query_relation_resolution_as_of(
            tx_id=tx_end,
            valid_at=dt(2024, 6, 1),
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

    full_window = store.query_relation_resolution_for_tx_window(
        tx_start=5,
        tx_end=7,
        valid_at=dt(2024, 6, 1),
    )
    assert full_window.active == tuple(
        sorted((start_active, end_active), key=lambda relation: relation.relation_id)
    )
    assert full_window.pending == tuple(
        sorted((pending_mid, pending_end), key=lambda relation: relation.relation_id)
    )


def test_query_relation_resolution_for_tx_window_includes_start_and_end_boundaries() -> None:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    target_core = ClaimCore(claim_type="residence", slots={"subject": "Ada Lovelace"})
    linked_core = ClaimCore(claim_type="document", slots={"id": "boundary-linked"})

    target_revision = store.assert_revision(
        core=target_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_target"),
        confidence_bp=8400,
        status="asserted",
    )
    linked_revision = store.assert_revision(
        core=linked_core,
        assertion="Boundary link",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_linked"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=9, recorded_at=dt(2024, 1, 10)),
    )
    start_active = store.attach_relation(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=10, recorded_at=dt(2024, 1, 11)),
    )
    end_active = store.attach_relation(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id=linked_revision.revision_id,
        transaction_time=TransactionTime(tx_id=12, recorded_at=dt(2024, 1, 13)),
    )
    orphan_replica = KnowledgeStore()
    pending_outside = RelationEdge(
        relation_type="depends_on",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-boundary-outside",
        transaction_time=TransactionTime(tx_id=9, recorded_at=dt(2024, 1, 10)),
    )
    pending_end = RelationEdge(
        relation_type="supports",
        from_revision_id=target_revision.revision_id,
        to_revision_id="missing-boundary-end",
        transaction_time=TransactionTime(tx_id=12, recorded_at=dt(2024, 1, 13)),
    )
    orphan_replica.relations[pending_outside.relation_id] = pending_outside
    orphan_replica.relations[pending_end.relation_id] = pending_end
    store = store.merge(orphan_replica).merged

    projection = store.query_relation_resolution_for_tx_window(
        tx_start=10,
        tx_end=12,
        valid_at=dt(2024, 6, 1),
    )
    assert projection.active == tuple(
        sorted((start_active, end_active), key=lambda relation: relation.relation_id)
    )
    assert projection.pending == (pending_end,)


def test_query_relation_resolution_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore().query_relation_resolution_for_tx_window(
            tx_start=8,
            tx_end=7,
            valid_at=dt(2024, 6, 1),
        )
