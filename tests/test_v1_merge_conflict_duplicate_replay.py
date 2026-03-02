from datetime import datetime, timezone

from dks import (
    ClaimCore,
    KnowledgeStore,
    MergeConflictProjection,
    MergeConflictProjectionTransition,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _signature_count_sort_key(signature_count: tuple[str, str, str, int]) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _assert_projection_ordering(projection: MergeConflictProjection) -> None:
    assert projection.signature_counts == tuple(
        sorted(
            projection.signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert projection.code_counts == tuple(
        sorted(
            projection.code_counts,
            key=_code_count_sort_key,
        )
    )


def _assert_transition_ordering(transition: MergeConflictProjectionTransition) -> None:
    assert transition.entered_signature_counts == tuple(
        sorted(
            transition.entered_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.exited_signature_counts == tuple(
        sorted(
            transition.exited_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.entered_code_counts == tuple(
        sorted(
            transition.entered_code_counts,
            key=_code_count_sort_key,
        )
    )
    assert transition.exited_code_counts == tuple(
        sorted(
            transition.exited_code_counts,
            key=_code_count_sort_key,
        )
    )


def build_merge_conflict_duplicate_replay_replicas(
    *,
    tx_base: int,
) -> tuple[
    list[KnowledgeStore],
    tuple[tuple[str, str, str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, str, str, int], ...],
    tuple[tuple[str, int], ...],
    int,
    int,
]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    competing_core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"merge-conflict-duplicate-subject-{tx_base}"},
    )
    anchor_core = ClaimCore(
        claim_type="document",
        slots={"id": f"merge-conflict-duplicate-anchor-{tx_base}"},
    )

    tx_competing = tx_base + 2
    tx_orphan_a = tx_base + 3
    tx_orphan_b = tx_base + 4

    replica_base = KnowledgeStore()
    anchor_revision = replica_base.assert_revision(
        core=anchor_core,
        assertion="Anchor document",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="anchor_source"),
        confidence_bp=9000,
        status="asserted",
    )
    competing_revision_a = replica_base.assert_revision(
        core=competing_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_competing, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="competing_a"),
        confidence_bp=8000,
        status="asserted",
    )

    replica_competing = KnowledgeStore()
    competing_revision_b = replica_competing.assert_revision(
        core=competing_core,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_competing, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="competing_b"),
        confidence_bp=8000,
        status="asserted",
    )

    orphan_missing_endpoint_a = f"missing-merge-conflict-duplicate-endpoint-a-{tx_base}"
    orphan_missing_endpoint_b = f"missing-merge-conflict-duplicate-endpoint-b-{tx_base}"

    replica_orphan_a = KnowledgeStore()
    orphan_relation_a = RelationEdge(
        relation_type="supports",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=orphan_missing_endpoint_a,
        transaction_time=TransactionTime(tx_id=tx_orphan_a, recorded_at=dt(2024, 1, 4)),
    )
    replica_orphan_a.relations[orphan_relation_a.relation_id] = orphan_relation_a

    replica_orphan_b = KnowledgeStore()
    orphan_relation_b = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=orphan_missing_endpoint_b,
        transaction_time=TransactionTime(tx_id=tx_orphan_b, recorded_at=dt(2024, 1, 5)),
    )
    replica_orphan_b.relations[orphan_relation_b.relation_id] = orphan_relation_b

    competing_revision_ids = tuple(
        sorted([competing_revision_a.revision_id, competing_revision_b.revision_id])
    )
    expected_competing_signature = (
        "competing_revision_same_slot",
        competing_core.core_id,
        (
            "same core_id + valid_time + tx_id but different revisions: "
            f"{competing_revision_ids[0]} vs {competing_revision_ids[1]}"
        ),
        1,
    )
    expected_orphan_signature_a = (
        "orphan_relation_endpoint",
        orphan_relation_a.relation_id,
        (
            "relation references missing revision endpoints: "
            + ", ".join(
                sorted(
                    [
                        anchor_revision.revision_id,
                        orphan_missing_endpoint_a,
                    ]
                )
            )
        ),
        1,
    )
    expected_orphan_signature_b = (
        "orphan_relation_endpoint",
        orphan_relation_b.relation_id,
        (
            "relation references missing revision endpoints: "
            + ", ".join(
                sorted(
                    [
                        anchor_revision.revision_id,
                        orphan_missing_endpoint_b,
                    ]
                )
            )
        ),
        1,
    )

    expected_signature_counts_as_of_to = tuple(
        sorted(
            (
                expected_competing_signature,
                expected_orphan_signature_a,
                expected_orphan_signature_b,
            ),
            key=_signature_count_sort_key,
        )
    )
    expected_code_counts_as_of_to = (
        ("competing_revision_same_slot", 1),
        ("orphan_relation_endpoint", 2),
    )

    expected_signature_counts_as_of_from = tuple(
        sorted(
            (
                expected_competing_signature,
                expected_orphan_signature_a,
            ),
            key=_signature_count_sort_key,
        )
    )
    expected_code_counts_as_of_from = (
        ("competing_revision_same_slot", 1),
        ("orphan_relation_endpoint", 1),
    )

    return (
        [
            replica_base,
            replica_competing,
            replica_orphan_a,
            replica_orphan_b,
        ],
        expected_signature_counts_as_of_to,
        expected_code_counts_as_of_to,
        expected_signature_counts_as_of_from,
        expected_code_counts_as_of_from,
        tx_orphan_a,
        tx_orphan_b,
    )


def replay_stream_with_results(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple[MergeResult, ...]]:
    merged = start if start is not None else KnowledgeStore()
    merge_results: list[MergeResult] = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_results.append(merge_result)
    return merged, tuple(merge_results)


def replica_stream_tx_id(replica: KnowledgeStore) -> int:
    tx_ids = [revision.transaction_time.tx_id for revision in replica.revisions.values()]
    tx_ids.extend(relation.transaction_time.tx_id for relation in replica.relations.values())
    tx_ids.extend(
        relation.transaction_time.tx_id for relation in replica._pending_relations.values()
    )
    return max(tx_ids, default=0)


def _duplicate_replay_stream_variants(
    replicas: list[KnowledgeStore],
) -> tuple[
    tuple[tuple[int, MergeResult], ...],
    tuple[tuple[int, MergeResult], ...],
    tuple[tuple[int, MergeResult], ...],
    tuple[int, ...],
]:
    replay_tx_ids = tuple(replica_stream_tx_id(replica) for replica in replicas)

    single_shot_merged, single_shot_results = replay_stream_with_results(replicas)
    single_shot_stream = tuple(zip(replay_tx_ids, single_shot_results))

    duplicate_merged, duplicate_results = replay_stream_with_results(
        replicas,
        start=single_shot_merged,
    )
    assert all(merge_result.conflicts == () for merge_result in duplicate_results)
    assert duplicate_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert duplicate_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert duplicate_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()
    duplicate_stream = single_shot_stream + tuple(zip(replay_tx_ids, duplicate_results))

    resumed_merged, resumed_results = replay_stream_with_results(
        replicas,
        start=single_shot_merged.checkpoint(),
    )
    assert all(merge_result.conflicts == () for merge_result in resumed_results)
    assert resumed_merged.revision_state_signatures() == single_shot_merged.revision_state_signatures()
    assert resumed_merged.relation_state_signatures() == single_shot_merged.relation_state_signatures()
    assert resumed_merged.pending_relation_ids() == single_shot_merged.pending_relation_ids()
    resumed_stream = single_shot_stream + tuple(zip(replay_tx_ids, resumed_results))

    return single_shot_stream, duplicate_stream, resumed_stream, replay_tx_ids


def test_query_merge_conflict_projection_as_of_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        expected_signature_counts_as_of_to,
        expected_code_counts_as_of_to,
        expected_signature_counts_as_of_from,
        expected_code_counts_as_of_from,
        tx_from,
        tx_to,
    ) = build_merge_conflict_duplicate_replay_replicas(tx_base=5200)
    single_shot_stream, duplicate_stream, resumed_stream, replay_tx_ids = (
        _duplicate_replay_stream_variants(replicas)
    )
    tx_values = sorted(set(replay_tx_ids))
    tx_cutoffs = (
        tx_values[0] - 1,
        tx_values[0],
        tx_from,
        tx_to,
        tx_to + 1,
    )

    for tx_cutoff in tx_cutoffs:
        single_shot_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            single_shot_stream,
            tx_id=tx_cutoff,
        )
        duplicate_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            duplicate_stream,
            tx_id=tx_cutoff,
        )
        resumed_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            resumed_stream,
            tx_id=tx_cutoff,
        )
        assert duplicate_projection.summary == single_shot_projection.summary
        assert resumed_projection.summary == single_shot_projection.summary
        _assert_projection_ordering(single_shot_projection)
        _assert_projection_ordering(duplicate_projection)
        _assert_projection_ordering(resumed_projection)

    from_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        single_shot_stream,
        tx_id=tx_from,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        single_shot_stream,
        tx_id=tx_to,
    )
    assert from_projection.signature_counts == expected_signature_counts_as_of_from
    assert from_projection.code_counts == expected_code_counts_as_of_from
    assert to_projection.signature_counts == expected_signature_counts_as_of_to
    assert to_projection.code_counts == expected_code_counts_as_of_to


def test_query_merge_conflict_projection_for_tx_window_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        expected_signature_counts_as_of_to,
        expected_code_counts_as_of_to,
        _expected_signature_counts_as_of_from,
        _expected_code_counts_as_of_from,
        tx_from,
        tx_to,
    ) = build_merge_conflict_duplicate_replay_replicas(tx_base=5280)
    single_shot_stream, duplicate_stream, resumed_stream, replay_tx_ids = (
        _duplicate_replay_stream_variants(replicas)
    )
    tx_values = sorted(set(replay_tx_ids))
    tx_windows = (
        (tx_values[0] - 1, tx_values[0] - 1),
        (tx_values[0], tx_values[0]),
        (tx_values[0], tx_from),
        (tx_values[0], tx_to),
        (tx_from, tx_to),
        (tx_to + 1, tx_to + 1),
    )

    for tx_start, tx_end in tx_windows:
        single_shot_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            single_shot_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        duplicate_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            duplicate_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        resumed_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            resumed_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        assert duplicate_projection.summary == single_shot_projection.summary
        assert resumed_projection.summary == single_shot_projection.summary
        _assert_projection_ordering(single_shot_projection)
        _assert_projection_ordering(duplicate_projection)
        _assert_projection_ordering(resumed_projection)

    full_window_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        single_shot_stream,
        tx_start=tx_values[0],
        tx_end=tx_to,
    )
    assert full_window_projection.signature_counts == expected_signature_counts_as_of_to
    assert full_window_projection.code_counts == expected_code_counts_as_of_to


def test_query_merge_conflict_projection_transition_for_tx_window_duplicate_replay_idempotence_matches_single_shot() -> None:
    (
        replicas,
        expected_signature_counts_as_of_to,
        expected_code_counts_as_of_to,
        expected_signature_counts_as_of_from,
        expected_code_counts_as_of_from,
        tx_from,
        tx_to,
    ) = build_merge_conflict_duplicate_replay_replicas(tx_base=5360)
    single_shot_stream, duplicate_stream, resumed_stream, _replay_tx_ids = (
        _duplicate_replay_stream_variants(replicas)
    )

    single_shot_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            single_shot_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=dt(2024, 6, 1),
        )
    )
    duplicate_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            duplicate_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=dt(2024, 6, 1),
        )
    )
    resumed_transition = (
        KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            resumed_stream,
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=dt(2024, 6, 1),
        )
    )

    assert duplicate_transition == single_shot_transition
    assert resumed_transition == single_shot_transition
    _assert_transition_ordering(single_shot_transition)
    _assert_transition_ordering(duplicate_transition)
    _assert_transition_ordering(resumed_transition)

    expected_entered_signature_counts = tuple(
        sorted(
            set(expected_signature_counts_as_of_to) - set(expected_signature_counts_as_of_from),
            key=_signature_count_sort_key,
        )
    )
    expected_exited_signature_counts = tuple(
        sorted(
            set(expected_signature_counts_as_of_from) - set(expected_signature_counts_as_of_to),
            key=_signature_count_sort_key,
        )
    )
    expected_entered_code_counts = tuple(
        sorted(
            set(expected_code_counts_as_of_to) - set(expected_code_counts_as_of_from),
            key=_code_count_sort_key,
        )
    )
    expected_exited_code_counts = tuple(
        sorted(
            set(expected_code_counts_as_of_from) - set(expected_code_counts_as_of_to),
            key=_code_count_sort_key,
        )
    )

    assert single_shot_transition.entered_signature_counts == expected_entered_signature_counts
    assert single_shot_transition.exited_signature_counts == expected_exited_signature_counts
    assert single_shot_transition.entered_code_counts == expected_entered_code_counts
    assert single_shot_transition.exited_code_counts == expected_exited_code_counts
