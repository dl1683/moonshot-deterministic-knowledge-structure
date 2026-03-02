from datetime import datetime, timezone

import pytest

from dks import (
    ClaimCore,
    KnowledgeStore,
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


def test_query_merge_conflict_projection_as_of_matches_stream_summary_by_tx_cutoff() -> None:
    replay_sequence = build_merge_conflict_projection_replicas(tx_base=1640)

    _, merge_results = replay_stream_with_results(replay_sequence)
    replay_tx_ids = tuple(replica_stream_tx_id(replica) for replica in replay_sequence)
    merge_results_by_tx = tuple(zip(replay_tx_ids, merge_results))

    one_shot_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
        OneShotIterable(merge_results_by_tx),
        tx_id=max(replay_tx_ids),
    )
    assert one_shot_projection.summary == MergeResult.stream_conflict_summary(merge_results)

    tx_cutoffs = (min(replay_tx_ids) - 1, *sorted(set(replay_tx_ids)), max(replay_tx_ids) + 1)
    for tx_cutoff in tx_cutoffs:
        projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_cutoff,
        )
        expected_results = tuple(
            merge_result
            for merge_result_tx_id, merge_result in merge_results_by_tx
            if merge_result_tx_id <= tx_cutoff
        )
        expected_signature_counts, expected_code_counts = MergeResult.stream_conflict_summary(
            expected_results
        )
        assert projection.signature_counts == expected_signature_counts
        assert projection.code_counts == expected_code_counts
        assert projection.summary == (expected_signature_counts, expected_code_counts)


def test_query_merge_conflict_projection_for_tx_window_matches_stream_summary_by_window() -> None:
    replay_sequence = build_merge_conflict_projection_replicas(tx_base=1720)

    _, merge_results = replay_stream_with_results(replay_sequence)
    replay_tx_ids = tuple(replica_stream_tx_id(replica) for replica in replay_sequence)
    merge_results_by_tx = tuple(zip(replay_tx_ids, merge_results))

    tx_values = sorted(set(replay_tx_ids))
    tx_lower = min(tx_values)
    tx_upper = max(tx_values)
    tx_middle = tx_values[len(tx_values) // 2]

    one_shot_projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        OneShotIterable(merge_results_by_tx),
        tx_start=tx_lower - 1,
        tx_end=tx_upper + 1,
    )
    assert one_shot_projection.summary == MergeResult.stream_conflict_summary(merge_results)

    tx_windows = (
        (tx_lower - 1, tx_lower - 1),
        (tx_lower, tx_lower),
        (tx_lower, tx_middle),
        (tx_middle, tx_upper),
        (tx_upper, tx_upper),
        (tx_upper + 1, tx_upper + 1),
        (tx_lower - 1, tx_upper + 1),
    )
    for tx_start, tx_end in tx_windows:
        projection = KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            merge_results_by_tx,
            tx_start=tx_start,
            tx_end=tx_end,
        )
        expected_results = tuple(
            merge_result
            for merge_result_tx_id, merge_result in merge_results_by_tx
            if tx_start <= merge_result_tx_id <= tx_end
        )
        expected_signature_counts, expected_code_counts = MergeResult.stream_conflict_summary(
            expected_results
        )
        assert projection.signature_counts == expected_signature_counts
        assert projection.code_counts == expected_code_counts
        assert projection.summary == (expected_signature_counts, expected_code_counts)


def test_query_merge_conflict_projection_for_tx_window_rejects_inverted_window() -> None:
    with pytest.raises(
        ValueError,
        match="tx_end must be greater than or equal to tx_start",
    ):
        KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            (),
            tx_start=5,
            tx_end=4,
        )
