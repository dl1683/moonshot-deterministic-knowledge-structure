from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TX_VALIDATION_HELPER_ROUTE = "self._validate_merge_conflict_journal_tx_membership"
_KNOWN_TX_HISTORY_ROUTE = "self._known_tx_history_for_merge_conflict_journal"

_SNAPSHOT_AND_PREFLIGHT_UPSTREAM_ROUTES: tuple[tuple[str, str, str, str], ...] = (
    (
        "KnowledgeStore",
        "from_canonical_json",
        "cls.from_canonical_payload",
        "payload",
    ),
    (
        "KnowledgeStore",
        "from_canonical_json_file",
        "cls.from_canonical_json",
        "canonical_json",
    ),
    (
        "KnowledgeStore",
        "validate_canonical_payload",
        "cls.from_canonical_payload",
        "payload",
    ),
    (
        "KnowledgeStore",
        "validate_canonical_json",
        "cls.from_canonical_json",
        "canonical_json",
    ),
    (
        "KnowledgeStore",
        "validate_canonical_json_file",
        "cls.from_canonical_json_file",
        "canonical_json_path",
    ),
)

_DISALLOWED_TX_VALIDATION_TEXT_SNIPPETS_BY_METHOD: dict[tuple[str, str], tuple[str, ...]] = {
    ("KnowledgeStore", "from_canonical_payload"): (
        "payload_obj.get(",
        "payload_obj.setdefault(",
        "payload_obj.pop(",
        "merge_conflict_journal = payload_obj.get(",
        "self._known_tx_history_for_merge_conflict_journal(",
        "store._known_tx_history_for_merge_conflict_journal(",
        "tx_id not in known_tx_ids",
        "if not known_tx_ids",
        "if known_tx_ids is None",
        "except ValueError",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
    ),
    ("KnowledgeStore", "record_merge_conflict_journal"): (
        "merge_results_by_tx.get(",
        "merge_results_by_tx.setdefault(",
        "merge_results_by_tx.pop(",
        "self._known_tx_history_for_merge_conflict_journal(",
        "tx_id not in known_tx_ids",
        "if not known_tx_ids",
        "if known_tx_ids is None",
        "except ValueError",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
    ),
    ("KnowledgeStore", "_validate_merge_conflict_journal_tx_membership"): (
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        "error_path or",
        "or error_path",
        "known_tx_ids = ()",
        "known_tx_ids = []",
        "known_tx_ids = {}",
        "known_tx_ids = None",
        "unknown_tx_ids = ()",
        "unknown_tx_ids = []",
        "unknown_tx_ids = {}",
        "unknown_tx_ids = None",
    ),
}

_SENSITIVE_NAMES_BY_METHOD: dict[tuple[str, str], set[str]] = {
    ("KnowledgeStore", "from_canonical_payload"): {
        "payload_obj",
        "merge_conflict_journal",
        "normalized_merge_conflict_journal",
    },
    ("KnowledgeStore", "record_merge_conflict_journal"): {
        "merge_results_by_tx",
        "recorded_chunk",
    },
    ("KnowledgeStore", "_validate_merge_conflict_journal_tx_membership"): {
        "merge_results_by_tx",
        "known_tx_ids",
        "unknown_tx_ids",
        "error_path",
        "message",
    },
}

_DISALLOWED_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_DIRECT_VALIDATION_ERROR_ROUTES = {
    "SnapshotValidationError",
    "SnapshotValidationError.from_value_error",
}


def _load_module(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text(encoding="utf-8-sig")
    return source, ast.parse(source, filename=str(path))


def _load_class_methods(module: ast.Module) -> dict[tuple[str, str], _DEF_OR_ASYNC]:
    methods: dict[tuple[str, str], _DEF_OR_ASYNC] = {}
    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(node.name, member.name)] = member
    return methods


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _iter_call_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Call):
            yield member


def _iter_if_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.If):
            yield member


def _iter_raise_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Raise):
            yield member


def _iter_bool_ops(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.BoolOp):
            yield member


def _iter_ifexp_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.IfExp):
            yield member


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_name(node: ast.AST | None, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _is_literal_text(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _method_source(source: str, method: _DEF_OR_ASYNC) -> str:
    segment = ast.get_source_segment(source, method)
    return segment or ""


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def _contains_sensitive_reference(node: ast.AST, sensitive_names: set[str]) -> bool:
    for member in ast.walk(node):
        if isinstance(member, ast.Name) and member.id in sensitive_names:
            return True
        if isinstance(member, ast.Constant) and isinstance(member.value, str):
            if member.value in sensitive_names:
                return True
            if "merge_conflict_journal" in member.value:
                return True
            if "known_tx_ids" in member.value or "unknown_tx_ids" in member.value:
                return True
    return False


def _is_error_path_is_none_guard(node: ast.If) -> bool:
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and len(test.comparators) == 1
        and _is_name(test.left, "error_path")
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    )


def test_journal_tx_validation_routes_through_centralized_helper() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    helper_key = ("KnowledgeStore", "_validate_merge_conflict_journal_tx_membership")
    helper = methods.get(helper_key)
    if helper is None:
        missing_targets.append(_format_method_name(helper_key))
    else:
        known_tx_history_calls = [
            call
            for call in _iter_call_nodes(helper)
            if _dotted_name(call.func) == _KNOWN_TX_HISTORY_ROUTE
        ]
        if len(known_tx_history_calls) != 1:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership routes known tx "
                f"history through {_KNOWN_TX_HISTORY_ROUTE} {len(known_tx_history_calls)} "
                "time(s); expected exactly 1"
            )
        elif known_tx_history_calls[0].args or known_tx_history_calls[0].keywords:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership known tx "
                "history route should not use arguments"
            )

    record_key = ("KnowledgeStore", "record_merge_conflict_journal")
    record_method = methods.get(record_key)
    if record_method is None:
        missing_targets.append(_format_method_name(record_key))
    else:
        helper_calls = [
            call
            for call in _iter_call_nodes(record_method)
            if _dotted_name(call.func) == _TX_VALIDATION_HELPER_ROUTE
        ]
        if len(helper_calls) != 1:
            failures.append(
                "KnowledgeStore.record_merge_conflict_journal routes through "
                f"{_TX_VALIDATION_HELPER_ROUTE} {len(helper_calls)} time(s); expected exactly 1"
            )
        else:
            helper_call = helper_calls[0]
            if helper_call.keywords:
                failures.append(
                    "KnowledgeStore.record_merge_conflict_journal helper route unexpectedly "
                    "uses keyword arguments"
                )
            if len(helper_call.args) != 1 or not _is_name(helper_call.args[0], "recorded_chunk"):
                failures.append(
                    "KnowledgeStore.record_merge_conflict_journal helper route drifted from "
                    "self._validate_merge_conflict_journal_tx_membership(recorded_chunk)"
                )

        known_tx_history_calls = [
            call
            for call in _iter_call_nodes(record_method)
            if _dotted_name(call.func) == _KNOWN_TX_HISTORY_ROUTE
        ]
        if known_tx_history_calls:
            failures.append(
                "KnowledgeStore.record_merge_conflict_journal reintroduced inline known tx "
                "history lookup instead of centralized helper routing"
            )

    merge_record_key = ("KnowledgeStore", "merge_and_record_conflicts")
    merge_record_method = methods.get(merge_record_key)
    if merge_record_method is None:
        missing_targets.append(_format_method_name(merge_record_key))
    else:
        journal_record_calls = [
            call
            for call in _iter_call_nodes(merge_record_method)
            if _dotted_name(call.func) == "merge_result.merged.record_merge_conflict_journal"
        ]
        if len(journal_record_calls) != 1:
            failures.append(
                "KnowledgeStore.merge_and_record_conflicts should route live journal writes "
                "through merge_result.merged.record_merge_conflict_journal exactly once; "
                f"observed {len(journal_record_calls)}"
            )
        else:
            record_call = journal_record_calls[0]
            if record_call.keywords or len(record_call.args) != 1:
                failures.append(
                    "KnowledgeStore.merge_and_record_conflicts journal route shape drifted "
                    "from one positional merge-result tuple payload"
                )
            elif not isinstance(record_call.args[0], ast.Tuple):
                failures.append(
                    "KnowledgeStore.merge_and_record_conflicts journal route payload is no "
                    "longer a tuple literal"
                )

        direct_helper_calls = [
            call
            for call in _iter_call_nodes(merge_record_method)
            if _dotted_name(call.func) == _TX_VALIDATION_HELPER_ROUTE
        ]
        if direct_helper_calls:
            failures.append(
                "KnowledgeStore.merge_and_record_conflicts should keep tx-membership "
                "validation centralized through record_merge_conflict_journal"
            )

    from_payload_key = ("KnowledgeStore", "from_canonical_payload")
    from_payload_method = methods.get(from_payload_key)
    if from_payload_method is None:
        missing_targets.append(_format_method_name(from_payload_key))
    else:
        helper_calls = [
            call
            for call in _iter_call_nodes(from_payload_method)
            if _dotted_name(call.func) == "store._validate_merge_conflict_journal_tx_membership"
        ]
        if len(helper_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes merge-conflict journal tx "
                "membership through store._validate_merge_conflict_journal_tx_membership "
                f"{len(helper_calls)} time(s); expected exactly 1"
            )
        else:
            helper_call = helper_calls[0]
            if len(helper_call.args) != 1 or not _is_name(
                helper_call.args[0], "normalized_merge_conflict_journal"
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_payload helper route drifted from "
                    "normalized_merge_conflict_journal positional argument"
                )
            if len(helper_call.keywords) != 1:
                failures.append(
                    "KnowledgeStore.from_canonical_payload helper route should use exactly "
                    "one keyword argument (error_path)"
                )
            error_path = _get_keyword_argument(helper_call, name="error_path")
            if not _is_literal_text(error_path, "payload.merge_conflict_journal"):
                failures.append(
                    "KnowledgeStore.from_canonical_payload helper error_path drifted from "
                    "'payload.merge_conflict_journal'"
                )

        known_tx_history_calls = [
            call
            for call in _iter_call_nodes(from_payload_method)
            if _dotted_name(call.func)
            in {
                _KNOWN_TX_HISTORY_ROUTE,
                "store._known_tx_history_for_merge_conflict_journal",
            }
        ]
        if known_tx_history_calls:
            failures.append(
                "KnowledgeStore.from_canonical_payload reintroduced inline tx-history lookup "
                "instead of centralized helper routing"
            )

    for class_name, method_name, upstream_route, upstream_arg in (
        _SNAPSHOT_AND_PREFLIGHT_UPSTREAM_ROUTES
    ):
        method_key = (class_name, method_name)
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        upstream_calls = [
            call for call in _iter_call_nodes(method) if _dotted_name(call.func) == upstream_route
        ]
        if len(upstream_calls) != 1:
            failures.append(
                f"{method_label} routes through {upstream_route} {len(upstream_calls)} time(s); "
                "expected exactly 1"
            )
        else:
            upstream_call = upstream_calls[0]
            if upstream_call.keywords:
                failures.append(
                    f"{method_label} {upstream_route} route unexpectedly uses keyword arguments"
                )
            if len(upstream_call.args) != 1 or not _is_name(upstream_call.args[0], upstream_arg):
                failures.append(
                    f"{method_label} {upstream_route} route drifted from positional {upstream_arg}"
                )

        direct_helper_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func)
            in {
                _TX_VALIDATION_HELPER_ROUTE,
                "cls._validate_merge_conflict_journal_tx_membership",
                "store._validate_merge_conflict_journal_tx_membership",
            }
        ]
        if direct_helper_calls:
            failures.append(
                f"{method_label} should route tx-membership validation through {upstream_route} "
                "rather than calling _validate_merge_conflict_journal_tx_membership directly"
            )

    assert not missing_targets, (
        "Journal tx-validation route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Merge-conflict journal tx-validation helper route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_journal_tx_validation_paths_reject_fallback_and_error_bypass_drift() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    helper_key = ("KnowledgeStore", "_validate_merge_conflict_journal_tx_membership")
    helper_method = methods.get(helper_key)
    if helper_method is None:
        missing_targets.append(_format_method_name(helper_key))
    else:
        helper_source = _method_source(source, helper_method)
        for required_snippet in (
            "known_tx_ids = self._known_tx_history_for_merge_conflict_journal()",
            "if tx_id not in known_tx_ids",
            "if unknown_tx_ids:",
            "if error_path is None:",
            "raise ValueError(message)",
            "raise _payload_validation_error(error_path, message)",
        ):
            if required_snippet not in helper_source:
                failures.append(
                    "KnowledgeStore._validate_merge_conflict_journal_tx_membership missing "
                    f"required fail-closed snippet {required_snippet!r}"
                )

        unknown_tx_guards = [
            if_node
            for if_node in _iter_if_nodes(helper_method)
            if _is_name(if_node.test, "unknown_tx_ids")
        ]
        if len(unknown_tx_guards) != 1:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership should gate "
                f"error routing with `if unknown_tx_ids:` exactly once; observed {len(unknown_tx_guards)}"
            )

        error_path_guards = [
            if_node for if_node in _iter_if_nodes(helper_method) if _is_error_path_is_none_guard(if_node)
        ]
        if len(error_path_guards) != 1:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership should branch on "
                "`if error_path is None:` exactly once; observed "
                f"{len(error_path_guards)}"
            )

        value_error_raises = [
            raise_node
            for raise_node in _iter_raise_nodes(helper_method)
            if isinstance(raise_node.exc, ast.Call)
            and _dotted_name(raise_node.exc.func) == "ValueError"
        ]
        if len(value_error_raises) != 1:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership should raise "
                f"ValueError exactly once for live recording paths; observed {len(value_error_raises)}"
            )
        else:
            value_error_raise = value_error_raises[0]
            value_error_call = value_error_raise.exc
            if (
                len(value_error_call.args) != 1
                or not _is_name(value_error_call.args[0], "message")
                or value_error_call.keywords
            ):
                failures.append(
                    "KnowledgeStore._validate_merge_conflict_journal_tx_membership ValueError "
                    "route drifted from ValueError(message)"
                )

        payload_error_raises = [
            raise_node
            for raise_node in _iter_raise_nodes(helper_method)
            if isinstance(raise_node.exc, ast.Call)
            and _dotted_name(raise_node.exc.func) == "_payload_validation_error"
        ]
        if len(payload_error_raises) != 1:
            failures.append(
                "KnowledgeStore._validate_merge_conflict_journal_tx_membership should raise "
                "_payload_validation_error exactly once for snapshot/preflight paths; observed "
                f"{len(payload_error_raises)}"
            )
        else:
            payload_error_raise = payload_error_raises[0]
            payload_error_call = payload_error_raise.exc
            if (
                len(payload_error_call.args) != 2
                or not _is_name(payload_error_call.args[0], "error_path")
                or not _is_name(payload_error_call.args[1], "message")
                or payload_error_call.keywords
            ):
                failures.append(
                    "KnowledgeStore._validate_merge_conflict_journal_tx_membership payload "
                    "error route drifted from _payload_validation_error(error_path, message)"
                )

    for method_key, disallowed_snippets in _DISALLOWED_TX_VALIDATION_TEXT_SNIPPETS_BY_METHOD.items():
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in disallowed_snippets:
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed tx-validation fallback snippet "
                    f"{snippet!r}"
                )

        sensitive_names = _SENSITIVE_NAMES_BY_METHOD[method_key]
        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)

            if route_name in _DISALLOWED_DIRECT_VALIDATION_ERROR_ROUTES:
                failures.append(
                    f"{method_label} reintroduced direct SnapshotValidationError route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_ACCESSORS
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive accessor .{call.func.attr}(...) "
                    f"at line {call.lineno}"
                )

            if (
                route_name is not None
                and route_name.startswith("_expect_")
                and _get_keyword_argument(call, name="default") is not None
            ):
                failures.append(
                    f"{method_label} reintroduced _expect_* default fallback route at line "
                    f"{call.lineno}"
                )

        for bool_op in _iter_bool_ops(method):
            if not isinstance(bool_op.op, ast.Or):
                continue
            if any(
                _contains_sensitive_reference(value, sensitive_names)
                for value in bool_op.values
            ):
                failures.append(
                    f"{method_label} reintroduced permissive fallback `or` route at line "
                    f"{bool_op.lineno}"
                )

        for if_exp in _iter_ifexp_nodes(method):
            if _contains_sensitive_reference(if_exp, sensitive_names):
                failures.append(
                    f"{method_label} reintroduced conditional fallback coercion at line "
                    f"{if_exp.lineno}"
                )

    assert not missing_targets, (
        "Journal tx-validation fallback guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Merge-conflict journal tx-validation fallback/error-bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
