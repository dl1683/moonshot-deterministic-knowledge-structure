from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import functools
import hashlib
import itertools
import json
import os
from pathlib import Path
import unicodedata
import tempfile
import time
from typing import Any, Callable, Dict, Iterable, Literal, Mapping, Optional, TypeVar


RELATION_TYPES = {"supports", "contradicts", "depends_on", "derived_from"}
RelationPayloadKey = tuple[str, str, str, int, str]
ConflictSignature = tuple[str, str, str]
ConflictSignatureCount = tuple[str, str, str, int]
ConflictCodeCount = tuple[str, int]
ConflictSummary = tuple[tuple[ConflictSignatureCount, ...], tuple[ConflictCodeCount, ...]]
RelationStateSignature = tuple[str, str, str, str, str, int, str]
RevisionStateSignature = tuple[str, str, str, str, str, int, str]
ProjectionChunk = TypeVar("ProjectionChunk", bound=tuple[Any, ...])
ParsedPayloadItem = TypeVar("ParsedPayloadItem")
_STATE_FINGERPRINT_MISSING_REVISION_ID = "__dks_state_fingerprint_no_winner__"
_WINDOWS_LOCK_PERMISSION_WINERRORS = frozenset({32, 33})
_CANONICAL_JSON_FILE_REPLACE_MAX_ATTEMPTS = 8
_CANONICAL_JSON_FILE_REPLACE_RETRY_BASE_DELAY_SECONDS = 0.005


_ZERO_WIDTH_CODEPOINTS = frozenset(
    "\u200b"  # zero-width space
    "\u200c"  # zero-width non-joiner
    "\u200d"  # zero-width joiner
    "\u200e"  # left-to-right mark
    "\u200f"  # right-to-left mark
    "\u202a"  # left-to-right embedding
    "\u202b"  # right-to-left embedding
    "\u202c"  # pop directional formatting
    "\u202d"  # left-to-right override
    "\u202e"  # right-to-left override
    "\u2060"  # word joiner
    "\u2061"  # function application
    "\u2062"  # invisible times
    "\u2063"  # invisible separator
    "\u2064"  # invisible plus
    "\ufeff"  # byte order mark / zero-width no-break space
    "\ufff9"  # interlinear annotation anchor
    "\ufffa"  # interlinear annotation separator
    "\ufffb"  # interlinear annotation terminator
)


def canonicalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = "".join(ch for ch in value if ch not in _ZERO_WIDTH_CODEPOINTS)
    return " ".join(value.strip().lower().split())


def _canonicalize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return canonicalize_text(value)
    if isinstance(value, Mapping):
        return {
            canonicalize_text(str(k)): _canonicalize_json_value(v)
            for k, v in sorted(
                value.items(), key=lambda kv: canonicalize_text(str(kv[0]))
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json_value(v) for v in value]
    if isinstance(value, set):
        normalized = [_canonicalize_json_value(v) for v in value]
        return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True))
    return value


def _stable_payload_hash(namespace: str, payload: Mapping[str, Any]) -> str:
    canonical_payload = _canonicalize_json_value(payload)
    blob = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{namespace}:{blob}".encode("utf-8")).hexdigest()
    return digest


def _canonical_json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _knowledge_store_snapshot_checksum(
    payload_without_checksum: Mapping[str, Any],
) -> str:
    canonical_json = _canonical_json_text(payload_without_checksum)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _knowledge_store_canonical_content_digest(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _is_windows_lock_permission_error(error: BaseException) -> bool:
    return (
        isinstance(error, PermissionError)
        and getattr(error, "winerror", None) in _WINDOWS_LOCK_PERMISSION_WINERRORS
    )


def _replace_file_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_CANONICAL_JSON_FILE_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            is_last_attempt = attempt >= _CANONICAL_JSON_FILE_REPLACE_MAX_ATTEMPTS - 1
            if not _is_windows_lock_permission_error(error) or is_last_attempt:
                raise
            time.sleep(
                _CANONICAL_JSON_FILE_REPLACE_RETRY_BASE_DELAY_SECONDS * (2**attempt)
            )


def _json_compatible_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_compatible_value(item) for item in value]
    if isinstance(value, list):
        return [_json_compatible_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_compatible_value(item)
            for key, item in value.items()
        }
    return value


class SnapshotValidationError(ValueError):
    CODE_SCHEMA_VERSION = "schema_version"
    CODE_STRICT_KEY_SET = "strict_key_set"
    CODE_MALFORMED_TYPE = "malformed_type"
    CODE_INVALID_JSON = "invalid_json"
    CODE_INVALID_ENCODING = "invalid_encoding"
    CODE_NON_CANONICAL = "non_canonical"
    CODE_VALIDATION_FAILED = "validation_failed"

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")

    @classmethod
    def _classify_code(cls, path: str, message: str) -> str:
        if (
            path == "payload.snapshot_schema_version"
            or "unsupported snapshot schema version" in message
            or "snapshot_schema_version" in message
        ):
            return cls.CODE_SCHEMA_VERSION
        if (
            message.startswith("missing keys ")
            or message.startswith("unexpected keys ")
            or "missing relation_id entries " in message
            or "unexpected relation_id entries " in message
        ):
            return cls.CODE_STRICT_KEY_SET
        if message.startswith("expected "):
            return cls.CODE_MALFORMED_TYPE
        if message.startswith("invalid JSON"):
            return cls.CODE_INVALID_JSON
        if message.startswith("invalid UTF-8"):
            return cls.CODE_INVALID_ENCODING
        if "does not match canonical deterministic knowledge store" in message:
            return cls.CODE_NON_CANONICAL
        return cls.CODE_VALIDATION_FAILED

    @classmethod
    def from_value_error(cls, error: ValueError) -> "SnapshotValidationError":
        if isinstance(error, SnapshotValidationError):
            return error
        raw_message = str(error)
        if ": " in raw_message:
            path, message = raw_message.split(": ", 1)
        else:
            path = "payload"
            message = raw_message
        return cls(
            code=cls._classify_code(path, message),
            path=path,
            message=message,
        )

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class SnapshotValidationReport:
    schema_version: int
    snapshot_checksum: str
    canonical_content_digest: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_checksum": self.snapshot_checksum,
            "canonical_content_digest": self.canonical_content_digest,
        }


def _payload_validation_error(path: str, message: str) -> ValueError:
    return ValueError(f"{path}: {message}")


ParsedReturn = TypeVar("ParsedReturn")


def _route_snapshot_validation_error(
    method: Callable[..., ParsedReturn],
) -> Callable[..., ParsedReturn]:
    @functools.wraps(method)
    def _wrapped(*args: Any, **kwargs: Any) -> ParsedReturn:
        try:
            return method(*args, **kwargs)
        except ValueError as error:
            if isinstance(error, SnapshotValidationError):
                raise
            raise SnapshotValidationError.from_value_error(error) from error

    return _wrapped


def _expect_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _payload_validation_error(
            path, f"expected object, got {type(value).__name__}"
        )
    return value


def _expect_exact_keys(
    payload: Mapping[str, Any],
    path: str,
    expected_keys: tuple[str, ...],
) -> None:
    expected = set(expected_keys)
    actual = set(payload.keys())
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if not missing and not unexpected:
        return
    parts: list[str] = []
    if missing:
        parts.append(f"missing keys {missing}")
    if unexpected:
        parts.append(f"unexpected keys {unexpected}")
    raise _payload_validation_error(path, ", ".join(parts))


def _expect_exact_dynamic_key_set(
    *,
    observed_keys: Iterable[str],
    expected_keys: Iterable[str],
    path: str,
    key_label: str,
) -> None:
    observed = set(observed_keys)
    expected = set(expected_keys)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if not missing and not unexpected:
        return
    parts: list[str] = []
    if missing:
        parts.append(f"missing {key_label} entries {missing}")
    if unexpected:
        parts.append(f"unexpected {key_label} entries {unexpected}")
    raise _payload_validation_error(path, ", ".join(parts))


def _expect_str(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise _payload_validation_error(
            path, f"expected string, got {type(value).__name__}"
        )
    return value


def _expect_optional_str(value: Any, path: str) -> Optional[str]:
    if value is None:
        return None
    return _expect_str(value, path)


def _expect_int(value: Any, path: str, *, min_value: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _payload_validation_error(
            path, f"expected integer, got {type(value).__name__}"
        )
    if min_value is not None and value < min_value:
        raise _payload_validation_error(path, f"must be greater than or equal to {min_value}")
    return value


def _expect_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _payload_validation_error(path, f"expected array, got {type(value).__name__}")
    return value


def _expect_sha256_hexdigest(value: Any, path: str) -> str:
    digest = _expect_str(value, path)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise _payload_validation_error(path, "expected 64-char lowercase hex digest")
    return digest


def _parse_iso8601_datetime(value: Any, path: str) -> datetime:
    timestamp = _expect_str(value, path)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise _payload_validation_error(path, f"invalid ISO-8601 datetime {timestamp!r}") from exc
    return _to_utc(parsed)


def _parse_payload_array(
    value: Any,
    path: str,
    item_parser: Callable[[Any, str], ParsedPayloadItem],
) -> tuple[ParsedPayloadItem, ...]:
    items = _expect_list(value, path)
    return tuple(item_parser(item, f"{path}[{index}]") for index, item in enumerate(items))


def _valid_time_from_payload(value: Any, path: str) -> ValidTime:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("start", "end"))
    start = _parse_iso8601_datetime(payload["start"], f"{path}.start")
    end_raw = payload["end"]
    end = (
        _parse_iso8601_datetime(end_raw, f"{path}.end")
        if end_raw is not None
        else None
    )
    try:
        return ValidTime(start=start, end=end)
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc


def _transaction_time_from_payload(value: Any, path: str) -> TransactionTime:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("tx_id", "recorded_at"))
    tx_id = _expect_int(payload["tx_id"], f"{path}.tx_id", min_value=0)
    recorded_at = _parse_iso8601_datetime(payload["recorded_at"], f"{path}.recorded_at")
    try:
        return TransactionTime(tx_id=tx_id, recorded_at=recorded_at)
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc


def _provenance_from_payload(value: Any, path: str) -> Provenance:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("source", "evidence_ref"))
    source = _expect_str(payload["source"], f"{path}.source")
    evidence_ref = _expect_optional_str(payload["evidence_ref"], f"{path}.evidence_ref")
    return Provenance(source=source, evidence_ref=evidence_ref)


def _claim_core_from_payload(value: Any, path: str) -> ClaimCore:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("core_id", "claim_type", "slots"))
    core_id = _expect_sha256_hexdigest(payload["core_id"], f"{path}.core_id")
    claim_type = _expect_str(payload["claim_type"], f"{path}.claim_type")
    slots_payload = _expect_mapping(payload["slots"], f"{path}.slots")
    slots: Dict[str, str] = {}
    for slot_index, (slot_key, slot_value) in enumerate(
        sorted(slots_payload.items(), key=lambda item: str(item[0]))
    ):
        slot_path = f"{path}.slots[{slot_index}]"
        if not isinstance(slot_key, str):
            raise _payload_validation_error(
                f"{slot_path}.key",
                f"expected string, got {type(slot_key).__name__}",
            )
        slots[slot_key] = _expect_str(slot_value, f"{slot_path}.value")

    try:
        core = ClaimCore(claim_type=claim_type, slots=slots)
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc

    if core.core_id != core_id:
        raise _payload_validation_error(
            f"{path}.core_id",
            f"mismatch; expected {core.core_id}, got {core_id}",
        )
    return core


def _claim_revision_from_payload(value: Any, path: str) -> ClaimRevision:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        path,
        (
            "revision_id",
            "core_id",
            "assertion",
            "valid_time",
            "transaction_time",
            "provenance",
            "confidence_bp",
            "status",
        ),
    )
    revision_id = _expect_sha256_hexdigest(payload["revision_id"], f"{path}.revision_id")
    core_id = _expect_sha256_hexdigest(payload["core_id"], f"{path}.core_id")
    assertion = _expect_str(payload["assertion"], f"{path}.assertion")
    valid_time = _valid_time_from_payload(payload["valid_time"], f"{path}.valid_time")
    transaction_time = _transaction_time_from_payload(
        payload["transaction_time"], f"{path}.transaction_time"
    )
    provenance = _provenance_from_payload(payload["provenance"], f"{path}.provenance")
    confidence_bp = _expect_int(payload["confidence_bp"], f"{path}.confidence_bp", min_value=0)
    status = _expect_str(payload["status"], f"{path}.status")

    try:
        revision = ClaimRevision(
            core_id=core_id,
            assertion=assertion,
            valid_time=valid_time,
            transaction_time=transaction_time,
            provenance=provenance,
            confidence_bp=confidence_bp,
            status=status,
        )
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc

    if revision.revision_id != revision_id:
        raise _payload_validation_error(
            f"{path}.revision_id",
            f"mismatch; expected {revision.revision_id}, got {revision_id}",
        )
    return revision


def _relation_edge_from_payload(value: Any, path: str) -> RelationEdge:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        path,
        (
            "relation_id",
            "relation_type",
            "from_revision_id",
            "to_revision_id",
            "transaction_time",
        ),
    )
    relation_id = _expect_sha256_hexdigest(payload["relation_id"], f"{path}.relation_id")
    relation_type = _expect_str(payload["relation_type"], f"{path}.relation_type")
    from_revision_id = _expect_sha256_hexdigest(
        payload["from_revision_id"], f"{path}.from_revision_id"
    )
    to_revision_id = _expect_str(payload["to_revision_id"], f"{path}.to_revision_id")
    transaction_time = _transaction_time_from_payload(
        payload["transaction_time"], f"{path}.transaction_time"
    )

    try:
        relation = RelationEdge(
            relation_type=relation_type,
            from_revision_id=from_revision_id,
            to_revision_id=to_revision_id,
            transaction_time=transaction_time,
        )
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc

    if relation.relation_id != relation_id:
        raise _payload_validation_error(
            f"{path}.relation_id",
            f"mismatch; expected {relation.relation_id}, got {relation_id}",
        )
    return relation


def _relation_edge_from_store_snapshot_payload(
    value: Any,
    path: str,
) -> RelationEdge:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        path,
        (
            "relation_id",
            "relation_type",
            "from_revision_id",
            "to_revision_id",
            "transaction_time",
        ),
    )
    relation_id = _expect_sha256_hexdigest(payload["relation_id"], f"{path}.relation_id")
    relation_type = _expect_str(payload["relation_type"], f"{path}.relation_type")
    from_revision_id = _expect_sha256_hexdigest(
        payload["from_revision_id"], f"{path}.from_revision_id"
    )
    to_revision_id = _expect_str(payload["to_revision_id"], f"{path}.to_revision_id")
    transaction_time = _transaction_time_from_payload(
        payload["transaction_time"], f"{path}.transaction_time"
    )

    try:
        relation = RelationEdge(
            relation_type=relation_type,
            from_revision_id=from_revision_id,
            to_revision_id=to_revision_id,
            transaction_time=transaction_time,
        )
    except ValueError as exc:
        raise _payload_validation_error(path, str(exc)) from exc

    # Snapshot payloads must be able to restore historical forced ids exactly,
    # including collision-tracking variants where relation_id was intentionally
    # set to a canonical competing id.
    if relation.relation_id != relation_id:
        object.__setattr__(relation, "relation_id", relation_id)
    return relation


def _relation_payload_key_from_payload(
    value: Any,
    path: str,
) -> RelationPayloadKey:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        path,
        ("relation_type", "from_revision_id", "to_revision_id", "tx_id", "recorded_at"),
    )
    relation_type = canonicalize_text(_expect_str(payload["relation_type"], f"{path}.relation_type"))
    if relation_type not in RELATION_TYPES:
        raise _payload_validation_error(
            f"{path}.relation_type",
            f"unsupported relation_type {payload['relation_type']!r}",
        )
    from_revision_id = _expect_sha256_hexdigest(
        payload["from_revision_id"],
        f"{path}.from_revision_id",
    )
    to_revision_id = _expect_str(payload["to_revision_id"], f"{path}.to_revision_id")
    tx_id = _expect_int(payload["tx_id"], f"{path}.tx_id", min_value=0)
    recorded_at = _parse_iso8601_datetime(payload["recorded_at"], f"{path}.recorded_at")
    return (
        relation_type,
        from_revision_id,
        to_revision_id,
        tx_id,
        recorded_at.isoformat(),
    )


def _relation_payload_key_as_payload(
    relation_key: RelationPayloadKey,
) -> Dict[str, Any]:
    return {
        "relation_type": relation_key[0],
        "from_revision_id": relation_key[1],
        "to_revision_id": relation_key[2],
        "tx_id": relation_key[3],
        "recorded_at": relation_key[4],
    }


def _relation_collision_pair_from_payload(
    value: Any,
    path: str,
) -> tuple[RelationPayloadKey, RelationPayloadKey]:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("left", "right"))
    return (
        _relation_payload_key_from_payload(payload["left"], f"{path}.left"),
        _relation_payload_key_from_payload(payload["right"], f"{path}.right"),
    )


def _relation_collision_pair_as_payload(
    pair_key: tuple[RelationPayloadKey, RelationPayloadKey],
) -> Dict[str, Any]:
    return {
        "left": _relation_payload_key_as_payload(pair_key[0]),
        "right": _relation_payload_key_as_payload(pair_key[1]),
    }


def _relation_state_signature_from_payload(
    value: Any,
    path: str,
) -> RelationStateSignature:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(
        payload,
        path,
        (
            "bucket",
            "relation_id",
            "relation_type",
            "from_revision_id",
            "to_revision_id",
            "tx_id",
            "recorded_at",
        ),
    )
    bucket = _expect_str(payload["bucket"], f"{path}.bucket")
    if bucket not in {"active", "pending"}:
        raise _payload_validation_error(
            f"{path}.bucket", f"expected 'active' or 'pending', got {bucket!r}"
        )
    relation_id = _expect_sha256_hexdigest(payload["relation_id"], f"{path}.relation_id")
    relation_type = canonicalize_text(_expect_str(payload["relation_type"], f"{path}.relation_type"))
    if relation_type not in RELATION_TYPES:
        raise _payload_validation_error(
            f"{path}.relation_type",
            f"unsupported relation_type {payload['relation_type']!r}",
        )
    from_revision_id = _expect_sha256_hexdigest(
        payload["from_revision_id"], f"{path}.from_revision_id"
    )
    to_revision_id = _expect_str(payload["to_revision_id"], f"{path}.to_revision_id")
    tx_id = _expect_int(payload["tx_id"], f"{path}.tx_id", min_value=0)
    recorded_at = _parse_iso8601_datetime(payload["recorded_at"], f"{path}.recorded_at")
    return (
        bucket,
        relation_id,
        relation_type,
        from_revision_id,
        to_revision_id,
        tx_id,
        recorded_at.isoformat(),
    )


def _conflict_signature_count_from_payload(
    value: Any,
    path: str,
) -> ConflictSignatureCount:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("code", "entity_id", "details", "count"))
    code = _expect_str(payload["code"], f"{path}.code")
    entity_id = _expect_str(payload["entity_id"], f"{path}.entity_id")
    details = _expect_str(payload["details"], f"{path}.details")
    count = _expect_int(payload["count"], f"{path}.count", min_value=0)
    return (code, entity_id, details, count)


def _conflict_code_count_from_payload(
    value: Any,
    path: str,
) -> ConflictCodeCount:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("code", "count"))
    code = _expect_str(payload["code"], f"{path}.code")
    count = _expect_int(payload["count"], f"{path}.count", min_value=0)
    return (code, count)


def _merge_conflict_from_payload(value: Any, path: str) -> MergeConflict:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("code", "entity_id", "details"))
    code_text = _expect_str(payload["code"], f"{path}.code")
    entity_id = _expect_str(payload["entity_id"], f"{path}.entity_id")
    details = _expect_str(payload["details"], f"{path}.details")
    try:
        code = ConflictCode(code_text)
    except ValueError as exc:
        raise _payload_validation_error(
            f"{path}.code",
            f"unsupported conflict code {code_text!r}",
        ) from exc
    return MergeConflict(code=code, entity_id=entity_id, details=details)


def _merge_result_from_store_snapshot_payload(
    value: Any,
    path: str,
) -> MergeResult:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("conflicts",))
    conflicts_payload = _expect_list(payload["conflicts"], f"{path}.conflicts")
    conflicts = tuple(
        _merge_conflict_from_payload(conflict, f"{path}.conflicts[{index}]")
        for index, conflict in enumerate(conflicts_payload)
    )
    return MergeResult(merged=KnowledgeStore(), conflicts=conflicts)


def _merge_result_by_tx_from_store_snapshot_payload(
    value: Any,
    path: str,
) -> tuple[int, MergeResult]:
    payload = _expect_mapping(value, path)
    _expect_exact_keys(payload, path, ("tx_id", "merge_result"))
    tx_id = _expect_int(payload["tx_id"], f"{path}.tx_id", min_value=0)
    merge_result = _merge_result_from_store_snapshot_payload(
        payload["merge_result"],
        f"{path}.merge_result",
    )
    return (tx_id, merge_result)


def _relation_state_signature_as_payload(
    signature: RelationStateSignature,
) -> Dict[str, Any]:
    return {
        "bucket": signature[0],
        "relation_id": signature[1],
        "relation_type": signature[2],
        "from_revision_id": signature[3],
        "to_revision_id": signature[4],
        "tx_id": signature[5],
        "recorded_at": signature[6],
    }


def _conflict_signature_count_as_payload(
    signature_count: ConflictSignatureCount,
) -> Dict[str, Any]:
    return {
        "code": signature_count[0],
        "entity_id": signature_count[1],
        "details": signature_count[2],
        "count": signature_count[3],
    }


def _conflict_code_count_as_payload(code_count: ConflictCodeCount) -> Dict[str, Any]:
    return {
        "code": code_count[0],
        "count": code_count[1],
    }


def _merge_conflict_as_payload(conflict: MergeConflict) -> Dict[str, Any]:
    return {
        "code": conflict.code.value,
        "entity_id": conflict.entity_id,
        "details": conflict.details,
    }


def _merge_result_as_store_snapshot_payload(
    merge_result: MergeResult,
) -> Dict[str, Any]:
    return {
        "conflicts": [
            _merge_conflict_as_payload(conflict)
            for conflict in merge_result.conflicts
        ]
    }


def _merge_result_by_tx_as_store_snapshot_payload(
    merge_result_by_tx: tuple[int, MergeResult],
) -> Dict[str, Any]:
    tx_id, merge_result = merge_result_by_tx
    return {
        "tx_id": tx_id,
        "merge_result": _merge_result_as_store_snapshot_payload(merge_result),
    }


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ValidTime:
    start: datetime
    end: Optional[datetime] = None

    def __post_init__(self) -> None:
        start_utc = _to_utc(self.start)
        end_utc = _to_utc(self.end) if self.end is not None else None
        if end_utc is not None and end_utc <= start_utc:
            raise ValueError("valid_time.end must be greater than valid_time.start")
        object.__setattr__(self, "start", start_utc)
        object.__setattr__(self, "end", end_utc)

    def contains(self, at: datetime) -> bool:
        point = _to_utc(at)
        if point < self.start:
            return False
        if self.end is not None and point >= self.end:
            return False
        return True

    def as_payload(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end is not None else None,
        }


@dataclass(frozen=True)
class TransactionTime:
    tx_id: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.tx_id < 0:
            raise ValueError("transaction_time.tx_id must be non-negative")
        object.__setattr__(self, "recorded_at", _to_utc(self.recorded_at))

    def as_payload(self) -> Dict[str, Any]:
        return {"tx_id": self.tx_id, "recorded_at": self.recorded_at.isoformat()}


@dataclass(frozen=True)
class Provenance:
    source: str
    evidence_ref: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", canonicalize_text(self.source))
        if self.evidence_ref is not None:
            object.__setattr__(self, "evidence_ref", canonicalize_text(self.evidence_ref))

    def as_payload(self) -> Dict[str, Any]:
        return {"source": self.source, "evidence_ref": self.evidence_ref}


@dataclass(frozen=True)
class ClaimCore:
    claim_type: str
    slots: Mapping[str, str]
    core_id: str = field(init=False)

    def __post_init__(self) -> None:
        canonical_claim_type = canonicalize_text(self.claim_type)
        canonical_slots: Dict[str, str] = {}
        for key, value in sorted(
            self.slots.items(), key=lambda kv: canonicalize_text(str(kv[0]))
        ):
            canonical_key = canonicalize_text(str(key))
            canonical_value = canonicalize_text(str(value))
            if canonical_key in canonical_slots and canonical_slots[canonical_key] != canonical_value:
                raise ValueError(f"duplicate canonical slot key with different values: {canonical_key}")
            canonical_slots[canonical_key] = canonical_value

        object.__setattr__(self, "claim_type", canonical_claim_type)
        object.__setattr__(self, "slots", canonical_slots)
        object.__setattr__(
            self,
            "core_id",
            _stable_payload_hash(
                "claim_core",
                {"claim_type": canonical_claim_type, "slots": canonical_slots},
            ),
        )

    def as_payload(self) -> Dict[str, Any]:
        return {
            "core_id": self.core_id,
            "claim_type": self.claim_type,
            "slots": dict(self.slots),
        }


@dataclass(frozen=True)
class ClaimRevision:
    core_id: str
    assertion: str
    valid_time: ValidTime
    transaction_time: TransactionTime
    provenance: Provenance
    confidence_bp: int
    status: Literal["asserted", "retracted"] = "asserted"
    revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        canonical_assertion = canonicalize_text(self.assertion)
        canonical_status = canonicalize_text(self.status)

        if canonical_status not in {"asserted", "retracted"}:
            raise ValueError("status must be 'asserted' or 'retracted'")
        if not 0 <= self.confidence_bp <= 10000:
            raise ValueError("confidence_bp must be between 0 and 10000")

        object.__setattr__(self, "assertion", canonical_assertion)
        object.__setattr__(self, "status", canonical_status)

        revision_payload = {
            "core_id": self.core_id,
            "assertion": canonical_assertion,
            "valid_time": self.valid_time.as_payload(),
            "transaction_time": self.transaction_time.as_payload(),
            "provenance": self.provenance.as_payload(),
            "confidence_bp": self.confidence_bp,
            "status": canonical_status,
        }
        object.__setattr__(
            self,
            "revision_id",
            _stable_payload_hash("claim_revision", revision_payload),
        )

    def as_payload(self) -> Dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "core_id": self.core_id,
            "assertion": self.assertion,
            "valid_time": self.valid_time.as_payload(),
            "transaction_time": self.transaction_time.as_payload(),
            "provenance": self.provenance.as_payload(),
            "confidence_bp": self.confidence_bp,
            "status": self.status,
        }


@dataclass(frozen=True)
class RelationEdge:
    relation_type: str
    from_revision_id: str
    to_revision_id: str
    transaction_time: TransactionTime
    relation_id: str = field(init=False)

    def __post_init__(self) -> None:
        relation_type = canonicalize_text(self.relation_type)
        if relation_type not in RELATION_TYPES:
            raise ValueError(f"unsupported relation_type: {self.relation_type}")

        from_id = self.from_revision_id
        to_id = self.to_revision_id
        if relation_type == "contradicts" and from_id > to_id:
            from_id, to_id = to_id, from_id

        object.__setattr__(self, "relation_type", relation_type)
        object.__setattr__(self, "from_revision_id", from_id)
        object.__setattr__(self, "to_revision_id", to_id)

        relation_payload = {
            "relation_type": relation_type,
            "from_revision_id": from_id,
            "to_revision_id": to_id,
            "transaction_time": self.transaction_time.as_payload(),
        }
        object.__setattr__(
            self,
            "relation_id",
            _stable_payload_hash("relation_edge", relation_payload),
        )

    def as_payload(self) -> Dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "from_revision_id": self.from_revision_id,
            "to_revision_id": self.to_revision_id,
            "transaction_time": self.transaction_time.as_payload(),
        }


class ConflictCode(str, Enum):
    CORE_ID_COLLISION = "core_id_collision"
    REVISION_ID_COLLISION = "revision_id_collision"
    RELATION_ID_COLLISION = "relation_id_collision"
    COMPETING_REVISION_SAME_SLOT = "competing_revision_same_slot"
    COMPETING_LIFECYCLE_SAME_SLOT = "competing_lifecycle_same_slot"
    ORPHAN_RELATION_ENDPOINT = "orphan_relation_endpoint"


@dataclass(frozen=True)
class MergeConflict:
    code: ConflictCode
    entity_id: str
    details: str

    def signature(self) -> ConflictSignature:
        return (self.code.value, self.entity_id, self.details)


@dataclass(frozen=True)
class MergeResult:
    merged: "KnowledgeStore"
    conflicts: tuple[MergeConflict, ...]

    def conflict_signatures(self) -> tuple[ConflictSignature, ...]:
        return KnowledgeStore.conflict_signatures(self.conflicts)

    def conflict_signature_counts(self) -> tuple[ConflictSignatureCount, ...]:
        return KnowledgeStore.conflict_signature_counts(self.conflicts)

    def conflict_code_counts(self) -> tuple[ConflictCodeCount, ...]:
        return KnowledgeStore.conflict_code_counts(self.conflicts)

    def conflict_summary(self) -> ConflictSummary:
        return KnowledgeStore.conflict_summary(self.conflicts)

    @staticmethod
    def combine_conflict_signature_counts(
        left: tuple[ConflictSignatureCount, ...],
        right: tuple[ConflictSignatureCount, ...],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult._compose_conflict_projection_pair_with_chunks(
            left,
            right,
            MergeResult.combine_conflict_signature_counts_from_chunks,
        )

    @staticmethod
    def combine_conflict_signature_counts_from_chunks(
        signature_count_chunks: Iterable[tuple[ConflictSignatureCount, ...]],
    ) -> tuple[ConflictSignatureCount, ...]:
        counts_by_signature: Dict[ConflictSignature, int] = {}
        for signature_count_chunk in MergeResult._iter_conflict_projection_composition_chunks(
            signature_count_chunks
        ):
            for code, entity_id, details, count in signature_count_chunk:
                signature = (code, entity_id, details)
                counts_by_signature[signature] = (
                    counts_by_signature.get(signature, 0) + count
                )
        return tuple(
            sorted(
                (
                    (
                        signature[0],
                        signature[1],
                        signature[2],
                        count,
                    )
                    for signature, count in counts_by_signature.items()
                ),
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )

    @staticmethod
    def combine_conflict_code_counts(
        left: tuple[ConflictCodeCount, ...],
        right: tuple[ConflictCodeCount, ...],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult._compose_conflict_projection_pair_with_chunks(
            left,
            right,
            MergeResult.combine_conflict_code_counts_from_chunks,
        )

    @staticmethod
    def combine_conflict_projection_counts_via_summary_pair(
        left_projection_counts: ConflictSummary,
        right_projection_counts: ConflictSummary,
    ) -> ConflictSummary:
        return MergeResult.combine_conflict_summaries(
            left_projection_counts,
            right_projection_counts,
        )

    @staticmethod
    def extend_conflict_projection_counts_with_precomposed_continuation(
        base_projection_counts: ConflictSummary,
        continuation_projection_counts: ConflictSummary,
    ) -> ConflictSummary:
        base_signature_counts, base_code_counts = base_projection_counts
        continuation_signature_counts, continuation_code_counts = (
            continuation_projection_counts
        )
        return (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_signature_counts,
                continuation_signature_counts,
            ),
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_code_counts,
                continuation_code_counts,
            ),
        )

    @staticmethod
    def extend_conflict_projection_counts_from_summary_chunks(
        base_projection_counts: ConflictSummary,
        summary_chunks: Iterable[ConflictSummary],
    ) -> ConflictSummary:
        signature_summary_chunks, code_summary_chunks = (
            MergeResult._fan_out_conflict_summary_chunks(summary_chunks)
        )
        return MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks(
            base_projection_counts,
            signature_summary_chunks,
            code_summary_chunks,
        )

    @staticmethod
    def _extend_conflict_projection_counts_from_fan_out_component_chunks(
        base_projection_counts: ConflictSummary,
        signature_summary_chunks: Iterable[ConflictSummary],
        code_summary_chunks: Iterable[ConflictSummary],
    ) -> ConflictSummary:
        base_signature_counts, base_code_counts = base_projection_counts
        return (
            MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                base_signature_counts,
                signature_summary_chunks,
            ),
            MergeResult.extend_conflict_code_counts_from_summary_chunks(
                base_code_counts,
                code_summary_chunks,
            ),
        )

    @staticmethod
    def _fan_out_conflict_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> tuple[Iterable[ConflictSummary], Iterable[ConflictSummary]]:
        return itertools.tee(iter(summary_chunks))

    @staticmethod
    def combine_conflict_code_counts_from_chunks(
        code_count_chunks: Iterable[tuple[ConflictCodeCount, ...]],
    ) -> tuple[ConflictCodeCount, ...]:
        counts_by_code: Dict[str, int] = {}
        for code_count_chunk in MergeResult._iter_conflict_projection_composition_chunks(
            code_count_chunks
        ):
            for conflict_code, count in code_count_chunk:
                counts_by_code[conflict_code] = (
                    counts_by_code.get(conflict_code, 0) + count
                )
        return tuple(
            sorted(
                counts_by_code.items(),
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )

    @staticmethod
    def combine_conflict_summaries(
        left: ConflictSummary,
        right: ConflictSummary,
    ) -> ConflictSummary:
        return MergeResult._compose_conflict_summary_pair_with_chunks(left, right)

    @staticmethod
    def _compose_conflict_summary_pair_with_chunks(
        left_summary: ConflictSummary,
        right_summary: ConflictSummary,
    ) -> ConflictSummary:
        return MergeResult._compose_conflict_summary_chunks(
            (left_summary, right_summary),
            MergeResult.stream_conflict_summary_from_chunks,
        )

    @staticmethod
    def combine_conflict_summaries_from_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> ConflictSummary:
        return MergeResult._compose_conflict_summary_chunks(
            summary_chunks,
            MergeResult.stream_conflict_summary_from_chunks,
        )

    @staticmethod
    def extend_conflict_summary(
        base_summary: ConflictSummary,
        merge_results: Iterable["MergeResult"],
    ) -> ConflictSummary:
        return MergeResult.extend_conflict_summary_from_chunks(
            base_summary,
            MergeResult._iter_conflict_summary_chunks(merge_results),
        )

    @staticmethod
    def extend_conflict_summary_from_chunks(
        base_summary: ConflictSummary,
        summary_chunks: Iterable[ConflictSummary],
    ) -> ConflictSummary:
        return MergeResult._extend_conflict_summary_from_chunks_with_precomposed_continuation(
            base_summary,
            summary_chunks,
            MergeResult.stream_conflict_summary_from_chunks,
            MergeResult.extend_conflict_summary_with_precomposed_continuation,
        )

    @staticmethod
    def extend_conflict_summary_with_precomposed_continuation(
        base_summary: ConflictSummary,
        continuation_summary: ConflictSummary,
    ) -> ConflictSummary:
        return MergeResult._extend_conflict_summary_with_precomposed_continuation(
            base_summary,
            continuation_summary,
            MergeResult.combine_conflict_summaries_from_chunks,
        )

    @staticmethod
    def stream_conflict_summary_from_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> ConflictSummary:
        normalized_chunks = MergeResult._iter_nonempty_conflict_summary_chunks(
            summary_chunks
        )
        signature_summary_chunks, code_summary_chunks = itertools.tee(normalized_chunks)
        return (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                signature_summary_chunks
            ),
            MergeResult.stream_conflict_code_counts_from_summary_chunks(
                code_summary_chunks
            ),
        )

    @staticmethod
    def extend_conflict_signature_counts_from_summary_chunks(
        base_signature_counts: tuple[ConflictSignatureCount, ...],
        summary_chunks: Iterable[ConflictSummary],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult._extend_projection_counts_from_summary_chunks_with_precomposed_continuation(
            base_signature_counts,
            summary_chunks,
            0,
            MergeResult.combine_conflict_signature_counts_from_chunks,
        )

    @staticmethod
    def stream_conflict_signature_counts_from_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult._compose_projection_counts_from_summary_chunks(
            summary_chunks,
            0,
            MergeResult.combine_conflict_signature_counts_from_chunks,
        )

    @staticmethod
    def extend_conflict_code_counts_from_summary_chunks(
        base_code_counts: tuple[ConflictCodeCount, ...],
        summary_chunks: Iterable[ConflictSummary],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult._extend_projection_counts_from_summary_chunks_with_precomposed_continuation(
            base_code_counts,
            summary_chunks,
            1,
            MergeResult.combine_conflict_code_counts_from_chunks,
        )

    @staticmethod
    def stream_conflict_code_counts_from_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult._compose_projection_counts_from_summary_chunks(
            summary_chunks,
            1,
            MergeResult.combine_conflict_code_counts_from_chunks,
        )

    @staticmethod
    def extend_conflict_signature_counts(
        base_signature_counts: tuple[ConflictSignatureCount, ...],
        merge_results: Iterable["MergeResult"],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult._extend_projection_counts_from_merge_results_with_precomposed_continuation(
            base_signature_counts,
            merge_results,
            0,
            MergeResult.combine_conflict_signature_counts_from_chunks,
        )

    @staticmethod
    def extend_conflict_signature_counts_from_chunks(
        base_signature_counts: tuple[ConflictSignatureCount, ...],
        signature_count_chunks: Iterable[tuple[ConflictSignatureCount, ...]],
    ) -> tuple[ConflictSignatureCount, ...]:
        continuation_signature_counts = (
            MergeResult.combine_conflict_signature_counts_from_chunks(
                signature_count_chunks
            )
        )
        return MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_signature_counts,
            continuation_signature_counts,
        )

    @staticmethod
    def extend_conflict_signature_counts_with_precomposed_continuation(
        base_signature_counts: tuple[ConflictSignatureCount, ...],
        continuation_signature_counts: tuple[ConflictSignatureCount, ...],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult._extend_projection_counts_with_precomposed_continuation(
            base_signature_counts,
            continuation_signature_counts,
            MergeResult.combine_conflict_signature_counts_from_chunks,
        )

    @staticmethod
    def stream_conflict_signature_counts_from_chunks(
        signature_count_chunks: Iterable[tuple[ConflictSignatureCount, ...]],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult.extend_conflict_signature_counts_from_chunks(
            tuple(),
            signature_count_chunks,
        )

    @staticmethod
    def extend_conflict_code_counts(
        base_code_counts: tuple[ConflictCodeCount, ...],
        merge_results: Iterable["MergeResult"],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult._extend_projection_counts_from_merge_results_with_precomposed_continuation(
            base_code_counts,
            merge_results,
            1,
            MergeResult.combine_conflict_code_counts_from_chunks,
        )

    @staticmethod
    def extend_conflict_code_counts_from_chunks(
        base_code_counts: tuple[ConflictCodeCount, ...],
        code_count_chunks: Iterable[tuple[ConflictCodeCount, ...]],
    ) -> tuple[ConflictCodeCount, ...]:
        continuation_code_counts = MergeResult.combine_conflict_code_counts_from_chunks(
            code_count_chunks
        )
        return MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_code_counts,
            continuation_code_counts,
        )

    @staticmethod
    def extend_conflict_code_counts_with_precomposed_continuation(
        base_code_counts: tuple[ConflictCodeCount, ...],
        continuation_code_counts: tuple[ConflictCodeCount, ...],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult._extend_projection_counts_with_precomposed_continuation(
            base_code_counts,
            continuation_code_counts,
            MergeResult.combine_conflict_code_counts_from_chunks,
        )

    @staticmethod
    def stream_conflict_code_counts_from_chunks(
        code_count_chunks: Iterable[tuple[ConflictCodeCount, ...]],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult.extend_conflict_code_counts_from_chunks(
            tuple(),
            code_count_chunks,
        )

    @staticmethod
    def _stream_conflict_summary(
        merge_results: Iterable["MergeResult"],
    ) -> ConflictSummary:
        return MergeResult.stream_conflict_summary_from_chunks(
            MergeResult._iter_conflict_summary_stream_chunks(merge_results)
        )

    @staticmethod
    def stream_conflict_signature_counts(
        merge_results: Iterable["MergeResult"],
    ) -> tuple[ConflictSignatureCount, ...]:
        return MergeResult.stream_conflict_signature_counts_from_chunks(
            MergeResult._iter_conflict_projection_stream_chunks(merge_results, 0)
        )

    @staticmethod
    def stream_conflict_code_counts(
        merge_results: Iterable["MergeResult"],
    ) -> tuple[ConflictCodeCount, ...]:
        return MergeResult.stream_conflict_code_counts_from_chunks(
            MergeResult._iter_conflict_projection_stream_chunks(merge_results, 1)
        )

    @staticmethod
    def stream_conflict_summary(
        merge_results: Iterable["MergeResult"],
    ) -> ConflictSummary:
        return MergeResult._stream_conflict_summary(merge_results)

    @staticmethod
    def _iter_conflict_summary_chunks(
        merge_results: Iterable["MergeResult"],
    ) -> Iterable[ConflictSummary]:
        for merge_result in merge_results:
            yield merge_result.conflict_summary()

    @staticmethod
    def _iter_conflict_summary_stream_chunks(
        merge_results: Iterable["MergeResult"],
    ) -> Iterable[ConflictSummary]:
        return MergeResult._iter_nonempty_conflict_summary_chunks(
            MergeResult._iter_conflict_summary_chunks(merge_results)
        )

    @staticmethod
    def _iter_conflict_projection_stream_chunks(
        merge_results: Iterable["MergeResult"],
        projection_index: Literal[0, 1],
    ) -> Iterable[ProjectionChunk]:
        return MergeResult._iter_projection_chunks_from_summary_chunks(
            MergeResult._iter_conflict_summary_stream_chunks(merge_results),
            projection_index,
        )

    @staticmethod
    def _iter_conflict_summary_composition_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> Iterable[ConflictSummary]:
        return MergeResult._iter_nonempty_conflict_summary_chunks(summary_chunks)

    @staticmethod
    def _iter_conflict_summary_pair_chunks(
        base_summary: ConflictSummary,
        continuation_summary: ConflictSummary,
    ) -> Iterable[ConflictSummary]:
        return MergeResult._iter_nonempty_conflict_summary_chunks(
            (base_summary, continuation_summary)
        )

    @staticmethod
    def _iter_conflict_projection_composition_chunks(
        projection_chunks: Iterable[ProjectionChunk],
    ) -> Iterable[ProjectionChunk]:
        return MergeResult._iter_nonempty_projection_chunks(projection_chunks)

    @staticmethod
    def _iter_conflict_projection_pair_chunks(
        base_projection_chunk: ProjectionChunk,
        continuation_projection_chunk: ProjectionChunk,
    ) -> Iterable[ProjectionChunk]:
        return MergeResult._iter_nonempty_projection_chunks(
            (base_projection_chunk, continuation_projection_chunk)
        )

    @staticmethod
    def _compose_conflict_projection_pair_with_chunks(
        left_projection_chunk: ProjectionChunk,
        right_projection_chunk: ProjectionChunk,
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        return combine_projection_chunks(
            MergeResult._iter_conflict_projection_pair_chunks(
                left_projection_chunk,
                right_projection_chunk,
            )
        )

    @staticmethod
    def _extend_conflict_summary_with_precomposed_continuation(
        base_summary: ConflictSummary,
        continuation_summary: ConflictSummary,
        combine_summary_chunks: Callable[
            [Iterable[ConflictSummary]],
            ConflictSummary,
        ],
    ) -> ConflictSummary:
        return combine_summary_chunks(
            MergeResult._iter_conflict_summary_pair_chunks(
                base_summary,
                continuation_summary,
            )
        )

    @staticmethod
    def _extend_projection_counts_with_precomposed_continuation(
        base_projection_counts: ProjectionChunk,
        continuation_projection_counts: ProjectionChunk,
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        return combine_projection_chunks(
            MergeResult._iter_conflict_projection_pair_chunks(
                base_projection_counts,
                continuation_projection_counts,
            )
        )

    @staticmethod
    def _compose_projection_counts_from_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
        projection_index: Literal[0, 1],
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        return combine_projection_chunks(
            MergeResult._iter_projection_chunks_from_summary_chunks(
                summary_chunks,
                projection_index,
            )
        )

    @staticmethod
    def _compose_conflict_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
        combine_summary_chunks: Callable[
            [Iterable[ConflictSummary]],
            ConflictSummary,
        ],
    ) -> ConflictSummary:
        return combine_summary_chunks(
            MergeResult._iter_conflict_summary_composition_chunks(summary_chunks)
        )

    @staticmethod
    def _extend_conflict_summary_from_chunks_with_precomposed_continuation(
        base_summary: ConflictSummary,
        summary_chunks: Iterable[ConflictSummary],
        combine_summary_chunks: Callable[
            [Iterable[ConflictSummary]],
            ConflictSummary,
        ],
        extend_summary_with_precomposed_continuation: Callable[
            [ConflictSummary, ConflictSummary],
            ConflictSummary,
        ],
    ) -> ConflictSummary:
        continuation_summary = MergeResult._compose_conflict_summary_chunks(
            summary_chunks,
            combine_summary_chunks,
        )
        return extend_summary_with_precomposed_continuation(
            base_summary,
            continuation_summary,
        )

    @staticmethod
    def _extend_projection_counts_from_merge_results_with_precomposed_continuation(
        base_projection_counts: ProjectionChunk,
        merge_results: Iterable["MergeResult"],
        projection_index: Literal[0, 1],
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        continuation_projection_counts = (
            MergeResult._compose_projection_counts_from_merge_results(
                merge_results,
                projection_index,
                combine_projection_chunks,
            )
        )
        return MergeResult._extend_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            continuation_projection_counts,
            combine_projection_chunks,
        )

    @staticmethod
    def _compose_projection_counts_from_merge_results(
        merge_results: Iterable["MergeResult"],
        projection_index: Literal[0, 1],
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        return MergeResult._compose_projection_counts_from_summary_chunks(
            MergeResult._iter_conflict_summary_chunks(merge_results),
            projection_index,
            combine_projection_chunks,
        )

    @staticmethod
    def _extend_projection_counts_from_summary_chunks_with_precomposed_continuation(
        base_projection_counts: ProjectionChunk,
        summary_chunks: Iterable[ConflictSummary],
        projection_index: Literal[0, 1],
        combine_projection_chunks: Callable[
            [Iterable[ProjectionChunk]],
            ProjectionChunk,
        ],
    ) -> ProjectionChunk:
        continuation_projection_counts = (
            MergeResult._compose_projection_counts_from_summary_chunks(
                summary_chunks,
                projection_index,
                combine_projection_chunks,
            )
        )
        return MergeResult._extend_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            continuation_projection_counts,
            combine_projection_chunks,
        )

    @staticmethod
    def _iter_projection_chunks_from_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
        projection_index: Literal[0, 1],
    ) -> Iterable[ProjectionChunk]:
        return MergeResult._iter_conflict_projection_composition_chunks(
            (
                summary_chunk[projection_index]
                for summary_chunk in MergeResult._iter_nonempty_conflict_summary_chunks(
                    summary_chunks
                )
            )
        )

    @staticmethod
    def _iter_nonempty_projection_chunks(
        projection_chunks: Iterable[ProjectionChunk],
    ) -> Iterable[ProjectionChunk]:
        for projection_chunk in projection_chunks:
            if projection_chunk:
                yield projection_chunk

    @staticmethod
    def _iter_nonempty_conflict_summary_chunks(
        summary_chunks: Iterable[ConflictSummary],
    ) -> Iterable[ConflictSummary]:
        for summary_chunk in summary_chunks:
            if summary_chunk[0] or summary_chunk[1]:
                yield summary_chunk


@dataclass(frozen=True)
class RevisionLifecycleProjection:
    active: tuple[ClaimRevision, ...]
    retracted: tuple[ClaimRevision, ...]


@dataclass(frozen=True)
class RevisionLifecycleTransition:
    tx_from: int
    tx_to: int
    entered_active: tuple[ClaimRevision, ...]
    exited_active: tuple[ClaimRevision, ...]
    entered_retracted: tuple[ClaimRevision, ...]
    exited_retracted: tuple[ClaimRevision, ...]


@dataclass(frozen=True)
class RelationLifecycleProjection:
    active: tuple[RelationEdge, ...]
    pending: tuple[RelationEdge, ...]


@dataclass(frozen=True)
class RelationLifecycleTransition:
    tx_from: int
    tx_to: int
    entered_active: tuple[RelationEdge, ...]
    exited_active: tuple[RelationEdge, ...]
    entered_pending: tuple[RelationEdge, ...]
    exited_pending: tuple[RelationEdge, ...]


@dataclass(frozen=True)
class RelationResolutionProjection:
    active: tuple[RelationEdge, ...]
    pending: tuple[RelationEdge, ...]


@dataclass(frozen=True)
class RelationResolutionTransition:
    tx_from: int
    tx_to: int
    entered_active: tuple[RelationEdge, ...]
    exited_active: tuple[RelationEdge, ...]
    entered_pending: tuple[RelationEdge, ...]
    exited_pending: tuple[RelationEdge, ...]


@dataclass(frozen=True)
class RelationLifecycleSignatureProjection:
    active: tuple[RelationStateSignature, ...]
    pending: tuple[RelationStateSignature, ...]


@dataclass(frozen=True)
class RelationLifecycleSignatureTransition:
    valid_from: datetime
    valid_to: datetime
    entered_active: tuple[RelationStateSignature, ...]
    exited_active: tuple[RelationStateSignature, ...]
    entered_pending: tuple[RelationStateSignature, ...]
    exited_pending: tuple[RelationStateSignature, ...]

    def __post_init__(self) -> None:
        valid_from_utc = _to_utc(self.valid_from)
        valid_to_utc = _to_utc(self.valid_to)
        if valid_to_utc < valid_from_utc:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        object.__setattr__(self, "valid_from", valid_from_utc)
        object.__setattr__(self, "valid_to", valid_to_utc)


@dataclass(frozen=True)
class MergeConflictProjection:
    signature_counts: tuple[ConflictSignatureCount, ...]
    code_counts: tuple[ConflictCodeCount, ...]

    @property
    def summary(self) -> ConflictSummary:
        return (self.signature_counts, self.code_counts)


@dataclass(frozen=True)
class MergeConflictProjectionTransition:
    tx_from: int
    tx_to: int
    entered_signature_counts: tuple[ConflictSignatureCount, ...]
    exited_signature_counts: tuple[ConflictSignatureCount, ...]
    entered_code_counts: tuple[ConflictCodeCount, ...]
    exited_code_counts: tuple[ConflictCodeCount, ...]


@dataclass(frozen=True)
class DeterministicStateFingerprintTransition:
    tx_from: int
    tx_to: int
    from_digest: str
    to_digest: str
    entered_revision_active: tuple[ClaimRevision, ...]
    exited_revision_active: tuple[ClaimRevision, ...]
    entered_revision_retracted: tuple[ClaimRevision, ...]
    exited_revision_retracted: tuple[ClaimRevision, ...]
    entered_relation_resolution_active: tuple[RelationEdge, ...]
    exited_relation_resolution_active: tuple[RelationEdge, ...]
    entered_relation_resolution_pending: tuple[RelationEdge, ...]
    exited_relation_resolution_pending: tuple[RelationEdge, ...]
    entered_relation_lifecycle_active: tuple[RelationEdge, ...]
    exited_relation_lifecycle_active: tuple[RelationEdge, ...]
    entered_relation_lifecycle_pending: tuple[RelationEdge, ...]
    exited_relation_lifecycle_pending: tuple[RelationEdge, ...]
    entered_relation_lifecycle_signature_active: tuple[RelationStateSignature, ...]
    exited_relation_lifecycle_signature_active: tuple[RelationStateSignature, ...]
    entered_relation_lifecycle_signature_pending: tuple[RelationStateSignature, ...]
    exited_relation_lifecycle_signature_pending: tuple[RelationStateSignature, ...]
    entered_merge_conflict_signature_counts: tuple[ConflictSignatureCount, ...]
    exited_merge_conflict_signature_counts: tuple[ConflictSignatureCount, ...]
    entered_merge_conflict_code_counts: tuple[ConflictCodeCount, ...]
    exited_merge_conflict_code_counts: tuple[ConflictCodeCount, ...]

    def as_payload(self) -> Dict[str, Any]:
        entered_revision_active = tuple(
            sorted(
                self.entered_revision_active,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )
        exited_revision_active = tuple(
            sorted(
                self.exited_revision_active,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )
        entered_revision_retracted = tuple(
            sorted(
                self.entered_revision_retracted,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )
        exited_revision_retracted = tuple(
            sorted(
                self.exited_revision_retracted,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )

        entered_relation_resolution_active = tuple(
            sorted(
                self.entered_relation_resolution_active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        exited_relation_resolution_active = tuple(
            sorted(
                self.exited_relation_resolution_active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        entered_relation_resolution_pending = tuple(
            sorted(
                self.entered_relation_resolution_pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        exited_relation_resolution_pending = tuple(
            sorted(
                self.exited_relation_resolution_pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )

        entered_relation_lifecycle_active = tuple(
            sorted(
                self.entered_relation_lifecycle_active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        exited_relation_lifecycle_active = tuple(
            sorted(
                self.exited_relation_lifecycle_active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        entered_relation_lifecycle_pending = tuple(
            sorted(
                self.entered_relation_lifecycle_pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        exited_relation_lifecycle_pending = tuple(
            sorted(
                self.exited_relation_lifecycle_pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )

        entered_relation_lifecycle_signature_active = tuple(
            sorted(self.entered_relation_lifecycle_signature_active)
        )
        exited_relation_lifecycle_signature_active = tuple(
            sorted(self.exited_relation_lifecycle_signature_active)
        )
        entered_relation_lifecycle_signature_pending = tuple(
            sorted(self.entered_relation_lifecycle_signature_pending)
        )
        exited_relation_lifecycle_signature_pending = tuple(
            sorted(self.exited_relation_lifecycle_signature_pending)
        )

        entered_merge_conflict_signature_counts = tuple(
            sorted(
                self.entered_merge_conflict_signature_counts,
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )
        exited_merge_conflict_signature_counts = tuple(
            sorted(
                self.exited_merge_conflict_signature_counts,
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )
        entered_merge_conflict_code_counts = tuple(
            sorted(
                self.entered_merge_conflict_code_counts,
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )
        exited_merge_conflict_code_counts = tuple(
            sorted(
                self.exited_merge_conflict_code_counts,
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )

        return {
            "tx_from": self.tx_from,
            "tx_to": self.tx_to,
            "from_digest": self.from_digest,
            "to_digest": self.to_digest,
            "entered_revision_active": [
                revision.as_payload() for revision in entered_revision_active
            ],
            "exited_revision_active": [
                revision.as_payload() for revision in exited_revision_active
            ],
            "entered_revision_retracted": [
                revision.as_payload() for revision in entered_revision_retracted
            ],
            "exited_revision_retracted": [
                revision.as_payload() for revision in exited_revision_retracted
            ],
            "entered_relation_resolution_active": [
                relation.as_payload()
                for relation in entered_relation_resolution_active
            ],
            "exited_relation_resolution_active": [
                relation.as_payload()
                for relation in exited_relation_resolution_active
            ],
            "entered_relation_resolution_pending": [
                relation.as_payload()
                for relation in entered_relation_resolution_pending
            ],
            "exited_relation_resolution_pending": [
                relation.as_payload()
                for relation in exited_relation_resolution_pending
            ],
            "entered_relation_lifecycle_active": [
                relation.as_payload()
                for relation in entered_relation_lifecycle_active
            ],
            "exited_relation_lifecycle_active": [
                relation.as_payload()
                for relation in exited_relation_lifecycle_active
            ],
            "entered_relation_lifecycle_pending": [
                relation.as_payload()
                for relation in entered_relation_lifecycle_pending
            ],
            "exited_relation_lifecycle_pending": [
                relation.as_payload()
                for relation in exited_relation_lifecycle_pending
            ],
            "entered_relation_lifecycle_signature_active": [
                _relation_state_signature_as_payload(signature)
                for signature in entered_relation_lifecycle_signature_active
            ],
            "exited_relation_lifecycle_signature_active": [
                _relation_state_signature_as_payload(signature)
                for signature in exited_relation_lifecycle_signature_active
            ],
            "entered_relation_lifecycle_signature_pending": [
                _relation_state_signature_as_payload(signature)
                for signature in entered_relation_lifecycle_signature_pending
            ],
            "exited_relation_lifecycle_signature_pending": [
                _relation_state_signature_as_payload(signature)
                for signature in exited_relation_lifecycle_signature_pending
            ],
            "entered_merge_conflict_signature_counts": [
                _conflict_signature_count_as_payload(signature_count)
                for signature_count in entered_merge_conflict_signature_counts
            ],
            "exited_merge_conflict_signature_counts": [
                _conflict_signature_count_as_payload(signature_count)
                for signature_count in exited_merge_conflict_signature_counts
            ],
            "entered_merge_conflict_code_counts": [
                _conflict_code_count_as_payload(code_count)
                for code_count in entered_merge_conflict_code_counts
            ],
            "exited_merge_conflict_code_counts": [
                _conflict_code_count_as_payload(code_count)
                for code_count in exited_merge_conflict_code_counts
            ],
        }

    def as_canonical_payload(self) -> Dict[str, Any]:
        return self.as_payload()

    def canonical_json(self) -> str:
        return _canonical_json_text(self.as_payload())

    def as_canonical_json(self) -> str:
        return self.canonical_json()

    @classmethod
    def from_canonical_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "DeterministicStateFingerprintTransition":
        payload_obj = _expect_mapping(payload, "payload")
        _expect_exact_keys(
            payload_obj,
            "payload",
            (
                "tx_from",
                "tx_to",
                "from_digest",
                "to_digest",
                "entered_revision_active",
                "exited_revision_active",
                "entered_revision_retracted",
                "exited_revision_retracted",
                "entered_relation_resolution_active",
                "exited_relation_resolution_active",
                "entered_relation_resolution_pending",
                "exited_relation_resolution_pending",
                "entered_relation_lifecycle_active",
                "exited_relation_lifecycle_active",
                "entered_relation_lifecycle_pending",
                "exited_relation_lifecycle_pending",
                "entered_relation_lifecycle_signature_active",
                "exited_relation_lifecycle_signature_active",
                "entered_relation_lifecycle_signature_pending",
                "exited_relation_lifecycle_signature_pending",
                "entered_merge_conflict_signature_counts",
                "exited_merge_conflict_signature_counts",
                "entered_merge_conflict_code_counts",
                "exited_merge_conflict_code_counts",
            ),
        )

        tx_from = _expect_int(payload_obj["tx_from"], "payload.tx_from", min_value=0)
        tx_to = _expect_int(payload_obj["tx_to"], "payload.tx_to", min_value=0)
        if tx_to < tx_from:
            raise _payload_validation_error(
                "payload.tx_to",
                "must be greater than or equal to payload.tx_from",
            )

        transition = cls(
            tx_from=tx_from,
            tx_to=tx_to,
            from_digest=_expect_sha256_hexdigest(
                payload_obj["from_digest"], "payload.from_digest"
            ),
            to_digest=_expect_sha256_hexdigest(
                payload_obj["to_digest"], "payload.to_digest"
            ),
            entered_revision_active=_parse_payload_array(
                payload_obj["entered_revision_active"],
                "payload.entered_revision_active",
                _claim_revision_from_payload,
            ),
            exited_revision_active=_parse_payload_array(
                payload_obj["exited_revision_active"],
                "payload.exited_revision_active",
                _claim_revision_from_payload,
            ),
            entered_revision_retracted=_parse_payload_array(
                payload_obj["entered_revision_retracted"],
                "payload.entered_revision_retracted",
                _claim_revision_from_payload,
            ),
            exited_revision_retracted=_parse_payload_array(
                payload_obj["exited_revision_retracted"],
                "payload.exited_revision_retracted",
                _claim_revision_from_payload,
            ),
            entered_relation_resolution_active=_parse_payload_array(
                payload_obj["entered_relation_resolution_active"],
                "payload.entered_relation_resolution_active",
                _relation_edge_from_payload,
            ),
            exited_relation_resolution_active=_parse_payload_array(
                payload_obj["exited_relation_resolution_active"],
                "payload.exited_relation_resolution_active",
                _relation_edge_from_payload,
            ),
            entered_relation_resolution_pending=_parse_payload_array(
                payload_obj["entered_relation_resolution_pending"],
                "payload.entered_relation_resolution_pending",
                _relation_edge_from_payload,
            ),
            exited_relation_resolution_pending=_parse_payload_array(
                payload_obj["exited_relation_resolution_pending"],
                "payload.exited_relation_resolution_pending",
                _relation_edge_from_payload,
            ),
            entered_relation_lifecycle_active=_parse_payload_array(
                payload_obj["entered_relation_lifecycle_active"],
                "payload.entered_relation_lifecycle_active",
                _relation_edge_from_payload,
            ),
            exited_relation_lifecycle_active=_parse_payload_array(
                payload_obj["exited_relation_lifecycle_active"],
                "payload.exited_relation_lifecycle_active",
                _relation_edge_from_payload,
            ),
            entered_relation_lifecycle_pending=_parse_payload_array(
                payload_obj["entered_relation_lifecycle_pending"],
                "payload.entered_relation_lifecycle_pending",
                _relation_edge_from_payload,
            ),
            exited_relation_lifecycle_pending=_parse_payload_array(
                payload_obj["exited_relation_lifecycle_pending"],
                "payload.exited_relation_lifecycle_pending",
                _relation_edge_from_payload,
            ),
            entered_relation_lifecycle_signature_active=_parse_payload_array(
                payload_obj["entered_relation_lifecycle_signature_active"],
                "payload.entered_relation_lifecycle_signature_active",
                _relation_state_signature_from_payload,
            ),
            exited_relation_lifecycle_signature_active=_parse_payload_array(
                payload_obj["exited_relation_lifecycle_signature_active"],
                "payload.exited_relation_lifecycle_signature_active",
                _relation_state_signature_from_payload,
            ),
            entered_relation_lifecycle_signature_pending=_parse_payload_array(
                payload_obj["entered_relation_lifecycle_signature_pending"],
                "payload.entered_relation_lifecycle_signature_pending",
                _relation_state_signature_from_payload,
            ),
            exited_relation_lifecycle_signature_pending=_parse_payload_array(
                payload_obj["exited_relation_lifecycle_signature_pending"],
                "payload.exited_relation_lifecycle_signature_pending",
                _relation_state_signature_from_payload,
            ),
            entered_merge_conflict_signature_counts=_parse_payload_array(
                payload_obj["entered_merge_conflict_signature_counts"],
                "payload.entered_merge_conflict_signature_counts",
                _conflict_signature_count_from_payload,
            ),
            exited_merge_conflict_signature_counts=_parse_payload_array(
                payload_obj["exited_merge_conflict_signature_counts"],
                "payload.exited_merge_conflict_signature_counts",
                _conflict_signature_count_from_payload,
            ),
            entered_merge_conflict_code_counts=_parse_payload_array(
                payload_obj["entered_merge_conflict_code_counts"],
                "payload.entered_merge_conflict_code_counts",
                _conflict_code_count_from_payload,
            ),
            exited_merge_conflict_code_counts=_parse_payload_array(
                payload_obj["exited_merge_conflict_code_counts"],
                "payload.exited_merge_conflict_code_counts",
                _conflict_code_count_from_payload,
            ),
        )

        if _canonical_json_text(payload_obj) != transition.canonical_json():
            raise _payload_validation_error(
                "payload",
                "does not match canonical deterministic state fingerprint transition payload",
            )
        return transition

    @classmethod
    def from_canonical_json(
        cls,
        canonical_json: str,
    ) -> "DeterministicStateFingerprintTransition":
        json_text = _expect_str(canonical_json, "canonical_json")
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise _payload_validation_error(
                "canonical_json", f"invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(payload, Mapping):
            raise _payload_validation_error(
                "canonical_json", "expected top-level JSON object"
            )

        transition = cls.from_canonical_payload(payload)
        if json_text != transition.canonical_json():
            raise _payload_validation_error(
                "canonical_json",
                "does not match canonical deterministic state fingerprint transition JSON",
            )
        return transition


@dataclass(frozen=True)
class DeterministicStateFingerprint:
    revision_lifecycle: RevisionLifecycleProjection
    relation_resolution: RelationResolutionProjection
    relation_lifecycle: RelationLifecycleProjection
    merge_conflict_projection: MergeConflictProjection
    relation_lifecycle_signatures: RelationLifecycleSignatureProjection
    ordered_projection: tuple[tuple[Any, ...], ...] = field(init=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        normalized_revision_lifecycle = RevisionLifecycleProjection(
            active=tuple(
                sorted(
                    self.revision_lifecycle.active,
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
            retracted=tuple(
                sorted(
                    self.revision_lifecycle.retracted,
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
        )
        normalized_relation_resolution = RelationResolutionProjection(
            active=tuple(
                sorted(
                    self.relation_resolution.active,
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
            pending=tuple(
                sorted(
                    self.relation_resolution.pending,
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
        )
        normalized_relation_lifecycle = RelationLifecycleProjection(
            active=tuple(
                sorted(
                    self.relation_lifecycle.active,
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
            pending=tuple(
                sorted(
                    self.relation_lifecycle.pending,
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
        )
        normalized_merge_conflict_projection = MergeConflictProjection(
            signature_counts=tuple(
                sorted(
                    self.merge_conflict_projection.signature_counts,
                    key=KnowledgeStore._merge_conflict_signature_sort_key,
                )
            ),
            code_counts=tuple(
                sorted(
                    self.merge_conflict_projection.code_counts,
                    key=KnowledgeStore._merge_conflict_code_sort_key,
                )
            ),
        )
        normalized_relation_lifecycle_signatures = RelationLifecycleSignatureProjection(
            active=tuple(sorted(self.relation_lifecycle_signatures.active)),
            pending=tuple(sorted(self.relation_lifecycle_signatures.pending)),
        )

        object.__setattr__(self, "revision_lifecycle", normalized_revision_lifecycle)
        object.__setattr__(self, "relation_resolution", normalized_relation_resolution)
        object.__setattr__(self, "relation_lifecycle", normalized_relation_lifecycle)
        object.__setattr__(
            self,
            "merge_conflict_projection",
            normalized_merge_conflict_projection,
        )
        object.__setattr__(
            self,
            "relation_lifecycle_signatures",
            normalized_relation_lifecycle_signatures,
        )

        ordered_projection = (
            tuple(
                revision.revision_id
                for revision in normalized_revision_lifecycle.active
            ),
            tuple(
                revision.revision_id
                for revision in normalized_revision_lifecycle.retracted
            ),
            tuple(
                relation.relation_id
                for relation in normalized_relation_resolution.active
            ),
            tuple(
                relation.relation_id
                for relation in normalized_relation_resolution.pending
            ),
            tuple(
                relation.relation_id
                for relation in normalized_relation_lifecycle.active
            ),
            tuple(
                relation.relation_id
                for relation in normalized_relation_lifecycle.pending
            ),
            normalized_relation_lifecycle_signatures.active,
            normalized_relation_lifecycle_signatures.pending,
            normalized_merge_conflict_projection.signature_counts,
            normalized_merge_conflict_projection.code_counts,
        )
        object.__setattr__(self, "ordered_projection", ordered_projection)
        object.__setattr__(
            self,
            "digest",
            _stable_payload_hash(
                "deterministic_state_fingerprint",
                {"ordered_projection": ordered_projection},
            ),
        )

    def as_payload(self) -> Dict[str, Any]:
        revision_active = tuple(
            sorted(
                self.revision_lifecycle.active,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )
        revision_retracted = tuple(
            sorted(
                self.revision_lifecycle.retracted,
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )
        relation_resolution_active = tuple(
            sorted(
                self.relation_resolution.active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        relation_resolution_pending = tuple(
            sorted(
                self.relation_resolution.pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        relation_lifecycle_active = tuple(
            sorted(
                self.relation_lifecycle.active,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        relation_lifecycle_pending = tuple(
            sorted(
                self.relation_lifecycle.pending,
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        relation_lifecycle_signature_active = tuple(
            sorted(self.relation_lifecycle_signatures.active)
        )
        relation_lifecycle_signature_pending = tuple(
            sorted(self.relation_lifecycle_signatures.pending)
        )
        merge_conflict_signature_counts = tuple(
            sorted(
                self.merge_conflict_projection.signature_counts,
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )
        merge_conflict_code_counts = tuple(
            sorted(
                self.merge_conflict_projection.code_counts,
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )
        return {
            "revision_lifecycle": {
                "active": [revision.as_payload() for revision in revision_active],
                "retracted": [
                    revision.as_payload() for revision in revision_retracted
                ],
            },
            "relation_resolution": {
                "active": [
                    relation.as_payload() for relation in relation_resolution_active
                ],
                "pending": [
                    relation.as_payload() for relation in relation_resolution_pending
                ],
            },
            "relation_lifecycle": {
                "active": [
                    relation.as_payload() for relation in relation_lifecycle_active
                ],
                "pending": [
                    relation.as_payload() for relation in relation_lifecycle_pending
                ],
            },
            "relation_lifecycle_signatures": {
                "active": [
                    _relation_state_signature_as_payload(signature)
                    for signature in relation_lifecycle_signature_active
                ],
                "pending": [
                    _relation_state_signature_as_payload(signature)
                    for signature in relation_lifecycle_signature_pending
                ],
            },
            "merge_conflict_projection": {
                "signature_counts": [
                    _conflict_signature_count_as_payload(signature_count)
                    for signature_count in merge_conflict_signature_counts
                ],
                "code_counts": [
                    _conflict_code_count_as_payload(code_count)
                    for code_count in merge_conflict_code_counts
                ],
            },
            "ordered_projection": _json_compatible_value(self.ordered_projection),
            "digest": self.digest,
        }

    def as_canonical_payload(self) -> Dict[str, Any]:
        return self.as_payload()

    def canonical_json(self) -> str:
        return _canonical_json_text(self.as_payload())

    def as_canonical_json(self) -> str:
        return self.canonical_json()

    @classmethod
    def from_canonical_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "DeterministicStateFingerprint":
        payload_obj = _expect_mapping(payload, "payload")
        _expect_exact_keys(
            payload_obj,
            "payload",
            (
                "revision_lifecycle",
                "relation_resolution",
                "relation_lifecycle",
                "merge_conflict_projection",
                "relation_lifecycle_signatures",
                "ordered_projection",
                "digest",
            ),
        )

        revision_lifecycle_payload = _expect_mapping(
            payload_obj["revision_lifecycle"],
            "payload.revision_lifecycle",
        )
        _expect_exact_keys(
            revision_lifecycle_payload,
            "payload.revision_lifecycle",
            ("active", "retracted"),
        )

        relation_resolution_payload = _expect_mapping(
            payload_obj["relation_resolution"],
            "payload.relation_resolution",
        )
        _expect_exact_keys(
            relation_resolution_payload,
            "payload.relation_resolution",
            ("active", "pending"),
        )

        relation_lifecycle_payload = _expect_mapping(
            payload_obj["relation_lifecycle"],
            "payload.relation_lifecycle",
        )
        _expect_exact_keys(
            relation_lifecycle_payload,
            "payload.relation_lifecycle",
            ("active", "pending"),
        )

        merge_conflict_payload = _expect_mapping(
            payload_obj["merge_conflict_projection"],
            "payload.merge_conflict_projection",
        )
        _expect_exact_keys(
            merge_conflict_payload,
            "payload.merge_conflict_projection",
            ("signature_counts", "code_counts"),
        )

        relation_signature_payload = _expect_mapping(
            payload_obj["relation_lifecycle_signatures"],
            "payload.relation_lifecycle_signatures",
        )
        _expect_exact_keys(
            relation_signature_payload,
            "payload.relation_lifecycle_signatures",
            ("active", "pending"),
        )

        ordered_projection = _expect_list(
            payload_obj["ordered_projection"],
            "payload.ordered_projection",
        )
        digest = _expect_sha256_hexdigest(payload_obj["digest"], "payload.digest")

        fingerprint = cls(
            revision_lifecycle=RevisionLifecycleProjection(
                active=_parse_payload_array(
                    revision_lifecycle_payload["active"],
                    "payload.revision_lifecycle.active",
                    _claim_revision_from_payload,
                ),
                retracted=_parse_payload_array(
                    revision_lifecycle_payload["retracted"],
                    "payload.revision_lifecycle.retracted",
                    _claim_revision_from_payload,
                ),
            ),
            relation_resolution=RelationResolutionProjection(
                active=_parse_payload_array(
                    relation_resolution_payload["active"],
                    "payload.relation_resolution.active",
                    _relation_edge_from_payload,
                ),
                pending=_parse_payload_array(
                    relation_resolution_payload["pending"],
                    "payload.relation_resolution.pending",
                    _relation_edge_from_payload,
                ),
            ),
            relation_lifecycle=RelationLifecycleProjection(
                active=_parse_payload_array(
                    relation_lifecycle_payload["active"],
                    "payload.relation_lifecycle.active",
                    _relation_edge_from_payload,
                ),
                pending=_parse_payload_array(
                    relation_lifecycle_payload["pending"],
                    "payload.relation_lifecycle.pending",
                    _relation_edge_from_payload,
                ),
            ),
            merge_conflict_projection=MergeConflictProjection(
                signature_counts=_parse_payload_array(
                    merge_conflict_payload["signature_counts"],
                    "payload.merge_conflict_projection.signature_counts",
                    _conflict_signature_count_from_payload,
                ),
                code_counts=_parse_payload_array(
                    merge_conflict_payload["code_counts"],
                    "payload.merge_conflict_projection.code_counts",
                    _conflict_code_count_from_payload,
                ),
            ),
            relation_lifecycle_signatures=RelationLifecycleSignatureProjection(
                active=_parse_payload_array(
                    relation_signature_payload["active"],
                    "payload.relation_lifecycle_signatures.active",
                    _relation_state_signature_from_payload,
                ),
                pending=_parse_payload_array(
                    relation_signature_payload["pending"],
                    "payload.relation_lifecycle_signatures.pending",
                    _relation_state_signature_from_payload,
                ),
            ),
        )

        canonical_payload = fingerprint.as_payload()
        if digest != fingerprint.digest:
            raise _payload_validation_error(
                "payload.digest",
                f"mismatch; expected {fingerprint.digest}, got {digest}",
            )
        if ordered_projection != canonical_payload["ordered_projection"]:
            raise _payload_validation_error(
                "payload.ordered_projection",
                "does not match deterministic ordered projection",
            )
        if _canonical_json_text(payload_obj) != fingerprint.canonical_json():
            raise _payload_validation_error(
                "payload",
                "does not match canonical deterministic state fingerprint payload",
            )
        return fingerprint

    @classmethod
    def from_canonical_json(
        cls,
        canonical_json: str,
    ) -> "DeterministicStateFingerprint":
        json_text = _expect_str(canonical_json, "canonical_json")
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise _payload_validation_error(
                "canonical_json", f"invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(payload, Mapping):
            raise _payload_validation_error(
                "canonical_json", "expected top-level JSON object"
            )

        fingerprint = cls.from_canonical_payload(payload)
        if json_text != fingerprint.canonical_json():
            raise _payload_validation_error(
                "canonical_json",
                "does not match canonical deterministic state fingerprint JSON",
            )
        return fingerprint


class KnowledgeStore:
    _REVISION_WINNER_STATUS_ORDER = {"retracted": 0, "asserted": 1}
    _CANONICAL_SNAPSHOT_SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.cores: Dict[str, ClaimCore] = {}
        self.revisions: Dict[str, ClaimRevision] = {}
        self.relations: Dict[str, RelationEdge] = {}
        self._pending_relations: Dict[str, RelationEdge] = {}
        self._relation_variants: Dict[str, Dict[RelationPayloadKey, RelationEdge]] = {}
        self._relation_collision_pairs: Dict[
            str, set[tuple[RelationPayloadKey, RelationPayloadKey]]
        ] = {}
        self._revisions_by_core: Dict[str, set[str]] = {}
        self._merge_conflict_journal: tuple[tuple[int, MergeResult], ...] = ()
        self._retracted_cache: Optional[frozenset[str]] = None

    def retracted_core_ids(self) -> frozenset[str]:
        """Return core_ids that have ANY retracted revision.

        Retraction is permanent for a core_id: once a retraction revision
        exists, the core is considered tainted regardless of later assertions.
        To reassert a claim, create a NEW core with fresh content.

        Results are cached as frozenset (immutable) and invalidated on
        assert_revision() calls.
        """
        if self._retracted_cache is not None:
            return self._retracted_cache
        result = frozenset(rev.core_id for rev in self.revisions.values()
                           if rev.status == "retracted")
        self._retracted_cache = result
        return result

    def _invalidate_retraction_cache(self) -> None:
        """Invalidate the retracted_core_ids cache after store mutation."""
        self._retracted_cache = None

    def checkpoint(self) -> "KnowledgeStore":
        snapshot = KnowledgeStore()
        snapshot.cores = dict(self.cores)
        snapshot.revisions = dict(self.revisions)
        snapshot.relations = dict(self.relations)
        snapshot._pending_relations = dict(self._pending_relations)
        snapshot._relation_variants = {
            relation_id: dict(variants)
            for relation_id, variants in self._relation_variants.items()
        }
        snapshot._relation_collision_pairs = {
            relation_id: set(pair_keys)
            for relation_id, pair_keys in self._relation_collision_pairs.items()
        }
        snapshot._revisions_by_core = {
            core_id: set(revision_ids)
            for core_id, revision_ids in self._revisions_by_core.items()
        }
        snapshot._merge_conflict_journal = self._merge_conflict_journal
        return snapshot

    def copy(self) -> "KnowledgeStore":
        return self.checkpoint()

    def as_canonical_payload(self) -> Dict[str, Any]:
        cores = tuple(
            sorted(self.cores.values(), key=KnowledgeStore._core_projection_sort_key)
        )
        cores_payload = [core.as_payload() for core in cores]
        revisions = tuple(
            sorted(self.revisions.values(), key=KnowledgeStore._revision_projection_sort_key)
        )
        revisions_payload = [revision.as_payload() for revision in revisions]
        active_relations = tuple(
            sorted(self.relations.values(), key=KnowledgeStore._relation_projection_sort_key)
        )
        active_relations_payload = [relation.as_payload() for relation in active_relations]
        pending_relations = tuple(
            sorted(
                self._pending_relations.values(),
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )
        pending_relations_payload = [
            relation.as_payload()
            for relation in pending_relations
        ]

        relation_variants_payload: list[Dict[str, Any]] = []
        for relation_id in sorted(self._relation_variants):
            variants = self._relation_variants[relation_id]
            ordered_variant_keys = tuple(sorted(variants.keys()))
            relation_variants_payload.append(
                {
                    "relation_id": relation_id,
                    "variants": [
                        {
                            "relation_key": _relation_payload_key_as_payload(variant_key),
                            "relation": variants[variant_key].as_payload(),
                        }
                        for variant_key in ordered_variant_keys
                    ],
                }
            )

        relation_collision_metadata_payload: list[Dict[str, Any]] = []
        for relation_id in sorted(self._relation_collision_pairs):
            pair_keys = tuple(sorted(self._relation_collision_pairs[relation_id]))
            relation_collision_metadata_payload.append(
                {
                    "relation_id": relation_id,
                    "collision_pairs": [
                        _relation_collision_pair_as_payload(pair_key)
                        for pair_key in pair_keys
                    ],
                }
            )

        merge_conflict_journal_payload = [
            _merge_result_by_tx_as_store_snapshot_payload(merge_result_by_tx)
            for merge_result_by_tx in (
                KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                    self._merge_conflict_journal
                )
            )
        ]

        payload_without_checksum = {
            "snapshot_schema_version": KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION,
            "cores": cores_payload,
            "revisions": revisions_payload,
            "active_relations": active_relations_payload,
            "pending_relations": pending_relations_payload,
            "relation_variants": relation_variants_payload,
            "relation_collision_metadata": relation_collision_metadata_payload,
            "merge_conflict_journal": merge_conflict_journal_payload,
        }
        snapshot_checksum = _knowledge_store_snapshot_checksum(payload_without_checksum)

        return {
            "snapshot_schema_version": KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION,
            "cores": cores_payload,
            "revisions": revisions_payload,
            "active_relations": active_relations_payload,
            "pending_relations": pending_relations_payload,
            "relation_variants": relation_variants_payload,
            "relation_collision_metadata": relation_collision_metadata_payload,
            "merge_conflict_journal": merge_conflict_journal_payload,
            "snapshot_checksum": snapshot_checksum,
        }

    def as_canonical_json(self) -> str:
        return _canonical_json_text(self.as_canonical_payload())

    @staticmethod
    def _canonical_json_file_path(
        file_path: str | os.PathLike[str],
        *,
        path_arg: str,
    ) -> Path:
        if not isinstance(file_path, (str, os.PathLike)):
            raise _payload_validation_error(
                path_arg,
                f"expected path-like, got {type(file_path).__name__}",
            )
        return Path(file_path)

    def to_canonical_json_file(
        self,
        canonical_json_path: str | os.PathLike[str],
    ) -> None:
        path = self._canonical_json_file_path(
            canonical_json_path,
            path_arg="canonical_json_path",
        )
        canonical_json_bytes = self.as_canonical_json().encode("utf-8", errors="strict")

        temp_path: Optional[Path] = None
        try:
            temp_fd, temp_name = tempfile.mkstemp(
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                text=False,
            )
            temp_path = Path(temp_name)
            with os.fdopen(temp_fd, "wb") as handle:
                handle.write(canonical_json_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_file_with_retry(temp_path, path)
        except Exception as write_or_replace_error:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                except Exception as cleanup_error:
                    write_or_replace_error.add_note(
                        f"temporary snapshot cleanup failed: {cleanup_error!r}"
                    )
            raise

    def write_canonical_json_file(
        self,
        canonical_json_path: str | os.PathLike[str],
    ) -> None:
        self.to_canonical_json_file(canonical_json_path)

    @classmethod
    @_route_snapshot_validation_error
    def from_canonical_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "KnowledgeStore":
        payload_obj = _expect_mapping(payload, "payload")
        _expect_exact_keys(
            payload_obj,
            "payload",
            (
                "snapshot_schema_version",
                "cores",
                "revisions",
                "active_relations",
                "pending_relations",
                "relation_variants",
                "relation_collision_metadata",
                "merge_conflict_journal",
                "snapshot_checksum",
            ),
        )
        snapshot_checksum = _expect_sha256_hexdigest(
            payload_obj["snapshot_checksum"],
            "payload.snapshot_checksum",
        )
        schema_version = _expect_int(
            payload_obj["snapshot_schema_version"],
            "payload.snapshot_schema_version",
            min_value=0,
        )
        if schema_version != cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION:
            raise _payload_validation_error(
                "payload.snapshot_schema_version",
                (
                    "unsupported snapshot schema version "
                    f"{schema_version}; expected {cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION}"
                ),
            )

        store = cls()
        cores = _parse_payload_array(
            payload_obj["cores"],
            "payload.cores",
            _claim_core_from_payload,
        )
        for index, core in enumerate(cores):
            if core.core_id in store.cores:
                raise _payload_validation_error(
                    f"payload.cores[{index}].core_id",
                    f"duplicate core_id {core.core_id}",
                )
            store.cores[core.core_id] = core

        revisions = _parse_payload_array(
            payload_obj["revisions"],
            "payload.revisions",
            _claim_revision_from_payload,
        )
        for index, revision in enumerate(revisions):
            if revision.revision_id in store.revisions:
                raise _payload_validation_error(
                    f"payload.revisions[{index}].revision_id",
                    f"duplicate revision_id {revision.revision_id}",
                )
            if revision.core_id not in store.cores:
                raise _payload_validation_error(
                    f"payload.revisions[{index}].core_id",
                    f"unknown core_id {revision.core_id}",
                )
            store.revisions[revision.revision_id] = revision
            store._revisions_by_core.setdefault(revision.core_id, set()).add(
                revision.revision_id
            )

        active_relations = _parse_payload_array(
            payload_obj["active_relations"],
            "payload.active_relations",
            _relation_edge_from_store_snapshot_payload,
        )
        for index, relation in enumerate(active_relations):
            relation_id = relation.relation_id
            if relation_id in store.relations or relation_id in store._pending_relations:
                raise _payload_validation_error(
                    f"payload.active_relations[{index}].relation_id",
                    f"duplicate relation_id {relation_id}",
                )
            missing_endpoints = cls._missing_relation_endpoints_from_index(
                revision_ids=store.revisions,
                incoming_relation=relation,
            )
            if missing_endpoints:
                raise _payload_validation_error(
                    f"payload.active_relations[{index}]",
                    (
                        "active relation references missing revision endpoints: "
                        + ", ".join(missing_endpoints)
                    ),
                )
            store.relations[relation_id] = relation

        pending_relations = _parse_payload_array(
            payload_obj["pending_relations"],
            "payload.pending_relations",
            _relation_edge_from_store_snapshot_payload,
        )
        for index, relation in enumerate(pending_relations):
            relation_id = relation.relation_id
            if relation_id in store.relations or relation_id in store._pending_relations:
                raise _payload_validation_error(
                    f"payload.pending_relations[{index}].relation_id",
                    f"duplicate relation_id {relation_id}",
                )
            store._pending_relations[relation_id] = relation

        relation_variants_payload = _expect_list(
            payload_obj["relation_variants"],
            "payload.relation_variants",
        )
        for entry_index, entry in enumerate(relation_variants_payload):
            entry_path = f"payload.relation_variants[{entry_index}]"
            entry_payload = _expect_mapping(entry, entry_path)
            _expect_exact_keys(entry_payload, entry_path, ("relation_id", "variants"))
            relation_id = _expect_sha256_hexdigest(
                entry_payload["relation_id"],
                f"{entry_path}.relation_id",
            )
            if relation_id in store._relation_variants:
                raise _payload_validation_error(
                    f"{entry_path}.relation_id",
                    f"duplicate relation_id {relation_id}",
                )
            variants_payload = _expect_list(entry_payload["variants"], f"{entry_path}.variants")
            variants: Dict[RelationPayloadKey, RelationEdge] = {}
            for variant_index, variant in enumerate(variants_payload):
                variant_path = f"{entry_path}.variants[{variant_index}]"
                variant_payload = _expect_mapping(variant, variant_path)
                _expect_exact_keys(
                    variant_payload,
                    variant_path,
                    ("relation_key", "relation"),
                )
                relation_key = _relation_payload_key_from_payload(
                    variant_payload["relation_key"],
                    f"{variant_path}.relation_key",
                )
                relation = _relation_edge_from_store_snapshot_payload(
                    variant_payload["relation"],
                    f"{variant_path}.relation",
                )
                if relation.relation_id != relation_id:
                    raise _payload_validation_error(
                        f"{variant_path}.relation.relation_id",
                        (
                            "mismatch; expected "
                            f"{relation_id}, got {relation.relation_id}"
                        ),
                    )
                if relation_id in store.relations:
                    missing_endpoints = cls._missing_relation_endpoints_from_index(
                        revision_ids=store.revisions,
                        incoming_relation=relation,
                    )
                    if missing_endpoints:
                        raise _payload_validation_error(
                            f"{variant_path}.relation",
                            (
                                "relation variant references missing revision endpoints: "
                                + ", ".join(missing_endpoints)
                            ),
                        )
                canonical_relation_key = cls._relation_payload_sort_key(relation)
                if relation_key != canonical_relation_key:
                    raise _payload_validation_error(
                        f"{variant_path}.relation_key",
                        "does not match relation payload sort key",
                    )
                if relation_key in variants:
                    raise _payload_validation_error(
                        f"{variant_path}.relation_key",
                        (
                            "duplicate relation payload key "
                            f"{cls._relation_payload_signature(relation_key)}"
                        ),
                    )
                variants[relation_key] = relation
            store._relation_variants[relation_id] = variants

        relation_collision_metadata_payload = _expect_list(
            payload_obj["relation_collision_metadata"],
            "payload.relation_collision_metadata",
        )
        for entry_index, entry in enumerate(relation_collision_metadata_payload):
            entry_path = f"payload.relation_collision_metadata[{entry_index}]"
            entry_payload = _expect_mapping(entry, entry_path)
            _expect_exact_keys(
                entry_payload,
                entry_path,
                ("relation_id", "collision_pairs"),
            )
            relation_id = _expect_sha256_hexdigest(
                entry_payload["relation_id"],
                f"{entry_path}.relation_id",
            )
            if relation_id in store._relation_collision_pairs:
                raise _payload_validation_error(
                    f"{entry_path}.relation_id",
                    f"duplicate relation_id {relation_id}",
                )
            collision_pairs_payload = _expect_list(
                entry_payload["collision_pairs"],
                f"{entry_path}.collision_pairs",
            )
            collision_pairs: set[tuple[RelationPayloadKey, RelationPayloadKey]] = set()
            for pair_index, pair in enumerate(collision_pairs_payload):
                pair_path = f"{entry_path}.collision_pairs[{pair_index}]"
                left_key, right_key = _relation_collision_pair_from_payload(
                    pair,
                    pair_path,
                )
                pair_key = cls._relation_collision_pair_key(left_key, right_key)
                if pair_key in collision_pairs:
                    raise _payload_validation_error(
                        pair_path,
                        (
                            "duplicate collision pair "
                            f"{cls._relation_payload_signature(pair_key[0])}::"
                            f"{cls._relation_payload_signature(pair_key[1])}"
                        ),
                    )
                collision_pairs.add(pair_key)
            store._relation_collision_pairs[relation_id] = collision_pairs

        _expect_exact_dynamic_key_set(
            observed_keys=store._relation_collision_pairs.keys(),
            expected_keys=store._relation_variants.keys(),
            path="payload.relation_collision_metadata",
            key_label="relation_id",
        )

        for relation_id, relation_variants in store._relation_variants.items():
            if not relation_variants:
                raise _payload_validation_error(
                    "payload.relation_variants",
                    f"relation_id {relation_id} has no variants",
                )
            canonical_relation = relation_variants[min(relation_variants)]
            active_relation = store.relations.get(relation_id)
            pending_relation = store._pending_relations.get(relation_id)
            if active_relation is None and pending_relation is None:
                raise _payload_validation_error(
                    "payload.relation_variants",
                    (
                        "relation_id "
                        f"{relation_id} is not present in active_relations "
                        "or pending_relations"
                    ),
                )
            if active_relation is not None and active_relation != canonical_relation:
                raise _payload_validation_error(
                    "payload.relation_variants",
                    f"relation_id {relation_id} canonical variant mismatch for active_relations",
                )
            if pending_relation is not None and pending_relation != canonical_relation:
                raise _payload_validation_error(
                    "payload.relation_variants",
                    f"relation_id {relation_id} canonical variant mismatch for pending_relations",
                )

        for relation_id, collision_pairs in store._relation_collision_pairs.items():
            relation_variants = store._relation_variants.get(relation_id)
            if relation_variants is None:
                raise _payload_validation_error(
                    "payload.relation_collision_metadata",
                    (
                        "relation_id "
                        f"{relation_id} collision metadata has no matching relation_variants entry"
                    ),
                )
            variant_keys = set(relation_variants)
            for pair_key in collision_pairs:
                if pair_key[0] not in variant_keys or pair_key[1] not in variant_keys:
                    raise _payload_validation_error(
                        "payload.relation_collision_metadata",
                        (
                            "relation_id "
                            f"{relation_id} collision pair references unknown relation variants"
                        ),
                    )

        merge_conflict_journal = _parse_payload_array(
            payload_obj["merge_conflict_journal"],
            "payload.merge_conflict_journal",
            _merge_result_by_tx_from_store_snapshot_payload,
        )
        normalized_merge_conflict_journal = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                merge_conflict_journal
            )
        )
        store._validate_merge_conflict_journal_tx_membership(
            normalized_merge_conflict_journal,
            error_path="payload.merge_conflict_journal",
        )
        store._merge_conflict_journal = normalized_merge_conflict_journal

        payload_without_checksum = {
            key: value
            for key, value in payload_obj.items()
            if key != "snapshot_checksum"
        }
        expected_snapshot_checksum = _knowledge_store_snapshot_checksum(
            payload_without_checksum
        )
        if snapshot_checksum != expected_snapshot_checksum:
            raise _payload_validation_error(
                "payload.snapshot_checksum",
                "does not match canonical deterministic knowledge store snapshot checksum",
            )

        if _canonical_json_text(payload_obj) != store.as_canonical_json():
            raise _payload_validation_error(
                "payload",
                "does not match canonical deterministic knowledge store payload",
            )
        return store

    @classmethod
    @_route_snapshot_validation_error
    def from_canonical_json(
        cls,
        canonical_json: str,
    ) -> "KnowledgeStore":
        json_text = _expect_str(canonical_json, "canonical_json")
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise _payload_validation_error(
                "canonical_json", f"invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(payload, Mapping):
            raise _payload_validation_error(
                "canonical_json",
                "expected top-level JSON object",
            )

        store = cls.from_canonical_payload(payload)
        if json_text != store.as_canonical_json():
            raise _payload_validation_error(
                "canonical_json",
                "does not match canonical deterministic knowledge store JSON",
            )
        return store

    @classmethod
    @_route_snapshot_validation_error
    def from_canonical_json_file(
        cls,
        canonical_json_path: str | os.PathLike[str],
    ) -> "KnowledgeStore":
        path = cls._canonical_json_file_path(
            canonical_json_path,
            path_arg="canonical_json_path",
        )
        canonical_json_bytes = path.read_bytes()
        try:
            canonical_json = canonical_json_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _payload_validation_error(
                "canonical_json_file",
                "invalid UTF-8 encoded snapshot content",
            ) from exc
        return cls.from_canonical_json(canonical_json)

    @staticmethod
    def _snapshot_validation_report_from_store(
        store: "KnowledgeStore",
    ) -> SnapshotValidationReport:
        canonical_payload = store.as_canonical_payload()
        canonical_json = _canonical_json_text(canonical_payload)
        return SnapshotValidationReport(
            schema_version=canonical_payload["snapshot_schema_version"],
            snapshot_checksum=canonical_payload["snapshot_checksum"],
            canonical_content_digest=_knowledge_store_canonical_content_digest(
                canonical_json
            ),
        )

    @classmethod
    @_route_snapshot_validation_error
    def validate_canonical_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> SnapshotValidationReport:
        store = cls.from_canonical_payload(payload)
        return cls._snapshot_validation_report_from_store(store)

    @classmethod
    @_route_snapshot_validation_error
    def validate_canonical_json(
        cls,
        canonical_json: str,
    ) -> SnapshotValidationReport:
        store = cls.from_canonical_json(canonical_json)
        return cls._snapshot_validation_report_from_store(store)

    @classmethod
    @_route_snapshot_validation_error
    def validate_canonical_json_file(
        cls,
        canonical_json_path: str | os.PathLike[str],
    ) -> SnapshotValidationReport:
        store = cls.from_canonical_json_file(canonical_json_path)
        return cls._snapshot_validation_report_from_store(store)

    @staticmethod
    def _core_projection_sort_key(core: ClaimCore) -> str:
        return core.core_id

    @staticmethod
    def _revision_winner_sort_key(revision: ClaimRevision) -> tuple[int, int, str]:
        return (
            -revision.transaction_time.tx_id,
            KnowledgeStore._REVISION_WINNER_STATUS_ORDER[revision.status],
            revision.revision_id,
        )

    @staticmethod
    def _revision_projection_sort_key(revision: ClaimRevision) -> str:
        return revision.revision_id

    @staticmethod
    def _ordered_revision_bucket(
        revisions_by_id: Mapping[str, ClaimRevision],
        revision_ids: Iterable[str],
    ) -> tuple[ClaimRevision, ...]:
        return tuple(
            sorted(
                (revisions_by_id[revision_id] for revision_id in revision_ids),
                key=KnowledgeStore._revision_projection_sort_key,
            )
        )

    @staticmethod
    def _relation_projection_sort_key(relation: RelationEdge) -> str:
        return relation.relation_id

    @staticmethod
    def _ordered_relation_bucket(
        relations_by_id: Mapping[str, RelationEdge],
        relation_ids: Iterable[str],
    ) -> tuple[RelationEdge, ...]:
        return tuple(
            sorted(
                (relations_by_id[relation_id] for relation_id in relation_ids),
                key=KnowledgeStore._relation_projection_sort_key,
            )
        )

    @staticmethod
    def _ordered_identity_bucket(
        values_by_key: Mapping[Any, Any],
        value_keys: Iterable[Any],
    ) -> tuple[Any, ...]:
        return tuple(sorted(values_by_key[value_key] for value_key in value_keys))

    @staticmethod
    def _merge_conflict_signature_sort_key(
        signature: ConflictSignature | ConflictSignatureCount,
    ) -> tuple[str, str, str]:
        return (signature[0], signature[1], signature[2])

    @staticmethod
    def _merge_conflict_code_sort_key(code_count: ConflictCodeCount) -> str:
        return code_count[0]

    @staticmethod
    def _ordered_merge_conflict_signature_bucket(
        signature_counts_by_key: Mapping[ConflictSignatureCount, ConflictSignatureCount],
        signature_keys: Iterable[ConflictSignatureCount],
    ) -> tuple[ConflictSignatureCount, ...]:
        return tuple(
            sorted(
                (
                    signature_counts_by_key[signature_key]
                    for signature_key in signature_keys
                ),
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )

    @staticmethod
    def _ordered_merge_conflict_code_bucket(
        code_counts_by_key: Mapping[ConflictCodeCount, ConflictCodeCount],
        code_keys: Iterable[ConflictCodeCount],
    ) -> tuple[ConflictCodeCount, ...]:
        return tuple(
            sorted(
                (code_counts_by_key[code_key] for code_key in code_keys),
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )

    @staticmethod
    def _identity_transition_key(value: Any) -> Any:
        return value

    @staticmethod
    def _query_as_of_buckets_via_projection(
        *,
        tx_id: int,
        projection_as_of: Callable[[int], Any],
        bucket_routes: Mapping[
            str,
            tuple[
                Callable[[Any], Iterable[Any]],
                Callable[[Any], int],
                Callable[[Any], Any],
                Callable[[Mapping[Any, Any], Iterable[Any]], tuple[Any, ...]],
            ],
        ],
    ) -> dict[str, tuple[Any, ...]]:
        as_of_projection = projection_as_of(tx_id)
        as_of_buckets: dict[str, tuple[Any, ...]] = {}

        for bucket_name, (
            projection_bucket,
            bucket_item_tx_id,
            bucket_key,
            bucket_orderer,
        ) in bucket_routes.items():
            bucket_at_tx_id = {
                bucket_key(bucket_item): bucket_item
                for bucket_item in projection_bucket(as_of_projection)
                if bucket_item_tx_id(bucket_item) <= tx_id
            }
            as_of_buckets[bucket_name] = bucket_orderer(
                bucket_at_tx_id,
                bucket_at_tx_id.keys(),
            )

        return as_of_buckets

    @staticmethod
    def _query_tx_window_buckets_via_as_of_projection(
        *,
        tx_start: int,
        tx_end: int,
        projection_as_of: Callable[[int], Any],
        bucket_routes: Mapping[
            str,
            tuple[
                Callable[[Any], Iterable[Any]],
                Callable[[Any], int],
                Callable[[Any], Any],
                Callable[[Mapping[Any, Any], Iterable[Any]], tuple[Any, ...]],
            ],
        ],
    ) -> dict[str, tuple[Any, ...]]:
        if tx_end < tx_start:
            raise ValueError("tx_end must be greater than or equal to tx_start")

        as_of_projection = projection_as_of(tx_end)
        tx_window_buckets: dict[str, tuple[Any, ...]] = {}

        for bucket_name, (
            projection_bucket,
            bucket_item_tx_id,
            bucket_key,
            bucket_orderer,
        ) in bucket_routes.items():
            bucket_at_tx_end = {
                bucket_key(bucket_item): bucket_item
                for bucket_item in projection_bucket(as_of_projection)
                if tx_start <= bucket_item_tx_id(bucket_item) <= tx_end
            }
            tx_window_buckets[bucket_name] = bucket_orderer(
                bucket_at_tx_end,
                bucket_at_tx_end.keys(),
            )

        return tx_window_buckets

    @staticmethod
    def _query_transition_buckets_via_as_of_diff(
        *,
        tx_from: int,
        tx_to: int,
        projection_from: Any,
        projection_to: Any,
        projection_as_of: Callable[[Any], Any],
        bucket_routes: Mapping[
            str,
            tuple[
                Callable[[Any], Iterable[Any]],
                Callable[[Any], Any],
                Callable[[Mapping[Any, Any], Iterable[Any]], tuple[Any, ...]],
            ],
        ],
        tx_from_label: str = "tx_from",
        tx_to_label: str = "tx_to",
    ) -> dict[str, tuple[Any, ...]]:
        if tx_to < tx_from:
            raise ValueError(f"{tx_to_label} must be greater than or equal to {tx_from_label}")

        from_projection = projection_as_of(projection_from)
        to_projection = projection_as_of(projection_to)
        transition_buckets: dict[str, tuple[Any, ...]] = {}

        for bucket_name, (projection_bucket, bucket_key, bucket_orderer) in bucket_routes.items():
            from_bucket = {
                bucket_key(bucket_item): bucket_item
                for bucket_item in projection_bucket(from_projection)
            }
            to_bucket = {
                bucket_key(bucket_item): bucket_item
                for bucket_item in projection_bucket(to_projection)
            }
            transition_buckets[f"entered_{bucket_name}"] = bucket_orderer(
                to_bucket,
                set(to_bucket) - set(from_bucket),
            )
            transition_buckets[f"exited_{bucket_name}"] = bucket_orderer(
                from_bucket,
                set(from_bucket) - set(to_bucket),
            )

        return transition_buckets

    @staticmethod
    def _merge_conflict_sort_key(conflict: MergeConflict) -> tuple[str, str, str]:
        return KnowledgeStore._merge_conflict_signature_sort_key(conflict.signature())

    @staticmethod
    def conflict_signatures(
        conflicts: Iterable[MergeConflict],
    ) -> tuple[ConflictSignature, ...]:
        return tuple(
            sorted(
                (conflict.signature() for conflict in conflicts),
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )

    @staticmethod
    def conflict_signature_counts(
        conflicts: Iterable[MergeConflict],
    ) -> tuple[ConflictSignatureCount, ...]:
        counts_by_signature: Dict[ConflictSignature, int] = {}
        for conflict in conflicts:
            signature = conflict.signature()
            counts_by_signature[signature] = counts_by_signature.get(signature, 0) + 1
        return tuple(
            sorted(
                (
                    (
                        signature[0],
                        signature[1],
                        signature[2],
                        count,
                    )
                    for signature, count in counts_by_signature.items()
                ),
                key=KnowledgeStore._merge_conflict_signature_sort_key,
            )
        )

    @staticmethod
    def conflict_code_counts(
        conflicts: Iterable[MergeConflict],
    ) -> tuple[ConflictCodeCount, ...]:
        counts_by_code: Dict[str, int] = {}
        for conflict in conflicts:
            code = conflict.code.value
            counts_by_code[code] = counts_by_code.get(code, 0) + 1
        return tuple(
            sorted(
                counts_by_code.items(),
                key=KnowledgeStore._merge_conflict_code_sort_key,
            )
        )

    @staticmethod
    def conflict_summary(
        conflicts: Iterable[MergeConflict],
    ) -> ConflictSummary:
        conflict_items = tuple(conflicts)
        return (
            KnowledgeStore.conflict_signature_counts(conflict_items),
            KnowledgeStore.conflict_code_counts(conflict_items),
        )

    @staticmethod
    def _normalize_merge_results_by_tx_for_merge_conflict_projection(
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
    ) -> tuple[tuple[int, MergeResult], ...]:
        stream = tuple(merge_results_by_tx)
        if len(stream) < 2:
            return stream

        return tuple(
            merge_result_by_tx
            for _stream_index, merge_result_by_tx in sorted(
                enumerate(stream),
                key=lambda indexed_merge_result: (
                    indexed_merge_result[1][0],
                    indexed_merge_result[0],
                ),
            )
        )

    def _known_tx_history_for_merge_conflict_journal(self) -> tuple[int, ...]:
        known_tx_ids = {
            revision.transaction_time.tx_id
            for revision in self.revisions.values()
        }
        known_tx_ids.update(
            relation.transaction_time.tx_id
            for relation in self.relations.values()
        )
        known_tx_ids.update(
            relation.transaction_time.tx_id
            for relation in self._pending_relations.values()
        )
        known_tx_ids.update(
            relation.transaction_time.tx_id
            for variants in self._relation_variants.values()
            for relation in variants.values()
        )
        return tuple(sorted(known_tx_ids))

    def _validate_merge_conflict_journal_tx_membership(
        self,
        merge_results_by_tx: tuple[tuple[int, MergeResult], ...],
        *,
        error_path: Optional[str] = None,
    ) -> None:
        known_tx_ids = self._known_tx_history_for_merge_conflict_journal()
        unknown_tx_ids = tuple(
            sorted(
                {
                    tx_id
                    for tx_id, _merge_result in merge_results_by_tx
                    if tx_id not in known_tx_ids
                }
            )
        )
        if unknown_tx_ids:
            message = (
                "merge-conflict journal tx_id(s) are not present in store tx "
                f"history: {unknown_tx_ids}; known tx_ids: {known_tx_ids}"
            )
            if error_path is None:
                raise ValueError(message)
            raise _payload_validation_error(error_path, message)

    def record_merge_conflict_journal(
        self,
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
    ) -> tuple[tuple[int, MergeResult], ...]:
        recorded_chunk = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                merge_results_by_tx
            )
        )
        if not recorded_chunk:
            return self._merge_conflict_journal
        self._validate_merge_conflict_journal_tx_membership(recorded_chunk)
        if not self._merge_conflict_journal:
            self._merge_conflict_journal = recorded_chunk
            return self._merge_conflict_journal

        self._merge_conflict_journal = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                (*self._merge_conflict_journal, *recorded_chunk)
            )
        )
        return self._merge_conflict_journal

    def merge_conflict_journal(self) -> tuple[tuple[int, MergeResult], ...]:
        return self._merge_conflict_journal

    def _resolve_merge_results_by_tx_for_conflict_queries(
        self,
        merge_results_by_tx: Optional[Iterable[tuple[int, MergeResult]]],
    ) -> Iterable[tuple[int, MergeResult]]:
        if merge_results_by_tx is None:
            return self._merge_conflict_journal
        return merge_results_by_tx

    def query_merge_conflict_projection_as_of_from_journal(
        self,
        *,
        tx_id: int,
    ) -> MergeConflictProjection:
        return KnowledgeStore.query_merge_conflict_projection_as_of(
            self._resolve_merge_results_by_tx_for_conflict_queries(None),
            tx_id=tx_id,
        )

    def query_merge_conflict_projection_for_tx_window_from_journal(
        self,
        *,
        tx_start: int,
        tx_end: int,
    ) -> MergeConflictProjection:
        return KnowledgeStore.query_merge_conflict_projection_for_tx_window(
            self._resolve_merge_results_by_tx_for_conflict_queries(None),
            tx_start=tx_start,
            tx_end=tx_end,
        )

    def query_merge_conflict_projection_transition_for_tx_window_from_journal(
        self,
        *,
        tx_from: int,
        tx_to: int,
        valid_at: Optional[datetime] = None,
    ) -> MergeConflictProjectionTransition:
        return KnowledgeStore.query_merge_conflict_projection_transition_for_tx_window(
            self._resolve_merge_results_by_tx_for_conflict_queries(None),
            tx_from=tx_from,
            tx_to=tx_to,
            valid_at=valid_at,
        )

    @staticmethod
    def query_merge_conflict_projection_as_of(
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
        *,
        tx_id: int,
    ) -> MergeConflictProjection:
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                merge_results_by_tx
            )
        )
        as_of_buckets = KnowledgeStore._query_as_of_buckets_via_projection(
            tx_id=tx_id,
            projection_as_of=lambda _tx_id: tuple(
                (stream_index, merge_result_tx_id, merge_result)
                for stream_index, (merge_result_tx_id, merge_result) in enumerate(
                    merge_results_by_tx
                )
            ),
            bucket_routes={
                "merge_results": (
                    KnowledgeStore._identity_transition_key,
                    lambda indexed_merge_result: indexed_merge_result[1],
                    lambda indexed_merge_result: indexed_merge_result[0],
                    KnowledgeStore._ordered_identity_bucket,
                ),
            },
        )
        summary = MergeResult.stream_conflict_summary(
            indexed_merge_result[2]
            for indexed_merge_result in as_of_buckets["merge_results"]
        )
        return MergeConflictProjection(
            signature_counts=summary[0],
            code_counts=summary[1],
        )

    @staticmethod
    def query_merge_conflict_projection_for_tx_window(
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
        *,
        tx_start: int,
        tx_end: int,
    ) -> MergeConflictProjection:
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                merge_results_by_tx
            )
        )
        tx_window_buckets = KnowledgeStore._query_tx_window_buckets_via_as_of_projection(
            tx_start=tx_start,
            tx_end=tx_end,
            projection_as_of=lambda tx_id: tuple(
                (stream_index, merge_result_tx_id, merge_result)
                for stream_index, (merge_result_tx_id, merge_result) in enumerate(
                    merge_results_by_tx
                )
                if merge_result_tx_id <= tx_id
            ),
            bucket_routes={
                "merge_results": (
                    KnowledgeStore._identity_transition_key,
                    lambda indexed_merge_result: indexed_merge_result[1],
                    lambda indexed_merge_result: indexed_merge_result[0],
                    KnowledgeStore._ordered_identity_bucket,
                ),
            },
        )
        summary = MergeResult.stream_conflict_summary(
            indexed_merge_result[2]
            for indexed_merge_result in tx_window_buckets["merge_results"]
        )
        return MergeConflictProjection(
            signature_counts=summary[0],
            code_counts=summary[1],
        )

    @staticmethod
    def query_merge_conflict_projection_transition_for_tx_window(
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
        *,
        tx_from: int,
        tx_to: int,
        valid_at: Optional[datetime] = None,
    ) -> MergeConflictProjectionTransition:
        _ = valid_at
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
                merge_results_by_tx
            )
        )
        stream = tuple(merge_results_by_tx)
        transition_buckets = KnowledgeStore._query_transition_buckets_via_as_of_diff(
            tx_from=tx_from,
            tx_to=tx_to,
            projection_from=tx_from,
            projection_to=tx_to,
            projection_as_of=lambda tx_id: KnowledgeStore.query_merge_conflict_projection_as_of(
                stream,
                tx_id=tx_id,
            ),
            bucket_routes={
                "signature_counts": (
                    lambda projection: projection.signature_counts,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_merge_conflict_signature_bucket,
                ),
                "code_counts": (
                    lambda projection: projection.code_counts,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_merge_conflict_code_bucket,
                ),
            },
        )
        return MergeConflictProjectionTransition(
            tx_from=tx_from,
            tx_to=tx_to,
            entered_signature_counts=transition_buckets["entered_signature_counts"],
            exited_signature_counts=transition_buckets["exited_signature_counts"],
            entered_code_counts=transition_buckets["entered_code_counts"],
            exited_code_counts=transition_buckets["exited_code_counts"],
        )

    @staticmethod
    def _normalize_merge_results_by_tx_for_state_fingerprint(
        merge_results_by_tx: Iterable[tuple[int, MergeResult]],
    ) -> tuple[tuple[int, MergeResult], ...]:
        return KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection(
            merge_results_by_tx
        )

    def pending_relation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending_relations.keys()))

    def relation_state_signatures(self) -> tuple[RelationStateSignature, ...]:
        signatures: list[RelationStateSignature] = []
        for relation_id, relation in sorted(self.relations.items()):
            signatures.append(
                self._relation_state_signature(
                    bucket="active",
                    relation_id=relation_id,
                    relation=relation,
                )
            )
        for relation_id, relation in sorted(self._pending_relations.items()):
            signatures.append(
                self._relation_state_signature(
                    bucket="pending",
                    relation_id=relation_id,
                    relation=relation,
                )
            )
        return tuple(signatures)

    def revision_state_signatures(self) -> tuple[RevisionStateSignature, ...]:
        signatures: list[RevisionStateSignature] = []
        for revision_id, revision in sorted(self.revisions.items()):
            signatures.append(
                self._revision_state_signature(
                    revision_id=revision_id,
                    revision=revision,
                )
            )
        return tuple(signatures)

    def assert_revision(
        self,
        core: ClaimCore,
        assertion: str,
        valid_time: ValidTime,
        transaction_time: TransactionTime,
        provenance: Provenance,
        confidence_bp: int,
        status: Literal["asserted", "retracted"] = "asserted",
    ) -> ClaimRevision:
        if status not in ("asserted", "retracted"):
            raise ValueError(
                f"Invalid status: {status!r}. Must be 'asserted' or 'retracted'."
            )
        if not isinstance(confidence_bp, int) or confidence_bp < 0 or confidence_bp > 10000:
            raise ValueError(
                f"confidence_bp must be an integer in [0, 10000], got {confidence_bp!r}."
            )
        existing_core = self.cores.get(core.core_id)
        if existing_core is not None and existing_core != core:
            raise ValueError(f"core_id collision: {core.core_id}")
        self.cores[core.core_id] = core

        revision = ClaimRevision(
            core_id=core.core_id,
            assertion=assertion,
            valid_time=valid_time,
            transaction_time=transaction_time,
            provenance=provenance,
            confidence_bp=confidence_bp,
            status=status,
        )
        existing_revision = self.revisions.get(revision.revision_id)
        if existing_revision is not None and existing_revision != revision:
            raise ValueError(f"revision_id collision: {revision.revision_id}")

        self.revisions[revision.revision_id] = revision
        self._revisions_by_core.setdefault(core.core_id, set()).add(revision.revision_id)
        self._invalidate_retraction_cache()
        return revision

    def attach_relation(
        self,
        relation_type: str,
        from_revision_id: str,
        to_revision_id: str,
        transaction_time: TransactionTime,
    ) -> RelationEdge:
        if from_revision_id not in self.revisions:
            raise KeyError(f"unknown from_revision_id: {from_revision_id}")
        if to_revision_id not in self.revisions:
            raise KeyError(f"unknown to_revision_id: {to_revision_id}")

        relation = RelationEdge(
            relation_type=relation_type,
            from_revision_id=from_revision_id,
            to_revision_id=to_revision_id,
            transaction_time=transaction_time,
        )
        existing_relation = self.relations.get(relation.relation_id)
        if existing_relation is not None and existing_relation != relation:
            raise ValueError(f"relation_id collision: {relation.relation_id}")

        self.relations[relation.relation_id] = relation
        return relation

    def _select_revision_winner_as_of(
        self,
        core_id: str,
        *,
        valid_at: datetime,
        tx_id: int,
    ) -> Optional[ClaimRevision]:
        candidate_ids = self._revisions_by_core.get(core_id)
        if not candidate_ids:
            return None

        candidates = [
            self.revisions[revision_id]
            for revision_id in candidate_ids
            if self.revisions[revision_id].transaction_time.tx_id <= tx_id
            and self.revisions[revision_id].valid_time.contains(valid_at)
        ]
        if not candidates:
            return None

        # Group by valid_time interval to prevent retraction splash (FM-009/INV-T5):
        # a retraction of [2010,2020) must not suppress an asserted [2015,2025)
        by_interval: Dict[tuple, list[ClaimRevision]] = {}
        for c in candidates:
            key = (c.valid_time.start, c.valid_time.end)
            by_interval.setdefault(key, []).append(c)

        # Within each interval, select the highest-precedence revision
        interval_winners: list[ClaimRevision] = []
        for group in by_interval.values():
            group.sort(key=KnowledgeStore._revision_winner_sort_key)
            interval_winners.append(group[0])

        # Prefer asserted winners over retracted winners from other intervals
        asserted = [w for w in interval_winners if w.status != "retracted"]
        if asserted:
            asserted.sort(key=KnowledgeStore._revision_winner_sort_key)
            return asserted[0]

        # All interval winners are retracted
        interval_winners.sort(key=KnowledgeStore._revision_winner_sort_key)
        return interval_winners[0]

    def query_as_of(
        self,
        core_id: str,
        *,
        valid_at: datetime,
        tx_id: int,
    ) -> Optional[ClaimRevision]:
        winner = self._select_revision_winner_as_of(
            core_id,
            valid_at=valid_at,
            tx_id=tx_id,
        )
        if winner is None:
            return None
        if winner.status == "retracted":
            return None
        return winner

    def query_state_fingerprint_as_of(
        self,
        *,
        tx_id: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
        merge_results_by_tx: Optional[Iterable[tuple[int, MergeResult]]] = (),
    ) -> DeterministicStateFingerprint:
        merge_results_by_tx = self._resolve_merge_results_by_tx_for_conflict_queries(
            merge_results_by_tx
        )
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_state_fingerprint(
                merge_results_by_tx
            )
        )
        revision_lifecycle_projection = self.query_revision_lifecycle_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            core_id=core_id,
        )
        relation_resolution_projection = self.query_relation_resolution_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            core_id=core_id,
        )

        relation_revision_id: Optional[str] = None
        if core_id is not None:
            winner = self.query_as_of(
                core_id,
                valid_at=valid_at,
                tx_id=tx_id,
            )
            relation_revision_id = (
                winner.revision_id
                if winner is not None
                else _STATE_FINGERPRINT_MISSING_REVISION_ID
            )

        relation_lifecycle_projection = self.query_relation_lifecycle_as_of(
            tx_id=tx_id,
            valid_at=valid_at,
            revision_id=relation_revision_id,
        )
        relation_lifecycle_signature_projection = (
            self.query_relation_lifecycle_signatures_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                revision_id=relation_revision_id,
            )
        )
        merge_conflict_projection = KnowledgeStore.query_merge_conflict_projection_as_of(
            merge_results_by_tx,
            tx_id=tx_id,
        )

        return DeterministicStateFingerprint(
            revision_lifecycle=revision_lifecycle_projection,
            relation_resolution=relation_resolution_projection,
            relation_lifecycle=relation_lifecycle_projection,
            merge_conflict_projection=merge_conflict_projection,
            relation_lifecycle_signatures=relation_lifecycle_signature_projection,
        )

    def query_state_fingerprint_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
        merge_results_by_tx: Optional[Iterable[tuple[int, MergeResult]]] = (),
    ) -> DeterministicStateFingerprint:
        merge_results_by_tx = self._resolve_merge_results_by_tx_for_conflict_queries(
            merge_results_by_tx
        )
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_state_fingerprint(
                merge_results_by_tx
            )
        )
        revision_lifecycle_projection = self.query_revision_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            core_id=core_id,
        )
        relation_resolution_projection = self.query_relation_resolution_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            core_id=core_id,
        )

        relation_revision_id: Optional[str] = None
        if core_id is not None:
            winner = self.query_as_of(
                core_id,
                valid_at=valid_at,
                tx_id=tx_end,
            )
            relation_revision_id = (
                winner.revision_id
                if winner is not None
                else _STATE_FINGERPRINT_MISSING_REVISION_ID
            )

        relation_lifecycle_projection = self.query_relation_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            revision_id=relation_revision_id,
        )
        relation_lifecycle_signature_projection = (
            self.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
                revision_id=relation_revision_id,
            )
        )
        merge_conflict_projection = (
            KnowledgeStore.query_merge_conflict_projection_for_tx_window(
                merge_results_by_tx,
                tx_start=tx_start,
                tx_end=tx_end,
            )
        )

        return DeterministicStateFingerprint(
            revision_lifecycle=revision_lifecycle_projection,
            relation_resolution=relation_resolution_projection,
            relation_lifecycle=relation_lifecycle_projection,
            merge_conflict_projection=merge_conflict_projection,
            relation_lifecycle_signatures=relation_lifecycle_signature_projection,
        )

    def query_state_fingerprint_transition_for_tx_window(
        self,
        *,
        tx_from: int,
        tx_to: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
        merge_results_by_tx: Optional[Iterable[tuple[int, MergeResult]]] = (),
    ) -> DeterministicStateFingerprintTransition:
        if tx_to < tx_from:
            raise ValueError("tx_to must be greater than or equal to tx_from")

        merge_results_by_tx = self._resolve_merge_results_by_tx_for_conflict_queries(
            merge_results_by_tx
        )
        merge_results_by_tx = (
            KnowledgeStore._normalize_merge_results_by_tx_for_state_fingerprint(
                merge_results_by_tx
            )
        )
        from_fingerprint = self.query_state_fingerprint_as_of(
            tx_id=tx_from,
            valid_at=valid_at,
            core_id=core_id,
            merge_results_by_tx=merge_results_by_tx,
        )
        to_fingerprint = self.query_state_fingerprint_as_of(
            tx_id=tx_to,
            valid_at=valid_at,
            core_id=core_id,
            merge_results_by_tx=merge_results_by_tx,
        )
        transition_buckets = self._query_transition_buckets_via_as_of_diff(
            tx_from=tx_from,
            tx_to=tx_to,
            projection_from=from_fingerprint,
            projection_to=to_fingerprint,
            projection_as_of=KnowledgeStore._identity_transition_key,
            bucket_routes={
                "revision_active": (
                    lambda fingerprint: fingerprint.revision_lifecycle.active,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
                "revision_retracted": (
                    lambda fingerprint: fingerprint.revision_lifecycle.retracted,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
                "relation_resolution_active": (
                    lambda fingerprint: fingerprint.relation_resolution.active,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "relation_resolution_pending": (
                    lambda fingerprint: fingerprint.relation_resolution.pending,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "relation_lifecycle_active": (
                    lambda fingerprint: fingerprint.relation_lifecycle.active,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "relation_lifecycle_pending": (
                    lambda fingerprint: fingerprint.relation_lifecycle.pending,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "relation_lifecycle_signature_active": (
                    lambda fingerprint: fingerprint.relation_lifecycle_signatures.active,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_identity_bucket,
                ),
                "relation_lifecycle_signature_pending": (
                    lambda fingerprint: fingerprint.relation_lifecycle_signatures.pending,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_identity_bucket,
                ),
                "merge_conflict_signature_counts": (
                    lambda fingerprint: fingerprint.merge_conflict_projection.signature_counts,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_merge_conflict_signature_bucket,
                ),
                "merge_conflict_code_counts": (
                    lambda fingerprint: fingerprint.merge_conflict_projection.code_counts,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_merge_conflict_code_bucket,
                ),
            },
        )
        return DeterministicStateFingerprintTransition(
            tx_from=tx_from,
            tx_to=tx_to,
            from_digest=from_fingerprint.digest,
            to_digest=to_fingerprint.digest,
            entered_revision_active=transition_buckets["entered_revision_active"],
            exited_revision_active=transition_buckets["exited_revision_active"],
            entered_revision_retracted=transition_buckets["entered_revision_retracted"],
            exited_revision_retracted=transition_buckets["exited_revision_retracted"],
            entered_relation_resolution_active=transition_buckets[
                "entered_relation_resolution_active"
            ],
            exited_relation_resolution_active=transition_buckets[
                "exited_relation_resolution_active"
            ],
            entered_relation_resolution_pending=transition_buckets[
                "entered_relation_resolution_pending"
            ],
            exited_relation_resolution_pending=transition_buckets[
                "exited_relation_resolution_pending"
            ],
            entered_relation_lifecycle_active=transition_buckets[
                "entered_relation_lifecycle_active"
            ],
            exited_relation_lifecycle_active=transition_buckets[
                "exited_relation_lifecycle_active"
            ],
            entered_relation_lifecycle_pending=transition_buckets[
                "entered_relation_lifecycle_pending"
            ],
            exited_relation_lifecycle_pending=transition_buckets[
                "exited_relation_lifecycle_pending"
            ],
            entered_relation_lifecycle_signature_active=transition_buckets[
                "entered_relation_lifecycle_signature_active"
            ],
            exited_relation_lifecycle_signature_active=transition_buckets[
                "exited_relation_lifecycle_signature_active"
            ],
            entered_relation_lifecycle_signature_pending=transition_buckets[
                "entered_relation_lifecycle_signature_pending"
            ],
            exited_relation_lifecycle_signature_pending=transition_buckets[
                "exited_relation_lifecycle_signature_pending"
            ],
            entered_merge_conflict_signature_counts=transition_buckets[
                "entered_merge_conflict_signature_counts"
            ],
            exited_merge_conflict_signature_counts=transition_buckets[
                "exited_merge_conflict_signature_counts"
            ],
            entered_merge_conflict_code_counts=transition_buckets[
                "entered_merge_conflict_code_counts"
            ],
            exited_merge_conflict_code_counts=transition_buckets[
                "exited_merge_conflict_code_counts"
            ],
        )

    def query_revision_lifecycle_as_of(
        self,
        *,
        tx_id: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RevisionLifecycleProjection:
        core_ids: Iterable[str]
        if core_id is None:
            core_ids = sorted(self._revisions_by_core.keys())
        else:
            core_ids = (core_id,)

        def winner_projection_as_of(cutoff_tx_id: int) -> tuple[ClaimRevision, ...]:
            winners: list[ClaimRevision] = []
            for candidate_core_id in core_ids:
                winner = self._select_revision_winner_as_of(
                    candidate_core_id,
                    valid_at=valid_at,
                    tx_id=cutoff_tx_id,
                )
                if winner is not None:
                    winners.append(winner)
            return tuple(winners)

        as_of_buckets = self._query_as_of_buckets_via_projection(
            tx_id=tx_id,
            projection_as_of=winner_projection_as_of,
            bucket_routes={
                "active": (
                    lambda winners: (
                        winner for winner in winners if winner.status != "retracted"
                    ),
                    lambda revision: revision.transaction_time.tx_id,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
                "retracted": (
                    lambda winners: (
                        winner for winner in winners if winner.status == "retracted"
                    ),
                    lambda revision: revision.transaction_time.tx_id,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
            },
        )

        return RevisionLifecycleProjection(
            active=tuple(
                sorted(
                    as_of_buckets["active"],
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
            retracted=tuple(
                sorted(
                    as_of_buckets["retracted"],
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
        )

    def query_revision_lifecycle_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RevisionLifecycleProjection:
        tx_window_buckets = self._query_tx_window_buckets_via_as_of_projection(
            tx_start=tx_start,
            tx_end=tx_end,
            projection_as_of=lambda tx_id: self.query_revision_lifecycle_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                core_id=core_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda revision: revision.transaction_time.tx_id,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
                "retracted": (
                    lambda projection: projection.retracted,
                    lambda revision: revision.transaction_time.tx_id,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
            },
        )
        return RevisionLifecycleProjection(
            active=tuple(
                sorted(
                    tx_window_buckets["active"],
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
            retracted=tuple(
                sorted(
                    tx_window_buckets["retracted"],
                    key=KnowledgeStore._revision_projection_sort_key,
                )
            ),
        )

    def query_revision_lifecycle_transition_for_tx_window(
        self,
        *,
        tx_from: int,
        tx_to: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RevisionLifecycleTransition:
        transition_buckets = self._query_transition_buckets_via_as_of_diff(
            tx_from=tx_from,
            tx_to=tx_to,
            projection_from=tx_from,
            projection_to=tx_to,
            projection_as_of=lambda tx_id: self.query_revision_lifecycle_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                core_id=core_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
                "retracted": (
                    lambda projection: projection.retracted,
                    KnowledgeStore._revision_projection_sort_key,
                    KnowledgeStore._ordered_revision_bucket,
                ),
            },
        )
        return RevisionLifecycleTransition(
            tx_from=tx_from,
            tx_to=tx_to,
            entered_active=transition_buckets["entered_active"],
            exited_active=transition_buckets["exited_active"],
            entered_retracted=transition_buckets["entered_retracted"],
            exited_retracted=transition_buckets["exited_retracted"],
        )

    def query_relation_resolution_as_of(
        self,
        *,
        tx_id: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RelationResolutionProjection:
        def relation_resolution_projection_as_of(cutoff_tx_id: int) -> RelationResolutionProjection:
            revision_id: Optional[str] = None
            if core_id is not None:
                winner = self.query_as_of(
                    core_id,
                    valid_at=valid_at,
                    tx_id=cutoff_tx_id,
                )
                if winner is None:
                    return RelationResolutionProjection(active=(), pending=())
                revision_id = winner.revision_id

            projection = self.query_relation_lifecycle_as_of(
                tx_id=cutoff_tx_id,
                valid_at=valid_at,
                revision_id=revision_id,
            )
            return RelationResolutionProjection(
                active=projection.active,
                pending=projection.pending,
            )

        as_of_buckets = self._query_as_of_buckets_via_projection(
            tx_id=tx_id,
            projection_as_of=relation_resolution_projection_as_of,
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationResolutionProjection(
            active=as_of_buckets["active"],
            pending=as_of_buckets["pending"],
        )

    def query_relation_resolution_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RelationResolutionProjection:
        tx_window_buckets = self._query_tx_window_buckets_via_as_of_projection(
            tx_start=tx_start,
            tx_end=tx_end,
            projection_as_of=lambda tx_id: self.query_relation_resolution_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                core_id=core_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationResolutionProjection(
            active=tuple(
                sorted(
                    tx_window_buckets["active"],
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
            pending=tuple(
                sorted(
                    tx_window_buckets["pending"],
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
        )

    def query_relation_resolution_transition_for_tx_window(
        self,
        *,
        tx_from: int,
        tx_to: int,
        valid_at: datetime,
        core_id: Optional[str] = None,
    ) -> RelationResolutionTransition:
        transition_buckets = self._query_transition_buckets_via_as_of_diff(
            tx_from=tx_from,
            tx_to=tx_to,
            projection_from=tx_from,
            projection_to=tx_to,
            projection_as_of=lambda tx_id: self.query_relation_resolution_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                core_id=core_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationResolutionTransition(
            tx_from=tx_from,
            tx_to=tx_to,
            entered_active=transition_buckets["entered_active"],
            exited_active=transition_buckets["exited_active"],
            entered_pending=transition_buckets["entered_pending"],
            exited_pending=transition_buckets["exited_pending"],
        )

    def query_relations_as_of(
        self,
        *,
        tx_id: int,
        revision_id: Optional[str] = None,
        valid_at: Optional[datetime] = None,
        active_only: bool = False,
    ) -> tuple[RelationEdge, ...]:
        if active_only and valid_at is None:
            raise ValueError("valid_at is required when active_only=True")

        active_winners_by_core: Dict[str, Optional[str]] = {}
        visible = [
            relation
            for relation in self.relations.values()
            if relation.transaction_time.tx_id <= tx_id
            and (
                revision_id is None
                or relation.from_revision_id == revision_id
                or relation.to_revision_id == revision_id
            )
            and (
                not active_only
                or self._relation_endpoints_active(
                    relation=relation,
                    tx_id=tx_id,
                    valid_at=valid_at,
                    active_winners_by_core=active_winners_by_core,
                )
            )
        ]
        visible.sort(key=KnowledgeStore._relation_projection_sort_key)
        return tuple(visible)

    def query_pending_relations_as_of(
        self,
        *,
        tx_id: int,
        revision_id: Optional[str] = None,
    ) -> tuple[RelationEdge, ...]:
        visible = [
            relation
            for relation in self._pending_relations.values()
            if relation.transaction_time.tx_id <= tx_id
            and (
                revision_id is None
                or relation.from_revision_id == revision_id
                or relation.to_revision_id == revision_id
            )
        ]
        visible.sort(key=KnowledgeStore._relation_projection_sort_key)
        return tuple(visible)

    def query_relation_lifecycle_as_of(
        self,
        *,
        tx_id: int,
        valid_at: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleProjection:
        as_of_buckets = self._query_as_of_buckets_via_projection(
            tx_id=tx_id,
            projection_as_of=lambda tx_id: RelationLifecycleProjection(
                active=self.query_relations_as_of(
                    tx_id=tx_id,
                    revision_id=revision_id,
                    valid_at=valid_at,
                    active_only=True,
                ),
                pending=self.query_pending_relations_as_of(
                    tx_id=tx_id,
                    revision_id=revision_id,
                ),
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationLifecycleProjection(
            active=as_of_buckets["active"],
            pending=as_of_buckets["pending"],
        )

    def query_relation_lifecycle_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_at: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleProjection:
        tx_window_buckets = self._query_tx_window_buckets_via_as_of_projection(
            tx_start=tx_start,
            tx_end=tx_end,
            projection_as_of=lambda tx_id: self.query_relation_lifecycle_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                revision_id=revision_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationLifecycleProjection(
            active=tuple(
                sorted(
                    tx_window_buckets["active"],
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
            pending=tuple(
                sorted(
                    tx_window_buckets["pending"],
                    key=KnowledgeStore._relation_projection_sort_key,
                )
            ),
        )

    def query_relation_lifecycle_transition_for_tx_window(
        self,
        *,
        tx_from: int,
        tx_to: int,
        valid_at: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleTransition:
        transition_buckets = self._query_transition_buckets_via_as_of_diff(
            tx_from=tx_from,
            tx_to=tx_to,
            projection_from=tx_from,
            projection_to=tx_to,
            projection_as_of=lambda tx_id: self.query_relation_lifecycle_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                revision_id=revision_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        return RelationLifecycleTransition(
            tx_from=tx_from,
            tx_to=tx_to,
            entered_active=transition_buckets["entered_active"],
            exited_active=transition_buckets["exited_active"],
            entered_pending=transition_buckets["entered_pending"],
            exited_pending=transition_buckets["exited_pending"],
        )

    def query_relation_lifecycle_signatures_as_of(
        self,
        *,
        tx_id: int,
        valid_at: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleSignatureProjection:
        as_of_buckets = self._query_as_of_buckets_via_projection(
            tx_id=tx_id,
            projection_as_of=lambda tx_id: self.query_relation_lifecycle_as_of(
                tx_id=tx_id,
                valid_at=valid_at,
                revision_id=revision_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    lambda relation: relation.transaction_time.tx_id,
                    KnowledgeStore._relation_projection_sort_key,
                    KnowledgeStore._ordered_relation_bucket,
                ),
            },
        )
        projection = RelationLifecycleProjection(
            active=as_of_buckets["active"],
            pending=as_of_buckets["pending"],
        )
        return RelationLifecycleSignatureProjection(
            active=tuple(
                sorted(
                    self._relation_state_signature(
                        bucket="active",
                        relation_id=relation.relation_id,
                        relation=relation,
                    )
                    for relation in projection.active
                )
            ),
            pending=tuple(
                sorted(
                    self._relation_state_signature(
                        bucket="pending",
                        relation_id=relation.relation_id,
                        relation=relation,
                    )
                    for relation in projection.pending
                )
            ),
        )

    def query_relation_lifecycle_signatures_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_at: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleSignatureProjection:
        projection = self.query_relation_lifecycle_for_tx_window(
            tx_start=tx_start,
            tx_end=tx_end,
            valid_at=valid_at,
            revision_id=revision_id,
        )
        return RelationLifecycleSignatureProjection(
            active=tuple(
                sorted(
                    self._relation_state_signature(
                        bucket="active",
                        relation_id=relation.relation_id,
                        relation=relation,
                    )
                    for relation in projection.active
                )
            ),
            pending=tuple(
                sorted(
                    self._relation_state_signature(
                        bucket="pending",
                        relation_id=relation.relation_id,
                        relation=relation,
                    )
                    for relation in projection.pending
                )
            ),
        )

    def query_relation_lifecycle_signature_transition_for_tx_window(
        self,
        *,
        tx_start: int,
        tx_end: int,
        valid_from: datetime,
        valid_to: datetime,
        revision_id: Optional[str] = None,
    ) -> RelationLifecycleSignatureTransition:
        transition_buckets = self._query_transition_buckets_via_as_of_diff(
            tx_from=tx_start,
            tx_to=tx_end,
            projection_from=valid_from,
            projection_to=valid_to,
            projection_as_of=lambda valid_at: self.query_relation_lifecycle_signatures_for_tx_window(
                tx_start=tx_start,
                tx_end=tx_end,
                valid_at=valid_at,
                revision_id=revision_id,
            ),
            bucket_routes={
                "active": (
                    lambda projection: projection.active,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_identity_bucket,
                ),
                "pending": (
                    lambda projection: projection.pending,
                    KnowledgeStore._identity_transition_key,
                    KnowledgeStore._ordered_identity_bucket,
                ),
            },
            tx_from_label="tx_start",
            tx_to_label="tx_end",
        )
        return RelationLifecycleSignatureTransition(
            valid_from=valid_from,
            valid_to=valid_to,
            entered_active=transition_buckets["entered_active"],
            exited_active=transition_buckets["exited_active"],
            entered_pending=transition_buckets["entered_pending"],
            exited_pending=transition_buckets["exited_pending"],
        )

    def _relation_endpoints_active(
        self,
        *,
        relation: RelationEdge,
        tx_id: int,
        valid_at: datetime,
        active_winners_by_core: Dict[str, Optional[str]],
    ) -> bool:
        for endpoint_revision_id in (relation.from_revision_id, relation.to_revision_id):
            endpoint_revision = self.revisions.get(endpoint_revision_id)
            if endpoint_revision is None:
                return False
            endpoint_core_id = endpoint_revision.core_id
            winner_revision_id = active_winners_by_core.get(endpoint_core_id)
            if endpoint_core_id not in active_winners_by_core:
                winner = self.query_as_of(
                    endpoint_core_id,
                    valid_at=valid_at,
                    tx_id=tx_id,
                )
                winner_revision_id = winner.revision_id if winner is not None else None
                active_winners_by_core[endpoint_core_id] = winner_revision_id
            if winner_revision_id != endpoint_revision_id:
                return False
        return True

    def merge(self, other: "KnowledgeStore") -> MergeResult:
        merged = self.checkpoint()
        conflicts: list[MergeConflict] = []
        seen_competing_pairs: set[tuple[ConflictCode, str, str]] = set()

        for core_id, incoming_core in sorted(other.cores.items()):
            existing_core = merged.cores.get(core_id)
            if existing_core is None:
                merged.cores[core_id] = incoming_core
                continue
            if existing_core != incoming_core:
                conflicts.append(
                    MergeConflict(
                        code=ConflictCode.CORE_ID_COLLISION,
                        entity_id=core_id,
                        details="incoming core payload differs for same core_id",
                    )
                )

        for revision_id, incoming_revision in sorted(other.revisions.items()):
            existing_revision = merged.revisions.get(revision_id)
            if existing_revision is not None:
                if existing_revision != incoming_revision:
                    conflicts.append(
                        MergeConflict(
                            code=ConflictCode.REVISION_ID_COLLISION,
                            entity_id=revision_id,
                            details="incoming revision payload differs for same revision_id",
                        )
                    )
                continue

            competing_ids = self._find_competing_slots(merged, incoming_revision)
            for competing_id in competing_ids:
                competing_revision = merged.revisions[competing_id]
                conflict_code, conflict_details = self._classify_competing_slot_conflict(
                    competing_revision,
                    incoming_revision,
                )
                conflict_pair = self._competing_conflict_pair_key(
                    conflict_code=conflict_code,
                    left_revision_id=competing_revision.revision_id,
                    right_revision_id=incoming_revision.revision_id,
                )
                if conflict_pair in seen_competing_pairs:
                    continue
                seen_competing_pairs.add(conflict_pair)
                conflicts.append(
                    MergeConflict(
                        code=conflict_code,
                        entity_id=incoming_revision.core_id,
                        details=conflict_details,
                    )
                )

            merged.revisions[revision_id] = incoming_revision
            merged._revisions_by_core.setdefault(incoming_revision.core_id, set()).add(
                revision_id
            )

        # Merge active relations, then pending relations (shared logic via helper)
        for relation_id, incoming_relation in sorted(other.relations.items()):
            self._merge_single_relation(
                merged, other, relation_id, incoming_relation, conflicts,
            )

        for relation_id, incoming_relation in sorted(other._pending_relations.items()):
            # Skip if already known-identical from the active relations pass
            if relation_id in merged.relations or relation_id in merged._pending_relations:
                existing = merged.relations.get(relation_id)
                existing_pending = merged._pending_relations.get(relation_id)
                if existing == incoming_relation or existing_pending == incoming_relation:
                    continue
            self._merge_single_relation(
                merged, other, relation_id, incoming_relation, conflicts,
            )

        # Merge variant/collision histories from other (P2/P3 fix: previously ignored)
        for relation_id, other_variants in other._relation_variants.items():
            merged_variants = merged._relation_variants.setdefault(relation_id, {})
            for variant_key, variant_relation in other_variants.items():
                merged_variants.setdefault(variant_key, variant_relation)
        for relation_id, other_collision_pairs in other._relation_collision_pairs.items():
            merged._relation_collision_pairs.setdefault(relation_id, set()).update(
                other_collision_pairs
            )

        self._promote_pending_relations(merged)

        conflicts.sort(key=KnowledgeStore._merge_conflict_sort_key)
        return MergeResult(merged=merged, conflicts=tuple(conflicts))

    def _merge_single_relation(
        self,
        merged: "KnowledgeStore",
        other: "KnowledgeStore",
        relation_id: str,
        incoming_relation: "RelationEdge",
        conflicts: list,
    ) -> None:
        """Merge a single relation entry into the merged store.

        Shared logic for both active and pending relation merge passes.
        Detects orphan endpoints, tracks variants/collisions, and places
        the canonical relation into active or pending as appropriate.
        """
        existing_relation = merged.relations.get(relation_id)
        existing_pending_relation = merged._pending_relations.get(relation_id)
        is_known_identical = (
            existing_relation == incoming_relation
            or existing_pending_relation == incoming_relation
        )

        source_missing_endpoints = self._missing_relation_endpoints_from_index(
            revision_ids=other.revisions,
            incoming_relation=incoming_relation,
        )
        merged_missing_endpoints = self._missing_relation_endpoints(
            merged=merged,
            incoming_relation=incoming_relation,
        )
        missing_endpoints = tuple(
            sorted(set(source_missing_endpoints).union(merged_missing_endpoints))
        )
        if missing_endpoints and not is_known_identical:
            conflicts.append(
                MergeConflict(
                    code=ConflictCode.ORPHAN_RELATION_ENDPOINT,
                    entity_id=relation_id,
                    details=(
                        "relation references missing revision endpoints: "
                        + ", ".join(missing_endpoints)
                    ),
                )
            )

        relation_variants = merged._relation_variants.setdefault(relation_id, {})
        relation_collision_pairs = merged._relation_collision_pairs.setdefault(
            relation_id, set()
        )

        if existing_relation is not None:
            existing_relation_key = self._relation_payload_sort_key(existing_relation)
            relation_variants.setdefault(existing_relation_key, existing_relation)
        if existing_pending_relation is not None:
            existing_pending_key = self._relation_payload_sort_key(existing_pending_relation)
            relation_variants.setdefault(existing_pending_key, existing_pending_relation)

        incoming_key = self._relation_payload_sort_key(incoming_relation)
        for variant_key in sorted(tuple(relation_variants.keys())):
            if variant_key == incoming_key:
                continue
            pair_key = self._relation_collision_pair_key(variant_key, incoming_key)
            if pair_key in relation_collision_pairs:
                continue
            relation_collision_pairs.add(pair_key)
            pair_signatures = tuple(
                self._relation_payload_signature(component_key)
                for component_key in pair_key
            )
            conflicts.append(
                MergeConflict(
                    code=ConflictCode.RELATION_ID_COLLISION,
                    entity_id=relation_id,
                    details=(
                        "incoming relation payload differs for same relation_id: "
                        f"{pair_signatures[0]} vs {pair_signatures[1]}"
                    ),
                )
            )
        relation_variants.setdefault(incoming_key, incoming_relation)

        canonical_relation = relation_variants[min(relation_variants.keys())]
        canonical_missing_endpoints = self._missing_relation_endpoints(
            merged=merged,
            incoming_relation=canonical_relation,
        )
        if canonical_missing_endpoints:
            merged.relations.pop(relation_id, None)
            merged._pending_relations[relation_id] = canonical_relation
            return

        merged.relations[relation_id] = canonical_relation
        merged._pending_relations.pop(relation_id, None)

    @staticmethod
    def _merge_conflict_journal_tx_ids_from_incoming_merge_content(
        other: "KnowledgeStore",
    ) -> tuple[int, ...]:
        incoming_tx_ids = {
            revision.transaction_time.tx_id
            for revision in other.revisions.values()
        }
        incoming_tx_ids.update(
            relation.transaction_time.tx_id
            for relation in other.relations.values()
        )
        return tuple(sorted(incoming_tx_ids))

    @staticmethod
    def _derive_merge_conflict_journal_tx_id_from_incoming_merge_content(
        other: "KnowledgeStore",
    ) -> int:
        ordered_tx_ids = (
            KnowledgeStore._merge_conflict_journal_tx_ids_from_incoming_merge_content(
                other
            )
        )
        if not ordered_tx_ids:
            raise ValueError(
                "cannot derive merge-conflict journal tx_id: incoming merge content has "
                "no revisions or relations"
            )
        if len(ordered_tx_ids) != 1:
            raise ValueError(
                "cannot derive merge-conflict journal tx_id: incoming merge content is "
                f"ambiguous across tx_ids {ordered_tx_ids}"
            )
        return ordered_tx_ids[0]

    def merge_and_record_conflicts(
        self,
        other: "KnowledgeStore",
        *,
        journal_tx_id: Optional[int] = None,
    ) -> MergeResult:
        merge_result = self.merge(other)
        if journal_tx_id is not None:
            tx_id = _expect_int(journal_tx_id, "journal_tx_id", min_value=0)
            incoming_tx_ids = (
                KnowledgeStore._merge_conflict_journal_tx_ids_from_incoming_merge_content(
                    other
                )
            )
            if len(incoming_tx_ids) == 1 and tx_id != incoming_tx_ids[0]:
                raise ValueError(
                    "merge-conflict journal_tx_id override must match derived tx_id "
                    "from incoming merge content when derivation is unambiguous: "
                    f"journal_tx_id={tx_id}, derived_tx_id={incoming_tx_ids[0]}"
                )
        else:
            tx_id = KnowledgeStore._derive_merge_conflict_journal_tx_id_from_incoming_merge_content(
                other
            )
        merge_result.merged.record_merge_conflict_journal(((tx_id, merge_result),))
        return merge_result

    @staticmethod
    def _find_competing_slots(
        merged: "KnowledgeStore", incoming_revision: ClaimRevision
    ) -> tuple[str, ...]:
        revision_ids = merged._revisions_by_core.get(incoming_revision.core_id, set())
        competing_ids: list[str] = []
        for revision_id in sorted(revision_ids):
            existing = merged.revisions[revision_id]
            if (
                existing.valid_time == incoming_revision.valid_time
                and existing.transaction_time.tx_id == incoming_revision.transaction_time.tx_id
                and existing.revision_id != incoming_revision.revision_id
            ):
                competing_ids.append(existing.revision_id)
        return tuple(competing_ids)

    @staticmethod
    def _competing_conflict_pair_key(
        *,
        conflict_code: ConflictCode,
        left_revision_id: str,
        right_revision_id: str,
    ) -> tuple[ConflictCode, str, str]:
        ordered_ids = tuple(sorted([left_revision_id, right_revision_id]))
        return (conflict_code, ordered_ids[0], ordered_ids[1])

    @staticmethod
    def _classify_competing_slot_conflict(
        competing_revision: ClaimRevision,
        incoming_revision: ClaimRevision,
    ) -> tuple[ConflictCode, str]:
        if competing_revision.status != incoming_revision.status:
            ordered = sorted(
                [competing_revision, incoming_revision],
                key=lambda revision: (revision.status, revision.revision_id),
            )
            return (
                ConflictCode.COMPETING_LIFECYCLE_SAME_SLOT,
                (
                    "same core_id + valid_time + tx_id but lifecycle differs: "
                    f"{ordered[0].status}={ordered[0].revision_id} vs "
                    f"{ordered[1].status}={ordered[1].revision_id}"
                ),
            )

        conflict_ids = sorted([competing_revision.revision_id, incoming_revision.revision_id])
        return (
            ConflictCode.COMPETING_REVISION_SAME_SLOT,
            (
                "same core_id + valid_time + tx_id but different revisions: "
                f"{conflict_ids[0]} vs {conflict_ids[1]}"
            ),
        )

    @staticmethod
    def _missing_relation_endpoints(
        *,
        merged: "KnowledgeStore",
        incoming_relation: RelationEdge,
    ) -> tuple[str, ...]:
        return KnowledgeStore._missing_relation_endpoints_from_index(
            revision_ids=merged.revisions,
            incoming_relation=incoming_relation,
        )

    @staticmethod
    def _missing_relation_endpoints_from_index(
        *,
        revision_ids: Mapping[str, ClaimRevision],
        incoming_relation: RelationEdge,
    ) -> tuple[str, ...]:
        endpoint_ids = sorted(
            {incoming_relation.from_revision_id, incoming_relation.to_revision_id}
        )
        missing = [
            endpoint_revision_id
            for endpoint_revision_id in endpoint_ids
            if endpoint_revision_id not in revision_ids
        ]
        return tuple(missing)

    @staticmethod
    def _promote_pending_relations(merged: "KnowledgeStore") -> None:
        for relation_id in sorted(tuple(merged._pending_relations.keys())):
            relation = merged._pending_relations[relation_id]
            missing_endpoints = KnowledgeStore._missing_relation_endpoints(
                merged=merged,
                incoming_relation=relation,
            )
            if missing_endpoints:
                continue
            merged.relations[relation_id] = relation
            merged._pending_relations.pop(relation_id, None)

    @staticmethod
    def _select_canonical_relation_payload(
        left: RelationEdge,
        right: RelationEdge,
    ) -> RelationEdge:
        left_key = KnowledgeStore._relation_payload_sort_key(left)
        right_key = KnowledgeStore._relation_payload_sort_key(right)
        if right_key < left_key:
            return right
        return left

    @staticmethod
    def _relation_payload_sort_key(
        relation: RelationEdge,
    ) -> RelationPayloadKey:
        return (
            relation.relation_type,
            relation.from_revision_id,
            relation.to_revision_id,
            relation.transaction_time.tx_id,
            relation.transaction_time.recorded_at.isoformat(),
        )

    @staticmethod
    def _relation_collision_pair_key(
        left_key: RelationPayloadKey,
        right_key: RelationPayloadKey,
    ) -> tuple[RelationPayloadKey, RelationPayloadKey]:
        if right_key < left_key:
            return (right_key, left_key)
        return (left_key, right_key)

    @staticmethod
    def _relation_payload_signature(relation_key: RelationPayloadKey) -> str:
        return (
            f"{relation_key[0]}|{relation_key[1]}|{relation_key[2]}|"
            f"{relation_key[3]}|{relation_key[4]}"
        )

    @staticmethod
    def _relation_state_signature(
        *,
        bucket: Literal["active", "pending"],
        relation_id: str,
        relation: RelationEdge,
    ) -> RelationStateSignature:
        relation_key = KnowledgeStore._relation_payload_sort_key(relation)
        return (
            bucket,
            relation_id,
            relation_key[0],
            relation_key[1],
            relation_key[2],
            relation_key[3],
            relation_key[4],
        )

    @staticmethod
    def _revision_state_signature(
        *,
        revision_id: str,
        revision: ClaimRevision,
    ) -> RevisionStateSignature:
        return (
            revision_id,
            revision.core_id,
            revision.status,
            revision.valid_time.start.isoformat(),
            revision.valid_time.end.isoformat() if revision.valid_time.end is not None else "",
            revision.transaction_time.tx_id,
            revision.transaction_time.recorded_at.isoformat(),
        )

    def iter_core_revisions(self, core_id: str) -> Iterable[ClaimRevision]:
        for revision_id in sorted(self._revisions_by_core.get(core_id, ())):
            yield self.revisions[revision_id]
