from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    KnowledgeStore,
    MergeConflictProjection,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def build_merge_conflict_projection_replicas(
    *,
    tx_base: int,
) -> list[KnowledgeStore]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    competing_core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"merge-conflict-subject-{tx_base}"},
    )
    anchor_core = ClaimCore(
        claim_type="document",
        slots={"id": f"merge-conflict-anchor-{tx_base}"},
    )

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
    replica_base.assert_revision(
        core=competing_core,
        assertion="Ada lives in London",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="competing_a"),
        confidence_bp=8000,
        status="asserted",
    )

    replica_competing = KnowledgeStore()
    replica_competing.assert_revision(
        core=competing_core,
        assertion="Ada lives in Paris",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_base + 2, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="competing_b"),
        confidence_bp=8000,
        status="asserted",
    )

    replica_orphans = KnowledgeStore()
    orphan_relation_a = RelationEdge(
        relation_type="supports",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=f"missing-merge-conflict-endpoint-a-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )
    orphan_relation_b = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=f"missing-merge-conflict-endpoint-b-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
    )
    replica_orphans.relations[orphan_relation_a.relation_id] = orphan_relation_a
    replica_orphans.relations[orphan_relation_b.relation_id] = orphan_relation_b

    return [replica_base, replica_competing, replica_orphans]


def replay_stream_with_results(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    merge_results = []
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


def _projection_signature(
    projection: MergeConflictProjection,
) -> tuple[tuple, tuple]:
    return (projection.signature_counts, projection.code_counts)


def _assert_projection_determinism(
    projection: MergeConflictProjection,
    expected_results: tuple[MergeResult, ...],
) -> None:
    expected_signature_counts, expected_code_counts = MergeResult.stream_conflict_summary(
        expected_results
    )
    assert projection.signature_counts == expected_signature_counts
    assert projection.code_counts == expected_code_counts
    assert projection.summary == (projection.signature_counts, projection.code_counts)
    assert projection.signature_counts == tuple(sorted(projection.signature_counts))
    assert projection.code_counts == tuple(sorted(projection.code_counts))

    expected_conflict_total = sum(len(result.conflicts) for result in expected_results)
    signature_total = sum(count for _, _, _, count in projection.signature_counts)
    code_total = sum(count for _, count in projection.code_counts)
    assert signature_total == expected_conflict_total
    assert code_total == expected_conflict_total


def _merge_results_as_of(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_id: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_id
    )


def _merge_results_for_window(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_start: int,
    tx_end: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if tx_start <= merge_result_tx_id <= tx_end
    )


def test_query_merge_conflict_projection_as_of_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    replay_sequence = build_merge_conflict_projection_replicas(tx_base=1800)
    baseline_signatures_by_cutoff: dict[int, tuple[tuple, tuple]] = {}

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        ordered_tx_ids = tuple(replica_stream_tx_id(replica) for replica in ordered_replicas)
        _, unsplit_results = replay_stream_with_results(ordered_replicas)
        unsplit_stream = tuple(zip(ordered_tx_ids, unsplit_results))

        tx_values = sorted(set(ordered_tx_ids))
        tx_cutoffs = tuple(
            dict.fromkeys(
                (
                    tx_values[0] - 1,
                    tx_values[0],
                    tx_values[-1] - 1,
                    tx_values[-1],
                    tx_values[-1] + 1,
                )
            )
        )

        unsplit_signatures_by_cutoff: dict[int, tuple[tuple, tuple]] = {}
        for tx_cutoff in tx_cutoffs:
            unsplit_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
                unsplit_stream,
                tx_id=tx_cutoff,
            )
            expected_unsplit_results = _merge_results_as_of(unsplit_stream, tx_id=tx_cutoff)
            _assert_projection_determinism(unsplit_projection, expected_unsplit_results)

            unsplit_signature = _projection_signature(unsplit_projection)
            unsplit_signatures_by_cutoff[tx_cutoff] = unsplit_signature
            if tx_cutoff not in baseline_signatures_by_cutoff:
                baseline_signatures_by_cutoff[tx_cutoff] = unsplit_signature
            else:
                assert unsplit_signature == baseline_signatures_by_cutoff[tx_cutoff]

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_results = replay_stream_with_results(
                ordered_replicas[:split_index]
            )
            _, resumed_suffix_results = replay_stream_with_results(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_stream = tuple(zip(ordered_tx_ids[:split_index], prefix_results)) + tuple(
                zip(ordered_tx_ids[split_index:], resumed_suffix_results)
            )
            for tx_cutoff in tx_cutoffs:
                resumed_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
                    resumed_stream,
                    tx_id=tx_cutoff,
                )
                expected_resumed_results = _merge_results_as_of(
                    resumed_stream,
                    tx_id=tx_cutoff,
                )
                _assert_projection_determinism(resumed_projection, expected_resumed_results)

                resumed_signature = _projection_signature(resumed_projection)
                assert resumed_signature == unsplit_signatures_by_cutoff[tx_cutoff]
                assert resumed_signature == baseline_signatures_by_cutoff[tx_cutoff]


def test_query_merge_conflict_projection_for_tx_window_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    replay_sequence = build_merge_conflict_projection_replicas(tx_base=1840)
    baseline_signatures_by_window: dict[tuple[int, int], tuple[tuple, tuple]] = {}

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        ordered_tx_ids = tuple(replica_stream_tx_id(replica) for replica in ordered_replicas)
        _, unsplit_results = replay_stream_with_results(ordered_replicas)
        unsplit_stream = tuple(zip(ordered_tx_ids, unsplit_results))

        tx_values = sorted(set(ordered_tx_ids))
        tx_windows = tuple(
            dict.fromkeys(
                (
                    (tx_values[0] - 1, tx_values[0] - 1),
                    (tx_values[0], tx_values[0]),
                    (tx_values[0], tx_values[-1] - 1),
                    (tx_values[0], tx_values[-1]),
                    (tx_values[-1], tx_values[-1]),
                    (tx_values[-1] + 1, tx_values[-1] + 1),
                    (tx_values[0] - 1, tx_values[-1] + 1),
                )
            )
        )

        unsplit_signatures_by_window: dict[tuple[int, int], tuple[tuple, tuple]] = {}
        for tx_start, tx_end in tx_windows:
            unsplit_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
                unsplit_stream,
                tx_start=tx_start,
                tx_end=tx_end,
            )
            expected_unsplit_results = _merge_results_for_window(
                unsplit_stream,
                tx_start=tx_start,
                tx_end=tx_end,
            )
            _assert_projection_determinism(unsplit_projection, expected_unsplit_results)

            window_key = (tx_start, tx_end)
            unsplit_signature = _projection_signature(unsplit_projection)
            unsplit_signatures_by_window[window_key] = unsplit_signature
            if window_key not in baseline_signatures_by_window:
                baseline_signatures_by_window[window_key] = unsplit_signature
            else:
                assert unsplit_signature == baseline_signatures_by_window[window_key]

        for split_index in range(1, len(ordered_replicas)):
            prefix_merged, prefix_results = replay_stream_with_results(
                ordered_replicas[:split_index]
            )
            _, resumed_suffix_results = replay_stream_with_results(
                ordered_replicas[split_index:],
                start=prefix_merged.checkpoint(),
            )
            resumed_stream = tuple(zip(ordered_tx_ids[:split_index], prefix_results)) + tuple(
                zip(ordered_tx_ids[split_index:], resumed_suffix_results)
            )
            for tx_start, tx_end in tx_windows:
                resumed_projection = (
                    KnowledgeStore.query_merge_conflict_projection_for_tx_window(
                        resumed_stream,
                        tx_start=tx_start,
                        tx_end=tx_end,
                    )
                )
                expected_resumed_results = _merge_results_for_window(
                    resumed_stream,
                    tx_start=tx_start,
                    tx_end=tx_end,
                )
                _assert_projection_determinism(resumed_projection, expected_resumed_results)

                window_key = (tx_start, tx_end)
                resumed_signature = _projection_signature(resumed_projection)
                assert resumed_signature == unsplit_signatures_by_window[window_key]
                assert resumed_signature == baseline_signatures_by_window[window_key]
