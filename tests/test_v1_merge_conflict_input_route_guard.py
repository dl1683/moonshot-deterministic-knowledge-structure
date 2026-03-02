from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_NORMALIZER_ROUTE = "KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection"

_TARGET_METHODS: tuple[tuple[str, str], ...] = (
    ("KnowledgeStore", "query_merge_conflict_projection_as_of"),
    ("KnowledgeStore", "query_merge_conflict_projection_for_tx_window"),
    ("KnowledgeStore", "query_merge_conflict_projection_transition_for_tx_window"),
)

_DISALLOWED_INLINE_CALL_ROUTES = {
    "list",
    "sorted",
}

_DISALLOWED_INLINE_TEXT_SNIPPETS = (
    "list(merge_results_by_tx)",
    "sorted(enumerate(",
    "key=lambda indexed_merge_result",
    "merge_results_by_tx.sort(",
)


def _load_source_and_class_methods(path: Path) -> tuple[str, dict[tuple[str, str], _DEF_OR_ASYNC]]:
    source = path.read_text(encoding="utf-8-sig")
    module = ast.parse(source, filename=str(path))
    methods: dict[tuple[str, str], _DEF_OR_ASYNC] = {}

    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(node.name, member.name)] = member

    return source, methods


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


def _iter_assignments(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            yield node


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_name(node: ast.AST | None, *, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _source_segment(source: str, function_node: _DEF_OR_ASYNC) -> str:
    segment = ast.get_source_segment(source, function_node)
    if segment is not None:
        return segment

    lines = source.splitlines()
    end_lineno = getattr(function_node, "end_lineno", function_node.lineno)
    return "\n".join(lines[function_node.lineno - 1 : end_lineno])


def _assert_projection_lambda_enumerates_merge_results_by_tx(
    *,
    projection_lambda: ast.AST | None,
    method_name: str,
    failures: list[str],
) -> None:
    if not isinstance(projection_lambda, ast.Lambda):
        failures.append(
            f"{method_name} projection_as_of route is no longer a lambda expression"
        )
        return

    enumerate_calls = [
        call
        for call in ast.walk(projection_lambda)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "enumerate"
        and len(call.args) >= 1
        and _is_name(call.args[0], name="merge_results_by_tx")
    ]
    if len(enumerate_calls) != 1:
        failures.append(
            f"{method_name} projection_as_of no longer enumerates normalized "
            f"merge_results_by_tx exactly once (observed {len(enumerate_calls)})"
        )


def test_merge_conflict_methods_route_merge_results_through_canonical_normalizer() -> None:
    source, methods = _load_source_and_class_methods(_CORE_PATH)
    failures: list[str] = []

    for class_name, method_name in _TARGET_METHODS:
        method = methods.get((class_name, method_name))
        if method is None:
            failures.append(
                "Merge-conflict input route-guard target missing from src/dks/core.py: "
                f"{class_name}.{method_name}"
            )
            continue

        normalizer_calls = [
            call for call in _iter_call_nodes(method) if _dotted_name(call.func) == _NORMALIZER_ROUTE
        ]
        if len(normalizer_calls) != 1:
            failures.append(
                f"{method_name} routes through {_NORMALIZER_ROUTE} "
                f"{len(normalizer_calls)} time(s); expected exactly 1"
            )
            continue

        normalizer_call = normalizer_calls[0]
        if normalizer_call.keywords:
            failures.append(
                f"{method_name} {_NORMALIZER_ROUTE} call uses keyword arguments; "
                "expected one positional merge_results_by_tx argument"
            )
        if len(normalizer_call.args) != 1:
            failures.append(
                f"{method_name} {_NORMALIZER_ROUTE} call uses "
                f"{len(normalizer_call.args)} positional argument(s); expected 1"
            )
        elif not _is_name(normalizer_call.args[0], name="merge_results_by_tx"):
            failures.append(
                f"{method_name} {_NORMALIZER_ROUTE} positional stream argument "
                "drifted from merge_results_by_tx"
            )

        normalizer_assignments = [
            node
            for node in _iter_assignments(method)
            if isinstance(node.value, ast.Call)
            and _dotted_name(node.value.func) == _NORMALIZER_ROUTE
            and any(_is_name(target, name="merge_results_by_tx") for target in node.targets)
        ]
        if len(normalizer_assignments) != 1:
            failures.append(
                f"{method_name} assigns normalized merge_results_by_tx "
                f"{len(normalizer_assignments)} time(s); expected exactly 1"
            )

        if method_name == "query_merge_conflict_projection_as_of":
            helper_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "KnowledgeStore._query_as_of_buckets_via_projection"
            ]
            if len(helper_calls) != 1:
                failures.append(
                    f"{method_name} routes through "
                    "KnowledgeStore._query_as_of_buckets_via_projection "
                    f"{len(helper_calls)} time(s); expected exactly 1"
                )
            elif helper_calls[0].args:
                failures.append(
                    f"{method_name} canonical as-of helper call unexpectedly uses "
                    "positional arguments"
                )
            else:
                _assert_projection_lambda_enumerates_merge_results_by_tx(
                    projection_lambda=_get_keyword_argument(
                        helper_calls[0], name="projection_as_of"
                    ),
                    method_name=method_name,
                    failures=failures,
                )

        if method_name == "query_merge_conflict_projection_for_tx_window":
            helper_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func)
                == "KnowledgeStore._query_tx_window_buckets_via_as_of_projection"
            ]
            if len(helper_calls) != 1:
                failures.append(
                    f"{method_name} routes through "
                    "KnowledgeStore._query_tx_window_buckets_via_as_of_projection "
                    f"{len(helper_calls)} time(s); expected exactly 1"
                )
            elif helper_calls[0].args:
                failures.append(
                    f"{method_name} canonical tx-window helper call unexpectedly uses "
                    "positional arguments"
                )
            else:
                _assert_projection_lambda_enumerates_merge_results_by_tx(
                    projection_lambda=_get_keyword_argument(
                        helper_calls[0], name="projection_as_of"
                    ),
                    method_name=method_name,
                    failures=failures,
                )

        if method_name == "query_merge_conflict_projection_transition_for_tx_window":
            stream_assignments = [
                node
                for node in _iter_assignments(method)
                if any(_is_name(target, name="stream") for target in node.targets)
            ]
            if len(stream_assignments) != 1:
                failures.append(
                    f"{method_name} assigns stream staging "
                    f"{len(stream_assignments)} time(s); expected exactly 1"
                )
            else:
                stream_value = stream_assignments[0].value
                if not isinstance(stream_value, ast.Call) or _dotted_name(stream_value.func) != "tuple":
                    failures.append(
                        f"{method_name} stream staging is no longer tuple(merge_results_by_tx)"
                    )
                elif len(stream_value.args) != 1 or not _is_name(
                    stream_value.args[0], name="merge_results_by_tx"
                ):
                    failures.append(
                        f"{method_name} stream staging drifted from tuple(merge_results_by_tx)"
                    )

            projection_as_of_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "KnowledgeStore.query_merge_conflict_projection_as_of"
            ]
            if len(projection_as_of_calls) != 1:
                failures.append(
                    f"{method_name} routes through "
                    "KnowledgeStore.query_merge_conflict_projection_as_of "
                    f"{len(projection_as_of_calls)} time(s); expected exactly 1"
                )
            else:
                projection_as_of_call = projection_as_of_calls[0]
                if len(projection_as_of_call.args) < 1 or not _is_name(
                    projection_as_of_call.args[0],
                    name="stream",
                ):
                    failures.append(
                        f"{method_name} projection-as-of route no longer consumes staged stream"
                    )

        method_source = _source_segment(source, method)
        if _NORMALIZER_ROUTE not in method_source:
            failures.append(
                f"{method_name} source no longer references canonical route {_NORMALIZER_ROUTE}"
            )

    assert not failures, (
        "Merge-conflict merge-results normalizer route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_merge_conflict_methods_reject_inline_iterator_materialization_and_sort_drift() -> None:
    source, methods = _load_source_and_class_methods(_CORE_PATH)
    failures: list[str] = []

    for class_name, method_name in _TARGET_METHODS:
        method = methods.get((class_name, method_name))
        if method is None:
            failures.append(
                "Merge-conflict input anti-drift target missing from src/dks/core.py: "
                f"{class_name}.{method_name}"
            )
            continue

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name in _DISALLOWED_INLINE_CALL_ROUTES:
                failures.append(
                    f"{method_name} reintroduced inline {route_name}(...) "
                    f"materialization/sort staging at line {call.lineno}"
                )

            if isinstance(call.func, ast.Attribute) and call.func.attr == "sort":
                failures.append(
                    f"{method_name} reintroduced inline .sort(...) staging "
                    f"at line {call.lineno}"
                )

        method_source = _source_segment(source, method)
        for snippet in _DISALLOWED_INLINE_TEXT_SNIPPETS:
            if snippet in method_source:
                failures.append(
                    f"{method_name} reintroduced inline merge-results normalization "
                    f"snippet {snippet!r}"
                )

        if (
            method_name != "query_merge_conflict_projection_transition_for_tx_window"
            and "tuple(merge_results_by_tx)" in method_source
        ):
            failures.append(
                f"{method_name} reintroduced inline tuple(merge_results_by_tx) staging"
            )

    assert not failures, (
        "Merge-conflict merge-results inline normalization drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
