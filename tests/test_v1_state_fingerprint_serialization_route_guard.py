from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_CANONICAL_ROUTE_METHODS: dict[tuple[str, str], str] = {
    ("DeterministicStateFingerprint", "as_canonical_payload"): "self.as_payload",
    ("DeterministicStateFingerprint", "canonical_json"): "_canonical_json_text",
    ("DeterministicStateFingerprint", "as_canonical_json"): "self.canonical_json",
    (
        "DeterministicStateFingerprintTransition",
        "as_canonical_payload",
    ): "self.as_payload",
    ("DeterministicStateFingerprintTransition", "canonical_json"): "_canonical_json_text",
    (
        "DeterministicStateFingerprintTransition",
        "as_canonical_json",
    ): "self.canonical_json",
}

_TARGET_SERIALIZATION_PAYLOAD_METHODS = (
    ("DeterministicStateFingerprint", "as_payload"),
    ("DeterministicStateFingerprintTransition", "as_payload"),
)

_PAYLOAD_SORT_KEY_MINIMUM_ROUTES: dict[tuple[str, str], dict[str, int]] = {
    ("DeterministicStateFingerprint", "as_payload"): {
        "KnowledgeStore._revision_projection_sort_key": 2,
        "KnowledgeStore._relation_projection_sort_key": 4,
        "KnowledgeStore._merge_conflict_signature_sort_key": 1,
        "KnowledgeStore._merge_conflict_code_sort_key": 1,
    },
    ("DeterministicStateFingerprintTransition", "as_payload"): {
        "KnowledgeStore._revision_projection_sort_key": 4,
        "KnowledgeStore._relation_projection_sort_key": 8,
        "KnowledgeStore._merge_conflict_signature_sort_key": 2,
        "KnowledgeStore._merge_conflict_code_sort_key": 2,
    },
}

_PAYLOAD_KEYLESS_SORT_MINIMUMS: dict[tuple[str, str], int] = {
    ("DeterministicStateFingerprint", "as_payload"): 2,
    ("DeterministicStateFingerprintTransition", "as_payload"): 4,
}

_DISALLOWED_SERIALIZATION_ROUTES = {
    "set",
    "json.dumps",
    "_stable_payload_hash",
}


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


def _load_module_functions(module: ast.Module) -> dict[str, _DEF_OR_ASYNC]:
    functions: dict[str, _DEF_OR_ASYNC] = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
    return functions


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


def test_state_fingerprint_canonical_serialization_routes_through_approved_helpers() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_TARGET_CANONICAL_ROUTE_METHODS):
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        return_nodes = list(_iter_return_nodes(method))
        if len(return_nodes) != 1:
            failures.append(
                f"{method_label} has {len(return_nodes)} return statement(s); "
                "expected exactly 1 deterministic helper-route return"
            )
            continue

        return_node = return_nodes[0]
        return_value = return_node.value
        if not isinstance(return_value, ast.Call):
            failures.append(
                f"{method_label} no longer returns a helper call expression"
            )
            continue

        expected_route = _TARGET_CANONICAL_ROUTE_METHODS[method_key]
        observed_route = _dotted_name(return_value.func)
        if observed_route != expected_route:
            failures.append(
                f"{method_label} helper route drifted from {expected_route} to "
                f"{observed_route!r}"
            )
            continue

        if method_key[1] == "canonical_json":
            if return_value.keywords:
                failures.append(
                    f"{method_label} canonical helper call unexpectedly uses keyword "
                    "arguments"
                )
            if len(return_value.args) != 1:
                failures.append(
                    f"{method_label} canonical helper call no longer uses exactly one "
                    "positional payload argument"
                )
                continue

            payload_route = return_value.args[0]
            if not isinstance(payload_route, ast.Call):
                failures.append(
                    f"{method_label} canonical helper payload route drifted from "
                    "self.as_payload()"
                )
                continue
            if _dotted_name(payload_route.func) != "self.as_payload":
                failures.append(
                    f"{method_label} canonical helper payload route drifted from "
                    f"self.as_payload() to {_dotted_name(payload_route.func)!r}"
                )
            if payload_route.args or payload_route.keywords:
                failures.append(
                    f"{method_label} self.as_payload helper payload route unexpectedly "
                    "uses arguments"
                )
        else:
            if return_value.args or return_value.keywords:
                failures.append(
                    f"{method_label} helper route unexpectedly uses arguments"
                )

    assert not missing_methods, (
        "State fingerprint serialization route guard targets missing from "
        f"src/dks/core.py: {', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic state fingerprint canonical serialization helper-route drift "
        "detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_canonical_json_helper_contract_is_locked() -> None:
    module = _load_module(_CORE_PATH)
    functions = _load_module_functions(module)
    helper = functions.get("_canonical_json_text")
    assert helper is not None, (
        "Canonical JSON helper route guard target missing from src/dks/core.py: "
        "_canonical_json_text"
    )

    failures: list[str] = []
    return_nodes = list(_iter_return_nodes(helper))
    if len(return_nodes) != 1:
        failures.append(
            f"_canonical_json_text has {len(return_nodes)} return statement(s); "
            "expected exactly 1"
        )
    else:
        return_value = return_nodes[0].value
        if not isinstance(return_value, ast.Call):
            failures.append("_canonical_json_text no longer returns a call expression")
        elif _dotted_name(return_value.func) != "json.dumps":
            failures.append(
                "_canonical_json_text no longer routes through json.dumps"
            )
        else:
            if len(return_value.args) != 1:
                failures.append(
                    "_canonical_json_text json.dumps route no longer uses exactly one "
                    "positional payload argument"
                )
            elif (
                not isinstance(return_value.args[0], ast.Name)
                or return_value.args[0].id != "payload"
            ):
                failures.append(
                    "_canonical_json_text json.dumps positional argument drifted from "
                    "payload"
                )

            sort_keys_value = _get_keyword_argument(return_value, name="sort_keys")
            if not (
                isinstance(sort_keys_value, ast.Constant)
                and sort_keys_value.value is True
            ):
                failures.append(
                    "_canonical_json_text json.dumps sort_keys routing drifted from "
                    "literal True"
                )

            separators_value = _get_keyword_argument(return_value, name="separators")
            if not (
                isinstance(separators_value, ast.Tuple)
                and len(separators_value.elts) == 2
                and isinstance(separators_value.elts[0], ast.Constant)
                and separators_value.elts[0].value == ","
                and isinstance(separators_value.elts[1], ast.Constant)
                and separators_value.elts[1].value == ":"
            ):
                failures.append(
                    "_canonical_json_text json.dumps separators routing drifted from "
                    "(',', ':')"
                )

            unexpected_keywords = sorted(
                keyword.arg
                for keyword in return_value.keywords
                if keyword.arg is not None
                and keyword.arg not in {"sort_keys", "separators"}
            )
            if unexpected_keywords:
                failures.append(
                    "_canonical_json_text json.dumps route has unexpected keyword(s) "
                    f"{unexpected_keywords}"
                )

    assert not failures, (
        "Deterministic state fingerprint canonical JSON helper-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_serialization_paths_reject_inline_json_diff_and_sort_drift() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    target_methods = sorted(
        set(_TARGET_CANONICAL_ROUTE_METHODS) | set(_TARGET_SERIALIZATION_PAYLOAD_METHODS)
    )

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in target_methods:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        expected_sort_routes = _PAYLOAD_SORT_KEY_MINIMUM_ROUTES.get(method_key)
        helper_routed_sorts = (
            {route_name: 0 for route_name in expected_sort_routes}
            if expected_sort_routes is not None
            else {}
        )
        keyless_sorted_calls = 0

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name in _DISALLOWED_SERIALIZATION_ROUTES:
                failures.append(
                    f"{method_label} reintroduced disallowed serialization route "
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
                    f"{method_label} reintroduced inline tuple sort-key routing at line "
                    f"{call.lineno}"
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

        if expected_sort_routes is None:
            continue

        for route_name, minimum_count in expected_sort_routes.items():
            observed_count = helper_routed_sorts[route_name]
            if observed_count < minimum_count:
                failures.append(
                    f"{method_label} has {observed_count} sort call(s) routed via "
                    f"{route_name}; expected at least {minimum_count}"
                )

        expected_keyless_sorted = _PAYLOAD_KEYLESS_SORT_MINIMUMS[method_key]
        if keyless_sorted_calls < expected_keyless_sorted:
            failures.append(
                f"{method_label} has {keyless_sorted_calls} keyless sorted(...) call(s); "
                f"expected at least {expected_keyless_sorted}"
            )

    assert not missing_methods, (
        "State fingerprint serialization bypass guard targets missing from "
        f"src/dks/core.py: {', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic state fingerprint serialization bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
