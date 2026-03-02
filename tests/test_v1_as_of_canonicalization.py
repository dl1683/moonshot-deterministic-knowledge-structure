from datetime import datetime, timezone

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


class OneShotIterable:
    def __init__(self, values: tuple) -> None:
        self._values = values
        self._iterated = False

    def __iter__(self):
        if self._iterated:
            raise AssertionError("one-shot iterable was iterated more than once")
        self._iterated = True
        return iter(self._values)


def _assert_revision_ordering(revisions: tuple) -> None:
    revision_ids = tuple(revision.revision_id for revision in revisions)
    assert revision_ids == tuple(sorted(revision_ids))


def _assert_relation_ordering(relations: tuple) -> None:
    relation_ids = tuple(relation.relation_id for relation in relations)
    assert relation_ids == tuple(sorted(relation_ids))


def _assert_signature_ordering(signatures: tuple) -> None:
    assert signatures == tuple(sorted(signatures))


def _revision_winner_as_of_explicit(
    store: KnowledgeStore,
    *,
    core_id: str,
    tx_id: int,
    valid_at: datetime,
):
    candidates = [
        revision
        for revision in store.revisions.values()
        if revision.core_id == core_id
        and revision.transaction_time.tx_id <= tx_id
        and revision.valid_time.contains(valid_at)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda revision: (
            -revision.transaction_time.tx_id,
            0 if revision.status == "retracted" else 1,
            revision.revision_id,
        ),
    )[0]


def _explicit_revision_projection_as_of(
    store: KnowledgeStore,
    *,
    tx_id: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple]:
    if core_id is None:
        core_ids = sorted(store._revisions_by_core.keys())
    else:
        core_ids = (core_id,)

    active = []
    retracted = []
    for candidate_core_id in core_ids:
        winner = _revision_winner_as_of_explicit(
            store,
            core_id=candidate_core_id,
            tx_id=tx_id,
            valid_at=valid_at,
        )
        if winner is None:
            continue
        if winner.status == "retracted":
            retracted.append(winner)
        else:
            active.append(winner)

    return (
        tuple(sorted(active, key=lambda revision: revision.revision_id)),
        tuple(sorted(retracted, key=lambda revision: revision.revision_id)),
    )


def _explicit_relation_lifecycle_projection_as_of(
    store: KnowledgeStore,
    *,
    tx_id: int,
    valid_at: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple]:
    winners_by_core = {
        core_id: _revision_winner_as_of_explicit(
            store,
            core_id=core_id,
            tx_id=tx_id,
            valid_at=valid_at,
        )
        for core_id in store._revisions_by_core
    }
    active_winner_revision_ids = {
        winner.revision_id
        for winner in winners_by_core.values()
        if winner is not None and winner.status != "retracted"
    }

    active = tuple(
        sorted(
            (
                relation
                for relation in store.relations.values()
                if relation.transaction_time.tx_id <= tx_id
                and (
                    revision_id is None
                    or relation.from_revision_id == revision_id
                    or relation.to_revision_id == revision_id
                )
                and relation.from_revision_id in active_winner_revision_ids
                and relation.to_revision_id in active_winner_revision_ids
            ),
            key=lambda relation: relation.relation_id,
        )
    )
    pending = tuple(
        sorted(
            (
                relation
                for relation in store._pending_relations.values()
                if relation.transaction_time.tx_id <= tx_id
                and (
                    revision_id is None
                    or relation.from_revision_id == revision_id
                    or relation.to_revision_id == revision_id
                )
            ),
            key=lambda relation: relation.relation_id,
        )
    )
    return active, pending


def _relation_state_signature(bucket: str, relation: RelationEdge) -> tuple[str, str, str, str, str, int, str]:
    return (
        bucket,
        relation.relation_id,
        relation.relation_type,
        relation.from_revision_id,
        relation.to_revision_id,
        relation.transaction_time.tx_id,
        relation.transaction_time.recorded_at.isoformat(),
    )


def _build_as_of_canonical_store() -> tuple[KnowledgeStore, datetime, int, str, str]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_as_of = 6

    core_subject = ClaimCore(claim_type="residence", slots={"subject": "ada-lifecycle-canonical"})
    core_anchor = ClaimCore(claim_type="document", slots={"id": "as-of-canonical-anchor"})
    core_context = ClaimCore(claim_type="fact", slots={"id": "as-of-canonical-context"})
    core_retracted = ClaimCore(claim_type="residence", slots={"subject": "retracted-canonical"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="as-of canonical anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_as_of_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    context_revision = store.assert_revision(
        core=core_context,
        assertion="as-of canonical context",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_as_of_context"),
        confidence_bp=9000,
        status="asserted",
    )
    subject_revision_a = store.assert_revision(
        core=core_subject,
        assertion="subject candidate A",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_as_of_subject_a"),
        confidence_bp=8200,
        status="asserted",
    )
    subject_revision_b = store.assert_revision(
        core=core_subject,
        assertion="subject candidate B",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_as_of_subject_b"),
        confidence_bp=8200,
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
        provenance=Provenance(source="source_as_of_retracted_asserted"),
        confidence_bp=8100,
        status="asserted",
    )
    store.assert_revision(
        core=core_retracted,
        assertion="retracted final winner",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
        provenance=Provenance(source="source_as_of_retracted_retracted"),
        confidence_bp=8100,
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
        to_revision_id="missing-as-of-canonical-pending-endpoint",
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    orphan_replica.relations[pending_relation.relation_id] = pending_relation
    store = store.merge(orphan_replica).merged

    return store, valid_at, tx_as_of, core_subject.core_id, core_retracted.core_id


def _build_merge_conflict_stream() -> tuple[tuple[int, MergeResult], ...]:
    orphan_a = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="as-of-canonical-orphan-a",
        details="missing endpoint as-of-canonical-orphan-a",
    )
    orphan_b = MergeConflict(
        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
        entity_id="as-of-canonical-orphan-b",
        details="missing endpoint as-of-canonical-orphan-b",
    )
    competing = MergeConflict(
        code=ConflictCode.COMPETING_REVISION_SAME_SLOT,
        entity_id="as-of-canonical-competing",
        details="competing revision winner",
    )
    return (
        (10, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a,))),
        (11, MergeResult(merged=KnowledgeStore(), conflicts=(orphan_a, orphan_b))),
        (13, MergeResult(merged=KnowledgeStore(), conflicts=(competing, orphan_b))),
    )


def _expected_merge_conflict_projection_as_of(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_id: int,
) -> MergeConflictProjection:
    expected_results = tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_id
    )
    expected_signature_counts, expected_code_counts = MergeResult.stream_conflict_summary(
        expected_results
    )
    return MergeConflictProjection(
        signature_counts=expected_signature_counts,
        code_counts=expected_code_counts,
    )


def test_as_of_canonicalization_revision_and_relation_surfaces_match_explicit_expectations() -> None:
    store, valid_at, tx_as_of, subject_core_id, retracted_core_id = _build_as_of_canonical_store()

    revision_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    expected_active, expected_retracted = _explicit_revision_projection_as_of(
        store,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert revision_projection.active == expected_active
    assert revision_projection.retracted == expected_retracted
    _assert_revision_ordering(revision_projection.active)
    _assert_revision_ordering(revision_projection.retracted)

    filtered_revision_projection = store.query_revision_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    filtered_expected_active, filtered_expected_retracted = _explicit_revision_projection_as_of(
        store,
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    assert filtered_revision_projection.active == filtered_expected_active
    assert filtered_revision_projection.retracted == filtered_expected_retracted

    relation_lifecycle_projection = store.query_relation_lifecycle_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    expected_active_relations, expected_pending_relations = (
        _explicit_relation_lifecycle_projection_as_of(
            store,
            tx_id=tx_as_of,
            valid_at=valid_at,
        )
    )
    assert relation_lifecycle_projection.active == expected_active_relations
    assert relation_lifecycle_projection.pending == expected_pending_relations
    _assert_relation_ordering(relation_lifecycle_projection.active)
    _assert_relation_ordering(relation_lifecycle_projection.pending)

    relation_resolution_projection = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert relation_resolution_projection.active == expected_active_relations
    assert relation_resolution_projection.pending == expected_pending_relations

    subject_winner = store.query_as_of(
        subject_core_id,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert subject_winner is not None
    filtered_relation_resolution = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=subject_core_id,
    )
    expected_subject_active, expected_subject_pending = _explicit_relation_lifecycle_projection_as_of(
        store,
        tx_id=tx_as_of,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    assert filtered_relation_resolution.active == expected_subject_active
    assert filtered_relation_resolution.pending == expected_subject_pending

    assert store.query_as_of(retracted_core_id, tx_id=tx_as_of, valid_at=valid_at) is None
    retracted_resolution_projection = store.query_relation_resolution_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        core_id=retracted_core_id,
    )
    assert retracted_resolution_projection.active == ()
    assert retracted_resolution_projection.pending == ()


def test_as_of_canonicalization_signature_surface_matches_explicit_relation_signatures() -> None:
    store, valid_at, tx_as_of, subject_core_id, _retracted_core_id = _build_as_of_canonical_store()

    lifecycle_active, lifecycle_pending = _explicit_relation_lifecycle_projection_as_of(
        store,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert projection.active == tuple(
        sorted(_relation_state_signature("active", relation) for relation in lifecycle_active)
    )
    assert projection.pending == tuple(
        sorted(_relation_state_signature("pending", relation) for relation in lifecycle_pending)
    )
    _assert_signature_ordering(projection.active)
    _assert_signature_ordering(projection.pending)

    subject_winner = store.query_as_of(
        subject_core_id,
        tx_id=tx_as_of,
        valid_at=valid_at,
    )
    assert subject_winner is not None
    subject_projection = store.query_relation_lifecycle_signatures_as_of(
        tx_id=tx_as_of,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    filtered_active, filtered_pending = _explicit_relation_lifecycle_projection_as_of(
        store,
        tx_id=tx_as_of,
        valid_at=valid_at,
        revision_id=subject_winner.revision_id,
    )
    assert subject_projection.active == tuple(
        sorted(_relation_state_signature("active", relation) for relation in filtered_active)
    )
    assert subject_projection.pending == tuple(
        sorted(_relation_state_signature("pending", relation) for relation in filtered_pending)
    )


def test_as_of_canonicalization_merge_conflict_surface_matches_explicit_cutoff_summary() -> None:
    merge_results_by_tx = _build_merge_conflict_stream()

    one_shot_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        OneShotIterable(merge_results_by_tx),
        tx_id=13,
    )
    expected_one_shot_projection = _expected_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=13,
    )
    assert one_shot_projection == expected_one_shot_projection

    for tx_cutoff in (9, 10, 11, 12, 13, 17):
        projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_cutoff,
        )
        expected_projection = _expected_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_cutoff,
        )
        assert projection == expected_projection
