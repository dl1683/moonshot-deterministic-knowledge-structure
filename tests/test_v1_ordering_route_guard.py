from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_SORT_KEY_ROUTE_REQUIREMENTS = {
    ("KnowledgeStore", "_select_revision_winner_as_of"): {
        "allowed_helpers": ("KnowledgeStore._revision_winner_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("KnowledgeStore", "query_revision_lifecycle_as_of"): {
        "allowed_helpers": ("KnowledgeStore._revision_projection_sort_key",),
        "minimum_helper_routed_sorts": 2,
    },
    ("KnowledgeStore", "query_revision_lifecycle_for_tx_window"): {
        "allowed_helpers": ("KnowledgeStore._revision_projection_sort_key",),
        "minimum_helper_routed_sorts": 2,
    },
    ("KnowledgeStore", "query_relations_as_of"): {
        "allowed_helpers": ("KnowledgeStore._relation_projection_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("KnowledgeStore", "query_pending_relations_as_of"): {
        "allowed_helpers": ("KnowledgeStore._relation_projection_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("KnowledgeStore", "query_relation_resolution_for_tx_window"): {
        "allowed_helpers": ("KnowledgeStore._relation_projection_sort_key",),
        "minimum_helper_routed_sorts": 2,
    },
    ("KnowledgeStore", "query_relation_lifecycle_for_tx_window"): {
        "allowed_helpers": ("KnowledgeStore._relation_projection_sort_key",),
        "minimum_helper_routed_sorts": 2,
    },
    ("KnowledgeStore", "conflict_signatures"): {
        "allowed_helpers": ("KnowledgeStore._merge_conflict_signature_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("KnowledgeStore", "conflict_signature_counts"): {
        "allowed_helpers": ("KnowledgeStore._merge_conflict_signature_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("KnowledgeStore", "conflict_code_counts"): {
        "allowed_helpers": ("KnowledgeStore._merge_conflict_code_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("MergeResult", "combine_conflict_signature_counts_from_chunks"): {
        "allowed_helpers": ("KnowledgeStore._merge_conflict_signature_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
    ("MergeResult", "combine_conflict_code_counts_from_chunks"): {
        "allowed_helpers": ("KnowledgeStore._merge_conflict_code_sort_key",),
        "minimum_helper_routed_sorts": 1,
    },
}

_ORDER_HELPER_ROUTE_REQUIREMENTS = {
    ("KnowledgeStore", "query_revision_lifecycle_transition_for_tx_window"): {
        "required_helpers": {"self._query_transition_buckets_via_as_of_diff": 1},
        "forbid_sort_calls": True,
    },
    ("KnowledgeStore", "query_relation_resolution_transition_for_tx_window"): {
        "required_helpers": {"self._query_transition_buckets_via_as_of_diff": 1},
        "forbid_sort_calls": True,
    },
    ("KnowledgeStore", "query_relation_lifecycle_transition_for_tx_window"): {
        "required_helpers": {"self._query_transition_buckets_via_as_of_diff": 1},
        "forbid_sort_calls": True,
    },
    ("KnowledgeStore", "query_merge_conflict_projection_as_of"): {
        "required_helpers": {"MergeResult.stream_conflict_summary": 1},
        "forbid_sort_calls": True,
    },
    ("KnowledgeStore", "query_merge_conflict_projection_for_tx_window"): {
        "required_helpers": {"MergeResult.stream_conflict_summary": 1},
        "forbid_sort_calls": True,
    },
}


def _load_class_methods(path: Path) -> dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    source = path.read_text(encoding="utf-8-sig")
    module = ast.parse(source, filename=str(path))
    methods: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}

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


def _iter_call_nodes(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
):
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


def test_deterministic_winner_and_projection_sort_keys_route_through_canonical_helpers() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_SORT_KEY_ROUTE_REQUIREMENTS):
        requirement = _SORT_KEY_ROUTE_REQUIREMENTS[method_key]
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        allowed_helpers = set(requirement["allowed_helpers"])
        minimum_helper_routed_sorts = requirement["minimum_helper_routed_sorts"]
        helper_routed_sorts = 0

        for call in _iter_call_nodes(method):
            if not _is_sort_call(call):
                continue

            key_argument = _get_keyword_argument(call, name="key")
            if key_argument is None:
                continue

            if isinstance(key_argument, ast.Lambda):
                failures.append(
                    f"{method_label} uses inline lambda ordering key at line {call.lineno}"
                )
                continue

            key_route = _dotted_name(key_argument)
            if key_route not in allowed_helpers:
                rendered_route = key_route or ast.dump(key_argument, include_attributes=False)
                failures.append(
                    f"{method_label} uses non-canonical ordering key {rendered_route!r} "
                    f"at line {call.lineno}; expected one of {sorted(allowed_helpers)}"
                )
                continue

            helper_routed_sorts += 1

        if helper_routed_sorts < minimum_helper_routed_sorts:
            failures.append(
                f"{method_label} has {helper_routed_sorts} helper-routed keyed sort call(s); "
                f"expected at least {minimum_helper_routed_sorts} via "
                f"{sorted(allowed_helpers)}"
            )

    assert not missing_methods, (
        "Ordering-route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic winner/projection sort-key routing drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_transition_and_merge_projection_methods_avoid_inline_sort_routes() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_ORDER_HELPER_ROUTE_REQUIREMENTS):
        requirement = _ORDER_HELPER_ROUTE_REQUIREMENTS[method_key]
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        required_helpers = requirement["required_helpers"]
        helper_counts = {helper: 0 for helper in required_helpers}
        sort_lines: list[int] = []

        for call in _iter_call_nodes(method):
            if _is_sort_call(call):
                sort_lines.append(call.lineno)
            helper_name = _dotted_name(call.func)
            if helper_name in helper_counts:
                helper_counts[helper_name] += 1

        if requirement["forbid_sort_calls"] and sort_lines:
            failures.append(
                f"{method_label} reintroduced inline sort/sorted calls at lines {sort_lines}"
            )

        for helper_name, minimum_calls in required_helpers.items():
            observed_calls = helper_counts[helper_name]
            if observed_calls < minimum_calls:
                failures.append(
                    f"{method_label} routes through {helper_name} {observed_calls} time(s); "
                    f"expected at least {minimum_calls}"
                )

    assert not missing_methods, (
        "Ordering-route helper targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic transition/merge ordering route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
