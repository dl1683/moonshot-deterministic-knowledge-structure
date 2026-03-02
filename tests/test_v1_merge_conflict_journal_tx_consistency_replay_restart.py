import importlib.util
import itertools
from pathlib import Path

from dks import KnowledgeStore, MergeResult

ReplicaTxStream = tuple[tuple[int, KnowledgeStore], ...]


def _load_peer_test_module(module_name: str, file_name: str):
    module_path = Path(__file__).with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_QUERY_REPLAY = _load_peer_test_module(
    "merge_conflict_journal_query_replay_restart_for_tx_consistency_replay_restart",
    "test_v1_merge_conflict_journal_query_replay_restart.py",
)


def _replicas_by_tx(context) -> ReplicaTxStream:
    return tuple(
        (_QUERY_REPLAY._replica_stream_tx_id(replica), replica)
        for replica in context.replicas
    )


def _representative_permutation_orders(
    replicas_by_tx: ReplicaTxStream,
) -> tuple[ReplicaTxStream, ...]:
    permutation_orders = tuple(itertools.permutations(replicas_by_tx))
    assert len(permutation_orders) == 24

    selected_indexes = (0, 7, 16, 23)
    selected_orders = tuple(
        tuple(permutation_orders[index]) for index in selected_indexes
    )
    assert len(selected_orders) == len(selected_indexes)
    return selected_orders


def _replay_with_journal_tx_mode(
    replicas_by_tx: ReplicaTxStream,
    *,
    use_explicit_override: bool,
    start: KnowledgeStore | None = None,
    boundaries: tuple[int, ...] = (),
) -> tuple[KnowledgeStore, tuple[MergeResult, ...]]:
    assert tuple(sorted(boundaries)) == boundaries
    assert all(0 < boundary < len(replicas_by_tx) for boundary in boundaries)

    merged = start if start is not None else KnowledgeStore()
    merge_results: list[MergeResult] = []
    start_index = 0

    for boundary in boundaries + (len(replicas_by_tx),):
        for merge_tx_id, replica in replicas_by_tx[start_index:boundary]:
            if use_explicit_override:
                merge_result = merged.merge_and_record_conflicts(
                    replica.checkpoint(),
                    journal_tx_id=merge_tx_id,
                )
            else:
                merge_result = merged.merge_and_record_conflicts(replica.checkpoint())
            merged = merge_result.merged
            merge_results.append(merge_result)

        start_index = boundary
        if boundary < len(replicas_by_tx):
            merged = merged.checkpoint()

    return merged, tuple(merge_results)


def _assert_direct_and_fingerprint_query_parity(store: KnowledgeStore, *, context) -> None:
    journal_stream = store.merge_conflict_journal()
    assert store.query_merge_conflict_projection_as_of_from_journal(
        tx_id=context.tx_to
    ) == KnowledgeStore.query_merge_conflict_projection_as_of(
        journal_stream,
        tx_id=context.tx_to,
    )
    assert store.query_merge_conflict_projection_for_tx_window_from_journal(
        tx_start=context.tx_from,
        tx_end=context.tx_to,
    ) == KnowledgeStore.query_merge_conflict_projection_for_tx_window(
        journal_stream,
        tx_start=context.tx_from,
        tx_end=context.tx_to,
    )
    assert (
        store.query_merge_conflict_projection_transition_for_tx_window_from_journal(
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
    assert store.query_state_fingerprint_as_of(
        tx_id=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=None,
    ) == store.query_state_fingerprint_as_of(
        tx_id=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=journal_stream,
    )
    assert store.query_state_fingerprint_for_tx_window(
        tx_start=context.tx_from,
        tx_end=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=None,
    ) == store.query_state_fingerprint_for_tx_window(
        tx_start=context.tx_from,
        tx_end=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=journal_stream,
    )
    assert store.query_state_fingerprint_transition_for_tx_window(
        tx_from=context.tx_from,
        tx_to=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=None,
    ) == store.query_state_fingerprint_transition_for_tx_window(
        tx_from=context.tx_from,
        tx_to=context.tx_to,
        valid_at=context.valid_at,
        merge_results_by_tx=journal_stream,
    )


def _assert_equivalent_history_parity(
    *,
    explicit_store: KnowledgeStore,
    derived_store: KnowledgeStore,
    context,
) -> None:
    assert explicit_store.as_canonical_json() == derived_store.as_canonical_json()
    assert _QUERY_REPLAY._journal_conflict_signatures(
        explicit_store
    ) == _QUERY_REPLAY._journal_conflict_signatures(derived_store)
    assert _QUERY_REPLAY._collect_journal_query_signature(
        explicit_store,
        context=context,
    ) == _QUERY_REPLAY._collect_journal_query_signature(
        derived_store,
        context=context,
    )


def test_merge_conflict_journal_tx_consistency_replay_restart_invariant_for_ingestion_permutations_and_checkpoint_segmentation() -> None:
    context = _QUERY_REPLAY._build_context(tx_base=12740)
    replicas_by_tx = _replicas_by_tx(context)

    baseline_explicit_store, _baseline_explicit_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=True,
    )
    baseline_derived_store, _baseline_derived_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=False,
    )
    _assert_equivalent_history_parity(
        explicit_store=baseline_explicit_store,
        derived_store=baseline_derived_store,
        context=context,
    )
    baseline_signature = _QUERY_REPLAY._collect_journal_query_signature(
        baseline_explicit_store,
        context=context,
    )
    baseline_conflict_signatures = _QUERY_REPLAY._journal_conflict_signatures(
        baseline_explicit_store
    )
    assert (
        tuple(
            tx_id
            for tx_id, _merge_result in baseline_explicit_store.merge_conflict_journal()
        )
        == context.expected_journal_tx_ids
    )
    _assert_direct_and_fingerprint_query_parity(
        baseline_explicit_store,
        context=context,
    )

    permutation_orders = _representative_permutation_orders(replicas_by_tx)

    for ordered_replicas_by_tx in permutation_orders:

        unsplit_explicit_store, _unsplit_explicit_results = _replay_with_journal_tx_mode(
            ordered_replicas_by_tx,
            use_explicit_override=True,
        )
        unsplit_derived_store, _unsplit_derived_results = _replay_with_journal_tx_mode(
            ordered_replicas_by_tx,
            use_explicit_override=False,
        )
        _assert_equivalent_history_parity(
            explicit_store=unsplit_explicit_store,
            derived_store=unsplit_derived_store,
            context=context,
        )
        assert (
            tuple(
                tx_id
                for tx_id, _merge_result in unsplit_explicit_store.merge_conflict_journal()
            )
            == context.expected_journal_tx_ids
        )
        assert (
            _QUERY_REPLAY._journal_conflict_signatures(unsplit_explicit_store)
            == baseline_conflict_signatures
        )
        unsplit_signature = _QUERY_REPLAY._collect_journal_query_signature(
            unsplit_explicit_store,
            context=context,
        )
        assert unsplit_signature == baseline_signature
        _assert_direct_and_fingerprint_query_parity(
            unsplit_explicit_store,
            context=context,
        )

        segmented_explicit_store, _segmented_explicit_results = _replay_with_journal_tx_mode(
            ordered_replicas_by_tx,
            use_explicit_override=True,
            boundaries=(1, 3),
        )
        segmented_derived_store, _segmented_derived_results = _replay_with_journal_tx_mode(
            ordered_replicas_by_tx,
            use_explicit_override=False,
            boundaries=(1, 3),
        )
        _assert_equivalent_history_parity(
            explicit_store=segmented_explicit_store,
            derived_store=segmented_derived_store,
            context=context,
        )
        assert (
            tuple(
                tx_id
                for tx_id, _merge_result in segmented_explicit_store.merge_conflict_journal()
            )
            == context.expected_journal_tx_ids
        )
        assert (
            _QUERY_REPLAY._journal_conflict_signatures(segmented_explicit_store)
            == baseline_conflict_signatures
        )
        segmented_signature = _QUERY_REPLAY._collect_journal_query_signature(
            segmented_explicit_store,
            context=context,
        )
        assert segmented_signature == unsplit_signature
        _assert_direct_and_fingerprint_query_parity(
            segmented_explicit_store,
            context=context,
        )


def test_merge_conflict_journal_tx_consistency_replay_restart_invariant_for_duplicate_replay_and_restarts(
    tmp_path: Path,
) -> None:
    context = _QUERY_REPLAY._build_context(tx_base=12910)
    replicas_by_tx = _replicas_by_tx(context)

    unsplit_explicit_store, _unsplit_explicit_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=True,
    )
    unsplit_derived_store, _unsplit_derived_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=False,
    )
    _assert_equivalent_history_parity(
        explicit_store=unsplit_explicit_store,
        derived_store=unsplit_derived_store,
        context=context,
    )
    unsplit_signature = _QUERY_REPLAY._collect_journal_query_signature(
        unsplit_explicit_store,
        context=context,
    )
    unsplit_conflict_signatures = _QUERY_REPLAY._journal_conflict_signatures(
        unsplit_explicit_store
    )

    segmented_explicit_store, _segmented_explicit_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=True,
        boundaries=(1, 3),
    )
    segmented_derived_store, _segmented_derived_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=False,
        boundaries=(1, 3),
    )
    _assert_equivalent_history_parity(
        explicit_store=segmented_explicit_store,
        derived_store=segmented_derived_store,
        context=context,
    )

    duplicate_explicit_store, duplicate_explicit_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=True,
        start=unsplit_explicit_store,
    )
    duplicate_derived_store, _duplicate_derived_results = _replay_with_journal_tx_mode(
        replicas_by_tx,
        use_explicit_override=False,
        start=unsplit_derived_store,
    )
    _assert_equivalent_history_parity(
        explicit_store=duplicate_explicit_store,
        derived_store=duplicate_derived_store,
        context=context,
    )

    resumed_duplicate_explicit_store, resumed_duplicate_explicit_results = (
        _replay_with_journal_tx_mode(
            replicas_by_tx,
            use_explicit_override=True,
            start=unsplit_explicit_store.checkpoint(),
        )
    )
    resumed_duplicate_derived_store, _resumed_duplicate_derived_results = (
        _replay_with_journal_tx_mode(
            replicas_by_tx,
            use_explicit_override=False,
            start=unsplit_derived_store.checkpoint(),
        )
    )
    _assert_equivalent_history_parity(
        explicit_store=resumed_duplicate_explicit_store,
        derived_store=resumed_duplicate_derived_store,
        context=context,
    )

    assert (
        segmented_explicit_store.as_canonical_json()
        == unsplit_explicit_store.as_canonical_json()
    )
    assert all(not merge_result.conflicts for merge_result in duplicate_explicit_results)
    assert all(
        not merge_result.conflicts
        for merge_result in resumed_duplicate_explicit_results
    )

    replay_variants = (
        ("unsplit", unsplit_explicit_store),
        ("segmented", segmented_explicit_store),
        ("duplicate", duplicate_explicit_store),
        ("resumed-duplicate", resumed_duplicate_explicit_store),
    )
    for variant_name, replay_store in replay_variants:
        assert (
            _QUERY_REPLAY._journal_conflict_signatures(replay_store)
            == unsplit_conflict_signatures
        )
        assert (
            _QUERY_REPLAY._collect_journal_query_signature(
                replay_store,
                context=context,
            )
            == unsplit_signature
        )
        _assert_direct_and_fingerprint_query_parity(
            replay_store,
            context=context,
        )

    restart_variants = (
        ("unsplit", unsplit_explicit_store),
        ("duplicate", duplicate_explicit_store),
        ("resumed-duplicate", resumed_duplicate_explicit_store),
    )
    for variant_name, replay_store in restart_variants:
        _QUERY_REPLAY._assert_restore_parity(
            replay_store,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-tx-consistency-replay-restart-{variant_name}.snapshot.canonical.json",
        )

        restarted_store = _QUERY_REPLAY._apply_restart_cycles(
            replay_store,
            restart_cycles=3,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-tx-consistency-replay-restart-{variant_name}.restart.canonical.json",
        )
        assert (
            _QUERY_REPLAY._collect_journal_query_signature(
                restarted_store,
                context=context,
            )
            == unsplit_signature
        )
        _assert_direct_and_fingerprint_query_parity(
            restarted_store,
            context=context,
        )
        _QUERY_REPLAY._assert_restore_parity(
            restarted_store,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"merge-conflict-journal-tx-consistency-replay-restart-{variant_name}.post-restart.canonical.json",
        )
