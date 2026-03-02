from datetime import datetime
import importlib.util
from pathlib import Path

from dks import KnowledgeStore, MergeResult

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
    "surface_parity_as_of_window_for_conflict_aware_fingerprint",
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


def _merge_bucket_signature(fingerprint) -> tuple[tuple, tuple]:
    projection = fingerprint.merge_conflict_projection
    return projection.signature_counts, projection.code_counts


def _transition_bucket_signature(transition) -> tuple[tuple, ...]:
    return (
        transition.entered_revision_active,
        transition.exited_revision_active,
        transition.entered_revision_retracted,
        transition.exited_revision_retracted,
        transition.entered_relation_resolution_active,
        transition.exited_relation_resolution_active,
        transition.entered_relation_resolution_pending,
        transition.exited_relation_resolution_pending,
        transition.entered_relation_lifecycle_active,
        transition.exited_relation_lifecycle_active,
        transition.entered_relation_lifecycle_pending,
        transition.exited_relation_lifecycle_pending,
        transition.entered_relation_lifecycle_signature_active,
        transition.exited_relation_lifecycle_signature_active,
        transition.entered_relation_lifecycle_signature_pending,
        transition.exited_relation_lifecycle_signature_pending,
        transition.entered_merge_conflict_signature_counts,
        transition.exited_merge_conflict_signature_counts,
        transition.entered_merge_conflict_code_counts,
        transition.exited_merge_conflict_code_counts,
    )


def _collect_conflict_aware_fingerprint_signature(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    valid_at: datetime,
    tx_start: int,
    tx_end: int,
    subject_core_id: str,
) -> tuple:
    merge_results_by_tx = tuple(merge_stream)

    as_of_start = store.query_state_fingerprint_as_of(
        tx_id=tx_start,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    as_of_end = store.query_state_fingerprint_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    as_of_end_one_shot = store.query_state_fingerprint_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    as_of_end_filtered = store.query_state_fingerprint_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    as_of_end_filtered_one_shot = store.query_state_fingerprint_as_of(
        tx_id=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert as_of_end_one_shot == as_of_end
    assert as_of_end_one_shot.digest == as_of_end.digest
    assert _merge_bucket_signature(as_of_end_one_shot) == _merge_bucket_signature(as_of_end)
    assert as_of_end_filtered_one_shot == as_of_end_filtered
    assert as_of_end_filtered_one_shot.digest == as_of_end_filtered.digest
    assert _merge_bucket_signature(as_of_end_filtered_one_shot) == _merge_bucket_signature(
        as_of_end_filtered
    )
    assert _merge_bucket_signature(as_of_end_filtered) == _merge_bucket_signature(as_of_end)

    window = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    window_one_shot = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    window_filtered = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    window_filtered_one_shot = store.query_state_fingerprint_for_tx_window(
        tx_start=tx_start,
        tx_end=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert window_one_shot == window
    assert window_one_shot.digest == window.digest
    assert _merge_bucket_signature(window_one_shot) == _merge_bucket_signature(window)
    assert window_filtered_one_shot == window_filtered
    assert window_filtered_one_shot.digest == window_filtered.digest
    assert _merge_bucket_signature(window_filtered_one_shot) == _merge_bucket_signature(
        window_filtered
    )
    assert _merge_bucket_signature(window_filtered) == _merge_bucket_signature(window)

    transition = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=merge_results_by_tx,
    )
    transition_one_shot = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    transition_filtered = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    )
    transition_filtered_one_shot = store.query_state_fingerprint_transition_for_tx_window(
        tx_from=tx_start,
        tx_to=tx_end,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=OneShotIterable(merge_results_by_tx),
    )
    assert transition_one_shot == transition
    assert transition_one_shot.from_digest == transition.from_digest
    assert transition_one_shot.to_digest == transition.to_digest
    assert _transition_bucket_signature(transition_one_shot) == _transition_bucket_signature(
        transition
    )
    assert transition_filtered_one_shot == transition_filtered
    assert transition_filtered_one_shot.from_digest == transition_filtered.from_digest
    assert transition_filtered_one_shot.to_digest == transition_filtered.to_digest
    assert _transition_bucket_signature(
        transition_filtered_one_shot
    ) == _transition_bucket_signature(transition_filtered)
    assert transition.from_digest == as_of_start.digest
    assert transition.to_digest == as_of_end.digest
    assert transition_filtered.from_digest == store.query_state_fingerprint_as_of(
        tx_id=tx_start,
        valid_at=valid_at,
        core_id=subject_core_id,
        merge_results_by_tx=merge_results_by_tx,
    ).digest
    assert transition_filtered.to_digest == as_of_end_filtered.digest

    return (
        store.as_canonical_json(),
        as_of_start.as_canonical_json(),
        as_of_end.as_canonical_json(),
        as_of_end_filtered.as_canonical_json(),
        _merge_bucket_signature(as_of_end),
        _merge_bucket_signature(as_of_end_filtered),
        window.as_canonical_json(),
        window_filtered.as_canonical_json(),
        _merge_bucket_signature(window),
        _merge_bucket_signature(window_filtered),
        transition.as_canonical_json(),
        transition_filtered.as_canonical_json(),
        transition.from_digest,
        transition.to_digest,
        transition_filtered.from_digest,
        transition_filtered.to_digest,
        _transition_bucket_signature(transition),
        _transition_bucket_signature(transition_filtered),
    )


def _build_conflict_aware_fingerprint_context(
    *,
    tx_base: int,
) -> tuple[tuple[tuple[int, KnowledgeStore], ...], datetime, int, int, str]:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        subject_core_id,
        _retracted_core_id,
    ) = _AS_OF_WINDOW._build_surface_parity_replicas(tx_base=tx_base)
    return replicas_by_tx, valid_at, tx_start, tx_end, subject_core_id


def test_store_snapshot_surface_parity_conflict_aware_fingerprint_payload_json_restore() -> None:
    replicas_by_tx, valid_at, tx_start, tx_end, subject_core_id = (
        _build_conflict_aware_fingerprint_context(tx_base=10010)
    )

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_conflict_aware_fingerprint_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    )

    restarted_store, restarted_merge_stream = _replay_with_payload_json_restarts(replicas_by_tx)
    restarted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        restarted_merge_stream,
        tx_end=tx_end,
    )
    assert restarted_store.as_canonical_payload() == uninterrupted_store.as_canonical_payload()
    assert restarted_store.as_canonical_json() == uninterrupted_store.as_canonical_json()
    assert _collect_conflict_aware_fingerprint_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    ) == uninterrupted_signature

    restored_from_payload = KnowledgeStore.from_canonical_payload(
        uninterrupted_store.as_canonical_payload()
    )
    restored_from_json = KnowledgeStore.from_canonical_json(
        uninterrupted_store.as_canonical_json()
    )
    assert _collect_conflict_aware_fingerprint_signature(
        restored_from_payload,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    ) == uninterrupted_signature
    assert _collect_conflict_aware_fingerprint_signature(
        restored_from_json,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    ) == uninterrupted_signature


def test_store_snapshot_surface_parity_conflict_aware_fingerprint_file_restore(
    tmp_path: Path,
) -> None:
    replicas_by_tx, valid_at, tx_start, tx_end, subject_core_id = (
        _build_conflict_aware_fingerprint_context(tx_base=10150)
    )

    uninterrupted_store, uninterrupted_merge_stream = _replay_uninterrupted(replicas_by_tx)
    uninterrupted_merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        uninterrupted_merge_stream,
        tx_end=tx_end,
    )
    uninterrupted_signature = _collect_conflict_aware_fingerprint_signature(
        uninterrupted_store,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    )

    snapshot_path = (
        tmp_path / "surface-parity-conflict-aware-fingerprint.snapshot.canonical.json"
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
    assert _collect_conflict_aware_fingerprint_signature(
        restarted_store,
        merge_stream=restarted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    ) == uninterrupted_signature

    _save_canonical_json(uninterrupted_store, snapshot_path)
    restored_from_file = _load_canonical_json(snapshot_path)
    assert _collect_conflict_aware_fingerprint_signature(
        restored_from_file,
        merge_stream=uninterrupted_merge_stream,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
    ) == uninterrupted_signature
