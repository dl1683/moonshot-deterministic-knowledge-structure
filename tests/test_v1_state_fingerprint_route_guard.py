from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_FINGERPRINT_METHOD = ("KnowledgeStore", "query_state_fingerprint_as_of")
_TARGET_FINGERPRINT_NORMALIZER = ("DeterministicStateFingerprint", "__post_init__")

_REQUIRED_QUERY_ROUTES: dict[str, dict[str, str]] = {
    "self.query_revision_lifecycle_as_of": {
        "tx_id": "tx_id",
        "valid_at": "valid_at",
        "core_id": "core_id",
    },
    "self.query_relation_resolution_as_of": {
        "tx_id": "tx_id",
        "valid_at": "valid_at",
        "core_id": "core_id",
    },
    "self.query_relation_lifecycle_as_of": {
        "tx_id": "tx_id",
        "valid_at": "valid_at",
        "revision_id": "relation_revision_id",
    },
    "self.query_relation_lifecycle_signatures_as_of": {
        "tx_id": "tx_id",
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
}

_SORT_KEY_MINIMUM_ROUTES = {
    "KnowledgeStore._revision_projection_sort_key": 2,
    "KnowledgeStore._relation_projection_sort_key": 4,
    "KnowledgeStore._merge_conflict_signature_sort_key": 1,
    "KnowledgeStore._merge_conflict_code_sort_key": 1,
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


def test_state_fingerprint_routes_through_canonical_as_of_projection_paths() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_METHOD)
    assert method is not None, (
        "State fingerprint route guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_METHOD[0]}.{_TARGET_FINGERPRINT_METHOD[1]}"
    )

    failures: list[str] = []

    for route_name, expected_kwargs in _REQUIRED_QUERY_ROUTES.items():
        route_calls = [
            call for call in _iter_call_nodes(method) if _dotted_name(call.func) == route_name
        ]
        if len(route_calls) != 1:
            failures.append(
                f"query_state_fingerprint_as_of routes through {route_name} "
                f"{len(route_calls)} time(s); expected exactly 1"
            )
            continue

        route_call = route_calls[0]
        if route_call.args:
            failures.append(
                f"query_state_fingerprint_as_of routes through {route_name} with "
                "positional arguments; expected keyword-only routing"
            )

        for keyword_name, expected_name in expected_kwargs.items():
            value = _get_keyword_argument(route_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    f"query_state_fingerprint_as_of {route_name} {keyword_name} routing "
                    f"drifted from {expected_name}"
                )

    query_as_of_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "self.query_as_of"
    ]
    if len(query_as_of_calls) != 1:
        failures.append(
            "query_state_fingerprint_as_of routes through self.query_as_of "
            f"{len(query_as_of_calls)} time(s); expected exactly 1"
        )
    else:
        query_as_of_call = query_as_of_calls[0]
        if len(query_as_of_call.args) != 1:
            failures.append(
                "query_state_fingerprint_as_of self.query_as_of route no longer uses "
                "exactly one positional core_id argument"
            )
        elif not isinstance(query_as_of_call.args[0], ast.Name) or query_as_of_call.args[0].id != "core_id":
            failures.append(
                "query_state_fingerprint_as_of self.query_as_of positional route drifted "
                "from core_id"
            )
        for keyword_name in ("valid_at", "tx_id"):
            value = _get_keyword_argument(query_as_of_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != keyword_name:
                failures.append(
                    f"query_state_fingerprint_as_of self.query_as_of {keyword_name} "
                    f"routing drifted from {keyword_name}"
                )

    merge_projection_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "KnowledgeStore.query_merge_conflict_projection_as_of"
    ]
    if len(merge_projection_calls) != 1:
        failures.append(
            "query_state_fingerprint_as_of routes through "
            "KnowledgeStore.query_merge_conflict_projection_as_of "
            f"{len(merge_projection_calls)} time(s); expected exactly 1"
        )
    else:
        merge_projection_call = merge_projection_calls[0]
        if len(merge_projection_call.args) != 1:
            failures.append(
                "query_state_fingerprint_as_of merge-conflict route no longer uses "
                "exactly one positional merge-results stream argument"
            )
        else:
            stream_arg = merge_projection_call.args[0]
            if not isinstance(stream_arg, ast.Name) or stream_arg.id != "merge_results_by_tx":
                failures.append(
                    "query_state_fingerprint_as_of merge-conflict route positional stream "
                    "argument drifted from merge_results_by_tx"
                )
        tx_id_value = _get_keyword_argument(merge_projection_call, name="tx_id")
        if not isinstance(tx_id_value, ast.Name) or tx_id_value.id != "tx_id":
            failures.append(
                "query_state_fingerprint_as_of merge-conflict tx_id routing drifted "
                "from tx_id"
            )

    fingerprint_build_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "DeterministicStateFingerprint"
    ]
    if len(fingerprint_build_calls) != 1:
        failures.append(
            "query_state_fingerprint_as_of constructs DeterministicStateFingerprint "
            f"{len(fingerprint_build_calls)} time(s); expected exactly 1"
        )
    else:
        fingerprint_build = fingerprint_build_calls[0]
        if fingerprint_build.args:
            failures.append(
                "query_state_fingerprint_as_of DeterministicStateFingerprint construction "
                "unexpectedly uses positional arguments"
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
                    "query_state_fingerprint_as_of "
                    f"{keyword_name} projection routing drifted from {expected_name}"
                )

    assert not failures, (
        "Deterministic state fingerprint helper-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_query_rejects_inline_winner_filter_diff_and_sort_drift() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_METHOD)
    assert method is not None, (
        "State fingerprint bypass guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_METHOD[0]}.{_TARGET_FINGERPRINT_METHOD[1]}"
    )

    failures: list[str] = []

    for call in _iter_call_nodes(method):
        route_name = _dotted_name(call.func)
        if route_name in _DISALLOWED_HELPER_BYPASS_ROUTES:
            failures.append(
                "query_state_fingerprint_as_of reintroduced non-canonical helper-bypass "
                f"route {route_name!r} at line {call.lineno}"
            )
        if route_name == "set":
            failures.append(
                "query_state_fingerprint_as_of reintroduced ad-hoc set(...) diff staging "
                f"at line {call.lineno}"
            )
        if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
            failures.append(
                "query_state_fingerprint_as_of reintroduced ad-hoc .difference(...) diff "
                f"staging at line {call.lineno}"
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
            "query_state_fingerprint_as_of reintroduced ad-hoc subtraction diff routing "
            f"at lines {subtraction_lines}"
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
            "query_state_fingerprint_as_of reintroduced inline tx boundary filtering at "
            f"lines {filter_lines}"
        )

    sort_calls = [call for call in _iter_call_nodes(method) if _is_sort_call(call)]
    if sort_calls:
        failures.append(
            "query_state_fingerprint_as_of reintroduced inline sort/sorted routing at "
            f"lines {[call.lineno for call in sort_calls]}"
        )
        for sort_call in sort_calls:
            key_argument = _get_keyword_argument(sort_call, name="key")
            if isinstance(key_argument, ast.Lambda):
                failures.append(
                    "query_state_fingerprint_as_of reintroduced inline lambda sort-key "
                    f"routing at line {sort_call.lineno}"
                )
                if isinstance(key_argument.body, ast.Tuple):
                    failures.append(
                        "query_state_fingerprint_as_of reintroduced inline tuple lambda "
                        f"sort-key routing at line {sort_call.lineno}"
                    )
            elif isinstance(key_argument, ast.Tuple):
                failures.append(
                    "query_state_fingerprint_as_of reintroduced inline tuple sort-key "
                    f"routing at line {sort_call.lineno}"
                )
            elif key_argument is not None:
                failures.append(
                    "query_state_fingerprint_as_of reintroduced explicit sort-key routing "
                    f"at line {sort_call.lineno}"
                )

    assert not failures, (
        "Deterministic state fingerprint helper bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_normalization_rejects_sort_key_lambda_tuple_drift() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_NORMALIZER)
    assert method is not None, (
        "State fingerprint ordering guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_NORMALIZER[0]}.{_TARGET_FINGERPRINT_NORMALIZER[1]}"
    )

    failures: list[str] = []
    helper_routed_sorts = {route: 0 for route in _SORT_KEY_MINIMUM_ROUTES}
    keyless_sorted_calls = 0

    for call in _iter_call_nodes(method):
        if not _is_sort_call(call):
            continue
        key_argument = _get_keyword_argument(call, name="key")
        if key_argument is None:
            keyless_sorted_calls += 1
            continue
        if isinstance(key_argument, ast.Lambda):
            failures.append(
                "DeterministicStateFingerprint.__post_init__ reintroduced inline lambda "
                f"sort-key routing at line {call.lineno}"
            )
            if isinstance(key_argument.body, ast.Tuple):
                failures.append(
                    "DeterministicStateFingerprint.__post_init__ reintroduced inline "
                    f"tuple lambda sort-key routing at line {call.lineno}"
                )
            continue
        if isinstance(key_argument, ast.Tuple):
            failures.append(
                "DeterministicStateFingerprint.__post_init__ reintroduced inline tuple "
                f"sort-key routing at line {call.lineno}"
            )
            continue

        key_route = _dotted_name(key_argument)
        if key_route not in helper_routed_sorts:
            failures.append(
                "DeterministicStateFingerprint.__post_init__ reintroduced non-canonical "
                f"sort-key route {key_route!r} at line {call.lineno}"
            )
            continue
        helper_routed_sorts[key_route] += 1

    for key_route, minimum_count in _SORT_KEY_MINIMUM_ROUTES.items():
        observed_count = helper_routed_sorts[key_route]
        if observed_count < minimum_count:
            failures.append(
                "DeterministicStateFingerprint.__post_init__ has "
                f"{observed_count} sort call(s) routed via {key_route}; expected at "
                f"least {minimum_count}"
            )

    if keyless_sorted_calls < 2:
        failures.append(
            "DeterministicStateFingerprint.__post_init__ has "
            f"{keyless_sorted_calls} keyless sorted(...) call(s); expected at least 2 "
            "for relation lifecycle signatures"
        )

    assert not failures, (
        "Deterministic state fingerprint normalization ordering-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
