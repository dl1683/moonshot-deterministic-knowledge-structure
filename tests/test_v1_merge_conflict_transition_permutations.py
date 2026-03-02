from datetime import datetime, timezone

import itertools

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeConflictProjectionTransition,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def build_merge_conflict_transition_replay_replicas(
    *,
    tx_base: int,
) -> list[KnowledgeStore]:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    competing_core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"merge-conflict-transition-subject-{tx_base}"},
    )
    anchor_core = ClaimCore(
        claim_type="document",
        slots={"id": f"merge-conflict-transition-anchor-{tx_base}"},
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

    replica_orphan_a = KnowledgeStore()
    orphan_relation_a = RelationEdge(
        relation_type="supports",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=f"missing-merge-conflict-transition-endpoint-a-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 3, recorded_at=dt(2024, 1, 4)),
    )
    replica_orphan_a.relations[orphan_relation_a.relation_id] = orphan_relation_a

    replica_orphan_b = KnowledgeStore()
    orphan_relation_b = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=f"missing-merge-conflict-transition-endpoint-b-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_base + 4, recorded_at=dt(2024, 1, 5)),
    )
    replica_orphan_b.relations[orphan_relation_b.relation_id] = orphan_relation_b

    return [
        replica_base,
        replica_competing,
        replica_orphan_a,
        replica_orphan_b,
    ]


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


def _transition_signature(
    transition: MergeConflictProjectionTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _expected_transition_signature_from_as_of(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
    *,
    tx_from: int,
    tx_to: int,
) -> tuple[tuple, tuple, tuple, tuple]:
    from_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_from,
    )
    to_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        merge_results_by_tx,
        tx_id=tx_to,
    )
    return (
        tuple(
            sorted(
                set(to_projection.signature_counts) - set(from_projection.signature_counts),
                key=lambda signature_count: (
                    signature_count[0],
                    signature_count[1],
                    signature_count[2],
                ),
            )
        ),
        tuple(
            sorted(
                set(from_projection.signature_counts) - set(to_projection.signature_counts),
                key=lambda signature_count: (
                    signature_count[0],
                    signature_count[1],
                    signature_count[2],
                ),
            )
        ),
        tuple(
            sorted(
                set(to_projection.code_counts) - set(from_projection.code_counts),
                key=lambda code_count: code_count[0],
            )
        ),
        tuple(
            sorted(
                set(from_projection.code_counts) - set(to_projection.code_counts),
                key=lambda code_count: code_count[0],
            )
        ),
    )


def _assert_transition_determinism(
    transition: MergeConflictProjectionTransition,
    expected_signature: tuple[tuple, tuple, tuple, tuple],
) -> None:
    assert transition.entered_signature_counts == expected_signature[0]
    assert transition.exited_signature_counts == expected_signature[1]
    assert transition.entered_code_counts == expected_signature[2]
    assert transition.exited_code_counts == expected_signature[3]

    assert transition.entered_signature_counts == tuple(
        sorted(
            transition.entered_signature_counts,
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    assert transition.exited_signature_counts == tuple(
        sorted(
            transition.exited_signature_counts,
            key=lambda signature_count: (
                signature_count[0],
                signature_count[1],
                signature_count[2],
            ),
        )
    )
    assert transition.entered_code_counts == tuple(
        sorted(
            transition.entered_code_counts,
            key=lambda code_count: code_count[0],
        )
    )
    assert transition.exited_code_counts == tuple(
        sorted(
            transition.exited_code_counts,
            key=lambda code_count: code_count[0],
        )
    )


def test_query_merge_conflict_projection_transition_for_tx_window_permutation_order_and_checkpoint_resume_are_equivalent() -> None:
    tx_base = 4700
    replay_sequence = build_merge_conflict_transition_replay_replicas(tx_base=tx_base)
    tx_windows = (
        (tx_base + 2, tx_base + 2),
        (tx_base + 2, tx_base + 4),
        (tx_base + 3, tx_base + 4),
        (tx_base + 4, tx_base + 4),
    )

    baseline_transition_signatures_by_window: dict[
        tuple[int, int], tuple[tuple, tuple, tuple, tuple]
    ] = {}

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        ordered_tx_ids = tuple(replica_stream_tx_id(replica) for replica in ordered_replicas)
        _, unsplit_results = replay_stream_with_results(ordered_replicas)
        unsplit_stream = tuple(zip(ordered_tx_ids, unsplit_results))

        unsplit_signatures_by_window: dict[
            tuple[int, int], tuple[tuple, tuple, tuple, tuple]
        ] = {}
        for tx_from, tx_to in tx_windows:
            unsplit_transition = (
                KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
                    unsplit_stream,
                    tx_from=tx_from,
                    tx_to=tx_to,
                    valid_at=dt(2024, 6, 1),
                )
            )
            expected_unsplit_signature = _expected_transition_signature_from_as_of(
                unsplit_stream,
                tx_from=tx_from,
                tx_to=tx_to,
            )
            _assert_transition_determinism(
                unsplit_transition,
                expected_unsplit_signature,
            )

            window_key = (tx_from, tx_to)
            unsplit_signature = _transition_signature(unsplit_transition)
            unsplit_signatures_by_window[window_key] = unsplit_signature

            if window_key == (tx_base + 3, tx_base + 4):
                assert unsplit_transition.entered_signature_counts
                assert unsplit_transition.exited_signature_counts == ()
                assert unsplit_transition.entered_code_counts == (
                    (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 2),
                )
                assert unsplit_transition.exited_code_counts == (
                    (ConflictCode.ORPHAN_RELATION_ENDPOINT.value, 1),
                )

            if window_key not in baseline_transition_signatures_by_window:
                baseline_transition_signatures_by_window[window_key] = unsplit_signature
            else:
                assert (
                    unsplit_signature
                    == baseline_transition_signatures_by_window[window_key]
                )

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

            for tx_from, tx_to in tx_windows:
                resumed_transition = (
                    KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
                        resumed_stream,
                        tx_from=tx_from,
                        tx_to=tx_to,
                        valid_at=dt(2024, 6, 1),
                    )
                )
                expected_resumed_signature = _expected_transition_signature_from_as_of(
                    resumed_stream,
                    tx_from=tx_from,
                    tx_to=tx_to,
                )
                _assert_transition_determinism(
                    resumed_transition,
                    expected_resumed_signature,
                )

                window_key = (tx_from, tx_to)
                resumed_signature = _transition_signature(resumed_transition)
                assert resumed_signature == unsplit_signatures_by_window[window_key]
                assert (
                    resumed_signature
                    == baseline_transition_signatures_by_window[window_key]
                )
