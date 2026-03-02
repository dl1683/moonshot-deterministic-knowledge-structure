from datetime import datetime, timezone

import pytest

import dks.core as core_module
from dks import ClaimCore, KnowledgeStore, Provenance, TransactionTime, ValidTime


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _windows_lock_permission_error() -> PermissionError:
    error = PermissionError("simulated persistent lock contention")
    error.winerror = 32
    return error


def _build_store_snapshot_fixture() -> KnowledgeStore:
    valid_time = ValidTime(start=dt(2024, 1, 1), end=None)
    store = KnowledgeStore()
    store.assert_revision(
        core=ClaimCore(claim_type="fact", slots={"id": "lock-failure-fixture"}),
        assertion="fixture revision",
        valid_time=valid_time,
        transaction_time=TransactionTime(tx_id=1, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_lock_failure_fixture"),
        confidence_bp=9000,
        status="asserted",
    )
    return store


def test_store_snapshot_file_io_fails_closed_after_lock_retry_exhaustion(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store_snapshot_fixture()
    snapshot_path = tmp_path / "snapshot.canonical.json"
    snapshot_path.write_text("existing-snapshot-content", encoding="utf-8")

    replace_call_count = 0
    retry_delays: list[float] = []

    def always_locked_replace(source, target) -> None:
        del source, target
        nonlocal replace_call_count
        replace_call_count += 1
        raise _windows_lock_permission_error()

    monkeypatch.setattr(core_module.os, "replace", always_locked_replace)
    monkeypatch.setattr(core_module.time, "sleep", retry_delays.append)

    with pytest.raises(PermissionError) as excinfo:
        store.to_canonical_json_file(snapshot_path)

    assert getattr(excinfo.value, "winerror", None) == 32
    assert replace_call_count == core_module._CANONICAL_JSON_FILE_REPLACE_MAX_ATTEMPTS

    expected_retry_delays = [
        core_module._CANONICAL_JSON_FILE_REPLACE_RETRY_BASE_DELAY_SECONDS * (2**attempt)
        for attempt in range(core_module._CANONICAL_JSON_FILE_REPLACE_MAX_ATTEMPTS - 1)
    ]
    assert retry_delays == expected_retry_delays

    assert snapshot_path.read_text(encoding="utf-8") == "existing-snapshot-content"
    assert list(tmp_path.glob(f".{snapshot_path.name}.*.tmp")) == []


def test_store_snapshot_file_io_cleanup_errors_do_not_mask_primary_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store_snapshot_fixture()
    snapshot_path = tmp_path / "snapshot.canonical.json"
    snapshot_path.write_text("existing-snapshot-content", encoding="utf-8")

    primary_error = PermissionError("simulated replace failure")
    primary_error.winerror = 5

    def always_failing_replace(source, target) -> None:
        del source, target
        raise primary_error

    def cleanup_unlink_failure(self, missing_ok=False) -> None:
        del self, missing_ok
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(core_module.os, "replace", always_failing_replace)
    monkeypatch.setattr(core_module.Path, "unlink", cleanup_unlink_failure)

    with pytest.raises(PermissionError) as excinfo:
        store.to_canonical_json_file(snapshot_path)

    assert excinfo.value is primary_error
    notes = getattr(excinfo.value, "__notes__", ())
    assert any("temporary snapshot cleanup failed" in note for note in notes)
    assert any("simulated cleanup failure" in note for note in notes)
    assert snapshot_path.read_text(encoding="utf-8") == "existing-snapshot-content"
