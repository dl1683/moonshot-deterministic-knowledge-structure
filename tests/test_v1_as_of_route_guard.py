from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_AS_OF_HELPER_METHODS: dict[tuple[str, str], str] = {
    (
        "KnowledgeStore",
        "query_merge_conflict_projection_as_of",
    ): "KnowledgeStore._query_as_of_buckets_via_projection",
    (
        "KnowledgeStore",
        "query_revision_lifecycle_as_of",
    ): "self._query_as_of_buckets_via_projection",
    (
        "KnowledgeStore",
        "query_relation_resolution_as_of",
    ): "self._query_as_of_buckets_via_projection",
    (
        "KnowledgeStore",
        "query_relation_lifecycle_as_of",
    ): "self._query_as_of_buckets_via_projection",
    (
        "KnowledgeStore",
        "query_relation_lifecycle_signatures_as_of",
    ): "self._query_as_of_buckets_via_projection",
}

_FORBID_SORT_CALLS = {
    ("KnowledgeStore", "query_merge_conflict_projection_as_of"),
    ("KnowledgeStore", "query_relation_resolution_as_of"),
    ("KnowledgeStore", "query_relation_lifecycle_as_of"),
}

_EXPECTED_SORT_KEY_ROUTES: dict[tuple[str, str], dict[str, int | str]] = {
    ("KnowledgeStore", "query_revision_lifecycle_as_of"): {
        "route": "KnowledgeStore._revision_projection_sort_key",
        "minimum_helper_routed_sorts": 2,
    },
}

_EXPECTED_SORT_FREE_METHODS = {
    ("KnowledgeStore", "query_relation_lifecycle_signatures_as_of"),
}

_AS_OF_FILTER_NAMES = {"tx_id", "cutoff_tx_id", "_tx_id"}


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


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def _names_in_node(node: ast.AST) -> set[str]:
    return {
        name_node.id
        for name_node in ast.walk(node)
        if isinstance(name_node, ast.Name)
    }


def test_as_of_queries_route_through_canonical_as_of_helper() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    required_helper_keywords = {
        "tx_id",
        "projection_as_of",
        "bucket_routes",
    }

    for method_key in sorted(_TARGET_AS_OF_HELPER_METHODS):
        expected_helper_route = _TARGET_AS_OF_HELPER_METHODS[method_key]
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        helper_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func) == expected_helper_route
        ]
        if len(helper_calls) != 1:
            failures.append(
                f"{method_label} routes through {expected_helper_route} "
                f"{len(helper_calls)} time(s); expected exactly 1"
            )
            continue

        helper_call = helper_calls[0]
        if helper_call.args:
            failures.append(
                f"{method_label} canonical as-of helper call unexpectedly uses "
                "positional arguments"
            )

        observed_keywords = {
            keyword.arg for keyword in helper_call.keywords if keyword.arg is not None
        }
        missing_keywords = sorted(required_helper_keywords - observed_keywords)
        if missing_keywords:
            failures.append(
                f"{method_label} canonical as-of helper call is missing keyword(s) "
                f"{missing_keywords}"
            )

        tx_id_argument = _get_keyword_argument(helper_call, name="tx_id")
        if not isinstance(tx_id_argument, ast.Name) or tx_id_argument.id != "tx_id":
            failures.append(
                f"{method_label} canonical as-of helper tx_id routing drifted from tx_id"
            )

    assert not missing_methods, (
        "As-of helper-route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic as-of helper-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_as_of_queries_reject_inline_filter_diff_and_sort_key_bypass_routes() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_TARGET_AS_OF_HELPER_METHODS):
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        sort_calls = [call for call in _iter_call_nodes(method) if _is_sort_call(call)]
        if method_key in _FORBID_SORT_CALLS and sort_calls:
            failures.append(
                f"{method_label} reintroduced inline sort/sorted routing at lines "
                f"{[call.lineno for call in sort_calls]}"
            )

        sort_key_requirement = _EXPECTED_SORT_KEY_ROUTES.get(method_key)
        if sort_key_requirement is not None:
            expected_sort_key_route = str(sort_key_requirement["route"])
            minimum_helper_routed_sorts = int(
                sort_key_requirement["minimum_helper_routed_sorts"]
            )
            helper_routed_sorts = 0
            for call in sort_calls:
                key_argument = _get_keyword_argument(call, name="key")
                if key_argument is None:
                    continue
                if isinstance(key_argument, ast.Lambda):
                    failures.append(
                        f"{method_label} reintroduced inline lambda sort-key routing "
                        f"at line {call.lineno}"
                    )
                    if isinstance(key_argument.body, ast.Tuple):
                        failures.append(
                            f"{method_label} reintroduced inline tuple lambda sort-key "
                            f"routing at line {call.lineno}"
                        )
                    continue
                if isinstance(key_argument, ast.Tuple):
                    failures.append(
                        f"{method_label} reintroduced inline tuple sort-key routing at "
                        f"line {call.lineno}"
                    )
                    continue
                observed_key_route = _dotted_name(key_argument) if key_argument is not None else None
                if observed_key_route != expected_sort_key_route:
                    failures.append(
                        f"{method_label} reintroduced non-canonical sort-key route "
                        f"{observed_key_route!r} at line {call.lineno}; expected "
                        f"{expected_sort_key_route!r}"
                    )
                    continue
                helper_routed_sorts += 1

            if helper_routed_sorts < minimum_helper_routed_sorts:
                failures.append(
                    f"{method_label} has {helper_routed_sorts} helper-routed keyed sort "
                    f"call(s); expected at least {minimum_helper_routed_sorts} via "
                    f"{expected_sort_key_route!r}"
                )

        if method_key in _EXPECTED_SORT_FREE_METHODS:
            for call in sort_calls:
                key_argument = _get_keyword_argument(call, name="key")
                if isinstance(key_argument, ast.Lambda):
                    failures.append(
                        f"{method_label} reintroduced inline lambda sort-key routing "
                        f"at line {call.lineno}"
                    )
                    if isinstance(key_argument.body, ast.Tuple):
                        failures.append(
                            f"{method_label} reintroduced inline tuple lambda sort-key "
                            f"routing at line {call.lineno}"
                        )
                elif isinstance(key_argument, ast.Tuple):
                    failures.append(
                        f"{method_label} reintroduced inline tuple sort-key routing at "
                        f"line {call.lineno}"
                    )
                elif key_argument is not None:
                    failures.append(
                        f"{method_label} reintroduced explicit sort-key routing at line "
                        f"{call.lineno}"
                    )

        for call in _iter_call_nodes(method):
            if _dotted_name(call.func) == "set":
                failures.append(
                    f"{method_label} reintroduced ad-hoc set(...) as-of diff staging "
                    f"at line {call.lineno}"
                )
            if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
                failures.append(
                    f"{method_label} reintroduced ad-hoc .difference(...) as-of diff "
                    f"routing at line {call.lineno}"
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
                f"{method_label} reintroduced ad-hoc subtraction as-of diff routing "
                f"at lines {subtraction_lines}"
            )

        as_of_filter_lines = sorted(
            {
                compare.lineno
                for compare in _iter_compare_nodes(method)
                if _AS_OF_FILTER_NAMES & _names_in_node(compare)
            }
        )
        if as_of_filter_lines:
            failures.append(
                f"{method_label} reintroduced inline as-of cutoff filtering at lines "
                f"{as_of_filter_lines}"
            )

    assert not missing_methods, (
        "As-of helper bypass guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic as-of helper bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
