from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_SNAPSHOT_METHODS = (
    ("KnowledgeStore", "as_canonical_payload"),
    ("KnowledgeStore", "as_canonical_json"),
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "from_canonical_json"),
)

_REQUIRED_HELPER_MINIMUM_ROUTES: dict[tuple[str, str], dict[str, int]] = {
    ("KnowledgeStore", "as_canonical_payload"): {
        "_relation_payload_key_as_payload": 1,
        "_relation_collision_pair_as_payload": 1,
    },
    ("KnowledgeStore", "as_canonical_json"): {
        "_canonical_json_text": 1,
        "self.as_canonical_payload": 1,
    },
    ("KnowledgeStore", "from_canonical_payload"): {
        "_expect_mapping": 4,
        "_expect_exact_keys": 4,
        "_parse_payload_array": 4,
        "_expect_list": 4,
        "_expect_sha256_hexdigest": 2,
        "_relation_payload_key_from_payload": 1,
        "_relation_edge_from_store_snapshot_payload": 1,
        "_relation_collision_pair_from_payload": 1,
        "cls._missing_relation_endpoints_from_index": 1,
        "cls._relation_payload_sort_key": 1,
        "cls._relation_collision_pair_key": 1,
        "_canonical_json_text": 1,
        "store.as_canonical_json": 1,
        "_payload_validation_error": 10,
    },
    ("KnowledgeStore", "from_canonical_json"): {
        "_expect_str": 1,
        "json.loads": 1,
        "isinstance": 1,
        "cls.from_canonical_payload": 1,
        "store.as_canonical_json": 1,
        "_payload_validation_error": 3,
    },
}

_SORT_KEY_MINIMUM_ROUTES: dict[tuple[str, str], dict[str, int]] = {
    ("KnowledgeStore", "as_canonical_payload"): {
        "KnowledgeStore._core_projection_sort_key": 1,
        "KnowledgeStore._revision_projection_sort_key": 1,
        "KnowledgeStore._relation_projection_sort_key": 2,
    },
}

_KEYLESS_SORTED_MINIMUMS: dict[tuple[str, str], int] = {
    ("KnowledgeStore", "as_canonical_payload"): 4,
}

_DISALLOWED_ROUTE_CALLS = {
    "json.dumps",
    "_canonicalize_json_value",
    "_stable_payload_hash",
}

_DISALLOWED_DESERIALIZATION_COERCION_ROUTES = {"dict", "list", "tuple"}


def _load_module(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8-sig")
    return ast.parse(source, filename=str(path))


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


def _iter_call_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            yield node


def _iter_return_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Return):
            yield node


def _iter_compare_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Compare):
            yield node


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_sort_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "sorted"
        or isinstance(call.func, ast.Attribute)
        and call.func.attr == "sort"
    )


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def _is_zero_arg_as_canonical_json_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "as_canonical_json"
        and not node.args
        and not node.keywords
    )


def _has_payload_canonical_parity_compare(method: _DEF_OR_ASYNC) -> bool:
    for compare in _iter_compare_nodes(method):
        if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.NotEq):
            continue
        if len(compare.comparators) != 1:
            continue
        left = compare.left
        right = compare.comparators[0]
        if (
            isinstance(left, ast.Call)
            and _dotted_name(left.func) == "_canonical_json_text"
            and len(left.args) == 1
            and isinstance(left.args[0], ast.Name)
            and left.args[0].id == "payload_obj"
            and _is_zero_arg_as_canonical_json_call(right)
        ):
            return True
        if (
            isinstance(right, ast.Call)
            and _dotted_name(right.func) == "_canonical_json_text"
            and len(right.args) == 1
            and isinstance(right.args[0], ast.Name)
            and right.args[0].id == "payload_obj"
            and _is_zero_arg_as_canonical_json_call(left)
        ):
            return True
    return False


def _has_json_text_canonical_parity_compare(method: _DEF_OR_ASYNC) -> bool:
    for compare in _iter_compare_nodes(method):
        if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.NotEq):
            continue
        if len(compare.comparators) != 1:
            continue
        left = compare.left
        right = compare.comparators[0]
        if (
            isinstance(left, ast.Name)
            and left.id == "json_text"
            and _is_zero_arg_as_canonical_json_call(right)
        ):
            return True
        if (
            isinstance(right, ast.Name)
            and right.id == "json_text"
            and _is_zero_arg_as_canonical_json_call(left)
        ):
            return True
    return False


def test_store_snapshot_routes_through_approved_helpers() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_SNAPSHOT_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        route_counts: dict[str, int] = {}
        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name is not None:
                route_counts[route_name] = route_counts.get(route_name, 0) + 1

        required_routes = _REQUIRED_HELPER_MINIMUM_ROUTES[method_key]
        for route_name, minimum_count in required_routes.items():
            observed_count = route_counts.get(route_name, 0)
            if observed_count < minimum_count:
                failures.append(
                    f"{method_label} routes through {route_name} {observed_count} time(s); "
                    f"expected at least {minimum_count}"
                )

        if method_key[1] == "as_canonical_json":
            return_nodes = list(_iter_return_nodes(method))
            if len(return_nodes) != 1:
                failures.append(
                    f"{method_label} has {len(return_nodes)} return statement(s); "
                    "expected exactly 1 helper-route return"
                )
            else:
                return_value = return_nodes[0].value
                if not isinstance(return_value, ast.Call):
                    failures.append(
                        f"{method_label} no longer returns a helper call expression"
                    )
                elif _dotted_name(return_value.func) != "_canonical_json_text":
                    failures.append(
                        f"{method_label} helper route drifted from _canonical_json_text "
                        f"to {_dotted_name(return_value.func)!r}"
                    )
                else:
                    if return_value.keywords:
                        failures.append(
                            f"{method_label} canonical helper route unexpectedly uses "
                            "keyword arguments"
                        )
                    if len(return_value.args) != 1:
                        failures.append(
                            f"{method_label} canonical helper route no longer uses "
                            "exactly one positional payload argument"
                        )
                    else:
                        payload_route = return_value.args[0]
                        if not isinstance(payload_route, ast.Call):
                            failures.append(
                                f"{method_label} canonical helper payload route drifted "
                                "from self.as_canonical_payload()"
                            )
                        elif _dotted_name(payload_route.func) != "self.as_canonical_payload":
                            failures.append(
                                f"{method_label} canonical helper payload route drifted "
                                "from self.as_canonical_payload()"
                            )
                        elif payload_route.args or payload_route.keywords:
                            failures.append(
                                f"{method_label} self.as_canonical_payload helper route "
                                "unexpectedly uses arguments"
                            )

        if method_key[1] == "from_canonical_payload":
            cls_calls = [
                call for call in _iter_call_nodes(method) if _dotted_name(call.func) == "cls"
            ]
            if len(cls_calls) != 1:
                failures.append(
                    f"{method_label} constructs cls {len(cls_calls)} time(s); expected "
                    "exactly 1"
                )
            else:
                cls_call = cls_calls[0]
                if cls_call.args or cls_call.keywords:
                    failures.append(
                        f"{method_label} cls construction unexpectedly uses arguments"
                    )
            if not _has_payload_canonical_parity_compare(method):
                failures.append(
                    f"{method_label} no longer enforces _canonical_json_text(payload_obj) "
                    "parity against deserialized .as_canonical_json()"
                )

        if method_key[1] == "from_canonical_json":
            from_payload_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "cls.from_canonical_payload"
            ]
            if len(from_payload_calls) != 1:
                failures.append(
                    f"{method_label} routes through cls.from_canonical_payload "
                    f"{len(from_payload_calls)} time(s); expected exactly 1"
                )
            else:
                from_payload_call = from_payload_calls[0]
                if from_payload_call.keywords:
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route unexpectedly "
                        "uses keyword arguments"
                    )
                if len(from_payload_call.args) != 1:
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route no longer uses "
                        "exactly one positional payload argument"
                    )
                elif (
                    not isinstance(from_payload_call.args[0], ast.Name)
                    or from_payload_call.args[0].id != "payload"
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_payload positional route "
                        "drifted from payload"
                    )
            if not _has_json_text_canonical_parity_compare(method):
                failures.append(
                    f"{method_label} no longer enforces json_text parity against "
                    "deserialized .as_canonical_json()"
                )

    assert not missing_methods, (
        "Store snapshot route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot helper-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_paths_reject_inline_json_coercion_and_sort_key_drift() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_SNAPSHOT_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        expected_sort_routes = _SORT_KEY_MINIMUM_ROUTES.get(method_key)
        helper_routed_sorts = (
            {route_name: 0 for route_name in expected_sort_routes}
            if expected_sort_routes is not None
            else {}
        )
        keyless_sorted_calls = 0

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name in _DISALLOWED_ROUTE_CALLS:
                failures.append(
                    f"{method_label} reintroduced disallowed snapshot route "
                    f"{route_name!r} at line {call.lineno}"
                )
            if (
                method_key[1].startswith("from_canonical_")
                and route_name in _DISALLOWED_DESERIALIZATION_COERCION_ROUTES
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc deserialization coercion route "
                    f"{route_name!r} at line {call.lineno}"
                )
            if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
                failures.append(
                    f"{method_label} reintroduced ad-hoc .difference(...) diff staging "
                    f"at line {call.lineno}"
                )

            if not _is_sort_call(call):
                continue

            key_argument = _get_keyword_argument(call, name="key")
            if expected_sort_routes is None:
                failures.append(
                    f"{method_label} reintroduced inline sort/sorted routing at line "
                    f"{call.lineno}"
                )
                if isinstance(key_argument, ast.Lambda):
                    failures.append(
                        f"{method_label} reintroduced inline lambda sort-key routing at "
                        f"line {call.lineno}"
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
                continue

            if key_argument is None:
                keyless_sorted_calls += 1
                continue

            if isinstance(key_argument, ast.Lambda):
                failures.append(
                    f"{method_label} reintroduced inline lambda sort-key routing at "
                    f"line {call.lineno}"
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

            key_route = _dotted_name(key_argument)
            if key_route not in helper_routed_sorts:
                failures.append(
                    f"{method_label} reintroduced non-canonical sort-key route "
                    f"{key_route!r} at line {call.lineno}"
                )
                continue
            helper_routed_sorts[key_route] += 1

        subtraction_lines = sorted(
            {
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)
            }
        )
        if subtraction_lines:
            failures.append(
                f"{method_label} reintroduced ad-hoc subtraction diff routing at lines "
                f"{subtraction_lines}"
            )

        lambda_lines = sorted(
            {node.lineno for node in ast.walk(method) if isinstance(node, ast.Lambda)}
        )
        if lambda_lines:
            failures.append(
                f"{method_label} reintroduced inline lambda snapshot routing at lines "
                f"{lambda_lines}"
            )

        if expected_sort_routes is None:
            continue

        for route_name, minimum_count in expected_sort_routes.items():
            observed_count = helper_routed_sorts[route_name]
            if observed_count < minimum_count:
                failures.append(
                    f"{method_label} has {observed_count} sort call(s) routed via "
                    f"{route_name}; expected at least {minimum_count}"
                )

        expected_keyless_sorted = _KEYLESS_SORTED_MINIMUMS[method_key]
        if keyless_sorted_calls < expected_keyless_sorted:
            failures.append(
                f"{method_label} has {keyless_sorted_calls} keyless sorted(...) call(s); "
                f"expected at least {expected_keyless_sorted}"
            )

    assert not missing_methods, (
        "Store snapshot bypass guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
