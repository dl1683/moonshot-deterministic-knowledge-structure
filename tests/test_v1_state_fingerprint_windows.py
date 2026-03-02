from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    ConflictCode,
    DeterministicStateFingerprint,
    KnowledgeStore,
    MergeConflict,
    MergeResult,
    Provenance,
    RelationEdge,
    RelationLifecycleProjection,
    RelationLifecycleSignatureProjection,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class OneShotIterable:
    def __init__(self, values: tuple) -> None:
        self._values = values
        self._iterated = False

    def __iter__(self):
        if self._iterated:
            raise AssertionError("one-shot iterable was iterated more than once")
        self._iterated = True
        return iter(self._values)


def _build_state_fingerprint_window_store() -> tuple[KnowledgeStore, datetime, int, int, str, str]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = 2
    tx_end = 5

    core_subject = ClaimCore(claim_type="residence", slots={"subject": "window-fingerprint-ada"})
    core_anchor = ClaimCore(claim_type="document", slots={"id": "window-fingerprint-anchor"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "window-fingerprint-context"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "window-fingerprint-retracted"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="window fingerprint anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_window_fingerprint_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = store.assert_revision(
        core=core_context,
        assertion="window fingerprint context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_window_fingerprint_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="window subject candidate A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_window_fingerprint_subject_a"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="window subject candidate B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_window_fingerprint_subject_b"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_winner = (
        subject_revision_a
        if subject_revision_a.revision_id < subject_revision_b.revision_id
        else subject_revision_b
    )
    subject_loser = (
        subject_revision_b
        if subject_winner.revision_id == subject_revision_a.revision_id
        else subject_revision_a
    )

    retracted_asserted = store.assert_revision(
        core=core_retracted,
        assertion="window retracted asserted candidate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_window_fingerprint_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="window retracted final winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_window_fingerprint_retracted_retracted"),
        confidence_bp=8300,
        status="retracted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=subject_winner.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=context_revision.revision_id,
        to_revision_id=subject_winner.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=context_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=subject_loser.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=retracted_asserted.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )

    orphan_replica = KnowledgeStore()
    pending_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=subject_winner.revision_id,
        to_revision_id="missing-window-fingerprint-pending-endpoint",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_start, tx_end, core_subject.core_id, core_retracted.core_id


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="window-fingerprint-orphan-a",
        details="missing endpoint window-fingerprint-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="window-fingerprint-orphan-b",
        details="missing endpoint window-fingerprint-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="window-fingerprint-competing",
        details="competing revision winner",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (13, MergeResult(merged=KnowledgeStore(), conflicts=(competing, orphan_b))),
    )


def _ordered_projection_tuple(
    fingerprint: DeterministicStateFingerprint,
) -> tuple[tuple, ...]:
    return (
        tuple(
            revision.revision_id for revision in fingerprint.revision_lifecycle.active
        ),
        tuple(
            revision.revision_id for revision in fingerprint.revision_lifecycle.retracted
        ),
        tuple(
            relation.relation_id for relation in fingerprint.relation_resolution.active
        ),
        tuple(
            relation.relation_id for relation in fingerprint.relation_resolution.pending
        ),
        tuple(
            relation.relation_id for relation in fingerprint.relation_lifecycle.active
        ),
        tuple(
            relation.relation_id for relation in fingerprint.relation_lifecycle.pending
        ),
        fingerprint.relation_lifecycle_signatures.active,
        fingerprint.relation_lifecycle_signatures.pending,
        fingerprint.merge_conflict_projection.signature_counts,
        fingerprint.merge_conflict_projection.code_counts,
    )


def test_state_fingerprint_window_projection_parity_matches_canonical_routes() -> None:
    store, valid_at, tx_start, tx_end, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_window_store()
    )
    fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )

    assert fingerprint.revision_lifecycle == store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert fingerprint.relation_resolution == store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert fingerprint.relation_lifecycle == store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert (
        fingerprint.relation_lifecycle_signatures
        == store.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
        )
    )
    assert (
        fingerprint.merge_conflict_projection
        == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            (),
            tx_start=tx_start,
            tx_end=tx_end,
        )
    )
    assert fingerprint.ordered_projection == _ordered_projection_tuple(fingerprint)


def test_state_fingerprint_window_ordering_and_digest_are_stable() -> None:
    store, valid_at, tx_start, tx_end, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_window_store()
    )
    fingerprint_first = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    fingerprint_second = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )

    assert fingerprint_first == fingerprint_second
    assert fingerprint_first.digest == fingerprint_second.digest
    assert fingerprint_first.revision_lifecycle.active == tuple(
        sorted(
            fingerprint_first.revision_lifecycle.active,
            key=lambda revision: revision.revision_id,
        )
    )
    assert fingerprint_first.revision_lifecycle.retracted == tuple(
        sorted(
            fingerprint_first.revision_lifecycle.retracted,
            key=lambda revision: revision.revision_id,
        )
    )
    assert fingerprint_first.relation_resolution.active == tuple(
        sorted(
            fingerprint_first.relation_resolution.active,
            key=lambda relation: relation.relation_id,
        )
    )
    assert fingerprint_first.relation_resolution.pending == tuple(
        sorted(
            fingerprint_first.relation_resolution.pending,
            key=lambda relation: relation.relation_id,
        )
    )
    assert fingerprint_first.relation_lifecycle.active == tuple(
        sorted(
            fingerprint_first.relation_lifecycle.active,
            key=lambda relation: relation.relation_id,
        )
    )
    assert fingerprint_first.relation_lifecycle.pending == tuple(
        sorted(
            fingerprint_first.relation_lifecycle.pending,
            key=lambda relation: relation.relation_id,
        )
    )
    assert fingerprint_first.relation_lifecycle_signatures.active == tuple(
        sorted(fingerprint_first.relation_lifecycle_signatures.active)
    )
    assert fingerprint_first.relation_lifecycle_signatures.pending == tuple(
        sorted(fingerprint_first.relation_lifecycle_signatures.pending)
    )
    assert fingerprint_first.merge_conflict_projection.signature_counts == tuple(
        sorted(
            fingerprint_first.merge_conflict_projection.signature_counts,
            key=lambda signature_count: signature_count[:3],
        )
    )
    assert fingerprint_first.merge_conflict_projection.code_counts == tuple(
        sorted(
            fingerprint_first.merge_conflict_projection.code_counts,
            key=lambda code_count: code_count[0],
        )
    )


def test_state_fingerprint_window_core_filtering_matches_canonical_routes() -> None:
    store, valid_at, tx_start, tx_end, subject_core_id, retracted_core_id = (
        _build_state_fingerprint_window_store()
    )

    subject_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    subject_winner = store.query_as_of(
        subject_core_id,
        tx_id=tx_end,
        valid_at=valid_at,
    )
    assert subject_winner is not None
    assert subject_fingerprint.revision_lifecycle == store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    assert subject_fingerprint.relation_resolution == store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    assert subject_fingerprint.relation_lifecycle == store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    assert (
        subject_fingerprint.relation_lifecycle_signatures
        == store.query_relation_lifecycle_signatures_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            revision_id=subject_winner.revision_id,
        )
    )

    retracted_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_fingerprint.revision_lifecycle == store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_fingerprint.relation_resolution == store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_fingerprint.relation_lifecycle == RelationLifecycleProjection(
        active=(),
        pending=(),
    )
    assert (
        retracted_fingerprint.relation_lifecycle_signatures
        == RelationLifecycleSignatureProjection(active=(), pending=())
    )


def test_state_fingerprint_window_rejects_inverted_tx_window() -> None:
    store = KnowledgeStore()

    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        store.query_state_fingerprint_for_tx_window(
            tx_start=12,
            tx_end=11,
            valid_at=dt(2024, 6, 1),
        )


def test_state_fingerprint_window_merge_conflict_component_matches_one_shot_iterable_projection() -> None:
    merge_results_by_tx = _build_merge_conflict_stream()
    projection_from_one_shot = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        OneShotIterable(merge_results_by_tx),
        tx_start=10,
        tx_end=13,
    )
    projection_from_tuple = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        merge_results_by_tx,
        tx_start=10,
        tx_end=13,
    )
    assert projection_from_one_shot == projection_from_tuple

    store, valid_at, tx_start, tx_end, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_window_store()
    )
    base_fingerprint = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert base_fingerprint.merge_conflict_projection == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        (),
        tx_start=tx_start,
        tx_end=tx_end,
    )

    fingerprint_from_one_shot_projection = DeterministicStateFingerprint(
        revision_lifecycle=base_fingerprint.revision_lifecycle,
        relation_resolution=base_fingerprint.relation_resolution,
        relation_lifecycle=base_fingerprint.relation_lifecycle,
        merge_conflict_projection=projection_from_one_shot,
        relation_lifecycle_signatures=base_fingerprint.relation_lifecycle_signatures,
    )
    fingerprint_from_tuple_projection = DeterministicStateFingerprint(
        revision_lifecycle=base_fingerprint.revision_lifecycle,
        relation_resolution=base_fingerprint.relation_resolution,
        relation_lifecycle=base_fingerprint.relation_lifecycle,
        merge_conflict_projection=projection_from_tuple,
        relation_lifecycle_signatures=base_fingerprint.relation_lifecycle_signatures,
    )
    assert fingerprint_from_one_shot_projection == fingerprint_from_tuple_projection
    assert (
        fingerprint_from_one_shot_projection.digest
        == fingerprint_from_tuple_projection.digest
    )
