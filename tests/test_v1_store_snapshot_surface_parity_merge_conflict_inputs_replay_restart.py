from dataclasses import dataclass
from datetime import datetime
import importlib.util
import itertools
from pathlib import Path

from dks import KnowledgeStore, MergeResult

ReplicaStream = tuple[tuple[int, KnowledgeStore], ...]
MergeStream = tuple[tuple[int, MergeResult], ...]


def _load_peer_test_module(module_name: str, file_name: str):
    module_path = Path(__file__).with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MERGE_CONFLICT_INPUTS = _load_peer_test_module(
    "surface_parity_merge_conflict_inputs_replay_restart",
    "test_v1_store_snapshot_surface_parity_merge_conflict_inputs.py",
)


@dataclass(frozen=True)
class MergeConflictInputSurfaceContext:
    replicas_by_tx: ReplicaStream
    valid_at: datetime
    tx_start: int
    tx_end: int


def _build_context(*, tx_base: int) -> MergeConflictInputSurfaceContext:
    replicas_by_tx, valid_at, tx_start, tx_end = (
        _MERGE_CONFLICT_INPUTS._build_merge_conflict_input_context(tx_base=tx_base)
    )
    return MergeConflictInputSurfaceContext(
        replicas_by_tx=replicas_by_tx,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
    )


def _collect_surface_signature(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    context: MergeConflictInputSurfaceContext,
) -> tuple:
    merge_stream_with_extras = (
        _MERGE_CONFLICT_INPUTS._AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
            merge_stream,
            tx_end=context.tx_end,
        )
    )
    return _MERGE_CONFLICT_INPUTS._collect_merge_conflict_input_signature(
        store,
        merge_stream=merge_stream_with_extras,
        valid_at=context.valid_at,
        tx_start=context.tx_start,
        tx_end=context.tx_end,
    )


def _stream_conflict_signatures(
    merge_stream: MergeStream,
) -> tuple[tuple[str, str, str], ...]:
    conflicts = tuple(
        conflict
        for _tx_id, merge_result in merge_stream
        for conflict in merge_result.conflicts
    )
    return KnowledgeStore.conflict_signatures(conflicts)


def _replay_replicas(
    replicas_by_tx: ReplicaStream,
    *,
    boundaries: tuple[int, ...] = (),
) -> tuple[KnowledgeStore, MergeStream]:
    assert tuple(sorted(boundaries)) == boundaries
    assert all(0 < boundary < len(replicas_by_tx) for boundary in boundaries)

    merged = KnowledgeStore()
    stream: list[tuple[int, MergeResult]] = []
    start_index = 0

    for boundary in boundaries + (len(replicas_by_tx),):
        for merge_tx_id, source_replica in replicas_by_tx[start_index:boundary]:
            merge_result = merged.merge(source_replica.checkpoint())
            merged = merge_result.merged
            stream.append((merge_tx_id, merge_result))

        start_index = boundary
        if boundary < len(replicas_by_tx):
            merged = merged.checkpoint()

    return merged, tuple(stream)


def _replay_duplicate_from(
    replicas_by_tx: ReplicaStream,
    *,
    start: KnowledgeStore,
) -> tuple[KnowledgeStore, MergeStream]:
    merged = start
    stream: list[tuple[int, MergeResult]] = []
    for merge_tx_id, source_replica in replicas_by_tx:
        merge_result = merged.merge(source_replica.checkpoint())
        merged = merge_result.merged
        stream.append((merge_tx_id, merge_result))
    return merged, tuple(stream)


def _assert_restore_parity(
    store: KnowledgeStore,
    *,
    merge_stream: MergeStream,
    context: MergeConflictInputSurfaceContext,
    expected_signature: tuple,
    snapshot_path: Path | None = None,
) -> None:
    canonical_payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert (
        _collect_surface_signature(
            restored_from_payload,
            merge_stream=merge_stream,
            context=context,
        )
        == expected_signature
    )
    assert (
        _collect_surface_signature(
            restored_from_json,
            merge_stream=merge_stream,
            context=context,
        )
        == expected_signature
    )

    if snapshot_path is not None:
        store.to_canonical_json_file(snapshot_path)
        restored_from_file = KnowledgeStore.from_canonical_json_file(snapshot_path)
        assert (
            _collect_surface_signature(
                restored_from_file,
                merge_stream=merge_stream,
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


def test_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart_invariant_for_ingestion_permutations() -> None:
    context = _build_context(tx_base=10670)

    baseline_store, baseline_stream = _replay_replicas(context.replicas_by_tx)
    baseline_signature = _collect_surface_signature(
        baseline_store,
        merge_stream=baseline_stream,
        context=context,
    )
    baseline_conflict_signatures = _stream_conflict_signatures(baseline_stream)
    _assert_restore_parity(
        baseline_store,
        merge_stream=baseline_stream,
        context=context,
        expected_signature=baseline_signature,
    )
    baseline_signature_without_boundary_window = (
        baseline_signature[:3] + baseline_signature[4:]
    )

    permutation_orders = tuple(itertools.permutations(context.replicas_by_tx))
    assert len(permutation_orders) == 24

    for order in permutation_orders:
        ordered_replicas = tuple(order)

        unsplit_store, unsplit_stream = _replay_replicas(ordered_replicas)
        assert _stream_conflict_signatures(unsplit_stream) == baseline_conflict_signatures
        unsplit_signature = _collect_surface_signature(
            unsplit_store,
            merge_stream=unsplit_stream,
            context=context,
        )
        assert (
            unsplit_signature[:3] + unsplit_signature[4:]
            == baseline_signature_without_boundary_window
        )
        _assert_restore_parity(
            unsplit_store,
            merge_stream=unsplit_stream,
            context=context,
            expected_signature=unsplit_signature,
        )

        segmented_store, segmented_stream = _replay_replicas(
            ordered_replicas,
            boundaries=(1, 3),
        )
        assert _stream_conflict_signatures(segmented_stream) == baseline_conflict_signatures
        segmented_signature = _collect_surface_signature(
            segmented_store,
            merge_stream=segmented_stream,
            context=context,
        )
        assert segmented_signature == unsplit_signature
        assert (
            segmented_signature[:3] + segmented_signature[4:]
            == baseline_signature_without_boundary_window
        )
        _assert_restore_parity(
            segmented_store,
            merge_stream=segmented_stream,
            context=context,
            expected_signature=segmented_signature,
        )


def test_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart_invariant_for_segmented_duplicate_and_restarts(
    tmp_path: Path,
) -> None:
    context = _build_context(tx_base=10850)

    unsplit_store, unsplit_stream = _replay_replicas(context.replicas_by_tx)
    unsplit_signature = _collect_surface_signature(
        unsplit_store,
        merge_stream=unsplit_stream,
        context=context,
    )
    unsplit_conflict_signatures = _stream_conflict_signatures(unsplit_stream)

    segmented_store, segmented_stream = _replay_replicas(
        context.replicas_by_tx,
        boundaries=(1, 3),
    )
    duplicate_store, duplicate_stream = _replay_duplicate_from(
        context.replicas_by_tx,
        start=unsplit_store,
    )
    resumed_duplicate_store, resumed_duplicate_stream = _replay_duplicate_from(
        context.replicas_by_tx,
        start=unsplit_store.checkpoint(),
    )

    assert segmented_store.as_canonical_json() == unsplit_store.as_canonical_json()
    assert all(not merge_result.conflicts for _tx_id, merge_result in duplicate_stream)
    assert all(
        not merge_result.conflicts
        for _tx_id, merge_result in resumed_duplicate_stream
    )

    duplicate_history_stream = unsplit_stream + duplicate_stream
    resumed_duplicate_history_stream = unsplit_stream + resumed_duplicate_stream

    assert _stream_conflict_signatures(segmented_stream) == unsplit_conflict_signatures
    assert (
        _stream_conflict_signatures(duplicate_history_stream)
        == unsplit_conflict_signatures
    )
    assert (
        _stream_conflict_signatures(resumed_duplicate_history_stream)
        == unsplit_conflict_signatures
    )

    replay_variants = (
        ("unsplit", unsplit_store, unsplit_stream),
        ("segmented", segmented_store, segmented_stream),
        ("duplicate", duplicate_store, duplicate_history_stream),
        (
            "resumed-duplicate",
            resumed_duplicate_store,
            resumed_duplicate_history_stream,
        ),
    )

    for variant_name, replay_store, replay_stream in replay_variants:
        assert (
            _collect_surface_signature(
                replay_store,
                merge_stream=replay_stream,
                context=context,
            )
            == unsplit_signature
        )
        _assert_restore_parity(
            replay_store,
            merge_stream=replay_stream,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"surface-parity-merge-conflict-inputs-{variant_name}.snapshot.canonical.json",
        )

        restarted_store = _apply_restart_cycles(
            replay_store,
            restart_cycles=3,
            snapshot_path=tmp_path
            / f"surface-parity-merge-conflict-inputs-{variant_name}.restart.canonical.json",
        )
        assert (
            _collect_surface_signature(
                restarted_store,
                merge_stream=replay_stream,
                context=context,
            )
            == unsplit_signature
        )
        _assert_restore_parity(
            restarted_store,
            merge_stream=replay_stream,
            context=context,
            expected_signature=unsplit_signature,
            snapshot_path=tmp_path
            / f"surface-parity-merge-conflict-inputs-{variant_name}.post-restart.canonical.json",
        )
