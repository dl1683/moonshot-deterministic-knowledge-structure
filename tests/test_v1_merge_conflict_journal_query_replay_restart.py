from dataclasses import dataclass
from datetime import datetime, timezone
import itertools
from pathlib import Path

from dks import (
    ClaimCore,
    DeterministicStateFingerprint,
    DeterministicStateFingerprintTransition,
    KnowledgeStore,
    MergeConflictProjection,
    MergeConflictProjectionTransition,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)

ReplicaStream = tuple[KnowledgeStore, ...]


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


@dataclass(frozen=True)
class JournalQueryReplayContext:
    replicas: ReplicaStream
    valid_at: datetime
    tx_from: int
    tx_to: int
    tx_cutoffs: tuple[int, ...]
    tx_windows: tuple[tuple[int, int], ...]
    tx_transitions: tuple[tuple[int, int], ...]
    subject_core_id: str
    expected_journal_tx_ids: tuple[int, ...]


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _assert_projection_ordering(projection: MergeConflictProjection) -> None:
    assert projection.signature_counts == tuple(
        sorted(projection.signature_counts, key=_signature_count_sort_key)
    )
    assert projection.code_counts == tuple(
        sorted(projection.code_counts, key=_code_count_sort_key)
    )


def _assert_projection_transition_ordering(
    transition: MergeConflictProjectionTransition,
) -> None:
    assert transition.entered_signature_counts == tuple(
        sorted(transition.entered_signature_counts, key=_signature_count_sort_key)
    )
    assert transition.exited_signature_counts == tuple(
        sorted(transition.exited_signature_counts, key=_signature_count_sort_key)
    )
    assert transition.entered_code_counts == tuple(
        sorted(transition.entered_code_counts, key=_code_count_sort_key)
    )
    assert transition.exited_code_counts == tuple(
        sorted(transition.exited_code_counts, key=_code_count_sort_key)
    )


def _assert_fingerprint_ordering(fingerprint: DeterministicStateFingerprint) -> None:
    projection = fingerprint.merge_conflict_projection
    assert projection.signature_counts == tuple(
        sorted(projection.signature_counts, key=_signature_count_sort_key)
    )
    assert projection.code_counts == tuple(
        sorted(projection.code_counts, key=_code_count_sort_key)
    )


def _assert_fingerprint_transition_ordering(
    transition: DeterministicStateFingerprintTransition,
) -> None:
    assert transition.entered_merge_conflict_signature_counts == tuple(
        sorted(
            transition.entered_merge_conflict_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.exited_merge_conflict_signature_counts == tuple(
        sorted(
            transition.exited_merge_conflict_signature_counts,
            key=_signature_count_sort_key,
        )
    )
    assert transition.entered_merge_conflict_code_counts == tuple(
        sorted(
            transition.entered_merge_conflict_code_counts,
            key=_code_count_sort_key,
        )
    )
    assert transition.exited_merge_conflict_code_counts == tuple(
        sorted(
            transition.exited_merge_conflict_code_counts,
            key=_code_count_sort_key,
        )
    )


def _replica_stream_tx_id(replica: KnowledgeStore) -> int:
    tx_ids = {
        revision.transaction_time.tx_id
        for revision in replica.revisions.values()
    }
    tx_ids.update(
        relation.transaction_time.tx_id
        for relation in replica.relations.values()
    )
    tx_ids.update(
        relation.transaction_time.tx_id
        for relation in replica._pending_relations.values()
    )
    assert len(tx_ids) == 1
    return next(iter(tx_ids))


def _build_context(*, tx_base: int) -> JournalQueryReplayContext:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    valid_at = dt(2024, 6, 1)
    tx_anchor = tx_base + 1
    tx_competing = tx_base + 2
    tx_orphan = tx_base + 4

    anchor_core = ClaimCore(
        claim_type="document",
        slots={"id": f"journal-query-replay-restart-anchor-{tx_base}"},
    )
    subject_core = ClaimCore(
        claim_type="residence",
        slots={"subject": f"journal-query-replay-restart-subject-{tx_base}"},
    )

    replica_anchor = KnowledgeStore()
    anchor_revision = replica_anchor.assert_revision(
        core=anchor_core,
        assertion="journal query replay restart anchor",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_anchor, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_journal_query_replay_restart_anchor"),
        confidence_bp=9100,
        status="asserted",
    )

    replica_competing_a = KnowledgeStore()
    replica_competing_a.assert_revision(
        core=subject_core,
        assertion="journal query replay restart competing a",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_competing, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_journal_query_replay_restart_competing_a"),
        confidence_bp=8400,
        status="asserted",
    )

    replica_competing_b = KnowledgeStore()
    replica_competing_b.assert_revision(
        core=subject_core,
        assertion="journal query replay restart competing b",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=tx_competing, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_journal_query_replay_restart_competing_b"),
        confidence_bp=8400,
        status="asserted",
    )

    replica_orphan = KnowledgeStore()
    orphan_relation = RelationEdge(
        relation_type="depends_on",
        from_revision_id=anchor_revision.revision_id,
        to_revision_id=f"missing-journal-query-replay-restart-endpoint-{tx_base}",
        transaction_time=TransactionTime(tx_id=tx_orphan, recorded_at=dt(2024, 1, 5)),
    )
    replica_orphan.relations[orphan_relation.relation_id] = orphan_relation

    replicas = (
        replica_anchor,
        replica_competing_a,
        replica_competing_b,
        replica_orphan,
    )

    expected_journal_tx_ids = tuple(
        sorted(_replica_stream_tx_id(replica) for replica in replicas)
    )

    tx_cutoffs = (
        tx_anchor - 1,
        tx_anchor,
        tx_competing,
        tx_orphan,
        tx_orphan + 1,
    )
    tx_windows = (
        (tx_anchor - 1, tx_anchor - 1),
        (tx_anchor, tx_anchor),
        (tx_anchor, tx_competing),
        (tx_competing, tx_orphan),
        (tx_anchor, tx_orphan),
        (tx_orphan + 1, tx_orphan + 1),
    )
    tx_transitions = (
        (tx_anchor, tx_competing),
        (tx_competing, tx_orphan),
        (tx_anchor, tx_orphan),
    )

    return JournalQueryReplayContext(
        replicas=replicas,
        valid_at=valid_at,
        tx_from=tx_competing,
        tx_to=tx_orphan,
        tx_cutoffs=tx_cutoffs,
        tx_windows=tx_windows,
        tx_transitions=tx_transitions,
        subject_core_id=subject_core.core_id,
        expected_journal_tx_ids=expected_journal_tx_ids,
    )


def _replay_with_annotation_free_journal(
    replicas: ReplicaStream,
    *,
    start: KnowledgeStore | None = None,
    boundaries: tuple[int, ...] = (),
) -> tuple[KnowledgeStore, tuple[MergeResult, ...]]:
    assert tuple(sorted(boundaries)) == boundaries
    assert all(0 < boundary < len(replicas) for boundary in boundaries)

    merged = start if start is not None else KnowledgeStore()
    merge_results: list[MergeResult] = []
    start_index = 0

    for boundary in boundaries + (len(replicas),):
        for replica in replicas[start_index:boundary]:
            merge_result = merged.merge_and_record_conflicts(replica.checkpoint())
            merged = merge_result.merged
            merge_results.append(merge_result)

        start_index = boundary
        if boundary < len(replicas):
            merged = merged.checkpoint()

    return merged, tuple(merge_results)


def _stream_conflict_signatures(
    merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
) -> tuple[tuple[str, str, str], ...]:
    conflicts = tuple(
        conflict
        for _tx_id, merge_result in merge_results_by_tx
        for conflict in merge_result.conflicts
    )
    return KnowledgeStore.conflict_signatures(conflicts)


def _journal_conflict_signatures(store: KnowledgeStore) -> tuple[tuple[str, str, str], ...]:
    return _stream_conflict_signatures(store.merge_conflict_journal())


def _collect_direct_projection_signature(
    store: KnowledgeStore,
    *,
    context: JournalQueryReplayContext,
) -> tuple:
    as_of_signature: list[tuple[int, tuple[tuple, tuple]]] = []
    for tx_id in context.tx_cutoffs:
        projection = store.query_merge_conflict_projection_as_of_from_journal(tx_id=tx_id)
        _assert_projection_ordering(projection)
        as_of_signature.append((tx_id, projection.summary))

    window_signature: list[tuple[tuple[int, int], tuple[tuple, tuple]]] = []
    for tx_start, tx_end in context.tx_windows:
        projection = store.query_merge_conflict_projection_for_tx_window_from_journal(
            tx_start=tx_start,
            tx_end=tx_end,
        )
        _assert_projection_ordering(projection)
        window_signature.append(((tx_start, tx_end), projection.summary))

    transition_signature: list[tuple] = []
    for tx_from, tx_to in context.tx_transitions:
        transition = (
            store.query_merge_conflict_projection_transition_for_tx_window_from_journal(
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=context.valid_at,
            )
        )
        _assert_projection_transition_ordering(transition)
        transition_signature.append(
            (
                (tx_from, tx_to),
                transition.entered_signature_counts,
                transition.exited_signature_counts,
                transition.entered_code_counts,
                transition.exited_code_counts,
            )
        )

    return (
        tuple(as_of_signature),
        tuple(window_signature),
        tuple(transition_signature),
    )


def _collect_conflict_aware_fingerprint_signature(
    store: KnowledgeStore,
    *,
    context: JournalQueryReplayContext,
) -> tuple:
    signatures_by_core: list[tuple] = []
    for core_id in (None, context.subject_core_id):
        as_of_signature: list[tuple] = []
        for tx_id in context.tx_cutoffs:
            fingerprint = store.query_state_fingerprint_as_of(
                tx_id=tx_id,
                valid_at=context.valid_at,
                core_id=core_id,
                merge_results_by_tx=None,
            )
            _assert_fingerprint_ordering(fingerprint)
            as_of_signature.append(
                (
                    tx_id,
                    fingerprint.digest,
                    fingerprint.merge_conflict_projection.summary,
                )
            )

        window_signature: list[tuple] = []
        for tx_start, tx_end in context.tx_windows:
            fingerprint = store.query_state_fingerprint_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=context.valid_at,
                core_id=core_id,
                merge_results_by_tx=None,
            )
            _assert_fingerprint_ordering(fingerprint)
            window_signature.append(
                (
                    (tx_start, tx_end),
                    fingerprint.digest,
                    fingerprint.merge_conflict_projection.summary,
                )
            )

        transition_signature: list[tuple] = []
        for tx_from, tx_to in context.tx_transitions:
            transition = store.query_state_fingerprint_transition_for_tx_window(
                tx_from=tx_from,
                tx_to=tx_to,
                valid_at=context.valid_at,
                core_id=core_id,
                merge_results_by_tx=None,
            )
            _assert_fingerprint_transition_ordering(transition)
            transition_signature.append(
                (
                    (tx_from, tx_to),
                    transition.from_digest,
                    transition.to_digest,
                    transition.entered_merge_conflict_signature_counts,
                    transition.exited_merge_conflict_signature_counts,
                    transition.entered_merge_conflict_code_counts,
                    transition.exited_merge_conflict_code_counts,
                )
            )

        signatures_by_core.append(
            (
                core_id,
                tuple(as_of_signature),
                tuple(window_signature),
                tuple(transition_signature),
            )
        )

    return tuple(signatures_by_core)


def _collect_journal_query_signature(
    store: KnowledgeStore,
    *,
    context: JournalQueryReplayContext,
) -> tuple:
    direct_projection_signature = _collect_direct_projection_signature(
        store,
        context=context,
    )
    conflict_aware_fingerprint_signature = (
        _collect_conflict_aware_fingerprint_signature(
            store,
            context=context,
        )
    )
    return (
        direct_projection_signature,
        conflict_aware_fingerprint_signature,
    )


def _assert_restore_parity(
    store: KnowledgeStore,
    *,
    context: JournalQueryReplayContext,
    expected_signature: tuple,
    snapshot_path: Path | None = None,
) -> None:
    canonical_payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert restored_from_payload.as_canonical_payload() == canonical_payload
    assert restored_from_payload.as_canonical_json() == canonical_json
    assert restored_from_json.as_canonical_payload() == canonical_payload
    assert restored_from_json.as_canonical_json() == canonical_json
    assert (
        _collect_journal_query_signature(
            restored_from_payload,
            context=context,
        )
        == expected_signature
    )
    assert (
        _collect_journal_query_signature(
            restored_from_json,
            context=context,
        )
        == expected_signature
    )

    if snapshot_path is not None:
        store.to_canonical_json_file(snapshot_path)
        canonical_file_text = snapshot_path.read_text(encoding="utf-8")
        assert canonical_file_text == canonical_json

        restored_from_file = KnowledgeStore.from_canonical_json_file(snapshot_path)
        assert restored_from_file.as_canonical_json() == canonical_file_text
        assert (
            _collect_journal_query_signature(
                restored_from_file,
                context=context,
            )
            == expected_signature
        )


def _apply_restart_cycles(
    store: KnowledgeStore,
    *,
    restart_cycles: int,
    snapshot_path: Path,
) -> KnowledgeStore:
    restarted = store
    for cycle in range(restart_cycles):
        canonical_payload = restarted.as_canonical_payload()
        canonical_json = restarted.as_canonical_json()

        restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
        restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

        assert restored_from_payload.as_canonical_payload() == canonical_payload
        assert restored_from_payload.as_canonical_json() == canonical_json
        assert restored_from_json.as_canonical_payload() == canonical_payload
        assert restored_from_json.as_canonical_json() == canonical_json

        restarted = restored_from_payload if cycle % 2 == 0 else restored_from_json

        restarted.to_canonical_json_file(snapshot_path)
        canonical_file_text = snapshot_path.read_text(encoding="utf-8")
        assert canonical_file_text == restarted.as_canonical_json()

        restarted = KnowledgeStore.from_canonical_json_file(snapshot_path)
        assert restarted.as_canonical_json() == canonical_file_text

    return restarted


def test_merge_conflict_journal_query_replay_restart_invariant_for_ingestion_permutations_and_checkpoint_segmentation() -> None:
    context = _build_context(tx_base=12320)

    baseline_store, _baseline_results = _replay_with_annotation_free_journal(
        context.replicas
    )
    baseline_signature = _collect_journal_query_signature(
        baseline_store,
        context=context,
    )
    baseline_conflict_signatures = _journal_conflict_signatures(baseline_store)
    assert (
        tuple(tx_id for tx_id, _merge_result in baseline_store.merge_conflict_journal())
        == context.expected_journal_tx_ids
    )

    journal_stream = baseline_store.merge_conflict_journal()
    assert baseline_store.query_merge_conflict_projection_as_of_from_journal(
        tx_id=context.tx_to
    ) == KnowledgeStore.query_merge_conflict_projection_as_of(
        journal_stream,
        tx_id=context.tx_to,
    )
    assert baseline_store.query_merge_conflict_projection_for_tx_window_from_journal(
        tx_start=context.tx_from,
        tx_end=context.tx_to,
    ) == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        journal_stream,
        tx_start=context.tx_from,
        tx_end=context.tx_to,
    )
    assert (
        baseline_store.query_merge_conflict_projection_transition_for_tx_window_from_journal(
            tx_from=context.tx_from,
            tx_to=context.tx_to,
            valid_at=context.valid_at,
        )
        == KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            journal_stream,
            tx_from=context.tx_from,
            tx_to=context.tx_to,
            valid_at=context.valid_at,
        )
    )
    assert baseline_store.query_state_fingerprint_as_of(
        tx_id=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=None,
    ) == baseline_store.query_state_fingerprint_as_of(
        tx_id=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=journal_stream,
    )
    assert (
        baseline_store.query_state_fingerprint_as_of(
            tx_id=context.tx_to,
            valid_at=context.valid_at,
            merge_results_by_tx=(),
        ).merge_conflict_projection
        != baseline_store.query_state_fingerprint_as_of(
            tx_id=context.tx_to,
            valid_at=context.valid_at,
            merge_results_by_tx=None,
        ).merge_conflict_projection
    )

    permutation_orders = tuple(itertools.permutations(context.replicas))
    assert len(permutation_orders) == 24

    for order in permutation_orders:
        ordered_replicas = tuple(order)

        unsplit_store, _unsplit_results = _replay_with_annotation_free_journal(
            ordered_replicas
        )
        assert (
            tuple(tx_id for tx_id, _merge_result in unsplit_store.merge_conflict_journal())
            == context.expected_journal_tx_ids
        )
        assert _journal_conflict_signatures(unsplit_store) == baseline_conflict_signatures
        unsplit_signature = _collect_journal_query_signature(
            unsplit_store,
            context=context,
        )
        assert unsplit_signature == baseline_signature

        segmented_store, _segmented_results = _replay_with_annotation_free_journal(
            ordered_replicas,
            boundaries=(1, 3),
        )
        assert (
            tuple(tx_id for tx_id, _merge_result in segmented_store.merge_conflict_journal())
            == context.expected_journal_tx_ids
        )
        assert _journal_conflict_signatures(segmented_store) == baseline_conflict_signatures
        segmented_signature = _collect_journal_query_signature(
            segmented_store,
            context=context,
        )
        assert segmented_signature == unsplit_signature


def test_merge_conflict_journal_query_replay_restart_invariant_for_duplicate_replay_and_restarts(
    tmp_path: Path,
) -> None:
    context = _build_context(tx_base=12610)

    unsplit_store, _unsplit_results = _replay_with_annotation_free_journal(context.replicas)
    unsplit_signature = _collect_journal_query_signature(
        unsplit_store,
        context=context,
    )
    unsplit_conflict_signatures = _journal_conflict_signatures(unsplit_store)

    segmented_store, _segmented_results = _replay_with_annotation_free_journal(
        context.replicas,
        boundaries=(1, 3),
    )
    duplicate_store, duplicate_results = _replay_with_annotation_free_journal(
        context.replicas,
        start=unsplit_store,
    )
    resumed_duplicate_store, resumed_duplicate_results = _replay_with_annotation_free_journal(
        context.replicas,
        start=unsplit_store.checkpoint(),
    )

    assert segmented_store.as_canonical_json() == unsplit_store.as_canonical_json()
    assert all(not merge_result.conflicts for merge_result in duplicate_results)
    assert all(not merge_result.conflicts for merge_result in resumed_duplicate_results)

    replay_variants = (
        ("unsplit", unsplit_store),
        ("segmented", segmented_store),
        ("duplicate", duplicate_store),
        ("resumed-duplicate", resumed_duplicate_store),
    )
    for variant_name, replay_store in replay_variants:
        assert _journal_conflict_signatures(replay_store) == unsplit_conflict_signatures
        assert (
            _collect_journal_query_signature(
                replay_store,
                context=context,
            )
            == unsplit_signature
        )
        _assert_restore_parity(
            replay_store,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-query-replay-restart-{variant_name}.snapshot.canonical.json",
        )

        restarted_store = _apply_restart_cycles(
            replay_store,
            restart_cycles=3,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-query-replay-restart-{variant_name}.restart.canonical.json",
        )
        assert (
            _collect_journal_query_signature(
                restarted_store,
                context=context,
            )
            == unsplit_signature
        )
        _assert_restore_parity(
            restarted_store,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-query-replay-restart-{variant_name}.post-restart.canonical.json",
        )
