from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_FINGERPRINT_TX_WINDOW_METHOD = (
    "KnowledgeStore",
    "query_state_fingerprint_for_tx_window",
)

_REQUIRED_QUERY_ROUTES: dict[str, dict[str, str]] = {
    "self.query_revision_lifecycle_for_tx_window": {
        "tx_start": "tx_start",
        "tx_end": "tx_end",
        "valid_at": "valid_at",
        "core_id": "core_id",
    },
    "self.query_relation_resolution_for_tx_window": {
        "tx_start": "tx_start",
        "tx_end": "tx_end",
        "valid_at": "valid_at",
        "core_id": "core_id",
    },
    "self.query_relation_lifecycle_for_tx_window": {
        "tx_start": "tx_start",
        "tx_end": "tx_end",
        "valid_at": "valid_at",
        "revision_id": "relation_revision_id",
    },
    "self.query_relation_lifecycle_signatures_for_tx_window": {
        "tx_start": "tx_start",
        "tx_end": "tx_end",
        "valid_at": "valid_at",
        "revision_id": "relation_revision_id",
    },
}

_DISALLOWED_HELPER_BYPASS_ROUTES = {
    "self._select_revision_winner_as_of",
    "self._query_as_of_buckets_via_projection",
    "KnowledgeStore._query_as_of_buckets_via_projection",
    "self._query_tx_window_buckets_via_as_of_projection",
    "KnowledgeStore._query_tx_window_buckets_via_as_of_projection",
    "self._query_transition_buckets_via_as_of_diff",
    "KnowledgeStore._query_transition_buckets_via_as_of_diff",
    "self.query_revision_lifecycle_as_of",
    "self.query_relation_resolution_as_of",
    "self.query_relation_lifecycle_as_of",
    "self.query_relation_lifecycle_signatures_as_of",
    "KnowledgeStore.query_merge_conflict_projection_as_of",
}


def _load_class_methods(path: Path) -> dict[tuple[str, str], _DEF_OR_ASYNC]:
    source = path.read_text(encoding="utf-8-sig")
    module = ast.parse(source, filename=str(path))
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


def _iter_call_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            yield node


def _iter_compare_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Compare):
            yield node


def _is_sort_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "sorted"
        or isinstance(call.func, ast.Attribute)
        and call.func.attr == "sort"
    )


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _names_in_node(node: ast.AST) -> set[str]:
    return {
        name_node.id
        for name_node in ast.walk(node)
        if isinstance(name_node, ast.Name)
    }


def test_state_fingerprint_tx_window_routes_through_canonical_projection_paths() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_TX_WINDOW_METHOD)
    assert method is not None, (
        "Tx-window state fingerprint route guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_TX_WINDOW_METHOD[0]}.{_TARGET_FINGERPRINT_TX_WINDOW_METHOD[1]}"
    )

    failures: list[str] = []

    for route_name, expected_kwargs in _REQUIRED_QUERY_ROUTES.items():
        route_calls = [
            call for call in _iter_call_nodes(method) if _dotted_name(call.func) == route_name
        ]
        if len(route_calls) != 1:
            failures.append(
                "query_state_fingerprint_for_tx_window routes through "
                f"{route_name} {len(route_calls)} time(s); expected exactly 1"
            )
            continue

        route_call = route_calls[0]
        if route_call.args:
            failures.append(
                "query_state_fingerprint_for_tx_window routes through "
                f"{route_name} with positional arguments; expected keyword-only routing"
            )

        for keyword_name, expected_name in expected_kwargs.items():
            value = _get_keyword_argument(route_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    "query_state_fingerprint_for_tx_window "
                    f"{route_name} {keyword_name} routing drifted from {expected_name}"
                )

    query_as_of_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "self.query_as_of"
    ]
    if len(query_as_of_calls) != 1:
        failures.append(
            "query_state_fingerprint_for_tx_window routes through self.query_as_of "
            f"{len(query_as_of_calls)} time(s); expected exactly 1"
        )
    else:
        query_as_of_call = query_as_of_calls[0]
        if len(query_as_of_call.args) != 1:
            failures.append(
                "query_state_fingerprint_for_tx_window self.query_as_of route no longer "
                "uses exactly one positional core_id argument"
            )
        elif not isinstance(query_as_of_call.args[0], ast.Name) or query_as_of_call.args[0].id != "core_id":
            failures.append(
                "query_state_fingerprint_for_tx_window self.query_as_of positional route "
                "drifted from core_id"
            )
        valid_at_value = _get_keyword_argument(query_as_of_call, name="valid_at")
        if not isinstance(valid_at_value, ast.Name) or valid_at_value.id != "valid_at":
            failures.append(
                "query_state_fingerprint_for_tx_window self.query_as_of valid_at routing "
                "drifted from valid_at"
            )
        tx_id_value = _get_keyword_argument(query_as_of_call, name="tx_id")
        if not isinstance(tx_id_value, ast.Name) or tx_id_value.id != "tx_end":
            failures.append(
                "query_state_fingerprint_for_tx_window self.query_as_of tx_id routing "
                "drifted from tx_end"
            )

    merge_projection_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "KnowledgeStore.query_merge_conflict_projection_for_tx_window"
    ]
    if len(merge_projection_calls) != 1:
        failures.append(
            "query_state_fingerprint_for_tx_window routes through "
            "KnowledgeStore.query_merge_conflict_projection_for_tx_window "
            f"{len(merge_projection_calls)} time(s); expected exactly 1"
        )
    else:
        merge_projection_call = merge_projection_calls[0]
        if len(merge_projection_call.args) != 1:
            failures.append(
                "query_state_fingerprint_for_tx_window merge-conflict route no longer "
                "uses exactly one positional merge-results stream argument"
            )
        else:
            stream_arg = merge_projection_call.args[0]
            if not isinstance(stream_arg, ast.Name) or stream_arg.id != "merge_results_by_tx":
                failures.append(
                    "query_state_fingerprint_for_tx_window merge-conflict route positional "
                    "stream argument drifted from merge_results_by_tx"
                )
        for keyword_name in ("tx_start", "tx_end"):
            value = _get_keyword_argument(merge_projection_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != keyword_name:
                failures.append(
                    "query_state_fingerprint_for_tx_window merge-conflict "
                    f"{keyword_name} routing drifted from {keyword_name}"
                )

    fingerprint_build_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "DeterministicStateFingerprint"
    ]
    if len(fingerprint_build_calls) != 1:
        failures.append(
            "query_state_fingerprint_for_tx_window constructs DeterministicStateFingerprint "
            f"{len(fingerprint_build_calls)} time(s); expected exactly 1"
        )
    else:
        fingerprint_build = fingerprint_build_calls[0]
        if fingerprint_build.args:
            failures.append(
                "query_state_fingerprint_for_tx_window DeterministicStateFingerprint "
                "construction unexpectedly uses positional arguments"
            )
        expected_projection_keywords = {
            "revision_lifecycle": "revision_lifecycle_projection",
            "relation_resolution": "relation_resolution_projection",
            "relation_lifecycle": "relation_lifecycle_projection",
            "merge_conflict_projection": "merge_conflict_projection",
            "relation_lifecycle_signatures": "relation_lifecycle_signature_projection",
        }
        for keyword_name, expected_name in expected_projection_keywords.items():
            value = _get_keyword_argument(fingerprint_build, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    "query_state_fingerprint_for_tx_window "
                    f"{keyword_name} projection routing drifted from {expected_name}"
                )

    assert not failures, (
        "Deterministic tx-window state fingerprint helper-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_tx_window_query_rejects_inline_filter_diff_and_sort_key_drift() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_TX_WINDOW_METHOD)
    assert method is not None, (
        "Tx-window state fingerprint bypass guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_TX_WINDOW_METHOD[0]}.{_TARGET_FINGERPRINT_TX_WINDOW_METHOD[1]}"
    )

    failures: list[str] = []

    for call in _iter_call_nodes(method):
        route_name = _dotted_name(call.func)
        if route_name in _DISALLOWED_HELPER_BYPASS_ROUTES:
            failures.append(
                "query_state_fingerprint_for_tx_window reintroduced non-canonical "
                f"helper-bypass route {route_name!r} at line {call.lineno}"
            )
        if route_name == "set":
            failures.append(
                "query_state_fingerprint_for_tx_window reintroduced ad-hoc set(...) diff "
                f"staging at line {call.lineno}"
            )
        if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
            failures.append(
                "query_state_fingerprint_for_tx_window reintroduced ad-hoc .difference(...) "
                f"diff staging at line {call.lineno}"
            )

    subtraction_lines = sorted(
        {
            node.lineno
            for node in ast.walk(method)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
        }
    )
    if subtraction_lines:
        failures.append(
            "query_state_fingerprint_for_tx_window reintroduced ad-hoc subtraction diff "
            f"routing at lines {subtraction_lines}"
        )

    filter_lines = sorted(
        {
            compare.lineno
            for compare in _iter_compare_nodes(method)
            if {
                "tx_id",
                "cutoff_tx_id",
                "_tx_id",
                "tx_start",
                "tx_end",
            }
            & _names_in_node(compare)
        }
    )
    if filter_lines:
        failures.append(
            "query_state_fingerprint_for_tx_window reintroduced inline tx boundary "
            f"filtering at lines {filter_lines}"
        )

    sort_calls = [call for call in _iter_call_nodes(method) if _is_sort_call(call)]
    if sort_calls:
        failures.append(
            "query_state_fingerprint_for_tx_window reintroduced inline sort/sorted routing "
            f"at lines {[call.lineno for call in sort_calls]}"
        )
        for sort_call in sort_calls:
            key_argument = _get_keyword_argument(sort_call, name="key")
            if isinstance(key_argument, ast.Lambda):
                failures.append(
                    "query_state_fingerprint_for_tx_window reintroduced inline lambda "
                    f"sort-key routing at line {sort_call.lineno}"
                )
                if isinstance(key_argument.body, ast.Tuple):
                    failures.append(
                        "query_state_fingerprint_for_tx_window reintroduced inline tuple "
                        f"lambda sort-key routing at line {sort_call.lineno}"
                    )
            elif isinstance(key_argument, ast.Tuple):
                failures.append(
                    "query_state_fingerprint_for_tx_window reintroduced inline tuple "
                    f"sort-key routing at line {sort_call.lineno}"
                )
            elif key_argument is not None:
                failures.append(
                    "query_state_fingerprint_for_tx_window reintroduced explicit sort-key "
                    f"routing at line {sort_call.lineno}"
                )

    assert not failures, (
        "Deterministic tx-window state fingerprint helper bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
