from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjection,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _assert_revision_ordering(revisions: tuple) -> None:
    revision_ids = tuple(revision.revision_id for revision in revisions)
    assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_ordering(relations: tuple) -> None:
    relation_ids = tuple(relation.relation_id for relation in relations)
    assert relation_ids == tuple(sorted(relation_ids))


def _assert_signature_ordering(signatures: tuple) -> None:
    assert signatures == tuple(sorted(signatures))


def _assert_merge_conflict_projection_ordering(projection: MergeConflictProjection) -> None:
    assert projection.signature_counts == tuple(
        sorted(projection.signature_counts, key=lambda signature_count: signature_count[:3])
    )
    assert projection.code_counts == tuple(
        sorted(projection.code_counts, key=lambda code_count: code_count[0])
    )


def _filter_for_window(
    items: tuple,
    *,
    tx_start: int,
    tx_end: int,
    tx_id_of,
) -> tuple:
    return tuple(item for item in items if tx_start <= tx_id_of(item) <= tx_end)


def _build_lifecycle_window_store() -> tuple[
    KnowledgeStore,
    datetime,
    int,
    int,
    str,
    str,
    str,
]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = 5
    tx_end = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "tx-window-canonical-anchor"})
    core_enter_active = ClaimCore(
        claim_type="residence",
        slots={"subject": "tx-window-canonical-enter"},
    )
    core_exit_active = ClaimCore(
        claim_type="residence",
        slots={"subject": "tx-window-canonical-exit"},
    )
    core_reactivate = ClaimCore(
        claim_type="residence",
        slots={"subject": "tx-window-canonical-reactivate"},
    )
    core_future = ClaimCore(claim_type="document", slots={"id": "tx-window-canonical-future"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="tx-window canonical anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_tx_window_canonical_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    exited_active_revision = store.assert_revision(
        core=core_exit_active,
        assertion="tx-window canonical exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_tx_window_canonical_exit_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_reactivate,
        assertion="tx-window canonical reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_tx_window_canonical_reactivate_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    entered_active_revision = store.assert_revision(
        core=core_enter_active,
        assertion="tx-window canonical entered active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_tx_window_canonical_enter"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_exit_active,
        assertion="tx-window canonical exited active",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_tx_window_canonical_exit_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    reactivated_revision = store.assert_revision(
        core=core_reactivate,
        assertion="tx-window canonical reactivate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_tx_window_canonical_reactivate_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    future_revision = store.assert_revision(
        core=core_future,
        assertion="tx-window canonical future",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_tx_window_canonical_future"),
        confidence_bp=9000,
        status="asserted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=future_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=reactivated_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    stable_pending = RelationEdge(
        relation_type="depends_on",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-tx-window-canonical-stable",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    entered_pending = RelationEdge(
        relation_type="supports",
        from_revision_id=entered_active_revision.revision_id,
        to_revision_id="missing-tx-window-canonical-entered",
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
    )
    orphan_replica.relations[stable_pending.relation_id] = stable_pending
    orphan_replica.relations[entered_pending.relation_id] = entered_pending
    store = store.merge(orphan_replica).merged

    return (
        store,
        valid_at,
        tx_start,
        tx_end,
        core_reactivate.core_id,
        core_anchor.core_id,
        anchor_revision.revision_id,
    )


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="tx-window-canonical-orphan-a",
        details="missing endpoint canonical orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="tx-window-canonical-orphan-b",
        details="missing endpoint canonical orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="tx-window-canonical-competing-subject",
        details="competing asserted revisions",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (12, MergeResult(merged=KnowledgeStore(), conflicts=(competing,))),
    )


def _expected_merge_conflict_window_projection_from_as_of_filtering(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> MergeConflictProjection:
    as_of_stream_at_tx_end = tuple(
        (merge_result_tx_id, merge_result)
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_end
    )
    explicitly_filtered_as_of_stream = tuple(
        (merge_result_tx_id, merge_result)
        for merge_result_tx_id, merge_result in as_of_stream_at_tx_end
        if tx_start <= merge_result_tx_id
    )
    return KnowledgeStore.query_merge_conflict_projection_as_of(
        explicitly_filtered_as_of_stream,
        tx_id=tx_end,
    )


def test_tx_window_canonicalization_matches_explicit_as_of_filtering_for_revision_surface() -> None:
    (
        store,
        valid_at,
        tx_start,
        tx_end,
        reactivated_core_id,
        _anchor_core_id,
        _anchor_revision_id,
    ) = _build_lifecycle_window_store()

    window_projection = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    as_of_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )

    assert window_projection.active == _filter_for_window(
        as_of_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda revision: revision.transaction_time.tx_id,
    )
    assert window_projection.retracted == _filter_for_window(
        as_of_projection.retracted,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda revision: revision.transaction_time.tx_id,
    )
    _assert_revision_ordering(window_projection.active)
    _assert_revision_ordering(window_projection.retracted)

    filtered_window_projection = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=reactivated_core_id,
    )
    filtered_as_of_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=reactivated_core_id,
    )
    assert filtered_window_projection.active == _filter_for_window(
        filtered_as_of_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda revision: revision.transaction_time.tx_id,
    )
    assert filtered_window_projection.retracted == _filter_for_window(
        filtered_as_of_projection.retracted,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda revision: revision.transaction_time.tx_id,
    )


def test_tx_window_canonicalization_matches_explicit_as_of_filtering_for_relation_surfaces() -> None:
    (
        store,
        valid_at,
        tx_start,
        tx_end,
        _reactivated_core_id,
        anchor_core_id,
        anchor_revision_id,
    ) = _build_lifecycle_window_store()

    resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    assert resolution_window.active == _filter_for_window(
        resolution_as_of.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    assert resolution_window.pending == _filter_for_window(
        resolution_as_of.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    _assert_relation_ordering(resolution_window.active)
    _assert_relation_ordering(resolution_window.pending)

    filtered_resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    filtered_resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=anchor_core_id,
    )
    assert filtered_resolution_window.active == _filter_for_window(
        filtered_resolution_as_of.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    assert filtered_resolution_window.pending == _filter_for_window(
        filtered_resolution_as_of.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )

    lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    lifecycle_as_of = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    assert lifecycle_window.active == _filter_for_window(
        lifecycle_as_of.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    assert lifecycle_window.pending == _filter_for_window(
        lifecycle_as_of.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    _assert_relation_ordering(lifecycle_window.active)
    _assert_relation_ordering(lifecycle_window.pending)

    filtered_lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    filtered_lifecycle_as_of = store.query_relation_lifecycle_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    assert filtered_lifecycle_window.active == _filter_for_window(
        filtered_lifecycle_as_of.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )
    assert filtered_lifecycle_window.pending == _filter_for_window(
        filtered_lifecycle_as_of.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda relation: relation.transaction_time.tx_id,
    )


def test_tx_window_canonicalization_matches_explicit_as_of_filtering_for_relation_signatures() -> None:
    (
        store,
        valid_at,
        tx_start,
        tx_end,
        _reactivated_core_id,
        _anchor_core_id,
        anchor_revision_id,
    ) = _build_lifecycle_window_store()

    window_projection = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    as_of_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
    )
    assert window_projection.active == _filter_for_window(
        as_of_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda signature: signature[5],
    )
    assert window_projection.pending == _filter_for_window(
        as_of_projection.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda signature: signature[5],
    )
    _assert_signature_ordering(window_projection.active)
    _assert_signature_ordering(window_projection.pending)

    filtered_window_projection = store.query_relation_lifecycle_signatures_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    filtered_as_of_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        revision_id=anchor_revision_id,
    )
    assert filtered_window_projection.active == _filter_for_window(
        filtered_as_of_projection.active,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda signature: signature[5],
    )
    assert filtered_window_projection.pending == _filter_for_window(
        filtered_as_of_projection.pending,
        tx_start=tx_start,
        tx_end=tx_end,
        tx_id_of=lambda signature: signature[5],
    )


def test_tx_window_canonicalization_matches_explicit_as_of_filtering_for_merge_conflict_projection() -> None:
    stream = _build_merge_conflict_stream()
    tx_windows = (
        (9, 9),
        (10, 10),
        (10, 11),
        (11, 11),
        (11, 12),
        (12, 12),
        (9, 12),
    )

    for tx_start, tx_end in tx_windows:
        window_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        expected_projection = _expected_merge_conflict_window_projection_from_as_of_filtering(
            stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert window_projection.summary == expected_projection.summary
        _assert_merge_conflict_projection_ordering(window_projection)


def test_tx_window_canonicalization_rejects_inverted_windows_across_surfaces() -> None:
    store = KnowledgeStore()
    valid_at = dt(2024, 6, 1)

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_revision_lifecycle_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=valid_at,
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_relation_resolution_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=valid_at,
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_relation_lifecycle_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=valid_at,
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            (),
            tx_start=11,
            tx_end=10,
        )

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=11,
            tx_end=10,
            valid_at=valid_at,
        )
