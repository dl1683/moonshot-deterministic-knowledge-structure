from datetime import datetime, timezone

from dks import (
    ClaimCore,
    ConflictCode,
    DeterministicStateFingerprint,
    KnowledgeStore,
    MergeConflict,
    MergeConflictProjection,
    MergeResult,
    Provenance,
    RelationEdge,
    RelationLifecycleProjection,
    RelationLifecycleSignatureProjection,
    RelationResolutionProjection,
    RevisionLifecycleProjection,
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


def _signature_count_sort_key(signature_count: tuple[str, str, str, int]) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _build_state_fingerprint_store() -> tuple[KnowledgeStore, datetime, int, str, str]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 6

    core_subject = ClaimCore(claim_type="residence", slots={"subject": "ada-fingerprint"})
    core_anchor = ClaimCore(claim_type="document", slots={"id": "fingerprint-anchor"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "fingerprint-context"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "retracted-fingerprint"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="fingerprint anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fingerprint_anchor"),
        confidence_bp=9100,
        status="asserted",
    )
    context_revision = store.assert_revision(
        core=core_context,
        assertion="fingerprint context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_fingerprint_context"),
        confidence_bp=9100,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="subject candidate A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_fingerprint_subject_a"),
        confidence_bp=8400,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="subject candidate B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_fingerprint_subject_b"),
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
        assertion="retracted asserted candidate",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_fingerprint_retracted_asserted"),
        confidence_bp=8300,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="retracted final winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_fingerprint_retracted_retracted"),
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
        to_revision_id="missing-fingerprint-pending-endpoint",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_as_of, core_subject.core_id, core_retracted.core_id


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="fingerprint-orphan-a",
        details="missing endpoint fingerprint-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="fingerprint-orphan-b",
        details="missing endpoint fingerprint-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="fingerprint-competing",
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


def test_state_fingerprint_projection_parity_matches_canonical_as_of_routes() -> None:
    store, valid_at, tx_as_of, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_store()
    )
    fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )

    assert fingerprint.revision_lifecycle == store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert fingerprint.relation_resolution == store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert fingerprint.relation_lifecycle == store.query_relation_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert (
        fingerprint.relation_lifecycle_signatures
        == store.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
    )
    assert (
        fingerprint.merge_conflict_projection
        == KnowledgeStore.query_merge_conflict_projection_as_of(
            (),
            tx_id=tx_as_of,
        )
    )
    assert fingerprint.ordered_projection == _ordered_projection_tuple(fingerprint)


def test_state_fingerprint_ordering_and_digest_are_stable_across_equivalent_inputs() -> None:
    store, valid_at, tx_as_of, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_store()
    )
    fingerprint_first = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    fingerprint_second = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
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

    merge_conflict_projection_a = MergeConflictProjection(
        signature_counts=(
            (
                ConflictCode.ORPHAN_RELATION_ENDPOINT.value,
                "fingerprint-orphan-z",
                "missing endpoint fingerprint-orphan-z",
                1,
            ),
            (
                ConflictCode.COMPETING_REVISION_SAME_SLOT.value,
                "fingerprint-competing-a",
                "competing revision winner",
                2,
            ),
        ),
        code_counts=(
            (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 1),
            (ConflictCode.COMPETING_REVISION_SAME_SLOT.value, 2),
        ),
    )
    merge_conflict_projection_b = MergeConflictProjection(
        signature_counts=tuple(reversed(merge_conflict_projection_a.signature_counts)),
        code_counts=tuple(reversed(merge_conflict_projection_a.code_counts)),
    )

    fingerprint_from_unsorted_inputs = DeterministicStateFingerprint(
        revision_lifecycle=RevisionLifecycleProjection(
            active=tuple(reversed(fingerprint_first.revision_lifecycle.active)),
            retracted=tuple(reversed(fingerprint_first.revision_lifecycle.retracted)),
        ),
        relation_resolution=RelationResolutionProjection(
            active=tuple(reversed(fingerprint_first.relation_resolution.active)),
            pending=tuple(reversed(fingerprint_first.relation_resolution.pending)),
        ),
        relation_lifecycle=RelationLifecycleProjection(
            active=tuple(reversed(fingerprint_first.relation_lifecycle.active)),
            pending=tuple(reversed(fingerprint_first.relation_lifecycle.pending)),
        ),
        merge_conflict_projection=merge_conflict_projection_a,
        relation_lifecycle_signatures=RelationLifecycleSignatureProjection(
            active=tuple(reversed(fingerprint_first.relation_lifecycle_signatures.active)),
            pending=tuple(reversed(fingerprint_first.relation_lifecycle_signatures.pending)),
        ),
    )
    fingerprint_from_sorted_inputs = DeterministicStateFingerprint(
        revision_lifecycle=fingerprint_first.revision_lifecycle,
        relation_resolution=fingerprint_first.relation_resolution,
        relation_lifecycle=fingerprint_first.relation_lifecycle,
        merge_conflict_projection=merge_conflict_projection_b,
        relation_lifecycle_signatures=fingerprint_first.relation_lifecycle_signatures,
    )

    assert fingerprint_from_unsorted_inputs == fingerprint_from_sorted_inputs
    assert fingerprint_from_unsorted_inputs.digest == fingerprint_from_sorted_inputs.digest
    assert fingerprint_from_unsorted_inputs.merge_conflict_projection.signature_counts == tuple(
        sorted(
            fingerprint_from_unsorted_inputs.merge_conflict_projection.signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert fingerprint_from_unsorted_inputs.merge_conflict_projection.code_counts == tuple(
        sorted(
            fingerprint_from_unsorted_inputs.merge_conflict_projection.code_counts,
            key=_code_count_sort_key,
        )
    )


def test_state_fingerprint_core_filtering_matches_canonical_routes() -> None:
    store, valid_at, tx_as_of, subject_core_id, retracted_core_id = (
        _build_state_fingerprint_store()
    )

    subject_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    subject_winner = store.query_as_of(
        subject_core_id,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert subject_winner is not None
    assert subject_fingerprint.revision_lifecycle == store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    assert subject_fingerprint.relation_resolution == store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    assert subject_fingerprint.relation_lifecycle == store.query_relation_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    assert (
        subject_fingerprint.relation_lifecycle_signatures
        == store.query_relation_lifecycle_signatures_as_of(
            tx_id=tx_as_of,
            valid_at=valid_at,
            revision_id=subject_winner.revision_id,
        )
    )

    retracted_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_fingerprint.revision_lifecycle == store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_fingerprint.relation_resolution == store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
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


def test_state_fingerprint_merge_conflict_component_matches_one_shot_iterable_projection() -> None:
    merge_results_by_tx = _build_merge_conflict_stream()
    projection_from_one_shot = KnowledgeStore.query_merge_conflict_projection_as_of(
        OneShotIterable(merge_results_by_tx),
        tx_id=13,
    )
    projection_from_tuple = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=13,
    )
    assert projection_from_one_shot == projection_from_tuple

    store, valid_at, tx_as_of, _subject_core_id, _retracted_core_id = (
        _build_state_fingerprint_store()
    )
    base_fingerprint = store.query_state_fingerprint_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
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
