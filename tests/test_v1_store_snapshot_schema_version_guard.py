from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_SCHEMA_METHODS = (
    ("KnowledgeStore", "as_canonical_payload"),
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "from_canonical_json"),
)

_EXPECTED_SNAPSHOT_PAYLOAD_KEYS = (
    "snapshot_schema_version",
    "cores",
    "revisions",
    "active_relations",
    "pending_relations",
    "relation_variants",
    "relation_collision_metadata",
    "merge_conflict_journal",
    "snapshot_checksum",
)

_DISALLOWED_SNAPSHOT_SCHEMA_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_SNAPSHOT_SCHEMA_COERCION_ROUTES = {"dict", "int", "str", "float", "bool", "getattr"}
_DISALLOWED_SNAPSHOT_SCHEMA_TEXT_SNIPPETS = (
    '.get("snapshot_schema_version"',
    ".get('snapshot_schema_version'",
    '.setdefault("snapshot_schema_version"',
    ".setdefault('snapshot_schema_version'",
    '.pop("snapshot_schema_version"',
    ".pop('snapshot_schema_version'",
    "or cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION",
    "or KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION",
)


def _load_module(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text(encoding="utf-8-sig")
    return source, ast.parse(source, filename=str(path))


def _load_classes(module: ast.Module) -> dict[str, ast.ClassDef]:
    classes: dict[str, ast.ClassDef] = {}
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = node
    return classes


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


def _iter_if_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.If):
            yield node


def _iter_assign_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            yield node


def _iter_bool_ops(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.BoolOp):
            yield node


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


def _dict_value_for_literal_key(node: ast.AST, key: str) -> ast.AST | None:
    if not isinstance(node, ast.Dict):
        return None
    for key_node, value_node in zip(node.keys, node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            return value_node
    return None


def _literal_text_sequence(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    for entry in node.elts:
        if not isinstance(entry, ast.Constant) or not isinstance(entry.value, str):
            return None
        values.append(entry.value)
    return tuple(values)


def _subscript_key_text(node: ast.Subscript) -> str | None:
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def _is_snapshot_schema_subscript(node: ast.AST, *, value_name: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and _is_name(node.value, value_name)
        and _subscript_key_text(node) == "snapshot_schema_version"
    )


def _call_mentions_snapshot_schema_key(call: ast.Call) -> bool:
    for node in ast.walk(call):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if "snapshot_schema_version" in node.value:
            return True
    return False


def _contains_snapshot_schema_reference(node: ast.AST) -> bool:
    for member in ast.walk(node):
        if _is_snapshot_schema_subscript(member, value_name="payload_obj"):
            return True
        if isinstance(member, ast.Constant) and isinstance(member.value, str):
            if "snapshot_schema_version" in member.value:
                return True
    return False


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def test_store_snapshot_schema_version_routes_emit_and_validate_fail_closed_contract() -> None:
    source, module = _load_module(_CORE_PATH)
    classes = _load_classes(module)
    methods = _load_class_methods(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    knowledge_store_class = classes.get("KnowledgeStore")
    if knowledge_store_class is None:
        missing_targets.append("KnowledgeStore")
    else:
        schema_constant_assignments = [
            node
            for node in knowledge_store_class.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_CANONICAL_SNAPSHOT_SCHEMA_VERSION"
                for target in node.targets
            )
        ]
        if len(schema_constant_assignments) != 1:
            failures.append(
                "KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION assignment count "
                f"is {len(schema_constant_assignments)}; expected exactly 1"
            )
        else:
            assignment = schema_constant_assignments[0]
            if not _is_literal_int(assignment.value, 1):
                failures.append(
                    "KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION drifted from "
                    "literal integer 1"
                )

    for method_key in _TARGET_SCHEMA_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        if method_key == ("KnowledgeStore", "as_canonical_payload"):
            dict_returns = [
                return_node
                for return_node in _iter_return_nodes(method)
                if isinstance(return_node.value, ast.Dict)
            ]
            if len(dict_returns) != 1:
                failures.append(
                    f"{method_label} returns dict payload {len(dict_returns)} time(s); "
                    "expected exactly 1 deterministic payload return"
                )
            else:
                schema_value = _dict_value_for_literal_key(
                    dict_returns[0].value,
                    "snapshot_schema_version",
                )
                if schema_value is None:
                    failures.append(
                        f"{method_label} no longer emits payload key "
                        "'snapshot_schema_version'"
                    )
                elif _dotted_name(schema_value) != (
                    "KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION"
                ):
                    failures.append(
                        f"{method_label} snapshot schema emit route drifted from "
                        "KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION"
                    )

        if method_key == ("KnowledgeStore", "from_canonical_payload"):
            exact_key_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "_expect_exact_keys"
                and len(call.args) >= 3
                and _is_name(call.args[0], "payload_obj")
                and _is_literal_text(call.args[1], "payload")
            ]
            matching_exact_key_calls = [
                call
                for call in exact_key_calls
                if _literal_text_sequence(call.args[2]) == _EXPECTED_SNAPSHOT_PAYLOAD_KEYS
            ]
            if len(matching_exact_key_calls) != 1:
                failures.append(
                    f"{method_label} routes exact payload-key validation through canonical "
                    f"snapshot keyset {len(matching_exact_key_calls)} time(s); expected exactly 1"
                )

            schema_assignments = [
                assignment
                for assignment in _iter_assign_nodes(method)
                if any(
                    isinstance(target, ast.Name) and target.id == "schema_version"
                    for target in assignment.targets
                )
            ]
            if len(schema_assignments) != 1:
                failures.append(
                    f"{method_label} assigns schema_version {len(schema_assignments)} "
                    "time(s); expected exactly 1 fail-closed _expect_int route"
                )
            else:
                schema_value = schema_assignments[0].value
                if not isinstance(schema_value, ast.Call):
                    failures.append(
                        f"{method_label} schema_version assignment no longer routes "
                        "through a helper call"
                    )
                elif _dotted_name(schema_value.func) != "_expect_int":
                    failures.append(
                        f"{method_label} schema_version assignment drifted from _expect_int "
                        f"to {_dotted_name(schema_value.func)!r}"
                    )
                else:
                    if len(schema_value.args) != 2:
                        failures.append(
                            f"{method_label} _expect_int schema_version route uses "
                            f"{len(schema_value.args)} positional args; expected exactly 2"
                        )
                    else:
                        if not _is_snapshot_schema_subscript(
                            schema_value.args[0],
                            value_name="payload_obj",
                        ):
                            failures.append(
                                f"{method_label} _expect_int schema-version source "
                                "drifted from payload_obj['snapshot_schema_version']"
                            )
                        if not _is_literal_text(
                            schema_value.args[1],
                            "payload.snapshot_schema_version",
                        ):
                            failures.append(
                                f"{method_label} _expect_int schema-version path "
                                "drifted from payload.snapshot_schema_version"
                            )
                    min_value = _get_keyword_argument(schema_value, name="min_value")
                    if not _is_literal_int(min_value, 0):
                        failures.append(
                            f"{method_label} schema-version int validation drifted from "
                            "min_value=0"
                        )
                    if _get_keyword_argument(schema_value, name="default") is not None:
                        failures.append(
                            f"{method_label} schema-version _expect_int route "
                            "reintroduced default=... fallback coercion"
                        )

            schema_version_guards = []
            for if_node in _iter_if_nodes(method):
                test = if_node.test
                if not isinstance(test, ast.Compare):
                    continue
                if len(test.ops) != 1 or not isinstance(test.ops[0], ast.NotEq):
                    continue
                if len(test.comparators) != 1:
                    continue
                if not _is_name(test.left, "schema_version"):
                    continue
                if _dotted_name(test.comparators[0]) != "cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION":
                    continue
                schema_version_guards.append(if_node)

            if len(schema_version_guards) != 1:
                failures.append(
                    f"{method_label} schema-version mismatch guard count is "
                    f"{len(schema_version_guards)}; expected exactly 1"
                )
            else:
                guard = schema_version_guards[0]
                guard_calls = [
                    call
                    for call in _iter_call_nodes(guard)
                    if _dotted_name(call.func) == "_payload_validation_error"
                ]
                if not any(
                    len(call.args) >= 1
                    and _is_literal_text(call.args[0], "payload.snapshot_schema_version")
                    for call in guard_calls
                ):
                    failures.append(
                        f"{method_label} schema-version mismatch guard no longer raises "
                        "_payload_validation_error at payload.snapshot_schema_version"
                    )
                guard_source = ast.get_source_segment(source, guard) or ""
                if "unsupported snapshot schema version" not in guard_source:
                    failures.append(
                        f"{method_label} schema-version mismatch guard no longer emits "
                        "'unsupported snapshot schema version' detail"
                    )
                if "cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION" not in guard_source:
                    failures.append(
                        f"{method_label} schema-version mismatch guard no longer references "
                        "cls._CANONICAL_SNAPSHOT_SCHEMA_VERSION in expected-version detail"
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
                    from_payload_call.args[0], "payload"
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_payload route drifted from payload"
                    )

    assert not missing_targets, (
        "Store snapshot schema-version guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot schema-version route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_schema_version_paths_reject_default_fallback_and_coercion_routes() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_SCHEMA_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_SNAPSHOT_SCHEMA_TEXT_SNIPPETS:
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed schema-version fallback "
                    f"snippet {snippet!r}"
                )

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if not _call_mentions_snapshot_schema_key(call):
                continue

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_SNAPSHOT_SCHEMA_ACCESSORS
            ):
                failures.append(
                    f"{method_label} reintroduced schema-version accessor fallback "
                    f"{call.func.attr!r} at line {call.lineno}"
                )

            if route_name in _DISALLOWED_SNAPSHOT_SCHEMA_COERCION_ROUTES:
                failures.append(
                    f"{method_label} reintroduced ad-hoc schema-version coercion route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if route_name == "_expect_int" and _get_keyword_argument(call, name="default") is not None:
                failures.append(
                    f"{method_label} reintroduced schema-version _expect_int default "
                    f"fallback at line {call.lineno}"
                )

        if method_key == ("KnowledgeStore", "from_canonical_payload"):
            for bool_op in _iter_bool_ops(method):
                if not isinstance(bool_op.op, ast.Or):
                    continue
                if any(_contains_snapshot_schema_reference(value) for value in bool_op.values):
                    failures.append(
                        f"{method_label} reintroduced schema-version fallback `or` route "
                        f"at line {bool_op.lineno}"
                    )

    assert not missing_methods, (
        "Store snapshot schema-version fallback guard targets missing from "
        "src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot schema-version fallback/coercion drift "
        "detected in src/dks/core.py: "
        + "; ".join(failures)
    )
