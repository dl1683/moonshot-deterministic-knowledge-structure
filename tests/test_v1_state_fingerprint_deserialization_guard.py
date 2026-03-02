from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_DESERIALIZATION_METHODS = (
    ("DeterministicStateFingerprint", "from_canonical_payload"),
    ("DeterministicStateFingerprint", "from_canonical_json"),
    ("DeterministicStateFingerprintTransition", "from_canonical_payload"),
    ("DeterministicStateFingerprintTransition", "from_canonical_json"),
)

_REQUIRED_HELPER_MINIMUM_ROUTES: dict[tuple[str, str], dict[str, int]] = {
    ("DeterministicStateFingerprint", "from_canonical_payload"): {
        "_expect_mapping": 6,
        "_expect_exact_keys": 6,
        "_expect_list": 1,
        "_expect_sha256_hexdigest": 1,
        "_parse_payload_array": 10,
        "_canonical_json_text": 1,
        "_payload_validation_error": 3,
    },
    ("DeterministicStateFingerprint", "from_canonical_json"): {
        "_expect_str": 1,
        "json.loads": 1,
        "cls.from_canonical_payload": 1,
        "isinstance": 1,
        "_payload_validation_error": 3,
    },
    ("DeterministicStateFingerprintTransition", "from_canonical_payload"): {
        "_expect_mapping": 1,
        "_expect_exact_keys": 1,
        "_expect_int": 2,
        "_expect_sha256_hexdigest": 2,
        "_parse_payload_array": 20,
        "_canonical_json_text": 1,
        "_payload_validation_error": 2,
    },
    ("DeterministicStateFingerprintTransition", "from_canonical_json"): {
        "_expect_str": 1,
        "json.loads": 1,
        "cls.from_canonical_payload": 1,
        "isinstance": 1,
        "_payload_validation_error": 3,
    },
}

_DISALLOWED_DESERIALIZATION_ROUTES = {
    "set",
    "sorted",
    "json.dumps",
    "_canonicalize_json_value",
    "_stable_payload_hash",
    "dict",
    "list",
    "tuple",
}

_DISALLOWED_ATTRIBUTE_CALLS = {
    "difference",
    "get",
    "pop",
    "setdefault",
    "sort",
    "update",
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


def _is_zero_arg_canonical_json_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "canonical_json"
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
            and _is_zero_arg_canonical_json_call(right)
        ):
            return True
        if (
            isinstance(right, ast.Call)
            and _dotted_name(right.func) == "_canonical_json_text"
            and len(right.args) == 1
            and isinstance(right.args[0], ast.Name)
            and right.args[0].id == "payload_obj"
            and _is_zero_arg_canonical_json_call(left)
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
            and _is_zero_arg_canonical_json_call(right)
        ):
            return True
        if (
            isinstance(right, ast.Name)
            and right.id == "json_text"
            and _is_zero_arg_canonical_json_call(left)
        ):
            return True
    return False


def test_state_fingerprint_deserialization_routes_through_approved_helpers() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_DESERIALIZATION_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        route_counts: dict[str, int] = {}
        canonical_json_calls = 0

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name is not None:
                route_counts[route_name] = route_counts.get(route_name, 0) + 1
            if _is_zero_arg_canonical_json_call(call):
                canonical_json_calls += 1

        required_routes = _REQUIRED_HELPER_MINIMUM_ROUTES[method_key]
        for route_name, minimum_count in required_routes.items():
            observed_count = route_counts.get(route_name, 0)
            if observed_count < minimum_count:
                failures.append(
                    f"{method_label} routes through {route_name} {observed_count} time(s); "
                    f"expected at least {minimum_count}"
                )

        if canonical_json_calls < 1:
            failures.append(
                f"{method_label} no longer validates canonical JSON parity via "
                "zero-argument .canonical_json() route"
            )

        cls_calls = [call for call in _iter_call_nodes(method) if _dotted_name(call.func) == "cls"]
        cls_from_payload_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func) == "cls.from_canonical_payload"
        ]
        if method_key[1] == "from_canonical_payload":
            if len(cls_calls) != 1:
                failures.append(
                    f"{method_label} constructs cls {len(cls_calls)} time(s); expected exactly 1"
                )
            else:
                cls_call = cls_calls[0]
                if cls_call.args:
                    failures.append(
                        f"{method_label} cls construction unexpectedly uses positional arguments"
                    )
        else:
            if len(cls_from_payload_calls) != 1:
                failures.append(
                    f"{method_label} routes through cls.from_canonical_payload "
                    f"{len(cls_from_payload_calls)} time(s); expected exactly 1"
                )
            else:
                cls_from_payload_call = cls_from_payload_calls[0]
                if cls_from_payload_call.keywords:
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route unexpectedly "
                        "uses keyword arguments"
                    )
                if len(cls_from_payload_call.args) != 1:
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route no longer uses "
                        "exactly one positional payload argument"
                    )
                elif (
                    not isinstance(cls_from_payload_call.args[0], ast.Name)
                    or cls_from_payload_call.args[0].id != "payload"
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_payload positional route drifted "
                        "from payload"
                    )

        if method_key[1] == "from_canonical_payload":
            if not _has_payload_canonical_parity_compare(method):
                failures.append(
                    f"{method_label} no longer enforces _canonical_json_text(payload_obj) "
                    "parity against deserialized .canonical_json()"
                )
        else:
            if not _has_json_text_canonical_parity_compare(method):
                failures.append(
                    f"{method_label} no longer enforces json_text parity against "
                    "deserialized .canonical_json()"
                )

    assert not missing_methods, (
        "State fingerprint deserialization route guard targets missing from "
        f"src/dks/core.py: {', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic state fingerprint deserialization helper-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_deserialization_paths_reject_coercion_fallback_and_sort_drift() -> None:
    module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_DESERIALIZATION_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name in _DISALLOWED_DESERIALIZATION_ROUTES:
                failures.append(
                    f"{method_label} reintroduced disallowed deserialization route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if isinstance(call.func, ast.Attribute):
                if call.func.attr in _DISALLOWED_ATTRIBUTE_CALLS:
                    failures.append(
                        f"{method_label} reintroduced ad-hoc coercion/fallback route "
                        f".{call.func.attr}(...) at line {call.lineno}"
                    )

            if _is_sort_call(call):
                failures.append(
                    f"{method_label} reintroduced inline sort/sorted routing at line "
                    f"{call.lineno}"
                )
                key_argument = _get_keyword_argument(call, name="key")
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

        fallback_or_lines = sorted(
            {
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
            }
        )
        if fallback_or_lines:
            failures.append(
                f"{method_label} reintroduced ad-hoc fallback-or coercion routing at lines "
                f"{fallback_or_lines}"
            )

        ifexp_lines = sorted(
            {
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.IfExp)
            }
        )
        if ifexp_lines:
            failures.append(
                f"{method_label} reintroduced ad-hoc conditional fallback coercion at "
                f"lines {ifexp_lines}"
            )

        lambda_lines = sorted(
            {
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.Lambda)
            }
        )
        if lambda_lines:
            failures.append(
                f"{method_label} reintroduced inline lambda deserialization routing at "
                f"lines {lambda_lines}"
            )

    assert not missing_methods, (
        "State fingerprint deserialization bypass guard targets missing from "
        f"src/dks/core.py: {', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic state fingerprint deserialization bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
