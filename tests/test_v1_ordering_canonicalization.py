from datetime import datetime, timezone

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflict,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _legacy_revision_winner(store: KnowledgeStore, core_id: str, *, tx_id: int, valid_at: datetime):
    candidate_ids = store._revisions_by_core.get(core_id)
    if not candidate_ids:
        return None
    status_rank = {"retracted": 0, "asserted": 1}
    candidates = [
        store.revisions[revision_id]
        for revision_id in candidate_ids
        if store.revisions[revision_id].transaction_time.tx_id <= tx_id
        and store.revisions[revision_id].valid_time.contains(valid_at)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda revision: (
            -revision.transaction_time.tx_id,
            status_rank[revision.status],
            revision.revision_id,
        ),
    )[0]


def _legacy_revision_projection(
    store: KnowledgeStore,
    *,
    tx_id: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple]:
    core_ids = sorted(store._revisions_by_core.keys()) if core_id is None else (core_id,)
    active = []
    retracted = []
    for candidate_core_id in core_ids:
        winner = _legacy_revision_winner(
            store,
            candidate_core_id,
            tx_id=tx_id,
            valid_at=valid_at,
        )
        if winner is None:
            continue
        if winner.status == "retracted":
            retracted.append(winner)
        else:
            active.append(winner)
    active.sort(key=lambda revision: revision.revision_id)
    retracted.sort(key=lambda revision: revision.revision_id)
    return (tuple(active), tuple(retracted))


def _legacy_relation_projection(
    store: KnowledgeStore,
    *,
    tx_id: int,
    valid_at: datetime,
    revision_id: str | None = None,
) -> tuple[tuple, tuple]:
    active_winners, _ = _legacy_revision_projection(store, tx_id=tx_id, valid_at=valid_at)
    winner_by_core = {revision.core_id: revision.revision_id for revision in active_winners}
    active = []
    for relation in store.relations.values():
        if relation.transaction_time.tx_id > tx_id:
            continue
        if (
            revision_id is not None
            and relation.from_revision_id != revision_id
            and relation.to_revision_id != revision_id
        ):
            continue
        from_revision = store.revisions.get(relation.from_revision_id)
        to_revision = store.revisions.get(relation.to_revision_id)
        if from_revision is None or to_revision is None:
            continue
        if winner_by_core.get(from_revision.core_id) != relation.from_revision_id:
            continue
        if winner_by_core.get(to_revision.core_id) != relation.to_revision_id:
            continue
        active.append(relation)
    active.sort(key=lambda relation: relation.relation_id)
    pending = [
        relation
        for relation in store._pending_relations.values()
        if relation.transaction_time.tx_id <= tx_id
        and (
            revision_id is None
            or relation.from_revision_id == revision_id
            or relation.to_revision_id == revision_id
        )
    ]
    pending.sort(key=lambda relation: relation.relation_id)
    return (tuple(active), tuple(pending))


def _legacy_relation_resolution_projection(
    store: KnowledgeStore,
    *,
    tx_id: int,
    valid_at: datetime,
    core_id: str | None = None,
) -> tuple[tuple, tuple]:
    revision_id = None
    if core_id is not None:
        winner = store.query_as_of(core_id, tx_id=tx_id, valid_at=valid_at)
        if winner is None:
            return ((), ())
        revision_id = winner.revision_id
    return _legacy_relation_projection(
        store,
        tx_id=tx_id,
        valid_at=valid_at,
        revision_id=revision_id,
    )


def _legacy_transition(from_bucket: tuple, to_bucket: tuple, id_attr: str) -> tuple[tuple, tuple]:
    from_by_id = {getattr(item, id_attr): item for item in from_bucket}
    to_by_id = {getattr(item, id_attr): item for item in to_bucket}
    return (
        tuple(to_by_id[item_id] for item_id in sorted(set(to_by_id) - set(from_by_id))),
        tuple(from_by_id[item_id] for item_id in sorted(set(from_by_id) - set(to_by_id))),
    )


def _legacy_conflict_projection(merge_results: tuple[MergeResult, ...]) -> tuple[tuple, tuple]:
    counts_by_signature = {}
    counts_by_code = {}
    for merge_result in merge_results:
        for conflict in merge_result.conflicts:
            signature = conflict.signature()
            counts_by_signature[signature] = counts_by_signature.get(signature, 0) + 1
            counts_by_code[conflict.code.value] = counts_by_code.get(conflict.code.value, 0) + 1
    return (
        tuple(
            sorted(
                (
                    signature[0],
                    signature[1],
                    signature[2],
                    count,
                )
                for signature, count in counts_by_signature.items()
            )
        ),
        tuple(sorted(counts_by_code.items())),
    )


def _build_ordering_scenario() -> tuple[KnowledgeStore, datetime, int, int, int, int, str]:
    store = KnowledgeStore()
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_start = 5
    tx_end = 7
    tx_from = 5
    tx_to = 7

    core_anchor = ClaimCore(claim_type="document", slots={"id": "ordering-anchor"})
    core_entered = ClaimCore(claim_type="residence", slots={"subject": "ordering-entered"})
    core_exited = ClaimCore(claim_type="residence", slots={"subject": "ordering-exited"})
    core_reactivated = ClaimCore(claim_type="residence", slots={"subject": "ordering-reactivated"})
    core_tie = ClaimCore(claim_type="fact", slots={"id": "ordering-tie"})
    core_status_tie = ClaimCore(claim_type="fact", slots={"id": "ordering-status-tie"})

    anchor_revision = store.assert_revision(
        core=core_anchor,
        assertion="ordering anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_anchor"),
        confidence_bp=9000,
        status="asserted",
    )
    entered_revision = store.assert_revision(
        core=core_entered,
        assertion="ordering entered",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_entered"),
        confidence_bp=8600,
        status="asserted",
    )
    exited_revision = store.assert_revision(
        core=core_exited,
        assertion="ordering exited",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_exited_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    store.assert_revision(
        core=core_exited,
        assertion="ordering exited",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=6, recorded_at=dt(2024, 1, 7)),
        provenance=Provenance(source="source_exited_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    store.assert_revision(
        core=core_reactivated,
        assertion="ordering reactivated",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_reactivated_retracted"),
        confidence_bp=8400,
        status="retracted",
    )
    reactivated_revision = store.assert_revision(
        core=core_reactivated,
        assertion="ordering reactivated",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
        provenance=Provenance(source="source_reactivated_asserted"),
        confidence_bp=8400,
        status="asserted",
    )
    tie_revision_a = store.assert_revision(
        core=core_tie,
        assertion="ordering tie a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_tie_a"),
        confidence_bp=8200,
        status="asserted",
    )
    tie_revision_b = store.assert_revision(
        core=core_tie,
        assertion="ordering tie b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
        provenance=Provenance(source="source_tie_b"),
        confidence_bp=8200,
        status="asserted",
    )
    tie_winner = min((tie_revision_a, tie_revision_b), key=lambda revision: revision.revision_id)
    tie_loser = tie_revision_b if tie_winner.revision_id == tie_revision_a.revision_id else tie_revision_a
    store.assert_revision(
        core=core_status_tie,
        assertion="ordering status tie",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_status_tie_asserted"),
        confidence_bp=8000,
        status="asserted",
    )
    store.assert_revision(
        core=core_status_tie,
        assertion="ordering status tie",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=3, recorded_at=dt(2024, 1, 4)),
        provenance=Provenance(source="source_status_tie_retracted"),
        confidence_bp=8000,
        status="retracted",
    )

    store.attach_relation(
        relation_type="derived_from",
        from_revision_id=exited_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=2, recorded_at=dt(2024, 1, 3)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=entered_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="depends_on",
        from_revision_id=tie_winner.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=tie_loser.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=5, recorded_at=dt(2024, 1, 6)),
    )
    store.attach_relation(
        relation_type="supports",
        from_revision_id=reactivated_revision.revision_id,
        to_revision_id=anchor_revision.revision_id,
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )

    orphan_replica = KnowledgeStore()
    pending_old = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id="missing-ordering-old",
        transaction_time=TransactionTime(tx_id=4, recorded_at=dt(2024, 1, 5)),
    )
    pending_new = RelationEdge(
        relation_type="supports",
        from_revision_id=entered_revision.revision_id,
        to_revision_id="missing-ordering-new",
        transaction_time=TransactionTime(tx_id=7, recorded_at=dt(2024, 1, 8)),
    )
    orphan_replica.relations[pending_old.relation_id] = pending_old
    orphan_replica.relations[pending_new.relation_id] = pending_new
    store = store.merge(orphan_replica).merged

    return (store, valid_at, tx_start, tx_end, tx_from, tx_to, core_entered.core_id)


def test_revision_ordering_routing_matches_legacy_inline_semantics() -> None:
    store, valid_at, tx_start, tx_end, tx_from, tx_to, _ = _build_ordering_scenario()

    for core_id in sorted(store._revisions_by_core):
        legacy_winner = _legacy_revision_winner(store, core_id, tx_id=tx_end, valid_at=valid_at)
        expected = legacy_winner if legacy_winner is not None and legacy_winner.status == "asserted" else None
        assert store.query_as_of(core_id, tx_id=tx_end, valid_at=valid_at) == expected

    expected_as_of = _legacy_revision_projection(store, tx_id=tx_end, valid_at=valid_at)
    as_of_projection = store.query_revision_lifecycle_as_of(tx_id=tx_end, valid_at=valid_at)
    assert as_of_projection.active == expected_as_of[0]
    assert as_of_projection.retracted == expected_as_of[1]

    expected_window = (
        tuple(
            revision
            for revision in expected_as_of[0]
            if tx_start <= revision.transaction_time.tx_id <= tx_end
        ),
        tuple(
            revision
            for revision in expected_as_of[1]
            if tx_start <= revision.transaction_time.tx_id <= tx_end
        ),
    )
    window_projection = store.query_revision_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert window_projection.active == expected_window[0]
    assert window_projection.retracted == expected_window[1]

    from_projection = _legacy_revision_projection(store, tx_id=tx_from, valid_at=valid_at)
    to_projection = _legacy_revision_projection(store, tx_id=tx_to, valid_at=valid_at)
    expected_transition = (
        *_legacy_transition(from_projection[0], to_projection[0], "revision_id"),
        *_legacy_transition(from_projection[1], to_projection[1], "revision_id"),
    )
    transition = store.query_revision_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert transition.entered_active == expected_transition[0]
    assert transition.exited_active == expected_transition[1]
    assert transition.entered_retracted == expected_transition[2]
    assert transition.exited_retracted == expected_transition[3]


def test_relation_ordering_routing_matches_legacy_inline_semantics() -> None:
    store, valid_at, tx_start, tx_end, tx_from, tx_to, entered_core_id = _build_ordering_scenario()
    entered_winner = store.query_as_of(entered_core_id, tx_id=tx_end, valid_at=valid_at)
    assert entered_winner is not None

    expected_lifecycle_as_of = _legacy_relation_projection(store, tx_id=tx_end, valid_at=valid_at)
    lifecycle_as_of = store.query_relation_lifecycle_as_of(tx_id=tx_end, valid_at=valid_at)
    assert lifecycle_as_of.active == expected_lifecycle_as_of[0]
    assert lifecycle_as_of.pending == expected_lifecycle_as_of[1]

    expected_lifecycle_window = (
        tuple(
            relation
            for relation in expected_lifecycle_as_of[0]
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        ),
        tuple(
            relation
            for relation in expected_lifecycle_as_of[1]
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        ),
    )
    lifecycle_window = store.query_relation_lifecycle_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert lifecycle_window.active == expected_lifecycle_window[0]
    assert lifecycle_window.pending == expected_lifecycle_window[1]

    lifecycle_from = _legacy_relation_projection(store, tx_id=tx_from, valid_at=valid_at)
    lifecycle_to = _legacy_relation_projection(store, tx_id=tx_to, valid_at=valid_at)
    expected_lifecycle_transition = (
        *_legacy_transition(lifecycle_from[0], lifecycle_to[0], "relation_id"),
        *_legacy_transition(lifecycle_from[1], lifecycle_to[1], "relation_id"),
    )
    lifecycle_transition = store.query_relation_lifecycle_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert lifecycle_transition.entered_active == expected_lifecycle_transition[0]
    assert lifecycle_transition.exited_active == expected_lifecycle_transition[1]
    assert lifecycle_transition.entered_pending == expected_lifecycle_transition[2]
    assert lifecycle_transition.exited_pending == expected_lifecycle_transition[3]

    expected_resolution_as_of = _legacy_relation_resolution_projection(
        store,
        tx_id=tx_end,
        valid_at=valid_at,
    )
    resolution_as_of = store.query_relation_resolution_as_of(tx_id=tx_end, valid_at=valid_at)
    assert resolution_as_of.active == expected_resolution_as_of[0]
    assert resolution_as_of.pending == expected_resolution_as_of[1]

    expected_filtered_resolution_as_of = _legacy_relation_resolution_projection(
        store,
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=entered_core_id,
    )
    filtered_resolution_as_of = store.query_relation_resolution_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=entered_core_id,
    )
    assert filtered_resolution_as_of.active == expected_filtered_resolution_as_of[0]
    assert filtered_resolution_as_of.pending == expected_filtered_resolution_as_of[1]

    expected_resolution_window = (
        tuple(
            relation
            for relation in expected_resolution_as_of[0]
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        ),
        tuple(
            relation
            for relation in expected_resolution_as_of[1]
            if tx_start <= relation.transaction_time.tx_id <= tx_end
        ),
    )
    resolution_window = store.query_relation_resolution_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
    )
    assert resolution_window.active == expected_resolution_window[0]
    assert resolution_window.pending == expected_resolution_window[1]

    resolution_from = _legacy_relation_resolution_projection(
        store,
        tx_id=tx_from,
        valid_at=valid_at,
    )
    resolution_to = _legacy_relation_resolution_projection(
        store,
        tx_id=tx_to,
        valid_at=valid_at,
    )
    expected_resolution_transition = (
        *_legacy_transition(resolution_from[0], resolution_to[0], "relation_id"),
        *_legacy_transition(resolution_from[1], resolution_to[1], "relation_id"),
    )
    resolution_transition = store.query_relation_resolution_transition_for_tx_window(
        tx_from=tx_from,
        tx_to=tx_to,
        valid_at=valid_at,
    )
    assert resolution_transition.entered_active == expected_resolution_transition[0]
    assert resolution_transition.exited_active == expected_resolution_transition[1]
    assert resolution_transition.entered_pending == expected_resolution_transition[2]
    assert resolution_transition.exited_pending == expected_resolution_transition[3]


def test_merge_conflict_projection_ordering_routing_matches_legacy_inline_semantics() -> None:
    merge_results_by_tx = (
        (
            3,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                        entity_id="entity-z",
                        details="missing z",
                    ),
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-a",
                        details="core collision",
                    ),
                ),
            ),
        ),
        (
            5,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                        entity_id="entity-a",
                        details="missing a",
                    ),
                    MergeConflict(
                        code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                        entity_id="entity-z",
                        details="missing z",
                    ),
                    MergeConflict(
                        code=ConflictCode.REVISION_ID_COLLISION,
                        entity_id="entity-r",
                        details="revision collision",
                    ),
                ),
            ),
        ),
        (
            7,
            MergeResult(
                merged=KnowledgeStore(),
                conflicts=(
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-b",
                        details="core collision",
                    ),
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id="entity-a",
                        details="core collision",
                    ),
                ),
            ),
        ),
    )

    for tx_id in (2, 3, 5, 6, 7, 8):
        projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_id,
        )
        expected = _legacy_conflict_projection(
            tuple(
                merge_result
                for merge_result_tx_id, merge_result in merge_results_by_tx
                if merge_result_tx_id <= tx_id
            )
        )
        assert projection.signature_counts == expected[0]
        assert projection.code_counts == expected[1]

    for tx_start, tx_end in ((2, 2), (3, 5), (4, 7), (7, 7), (8, 8)):
        projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            merge_results_by_tx,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        expected = _legacy_conflict_projection(
            tuple(
                merge_result
                for merge_result_tx_id, merge_result in merge_results_by_tx
                if tx_start <= merge_result_tx_id <= tx_end
            )
        )
        assert projection.signature_counts == expected[0]
        assert projection.code_counts == expected[1]
