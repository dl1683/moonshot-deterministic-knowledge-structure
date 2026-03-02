from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_TRANSITION_METHODS: dict[tuple[str, str], str] = {
    (
        "KnowledgeStore",
        "query_merge_conflict_projection_transition_for_tx_window",
    ): "KnowledgeStore._query_transition_buckets_via_as_of_diff",
    (
        "KnowledgeStore",
        "query_revision_lifecycle_transition_for_tx_window",
    ): "self._query_transition_buckets_via_as_of_diff",
    (
        "KnowledgeStore",
        "query_relation_resolution_transition_for_tx_window",
    ): "self._query_transition_buckets_via_as_of_diff",
    (
        "KnowledgeStore",
        "query_relation_lifecycle_transition_for_tx_window",
    ): "self._query_transition_buckets_via_as_of_diff",
    (
        "KnowledgeStore",
        "query_relation_lifecycle_signature_transition_for_tx_window",
    ): "self._query_transition_buckets_via_as_of_diff",
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


def test_transition_queries_route_through_canonical_transition_helper() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    required_helper_keywords = {
        "tx_from",
        "tx_to",
        "projection_from",
        "projection_to",
        "projection_as_of",
        "bucket_routes",
    }

    for method_key in sorted(_TARGET_TRANSITION_METHODS):
        expected_helper_route = _TARGET_TRANSITION_METHODS[method_key]
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
                f"{method_label} canonical transition helper call unexpectedly uses "
                "positional arguments"
            )

        observed_keywords = {
            keyword.arg for keyword in helper_call.keywords if keyword.arg is not None
        }
        missing_keywords = sorted(required_helper_keywords - observed_keywords)
        if missing_keywords:
            failures.append(
                f"{method_label} canonical transition helper call is missing keyword(s) "
                f"{missing_keywords}"
            )

    assert not missing_methods, (
        "Transition helper-route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic transition helper-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_transition_queries_reject_inline_set_diff_and_sort_key_bypass_routes() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_TARGET_TRANSITION_METHODS):
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        for call in _iter_call_nodes(method):
            if _is_sort_call(call):
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
                elif key_argument is None:
                    failures.append(
                        f"{method_label} reintroduced inline sort/sorted routing at line "
                        f"{call.lineno}"
                    )
                else:
                    failures.append(
                        f"{method_label} reintroduced explicit sort-key routing at line "
                        f"{call.lineno}"
                    )

            if _dotted_name(call.func) == "set":
                failures.append(
                    f"{method_label} reintroduced ad-hoc set(...) transition diff staging "
                    f"at line {call.lineno}"
                )

            if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
                failures.append(
                    f"{method_label} reintroduced ad-hoc .difference(...) transition diff "
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
                f"{method_label} reintroduced ad-hoc subtraction transition diff routing "
                f"at lines {subtraction_lines}"
            )

    assert not missing_methods, (
        "Transition helper bypass guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic transition helper bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
