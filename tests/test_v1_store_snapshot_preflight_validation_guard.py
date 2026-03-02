from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_PREFLIGHT_METHODS = (
    ("KnowledgeStore", "_snapshot_validation_report_from_store"),
    ("KnowledgeStore", "validate_canonical_payload"),
    ("KnowledgeStore", "validate_canonical_json"),
    ("KnowledgeStore", "validate_canonical_json_file"),
)

_ALLOWED_PREFLIGHT_ROUTES_BY_METHOD: dict[tuple[str, str], dict[str, int]] = {
    ("KnowledgeStore", "_snapshot_validation_report_from_store"): {
        "store.as_canonical_payload": 1,
        "_canonical_json_text": 1,
        "SnapshotValidationReport": 1,
        "_knowledge_store_canonical_content_digest": 1,
    },
    ("KnowledgeStore", "validate_canonical_payload"): {
        "cls.from_canonical_payload": 1,
        "cls._snapshot_validation_report_from_store": 1,
    },
    ("KnowledgeStore", "validate_canonical_json"): {
        "cls.from_canonical_json": 1,
        "cls._snapshot_validation_report_from_store": 1,
    },
    ("KnowledgeStore", "validate_canonical_json_file"): {
        "cls.from_canonical_json_file": 1,
        "cls._snapshot_validation_report_from_store": 1,
    },
}

_DISALLOWED_PREFLIGHT_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_PREFLIGHT_COERCION_ROUTES = {
    "dict",
    "list",
    "tuple",
    "set",
    "int",
    "float",
    "str",
    "bool",
    "getattr",
}
_DISALLOWED_PREFLIGHT_PARSING_OR_BYPASS_ROUTES = {
    "json.loads",
    "json.dumps",
    "hashlib.sha256",
    "_canonicalize_json_value",
    "_stable_payload_hash",
    "_knowledge_store_snapshot_checksum",
    "_payload_validation_error",
    "SnapshotValidationError",
    "SnapshotValidationError.from_value_error",
}
_DISALLOWED_PREFLIGHT_ATTRIBUTE_PARSE_ROUTES = {"read_bytes", "read_text", "decode"}

_DISALLOWED_TEXT_SNIPPETS_BY_METHOD: dict[tuple[str, str], tuple[str, ...]] = {
    ("KnowledgeStore", "_snapshot_validation_report_from_store"): (
        "json.loads(",
        "json.dumps(",
        "_knowledge_store_snapshot_checksum(",
        "hashlib.sha256(",
        "payload_without_checksum",
    ),
    ("KnowledgeStore", "validate_canonical_payload"): (
        "payload.get(",
        "payload.setdefault(",
        "payload.pop(",
        "json.loads(",
        "json.dumps(",
        "_knowledge_store_snapshot_checksum(",
        "hashlib.sha256(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or {}",
        " or []",
        " or ()",
        " or \"\"",
        " or None",
    ),
    ("KnowledgeStore", "validate_canonical_json"): (
        "payload.get(",
        "payload.setdefault(",
        "payload.pop(",
        "canonical_json.get(",
        "canonical_json.setdefault(",
        "canonical_json.pop(",
        "json.loads(",
        "json.dumps(",
        "_knowledge_store_snapshot_checksum(",
        "hashlib.sha256(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or {}",
        " or []",
        " or ()",
        " or \"\"",
        " or None",
    ),
    ("KnowledgeStore", "validate_canonical_json_file"): (
        "canonical_json_bytes =",
        ".read_bytes(",
        ".read_text(",
        ".decode(",
        "json.loads(",
        "json.dumps(",
        "_knowledge_store_snapshot_checksum(",
        "hashlib.sha256(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or b\"\"",
        " or \"\"",
        " or None",
    ),
}

_SENSITIVE_NAMES_BY_METHOD: dict[tuple[str, str], set[str]] = {
    ("KnowledgeStore", "_snapshot_validation_report_from_store"): {
        "store",
        "canonical_payload",
        "canonical_json",
    },
    ("KnowledgeStore", "validate_canonical_payload"): {
        "payload",
        "store",
    },
    ("KnowledgeStore", "validate_canonical_json"): {
        "canonical_json",
        "payload",
        "store",
    },
    ("KnowledgeStore", "validate_canonical_json_file"): {
        "canonical_json_path",
        "canonical_json",
        "canonical_json_bytes",
        "path",
        "store",
    },
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


def _iter_assign_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            yield node


def _iter_assign_targets(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield target
        if isinstance(node, ast.AnnAssign):
            yield node.target
        if isinstance(node, ast.AugAssign):
            yield node.target


def _iter_bool_ops(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.BoolOp):
            yield node


def _iter_ifexp_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.IfExp):
            yield node


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_name(node: ast.AST | None, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _is_literal_text(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _subscript_key_text(node: ast.Subscript) -> str | None:
    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _is_subscript_name_key(node: ast.AST | None, *, value_name: str, key: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and _is_name(node.value, value_name)
        and _subscript_key_text(node) == key
    )


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
            if member.value.startswith("payload.") or member.value.startswith(
                "canonical_json"
            ):
                return True
            if "snapshot_checksum" in member.value:
                return True
    return False


def test_store_snapshot_preflight_validation_routes_through_approved_helpers() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)
    functions = _load_module_functions(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    digest_helper = functions.get("_knowledge_store_canonical_content_digest")
    if digest_helper is None:
        missing_targets.append("_knowledge_store_canonical_content_digest")
    else:
        encode_calls = [
            call
            for call in _iter_call_nodes(digest_helper)
            if _dotted_name(call.func) == "canonical_json.encode"
            and len(call.args) == 1
            and _is_literal_text(call.args[0], "utf-8")
            and not call.keywords
        ]
        if len(encode_calls) != 1:
            failures.append(
                "_knowledge_store_canonical_content_digest routes UTF-8 encoding through "
                f"canonical_json.encode('utf-8') {len(encode_calls)} time(s); expected "
                "exactly 1"
            )

        helper_returns = list(_iter_return_nodes(digest_helper))
        if len(helper_returns) != 1:
            failures.append(
                "_knowledge_store_canonical_content_digest has "
                f"{len(helper_returns)} return statement(s); expected exactly 1"
            )
        else:
            return_value = helper_returns[0].value
            if not (
                isinstance(return_value, ast.Call)
                and isinstance(return_value.func, ast.Attribute)
                and return_value.func.attr == "hexdigest"
                and not return_value.args
                and not return_value.keywords
            ):
                failures.append(
                    "_knowledge_store_canonical_content_digest return route drifted from "
                    "hashlib.sha256(...).hexdigest()"
                )
            elif not (
                isinstance(return_value.func.value, ast.Call)
                and _dotted_name(return_value.func.value.func) == "hashlib.sha256"
                and len(return_value.func.value.args) == 1
                and not return_value.func.value.keywords
                and isinstance(return_value.func.value.args[0], ast.Call)
                and _dotted_name(return_value.func.value.args[0].func)
                == "canonical_json.encode"
                and len(return_value.func.value.args[0].args) == 1
                and _is_literal_text(return_value.func.value.args[0].args[0], "utf-8")
                and not return_value.func.value.args[0].keywords
            ):
                failures.append(
                    "_knowledge_store_canonical_content_digest hash route drifted from "
                    "hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()"
                )

    report_method_key = ("KnowledgeStore", "_snapshot_validation_report_from_store")
    report_method = methods.get(report_method_key)
    if report_method is None:
        missing_targets.append(_format_method_name(report_method_key))
    else:
        decorators = [_dotted_name(decorator) for decorator in report_method.decorator_list]
        if decorators.count("staticmethod") != 1:
            failures.append(
                "KnowledgeStore._snapshot_validation_report_from_store staticmethod "
                f"decoration count is {decorators.count('staticmethod')}; expected exactly 1"
            )

        route_counts: dict[str, int] = {}
        for call in _iter_call_nodes(report_method):
            route_name = _dotted_name(call.func)
            if route_name is None:
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store has "
                    f"non-dotted call route at line {call.lineno}; expected explicit helper routing"
                )
                continue
            route_counts[route_name] = route_counts.get(route_name, 0) + 1

        required_routes = _ALLOWED_PREFLIGHT_ROUTES_BY_METHOD[report_method_key]
        for route_name, expected_count in required_routes.items():
            observed_count = route_counts.get(route_name, 0)
            if observed_count != expected_count:
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store routes through "
                    f"{route_name} {observed_count} time(s); expected exactly {expected_count}"
                )
        for route_name in sorted(route_counts):
            if route_name not in required_routes:
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store reintroduced "
                    f"non-canonical helper route {route_name!r}"
                )

        payload_assignments = [
            assignment
            for assignment in _iter_assign_nodes(report_method)
            if any(_is_name(target, "canonical_payload") for target in assignment.targets)
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == "store.as_canonical_payload"
            and not assignment.value.args
            and not assignment.value.keywords
        ]
        if len(payload_assignments) != 1:
            failures.append(
                "KnowledgeStore._snapshot_validation_report_from_store assigns "
                "canonical_payload via store.as_canonical_payload() "
                f"{len(payload_assignments)} time(s); expected exactly 1"
            )

        json_assignments = [
            assignment
            for assignment in _iter_assign_nodes(report_method)
            if any(_is_name(target, "canonical_json") for target in assignment.targets)
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == "_canonical_json_text"
            and len(assignment.value.args) == 1
            and _is_name(assignment.value.args[0], "canonical_payload")
            and not assignment.value.keywords
        ]
        if len(json_assignments) != 1:
            failures.append(
                "KnowledgeStore._snapshot_validation_report_from_store assigns "
                "canonical_json via _canonical_json_text(canonical_payload) "
                f"{len(json_assignments)} time(s); expected exactly 1"
            )

        report_constructor_calls = [
            call
            for call in _iter_call_nodes(report_method)
            if _dotted_name(call.func) == "SnapshotValidationReport"
        ]
        if len(report_constructor_calls) != 1:
            failures.append(
                "KnowledgeStore._snapshot_validation_report_from_store constructs "
                "SnapshotValidationReport(...) "
                f"{len(report_constructor_calls)} time(s); expected exactly 1"
            )
        else:
            report_constructor = report_constructor_calls[0]
            if report_constructor.args:
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store report constructor "
                    "unexpectedly uses positional arguments"
                )
            if not _is_subscript_name_key(
                _get_keyword_argument(report_constructor, name="schema_version"),
                value_name="canonical_payload",
                key="snapshot_schema_version",
            ):
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store report "
                    "schema_version route drifted from canonical_payload['snapshot_schema_version']"
                )
            if not _is_subscript_name_key(
                _get_keyword_argument(report_constructor, name="snapshot_checksum"),
                value_name="canonical_payload",
                key="snapshot_checksum",
            ):
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store report "
                    "snapshot_checksum route drifted from canonical_payload['snapshot_checksum']"
                )
            digest_keyword = _get_keyword_argument(
                report_constructor,
                name="canonical_content_digest",
            )
            if not (
                isinstance(digest_keyword, ast.Call)
                and _dotted_name(digest_keyword.func)
                == "_knowledge_store_canonical_content_digest"
                and len(digest_keyword.args) == 1
                and _is_name(digest_keyword.args[0], "canonical_json")
                and not digest_keyword.keywords
            ):
                failures.append(
                    "KnowledgeStore._snapshot_validation_report_from_store report "
                    "canonical_content_digest route drifted from "
                    "_knowledge_store_canonical_content_digest(canonical_json)"
                )

    for class_name, method_name, upstream_route, upstream_arg_name in (
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
    ):
        method_key = (class_name, method_name)
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        decorators = [_dotted_name(decorator) for decorator in method.decorator_list]
        if decorators.count("classmethod") != 1:
            failures.append(
                f"{method_label} classmethod decoration count is "
                f"{decorators.count('classmethod')}; expected exactly 1"
            )
        if decorators.count("_route_snapshot_validation_error") != 1:
            failures.append(
                f"{method_label} _route_snapshot_validation_error decoration count is "
                f"{decorators.count('_route_snapshot_validation_error')}; expected exactly 1"
            )

        route_counts: dict[str, int] = {}
        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name is None:
                failures.append(
                    f"{method_label} has non-dotted call route at line {call.lineno}; "
                    "expected explicit helper routing"
                )
                continue
            route_counts[route_name] = route_counts.get(route_name, 0) + 1

        required_routes = _ALLOWED_PREFLIGHT_ROUTES_BY_METHOD[method_key]
        for route_name, expected_count in required_routes.items():
            observed_count = route_counts.get(route_name, 0)
            if observed_count != expected_count:
                failures.append(
                    f"{method_label} routes through {route_name} {observed_count} time(s); "
                    f"expected exactly {expected_count}"
                )
        for route_name in sorted(route_counts):
            if route_name not in required_routes:
                failures.append(
                    f"{method_label} reintroduced non-canonical helper route "
                    f"{route_name!r}"
                )

        upstream_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func) == upstream_route
        ]
        if len(upstream_calls) != 1:
            failures.append(
                f"{method_label} routes through {upstream_route} {len(upstream_calls)} "
                "time(s); expected exactly 1"
            )
        else:
            upstream_call = upstream_calls[0]
            if upstream_call.keywords:
                failures.append(
                    f"{method_label} {upstream_route} route unexpectedly uses keyword arguments"
                )
            if len(upstream_call.args) != 1 or not _is_name(
                upstream_call.args[0],
                upstream_arg_name,
            ):
                failures.append(
                    f"{method_label} {upstream_route} route drifted from positional "
                    f"{upstream_arg_name}"
                )

        store_assignments = [
            assignment
            for assignment in _iter_assign_nodes(method)
            if any(_is_name(target, "store") for target in assignment.targets)
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == upstream_route
            and len(assignment.value.args) == 1
            and _is_name(assignment.value.args[0], upstream_arg_name)
            and not assignment.value.keywords
        ]
        if len(store_assignments) != 1:
            failures.append(
                f"{method_label} assigns store via {upstream_route}({upstream_arg_name}) "
                f"{len(store_assignments)} time(s); expected exactly 1"
            )

        return_nodes = list(_iter_return_nodes(method))
        if len(return_nodes) != 1:
            failures.append(
                f"{method_label} has {len(return_nodes)} return statement(s); expected exactly 1"
            )
        else:
            return_value = return_nodes[0].value
            if not (
                isinstance(return_value, ast.Call)
                and _dotted_name(return_value.func)
                == "cls._snapshot_validation_report_from_store"
                and len(return_value.args) == 1
                and _is_name(return_value.args[0], "store")
                and not return_value.keywords
            ):
                failures.append(
                    f"{method_label} return route drifted from "
                    "cls._snapshot_validation_report_from_store(store)"
                )

    assert not missing_targets, (
        "Store snapshot preflight validation guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot preflight validation route drift detected "
        "in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_preflight_validation_paths_reject_json_fallback_and_checksum_bypass() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_PREFLIGHT_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed preflight snippet {snippet!r}"
                )

        sensitive_names = _SENSITIVE_NAMES_BY_METHOD[method_key]

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)

            if route_name in _DISALLOWED_PREFLIGHT_PARSING_OR_BYPASS_ROUTES:
                failures.append(
                    f"{method_label} reintroduced disallowed preflight route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if (
                route_name is not None
                and route_name.startswith("_expect_")
                and any(
                    _contains_sensitive_reference(argument, sensitive_names)
                    for argument in call.args
                )
            ):
                failures.append(
                    f"{method_label} reintroduced _expect_* parsing/coercion route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_PREFLIGHT_ACCESSORS
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive accessor "
                    f".{call.func.attr}(...) at line {call.lineno}"
                )

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_PREFLIGHT_ATTRIBUTE_PARSE_ROUTES
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc parse/decode route "
                    f".{call.func.attr}(...) at line {call.lineno}"
                )

            if route_name in _DISALLOWED_PREFLIGHT_COERCION_ROUTES and any(
                _contains_sensitive_reference(argument, sensitive_names)
                for argument in call.args
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc preflight coercion route "
                    f"{route_name!r} at line {call.lineno}"
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

        for target in _iter_assign_targets(method):
            if not isinstance(target, ast.Subscript):
                continue
            if _contains_sensitive_reference(target.value, sensitive_names):
                failures.append(
                    f"{method_label} reintroduced payload/path mutation assignment route at "
                    f"line {target.lineno}"
                )

    assert not missing_methods, (
        "Store snapshot preflight fallback guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot preflight validation fallback/coercion/"
        "checksum-bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
