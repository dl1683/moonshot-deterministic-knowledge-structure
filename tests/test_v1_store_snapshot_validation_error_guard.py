from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_DESERIALIZATION_METHODS = (
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "from_canonical_json"),
    ("KnowledgeStore", "from_canonical_json_file"),
)

_DISALLOWED_DESERIALIZATION_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_DESERIALIZATION_COERCION_ROUTES = {
    "dict",
    "list",
    "tuple",
    "set",
    "int",
    "float",
    "bool",
    "getattr",
}

_DISALLOWED_TEXT_SNIPPETS_BY_METHOD: dict[tuple[str, str], tuple[str, ...]] = {
    ("KnowledgeStore", "from_canonical_payload"): (
        "payload_obj.get(",
        "payload_obj.setdefault(",
        "payload_obj.pop(",
        "entry_payload.get(",
        "entry_payload.setdefault(",
        "entry_payload.pop(",
        "variant_payload.get(",
        "variant_payload.setdefault(",
        "variant_payload.pop(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or {}",
        " or []",
        " or ()",
    ),
    ("KnowledgeStore", "from_canonical_json"): (
        "payload.get(",
        "payload.setdefault(",
        "payload.pop(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or {}",
        " or []",
        " or ()",
    ),
    ("KnowledgeStore", "from_canonical_json_file"): (
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or b\"\"",
        " or \"\"",
    ),
}

_SENSITIVE_NAMES_BY_METHOD: dict[tuple[str, str], set[str]] = {
    ("KnowledgeStore", "from_canonical_payload"): {
        "payload",
        "payload_obj",
        "entry",
        "entry_payload",
        "variant",
        "variant_payload",
        "variants_payload",
        "pair",
        "collision_pairs_payload",
        "relation_variants_payload",
        "relation_collision_metadata_payload",
    },
    ("KnowledgeStore", "from_canonical_json"): {
        "canonical_json",
        "json_text",
        "payload",
    },
    ("KnowledgeStore", "from_canonical_json_file"): {
        "canonical_json_path",
        "canonical_json_bytes",
        "canonical_json",
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


def _iter_raise_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Raise):
            yield node


def _iter_except_handlers(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.ExceptHandler):
            yield node


def _iter_bool_ops(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.BoolOp):
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


def _is_name(node: ast.AST, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _is_literal_text(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _is_literal_int(node: ast.AST | None, expected: int) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


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
            if "payload." in member.value:
                return True
            if member.value in sensitive_names:
                return True
    return False


def test_store_snapshot_validation_error_routes_through_centralized_helpers() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)
    functions = _load_module_functions(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    from_value_error_key = ("SnapshotValidationError", "from_value_error")
    from_value_error = methods.get(from_value_error_key)
    if from_value_error is None:
        missing_targets.append(_format_method_name(from_value_error_key))
    else:
        classify_calls = [
            call
            for call in _iter_call_nodes(from_value_error)
            if _dotted_name(call.func) == "cls._classify_code"
            and len(call.args) == 2
            and _is_name(call.args[0], "path")
            and _is_name(call.args[1], "message")
        ]
        if len(classify_calls) != 1:
            failures.append(
                "SnapshotValidationError.from_value_error routes code classification "
                f"through cls._classify_code(path, message) {len(classify_calls)} "
                "time(s); expected exactly 1"
            )

        split_calls = [
            call
            for call in _iter_call_nodes(from_value_error)
            if _dotted_name(call.func) == "raw_message.split"
            and len(call.args) == 2
            and _is_literal_text(call.args[0], ": ")
            and _is_literal_int(call.args[1], 1)
        ]
        if len(split_calls) != 1:
            failures.append(
                "SnapshotValidationError.from_value_error routes path/message extraction "
                f"through raw_message.split(': ', 1) {len(split_calls)} time(s); "
                "expected exactly 1"
            )

        constructor_calls = [
            call for call in _iter_call_nodes(from_value_error) if _dotted_name(call.func) == "cls"
        ]
        if len(constructor_calls) != 1:
            failures.append(
                "SnapshotValidationError.from_value_error constructs cls(...) "
                f"{len(constructor_calls)} time(s); expected exactly 1"
            )
        else:
            constructor_call = constructor_calls[0]
            code_arg = _get_keyword_argument(constructor_call, name="code")
            if not (
                isinstance(code_arg, ast.Call)
                and _dotted_name(code_arg.func) == "cls._classify_code"
                and len(code_arg.args) == 2
                and _is_name(code_arg.args[0], "path")
                and _is_name(code_arg.args[1], "message")
            ):
                failures.append(
                    "SnapshotValidationError.from_value_error cls(...) code route "
                    "drifted from cls._classify_code(path, message)"
                )
            if not _is_name(_get_keyword_argument(constructor_call, name="path"), "path"):
                failures.append(
                    "SnapshotValidationError.from_value_error cls(...) path route drifted "
                    "from path=path"
                )
            if not _is_name(_get_keyword_argument(constructor_call, name="message"), "message"):
                failures.append(
                    "SnapshotValidationError.from_value_error cls(...) message route drifted "
                    "from message=message"
                )

    route_helper = functions.get("_route_snapshot_validation_error")
    if route_helper is None:
        missing_targets.append("_route_snapshot_validation_error")
    else:
        exception_handlers = list(_iter_except_handlers(route_helper))
        if len(exception_handlers) != 1:
            failures.append(
                "_route_snapshot_validation_error has "
                f"{len(exception_handlers)} except handler(s); expected exactly 1 ValueError route"
            )
        else:
            handler = exception_handlers[0]
            if not _is_name(handler.type, "ValueError"):
                failures.append(
                    "_route_snapshot_validation_error no longer catches ValueError as "
                    "its centralized conversion route"
                )
            if handler.name != "error":
                failures.append(
                    "_route_snapshot_validation_error ValueError handler drifted from "
                    "name 'error'"
                )

        method_calls = [
            call
            for call in _iter_call_nodes(route_helper)
            if _dotted_name(call.func) == "method"
        ]
        if len(method_calls) != 1:
            failures.append(
                "_route_snapshot_validation_error invokes wrapped method "
                f"{len(method_calls)} time(s); expected exactly 1"
            )

        isinstance_calls = [
            call
            for call in _iter_call_nodes(route_helper)
            if _dotted_name(call.func) == "isinstance"
            and len(call.args) == 2
            and _is_name(call.args[0], "error")
            and _is_name(call.args[1], "SnapshotValidationError")
        ]
        if len(isinstance_calls) != 1:
            failures.append(
                "_route_snapshot_validation_error routes pass-through checks via "
                "isinstance(error, SnapshotValidationError) "
                f"{len(isinstance_calls)} time(s); expected exactly 1"
            )

        conversion_calls = [
            call
            for call in _iter_call_nodes(route_helper)
            if _dotted_name(call.func) == "SnapshotValidationError.from_value_error"
            and len(call.args) == 1
            and _is_name(call.args[0], "error")
        ]
        if len(conversion_calls) != 1:
            failures.append(
                "_route_snapshot_validation_error routes conversion through "
                "SnapshotValidationError.from_value_error(error) "
                f"{len(conversion_calls)} time(s); expected exactly 1"
            )

        chained_conversion_raises = [
            raise_node
            for raise_node in _iter_raise_nodes(route_helper)
            if (
                isinstance(raise_node.exc, ast.Call)
                and _dotted_name(raise_node.exc.func)
                == "SnapshotValidationError.from_value_error"
                and len(raise_node.exc.args) == 1
                and _is_name(raise_node.exc.args[0], "error")
                and _is_name(raise_node.cause, "error")
            )
        ]
        if len(chained_conversion_raises) != 1:
            failures.append(
                "_route_snapshot_validation_error no longer raises "
                "SnapshotValidationError.from_value_error(error) from error exactly once"
            )

    for method_key in _TARGET_DESERIALIZATION_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
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

        direct_conversion_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func)
            in {"SnapshotValidationError", "SnapshotValidationError.from_value_error"}
        ]
        if direct_conversion_calls:
            failures.append(
                f"{method_label} reintroduced direct SnapshotValidationError conversion "
                "inside method body; expected centralized decorator routing only"
            )

        if method_key == ("KnowledgeStore", "from_canonical_json"):
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
                if len(from_payload_call.args) != 1 or not _is_name(
                    from_payload_call.args[0],
                    "payload",
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route drifted from "
                        "positional payload"
                    )

        if method_key == ("KnowledgeStore", "from_canonical_json_file"):
            from_json_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "cls.from_canonical_json"
            ]
            if len(from_json_calls) != 1:
                failures.append(
                    f"{method_label} routes through cls.from_canonical_json "
                    f"{len(from_json_calls)} time(s); expected exactly 1"
                )
            else:
                from_json_call = from_json_calls[0]
                if from_json_call.keywords:
                    failures.append(
                        f"{method_label} cls.from_canonical_json route unexpectedly uses "
                        "keyword arguments"
                    )
                if len(from_json_call.args) != 1 or not _is_name(
                    from_json_call.args[0],
                    "canonical_json",
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_json route drifted from "
                        "positional canonical_json"
                    )

    assert not missing_targets, (
        "Store snapshot validation-error guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot validation-error route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_validation_error_paths_reject_permissive_fallback_and_coercion() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)
    functions = _load_module_functions(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_DESERIALIZATION_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed validation-error fallback "
                    f"snippet {snippet!r}"
                )

        sensitive_names = _SENSITIVE_NAMES_BY_METHOD[method_key]

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_DESERIALIZATION_ACCESSORS
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive accessor "
                    f"{call.func.attr!r} in validation path at line {call.lineno}"
                )

            if route_name in _DISALLOWED_DESERIALIZATION_COERCION_ROUTES and any(
                _contains_sensitive_reference(argument, sensitive_names)
                for argument in call.args
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc coercion route "
                    f"{route_name!r} over deterministic deserialization inputs at line "
                    f"{call.lineno}"
                )

            if (
                route_name is not None
                and route_name.startswith("_expect_")
                and _get_keyword_argument(call, name="default") is not None
            ):
                failures.append(
                    f"{method_label} reintroduced _expect_* default fallback at line "
                    f"{call.lineno}"
                )

            if route_name in {"SnapshotValidationError", "SnapshotValidationError.from_value_error"}:
                failures.append(
                    f"{method_label} reintroduced direct SnapshotValidationError route "
                    f"{route_name!r} at line {call.lineno}; expected centralized decorator "
                    "conversion"
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

        for target in _iter_assign_targets(method):
            if not isinstance(target, ast.Subscript):
                continue
            if _contains_sensitive_reference(target.value, sensitive_names):
                failures.append(
                    f"{method_label} reintroduced payload mutation assignment route at "
                    f"line {target.lineno}"
                )

    route_helper = functions.get("_route_snapshot_validation_error")
    if route_helper is None:
        missing_targets.append("_route_snapshot_validation_error")
    else:
        for handler in _iter_except_handlers(route_helper):
            handler_type = _dotted_name(handler.type) if handler.type is not None else None
            if handler_type in {None, "Exception", "BaseException"}:
                failures.append(
                    "_route_snapshot_validation_error reintroduced broad exception catch "
                    "route; expected ValueError-only conversion path"
                )
            if handler_type not in {None, "ValueError"}:
                failures.append(
                    "_route_snapshot_validation_error reintroduced non-ValueError catch "
                    f"route {handler_type!r}"
                )
            if any(isinstance(node, ast.Return) for node in handler.body):
                failures.append(
                    "_route_snapshot_validation_error reintroduced return-based fallback "
                    "inside exception conversion path"
                )

        helper_source = _method_source(source, route_helper)
        for snippet in ("except Exception", "except BaseException", "return None"):
            if snippet in helper_source:
                failures.append(
                    "_route_snapshot_validation_error reintroduced disallowed conversion "
                    f"helper snippet {snippet!r}"
                )

    assert not missing_targets, (
        "Store snapshot validation-error fallback guard targets missing from "
        "src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot validation-error fallback/coercion drift "
        "detected in src/dks/core.py: "
        + "; ".join(failures)
    )
