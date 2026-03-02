from datetime import datetime
import importlib.util
from pathlib import Path

from dks import KnowledgeStore, MergeConflictProjectionTransition, MergeResult

MergeStream = tuple[tuple[int, MergeResult], ...]


class OneShotIterable:
    def __init__(self, values: tuple) -> None:
        self._values = values
        self._iterated = False

    def __iter__(self):
        if self._iterated:
            raise AssertionError("one-shot iterable was iterated more than once")
        self._iterated = True
        return iter(self._values)


def _load_peer_test_module(module_name: str, file_name: str):
    module_path = Path(__file__).with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AS_OF_WINDOW = _load_peer_test_module(
    "surface_parity_as_of_window_for_merge_conflict_inputs",
    "test_v1_store_snapshot_surface_parity_as_of_window.py",
)


def _save_canonical_json(store: KnowledgeStore, snapshot_path: Path) -> None:
    store.to_canonical_json_file(snapshot_path)


def _load_canonical_json(snapshot_path: Path) -> KnowledgeStore:
    return KnowledgeStore.from_canonical_json_file(snapshot_path)


def _replay_uninterrupted(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for merge_tx_id, replica in replicas_by_tx:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))
    return merged, tuple(merge_stream)


def _replay_with_payload_json_restarts(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for index, (merge_tx_id, replica) in enumerate(replicas_by_tx):
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))

        canonical_payload = merged.as_canonical_payload()
        canonical_json = merged.as_canonical_json()
        restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
        restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

        assert restored_from_payload.as_canonical_payload() == canonical_payload
        assert restored_from_payload.as_canonical_json() == canonical_json
        assert restored_from_json.as_canonical_payload() == canonical_payload
        assert restored_from_json.as_canonical_json() == canonical_json

        merged = restored_from_payload if index % 2 == 0 else restored_from_json

    return merged, tuple(merge_stream)


def _replay_with_file_restarts(
    replicas_by_tx: tuple[tuple[int, KnowledgeStore], ...],
    *,
    snapshot_path: Path,
) -> tuple[KnowledgeStore, MergeStream]:
    merged = KnowledgeStore()
    merge_stream: list[tuple[int, MergeResult]] = []
    for merge_tx_id, replica in replicas_by_tx:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_stream.append((merge_tx_id, merge_result))

        _save_canonical_json(merged, snapshot_path)
        canonical_file_text = snapshot_path.read_text(encoding="utf-8")
        assert canonical_file_text == merged.as_canonical_json()

        merged = _load_canonical_json(snapshot_path)
        assert merged.as_canonical_json() == canonical_file_text

    return merged, tuple(merge_stream)


def _canonical_stream(stream: MergeStream) -> MergeStream:
    return tuple(
        merge_result_by_tx
        for _index, merge_result_by_tx in sorted(
            enumerate(stream),
            key=lambda indexed_merge_result: (
                indexed_merge_result[1][0],
                indexed_merge_result[0],
            ),
        )
    )


def _merge_results_as_of(
    merge_results_by_tx: MergeStream,
    *,
    tx_id: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if merge_result_tx_id <= tx_id
    )


def _merge_results_for_window(
    merge_results_by_tx: MergeStream,
    *,
    tx_start: int,
    tx_end: int,
) -> tuple[MergeResult, ...]:
    return tuple(
        merge_result
        for merge_result_tx_id, merge_result in merge_results_by_tx
        if tx_start <= merge_result_tx_id <= tx_end
    )


def _signature_count_sort_key(
    signature_count: tuple[str, str, str, int],
) -> tuple[str, str, str]:
    return (signature_count[0], signature_count[1], signature_count[2])


def _code_count_sort_key(code_count: tuple[str, int]) -> str:
    return code_count[0]


def _transition_buckets(
    transition: MergeConflictProjectionTransition,
) -> tuple[tuple, tuple, tuple, tuple]:
    return (
        transition.entered_signature_counts,
        transition.exited_signature_counts,
        transition.entered_code_counts,
        transition.exited_code_counts,
    )


def _transition_has_delta(transition: MergeConflictProjectionTransition) -> bool:
    return any(_transition_buckets(transition))


def _expected_transition_buckets_from_as_of_diffs(
    merge_results_by_tx: MergeStream,
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
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.signature_counts) - set(to_projection.signature_counts),
                key=_signature_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(to_projection.code_counts) - set(from_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
        tuple(
            sorted(
                set(from_projection.code_counts) - set(to_projection.code_counts),
                key=_code_count_sort_key,
            )
        ),
    )


def _conflict_total(summary: tuple[tuple, tuple]) -> int:
    return sum(count for *_signature, count in summary[0])


def _collect_merge_conflict_input_signature(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    valid_at: datetime,
    tx_start: int,
    tx_end: int,
) -> tuple:
    shuffled_stream = tuple(reversed(merge_stream))
    canonical_stream = _canonical_stream(shuffled_stream)

    assert shuffled_stream != canonical_stream

    as_of_canonical = store.query_merge_conflict_projection_as_of(
        canonical_stream,
        tx_id=tx_end,
    )
    as_of_shuffled = store.query_merge_conflict_projection_as_of(
        shuffled_stream,
        tx_id=tx_end,
    )
    as_of_one_shot = store.query_merge_conflict_projection_as_of(
        OneShotIterable(shuffled_stream),
        tx_id=tx_end,
    )
    expected_as_of_summary = MergeResult.stream_conflict_summary(
        _merge_results_as_of(canonical_stream, tx_id=tx_end)
    )
    assert as_of_canonical.summary == expected_as_of_summary
    assert as_of_shuffled == as_of_canonical
    assert as_of_one_shot == as_of_canonical

    window_canonical = store.query_merge_conflict_projection_for_tx_window(
        canonical_stream,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    window_shuffled = store.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_start,
        tx_end=tx_end,
    )
    window_one_shot = store.query_merge_conflict_projection_for_tx_window(
        OneShotIterable(shuffled_stream),
        tx_start=tx_start,
        tx_end=tx_end,
    )
    expected_window_summary = MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_start,
            tx_end=tx_end,
        )
    )
    assert window_canonical.summary == expected_window_summary
    assert window_shuffled == window_canonical
    assert window_one_shot == window_canonical

    boundary_start_inclusive_window = store.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_end - 2,
        tx_end=tx_end - 1,
    )
    boundary_start_exclusive_window = store.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_end - 1,
        tx_end=tx_end - 1,
    )
    assert boundary_start_inclusive_window.summary == MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_end - 2,
            tx_end=tx_end - 1,
        )
    )
    assert boundary_start_exclusive_window.summary == MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_end - 1,
            tx_end=tx_end - 1,
        )
    )
    assert _conflict_total(boundary_start_inclusive_window.summary) > _conflict_total(
        boundary_start_exclusive_window.summary
    )

    boundary_end_inclusive_window = store.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_end - 1,
        tx_end=tx_end,
    )
    boundary_end_exclusive_window = store.query_merge_conflict_projection_for_tx_window(
        shuffled_stream,
        tx_start=tx_end - 1,
        tx_end=tx_end - 1,
    )
    assert boundary_end_inclusive_window.summary == MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_end - 1,
            tx_end=tx_end,
        )
    )
    assert boundary_end_exclusive_window.summary == MergeResult.stream_conflict_summary(
        _merge_results_for_window(
            canonical_stream,
            tx_start=tx_end - 1,
            tx_end=tx_end - 1,
        )
    )
    assert _conflict_total(boundary_end_inclusive_window.summary) > _conflict_total(
        boundary_end_exclusive_window.summary
    )

    transition_canonical = store.query_merge_conflict_projection_transition_for_tx_window(
        canonical_stream,
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
    )
    transition_shuffled = store.query_merge_conflict_projection_transition_for_tx_window(
        shuffled_stream,
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
    )
    transition_one_shot = store.query_merge_conflict_projection_transition_for_tx_window(
        OneShotIterable(shuffled_stream),
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
    )
    assert transition_shuffled == transition_canonical
    assert transition_one_shot == transition_canonical
    assert _transition_buckets(transition_canonical) == (
        _expected_transition_buckets_from_as_of_diffs(
            canonical_stream,
            tx_from=tx_start,
            tx_to=tx_end,
        )
    )

    zero_delta_transition = store.query_merge_conflict_projection_transition_for_tx_window(
        OneShotIterable(shuffled_stream),
        tx_from=tx_end,
        tx_to=tx_end,
        valid_at=valid_at,
    )
    assert _transition_buckets(zero_delta_transition) == ((), (), (), ())
    assert _transition_buckets(zero_delta_transition) == (
        _expected_transition_buckets_from_as_of_diffs(
            canonical_stream,
            tx_from=tx_end,
            tx_to=tx_end,
        )
    )

    boundary_start_inclusive_transition = (
        store.query_merge_conflict_projection_transition_for_tx_window(
            shuffled_stream,
            tx_from=tx_end - 2,
            tx_to=tx_end - 1,
            valid_at=valid_at,
        )
    )
    boundary_start_exclusive_transition = (
        store.query_merge_conflict_projection_transition_for_tx_window(
            shuffled_stream,
            tx_from=tx_end - 1,
            tx_to=tx_end - 1,
            valid_at=valid_at,
        )
    )
    boundary_end_inclusive_transition = (
        store.query_merge_conflict_projection_transition_for_tx_window(
            shuffled_stream,
            tx_from=tx_end - 1,
            tx_to=tx_end,
            valid_at=valid_at,
        )
    )
    boundary_end_exclusive_transition = (
        store.query_merge_conflict_projection_transition_for_tx_window(
            shuffled_stream,
            tx_from=tx_end - 1,
            tx_to=tx_end - 1,
            valid_at=valid_at,
        )
    )
    assert _transition_has_delta(boundary_start_inclusive_transition)
    assert not _transition_has_delta(boundary_start_exclusive_transition)
    assert _transition_has_delta(boundary_end_inclusive_transition)
    assert not _transition_has_delta(boundary_end_exclusive_transition)

    return (
        store.as_canonical_json(),
        as_of_canonical.summary,
        window_canonical.summary,
        boundary_start_inclusive_window.summary,
        boundary_start_exclusive_window.summary,
        boundary_end_inclusive_window.summary,
        boundary_end_exclusive_window.summary,
        _transition_buckets(transition_canonical),
        _transition_buckets(zero_delta_transition),
        _transition_buckets(boundary_start_inclusive_transition),
        _transition_buckets(boundary_start_exclusive_transition),
        _transition_buckets(boundary_end_inclusive_transition),
        _transition_buckets(boundary_end_exclusive_transition),
    )


def _build_merge_conflict_input_context(
    *,
    tx_base: int,
) -> tuple[tuple[tuple[int, KnowledgeStore], ...], datetime, int, int]:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        _subject_core_id,
        _retracted_core_id,
    ) = _AS_OF_WINDOW._build_surface_parity_replicas(tx_base=tx_base)
    return replicas_by_tx, valid_at, tx_start, tx_end


def test_store_snapshot_surface_parity_merge_conflict_inputs_payload_json_restore() -> None:
    replicas_by_tx, valid_at, tx_start, tx_end = _build_merge_conflict_input_context(
        tx_base=10390
    )

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_merge_conflict_input_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    )

    restarted_store, restarted_merge_stream = _replay_with_payload_json_restarts(replicas_by_tx)
    restarted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_end=tx_end,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_merge_conflict_input_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    ) == uninterrupted_signature

    restored_from_payload = KnowledgeStore.from_canonical_payload(
        uninterrupted_store.as_canonical_payload()
    )
    restored_from_json = KnowledgeStore.from_canonical_json(
        uninterrupted_store.as_canonical_json()
    )
    assert _collect_merge_conflict_input_signature(
        restored_from_payload,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    ) == uninterrupted_signature
    assert _collect_merge_conflict_input_signature(
        restored_from_json,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    ) == uninterrupted_signature


def test_store_snapshot_surface_parity_merge_conflict_inputs_file_restore(
    tmp_path: Path,
) -> None:
    replicas_by_tx, valid_at, tx_start, tx_end = _build_merge_conflict_input_context(
        tx_base=10520
    )

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_merge_conflict_input_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    )

    snapshot_path = (
        tmp_path / "surface-parity-merge-conflict-inputs.snapshot.canonical.json"
    )
    restarted_store, restarted_merge_stream = _replay_with_file_restarts(
        replicas_by_tx,
        snapshot_path=snapshot_path,
    )
    restarted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_end=tx_end,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_merge_conflict_input_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    ) == uninterrupted_signature

    _save_canonical_json(uninterrupted_store, snapshot_path)
    restored_from_file = _load_canonical_json(snapshot_path)
    assert _collect_merge_conflict_input_signature(
        restored_from_file,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    ) == uninterrupted_signature
