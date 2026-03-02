from dataclasses import dataclass
from datetime import datetime
import importlib.util
import itertools
from pathlib import Path
from typing import Any, Callable

from dks import KnowledgeStore

ReplicaStream = tuple[tuple[int, KnowledgeStore], ...]


def _load_peer_test_module(module_name: str, file_name: str):
    module_path = Path(__file__).with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AS_OF_WINDOW = _load_peer_test_module(
    "surface_parity_as_of_window",
    "test_v1_store_snapshot_surface_parity_as_of_window.py",
)
_TRANSITIONS = _load_peer_test_module(
    "surface_parity_transitions",
    "test_v1_store_snapshot_surface_parity_transitions.py",
)


@dataclass(frozen=True)
class AsOfWindowSurfaceContext:
    replicas_by_tx: ReplicaStream
    valid_at: datetime
    tx_start: int
    tx_end: int
    subject_core_id: str
    retracted_core_id: str


@dataclass(frozen=True)
class TransitionSurfaceContext:
    replicas_by_tx: ReplicaStream
    scenario: Any


def _build_as_of_window_context(*, tx_base: int) -> AsOfWindowSurfaceContext:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        subject_core_id,
        retracted_core_id,
    ) = _AS_OF_WINDOW._build_surface_parity_replicas(tx_base=tx_base)
    return AsOfWindowSurfaceContext(
        replicas_by_tx=replicas_by_tx,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
        retracted_core_id=retracted_core_id,
    )


def _build_transition_context(*, tx_base: int) -> TransitionSurfaceContext:
    replicas_by_tx, scenario = _TRANSITIONS._build_transition_surface_parity_replicas(
        tx_base=tx_base
    )
    return TransitionSurfaceContext(
        replicas_by_tx=replicas_by_tx,
        scenario=scenario,
    )


def _apply_restart_cycles(
    store: KnowledgeStore,
    *,
    restart_cycles: int,
    snapshot_path: Path | None,
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
        if snapshot_path is not None:
            restarted.to_canonical_json_file(snapshot_path)
            canonical_file_text = snapshot_path.read_text(encoding="utf-8")
            assert canonical_file_text == restarted.as_canonical_json()
            restarted = KnowledgeStore.from_canonical_json_file(snapshot_path)
            assert restarted.as_canonical_json() == canonical_file_text
    return restarted


def _replay_replicas(
    replicas_by_tx: ReplicaStream,
    *,
    boundaries: tuple[int, ...] = (),
    duplicate_payloads: bool = False,
) -> KnowledgeStore:
    assert tuple(sorted(boundaries)) == boundaries
    assert all(0 < boundary < len(replicas_by_tx) for boundary in boundaries)

    merged = KnowledgeStore()
    start_index = 0
    for boundary in boundaries + (len(replicas_by_tx),):
        for _merge_tx_id, source_replica in replicas_by_tx[start_index:boundary]:
            repeat_count = 2 if duplicate_payloads else 1
            for replay_index in range(repeat_count):
                replica = source_replica.checkpoint()
                merge_result = merged.merge(replica)
                merged = merge_result.merged

                if duplicate_payloads and replay_index == 1:
                    assert merge_result.conflicts == ()

        start_index = boundary
        if boundary < len(replicas_by_tx):
            merged = merged.checkpoint()

    return merged

def _collect_as_of_window_signature(
    store: KnowledgeStore,
    *,
    context: AsOfWindowSurfaceContext,
) -> tuple:
    merge_stream = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        tuple(),
        tx_end=context.tx_end,
    )
    return _AS_OF_WINDOW._collect_surface_signature(
        store,
        merge_stream=merge_stream,
        valid_at=context.valid_at,
        tx_start=context.tx_start,
        tx_end=context.tx_end,
        subject_core_id=context.subject_core_id,
        retracted_core_id=context.retracted_core_id,
    )


def _collect_transition_signature(
    store: KnowledgeStore,
    *,
    context: TransitionSurfaceContext,
) -> tuple:
    merge_stream = _TRANSITIONS._merge_conflict_stream_with_surface_extras(
        tuple(),
        tx_base=context.scenario.tx_base,
    )
    return _TRANSITIONS._collect_transition_surface_signature(
        store,
        merge_stream=merge_stream,
        scenario=context.scenario,
    )


def _assert_restore_parity(
    store: KnowledgeStore,
    *,
    collect_signature: Callable[[KnowledgeStore], tuple],
    expected_signature: tuple,
    snapshot_path: Path | None = None,
) -> None:
    canonical_payload = store.as_canonical_payload()
    canonical_json = store.as_canonical_json()

    restored_from_payload = KnowledgeStore.from_canonical_payload(canonical_payload)
    restored_from_json = KnowledgeStore.from_canonical_json(canonical_json)

    assert collect_signature(restored_from_payload) == expected_signature
    assert collect_signature(restored_from_json) == expected_signature

    if snapshot_path is not None:
        store.to_canonical_json_file(snapshot_path)
        restored_from_file = KnowledgeStore.from_canonical_json_file(snapshot_path)
        assert collect_signature(restored_from_file) == expected_signature


def _assert_permutation_invariance(
    replicas_by_tx: ReplicaStream,
    *,
    collect_signature: Callable[[KnowledgeStore], tuple],
) -> None:
    baseline_store = _replay_replicas(replicas_by_tx)
    baseline_signature = collect_signature(baseline_store)
    _assert_restore_parity(
        baseline_store,
        collect_signature=collect_signature,
        expected_signature=baseline_signature,
    )

    permutation_orders = tuple(itertools.permutations(replicas_by_tx))
    assert len(permutation_orders) == 24

    for order in permutation_orders:
        permuted_store = _replay_replicas(tuple(order))
        permuted_signature = collect_signature(permuted_store)
        assert permuted_signature == baseline_signature
        _assert_restore_parity(
            permuted_store,
            collect_signature=collect_signature,
            expected_signature=baseline_signature,
        )


def _assert_segmented_duplicate_restart_invariance(
    replicas_by_tx: ReplicaStream,
    *,
    collect_signature: Callable[[KnowledgeStore], tuple],
    snapshot_path: Path,
) -> None:
    baseline_store = _replay_replicas(replicas_by_tx)
    baseline_signature = collect_signature(baseline_store)
    replay_variants = (
        baseline_store,
        _replay_replicas(replicas_by_tx, boundaries=(1, 3)),
        _replay_replicas(replicas_by_tx, duplicate_payloads=True),
        _replay_replicas(
            replicas_by_tx,
            boundaries=(1, 3),
            duplicate_payloads=True,
        ),
    )

    for replay_store in replay_variants:
        assert collect_signature(replay_store) == baseline_signature
        _assert_restore_parity(
            replay_store,
            collect_signature=collect_signature,
            expected_signature=baseline_signature,
            snapshot_path=snapshot_path,
        )

        restarted_store = _apply_restart_cycles(
            replay_store,
            restart_cycles=2,
            snapshot_path=snapshot_path,
        )
        assert collect_signature(restarted_store) == baseline_signature
        _assert_restore_parity(
            restarted_store,
            collect_signature=collect_signature,
            expected_signature=baseline_signature,
            snapshot_path=snapshot_path,
        )

def test_store_snapshot_surface_parity_replay_restart_invariant_for_ingestion_permutations() -> None:
    as_of_context = _build_as_of_window_context(tx_base=9340)
    transition_context = _build_transition_context(tx_base=9470)

    _assert_permutation_invariance(
        as_of_context.replicas_by_tx,
        collect_signature=lambda store: _collect_as_of_window_signature(
            store,
            context=as_of_context,
        ),
    )
    _assert_permutation_invariance(
        transition_context.replicas_by_tx,
        collect_signature=lambda store: _collect_transition_signature(
            store,
            context=transition_context,
        ),
    )


def test_store_snapshot_surface_parity_replay_restart_invariant_for_segmented_duplicate_and_restarts(
    tmp_path: Path,
) -> None:
    as_of_context = _build_as_of_window_context(tx_base=9530)
    transition_context = _build_transition_context(tx_base=9660)

    _assert_segmented_duplicate_restart_invariance(
        as_of_context.replicas_by_tx,
        collect_signature=lambda store: _collect_as_of_window_signature(
            store,
            context=as_of_context,
        ),
        snapshot_path=tmp_path / "surface-replay-restart-as-of.snapshot.canonical.json",
    )
    _assert_segmented_duplicate_restart_invariance(
        transition_context.replicas_by_tx,
        collect_signature=lambda store: _collect_transition_signature(
            store,
            context=transition_context,
        ),
        snapshot_path=tmp_path / "surface-replay-restart-transitions.snapshot.canonical.json",
    )
