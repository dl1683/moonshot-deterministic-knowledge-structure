from dataclasses import dataclass
from datetime import datetime
import importlib.util
import itertools
from pathlib import Path

from dks import KnowledgeStore, MergeResult

ReplicaStream = tuple[tuple[int, KnowledgeStore], ...]
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
    "surface_parity_as_of_window_for_merge_conflict_journal_replay_restart",
    "test_v1_store_snapshot_surface_parity_as_of_window.py",
)
_CONFLICT_AWARE = _load_peer_test_module(
    "surface_parity_conflict_aware_fingerprint_for_merge_conflict_journal_replay_restart",
    "test_v1_store_snapshot_surface_parity_conflict_aware_fingerprint.py",
)
_MERGE_CONFLICT_INPUTS = _load_peer_test_module(
    "surface_parity_merge_conflict_inputs_for_merge_conflict_journal_replay_restart",
    "test_v1_store_snapshot_surface_parity_merge_conflict_inputs.py",
)


@dataclass(frozen=True)
class JournalBackedSurfaceContext:
    replicas_by_tx: ReplicaStream
    valid_at: datetime
    tx_start: int
    tx_end: int
    subject_core_id: str


def _build_context(*, tx_base: int) -> JournalBackedSurfaceContext:
    (
        replicas_by_tx,
        valid_at,
        tx_start,
        tx_end,
        subject_core_id,
        _retracted_core_id,
    ) = _AS_OF_WINDOW._build_surface_parity_replicas(tx_base=tx_base)
    return JournalBackedSurfaceContext(
        replicas_by_tx=replicas_by_tx,
        valid_at=valid_at,
        tx_start=tx_start,
        tx_end=tx_end,
        subject_core_id=subject_core_id,
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


def _record_merge_result_in_journal(
    store: KnowledgeStore,
    *,
    tx_id: int,
    merge_result: MergeResult,
) -> None:
    store.record_merge_conflict_journal(
        OneShotIterable(((tx_id, merge_result),))
    )


def _replay_replicas_with_journal(
    replicas_by_tx: ReplicaStream,
    *,
    tx_end: int,
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
            _record_merge_result_in_journal(
                merged,
                tx_id=merge_tx_id,
                merge_result=merge_result,
            )
            stream.append((merge_tx_id, merge_result))

        start_index = boundary
        if boundary < len(replicas_by_tx):
            merged = merged.checkpoint()

    surface_extras = _AS_OF_WINDOW._merge_conflict_stream_with_surface_extras(
        tuple(),
        tx_end=tx_end,
    )
    merged.record_merge_conflict_journal(OneShotIterable(surface_extras))
    stream.extend(surface_extras)

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
        _record_merge_result_in_journal(
            merged,
            tx_id=merge_tx_id,
            merge_result=merge_result,
        )
        stream.append((merge_tx_id, merge_result))
    return merged, tuple(stream)


def _collect_journal_backed_surface_signature(
    store: KnowledgeStore,
    *,
    context: JournalBackedSurfaceContext,
) -> tuple:
    journal_stream = store.merge_conflict_journal()
    direct_merge_conflict_signature = _MERGE_CONFLICT_INPUTS._collect_merge_conflict_input_signature(
        store,
        merge_stream=journal_stream,
        valid_at=context.valid_at,
        tx_start=context.tx_start,
        tx_end=context.tx_end,
    )[1:]
    conflict_aware_fingerprint_signature = _CONFLICT_AWARE._collect_conflict_aware_fingerprint_signature(
        store,
        merge_stream=journal_stream,
        valid_at=context.valid_at,
        tx_start=context.tx_start,
        tx_end=context.tx_end,
        subject_core_id=context.subject_core_id,
    )[1:]
    return (
        _stream_conflict_signatures(journal_stream),
        direct_merge_conflict_signature,
        conflict_aware_fingerprint_signature,
    )


def _permutation_invariant_signature(signature: tuple) -> tuple:
    conflict_signatures, direct_signature, conflict_aware_signature = signature
    direct_signature_without_boundary_window = (
        direct_signature[:2] + direct_signature[3:]
    )
    return (
        conflict_signatures,
        direct_signature_without_boundary_window,
        conflict_aware_signature,
    )


def _assert_restore_parity(
    store: KnowledgeStore,
    *,
    context: JournalBackedSurfaceContext,
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
        _collect_journal_backed_surface_signature(
            restored_from_payload,
            context=context,
        )
        == expected_signature
    )
    assert (
        _collect_journal_backed_surface_signature(
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
            _collect_journal_backed_surface_signature(
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


def test_store_snapshot_merge_conflict_journal_replay_restart_invariant_for_ingestion_permutations() -> None:
    context = _build_context(tx_base=11140)

    baseline_store, baseline_stream = _replay_replicas_with_journal(
        context.replicas_by_tx,
        tx_end=context.tx_end,
    )
    baseline_signature = _collect_journal_backed_surface_signature(
        baseline_store,
        context=context,
    )
    baseline_permutation_signature = _permutation_invariant_signature(
        baseline_signature
    )
    baseline_conflict_signatures = baseline_signature[0]
    assert _stream_conflict_signatures(baseline_stream) == baseline_conflict_signatures
    assert (
        _stream_conflict_signatures(baseline_store.merge_conflict_journal())
        == baseline_conflict_signatures
    )
    _assert_restore_parity(
        baseline_store,
        context=context,
        expected_signature=baseline_signature,
    )

    permutation_orders = tuple(itertools.permutations(context.replicas_by_tx))
    assert len(permutation_orders) == 24

    for order in permutation_orders:
        ordered_replicas = tuple(order)

        unsplit_store, unsplit_stream = _replay_replicas_with_journal(
            ordered_replicas,
            tx_end=context.tx_end,
        )
        assert _stream_conflict_signatures(unsplit_stream) == baseline_conflict_signatures
        assert (
            _stream_conflict_signatures(unsplit_store.merge_conflict_journal())
            == baseline_conflict_signatures
        )
        unsplit_signature = _collect_journal_backed_surface_signature(
            unsplit_store,
            context=context,
        )
        assert (
            _permutation_invariant_signature(unsplit_signature)
            == baseline_permutation_signature
        )
        _assert_restore_parity(
            unsplit_store,
            context=context,
            expected_signature=unsplit_signature,
        )

        segmented_store, segmented_stream = _replay_replicas_with_journal(
            ordered_replicas,
            tx_end=context.tx_end,
            boundaries=(1, 3),
        )
        assert _stream_conflict_signatures(segmented_stream) == baseline_conflict_signatures
        assert (
            _stream_conflict_signatures(segmented_store.merge_conflict_journal())
            == baseline_conflict_signatures
        )
        segmented_signature = _collect_journal_backed_surface_signature(
            segmented_store,
            context=context,
        )
        assert segmented_signature == unsplit_signature
        assert (
            _permutation_invariant_signature(segmented_signature)
            == baseline_permutation_signature
        )
        _assert_restore_parity(
            segmented_store,
            context=context,
            expected_signature=segmented_signature,
        )


def test_store_snapshot_merge_conflict_journal_replay_restart_invariant_for_segmented_duplicate_and_restarts(
    tmp_path: Path,
) -> None:
    context = _build_context(tx_base=11310)

    unsplit_store, unsplit_stream = _replay_replicas_with_journal(
        context.replicas_by_tx,
        tx_end=context.tx_end,
    )
    unsplit_signature = _collect_journal_backed_surface_signature(
        unsplit_store,
        context=context,
    )
    unsplit_conflict_signatures = unsplit_signature[0]

    segmented_store, segmented_stream = _replay_replicas_with_journal(
        context.replicas_by_tx,
        tx_end=context.tx_end,
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
        not merge_result.conflicts for _tx_id, merge_result in resumed_duplicate_stream
    )

    duplicate_history_stream = unsplit_stream + duplicate_stream
    resumed_duplicate_history_stream = unsplit_stream + resumed_duplicate_stream

    assert _stream_conflict_signatures(unsplit_stream) == unsplit_conflict_signatures
    assert _stream_conflict_signatures(segmented_stream) == unsplit_conflict_signatures
    assert (
        _stream_conflict_signatures(duplicate_history_stream)
        == unsplit_conflict_signatures
    )
    assert (
        _stream_conflict_signatures(resumed_duplicate_history_stream)
        == unsplit_conflict_signatures
    )
    assert (
        _stream_conflict_signatures(segmented_store.merge_conflict_journal())
        == unsplit_conflict_signatures
    )
    assert (
        _stream_conflict_signatures(duplicate_store.merge_conflict_journal())
        == unsplit_conflict_signatures
    )
    assert (
        _stream_conflict_signatures(resumed_duplicate_store.merge_conflict_journal())
        == unsplit_conflict_signatures
    )

    replay_variants = (
        ("unsplit", unsplit_store),
        ("segmented", segmented_store),
        ("duplicate", duplicate_store),
        ("resumed-duplicate", resumed_duplicate_store),
    )

    for variant_name, replay_store in replay_variants:
        assert (
            _collect_journal_backed_surface_signature(
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
            / f"surface-parity-merge-conflict-journal-{variant_name}.snapshot.canonical.json",
        )

        restarted_store = _apply_restart_cycles(
            replay_store,
            restart_cycles=3,
            snapshot_path=tmp_path
            / f"surface-parity-merge-conflict-journal-{variant_name}.restart.canonical.json",
        )
        assert (
            _collect_journal_backed_surface_signature(
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
            / f"surface-parity-merge-conflict-journal-{variant_name}.post-restart.canonical.json",
        )
