from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_CHECKSUM_METHODS = (
    ("KnowledgeStore", "as_canonical_payload"),
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "from_canonical_json"),
    ("KnowledgeStore", "from_canonical_json_file"),
)

_EXPECTED_SNAPSHOT_KEYS_WITH_CHECKSUM = (
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

_EXPECTED_SNAPSHOT_KEYS_WITHOUT_CHECKSUM = (
    "snapshot_schema_version",
    "cores",
    "revisions",
    "active_relations",
    "pending_relations",
    "relation_variants",
    "relation_collision_metadata",
    "merge_conflict_journal",
)

_EXPECTED_CHECKSUM_MISMATCH_MESSAGE = (
    "does not match canonical deterministic knowledge store snapshot checksum"
)

_DISALLOWED_CHECKSUM_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_CHECKSUM_COERCION_ROUTES = {
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
_DISALLOWED_HASH_BYPASS_ROUTES = {
    "_stable_payload_hash",
    "_canonicalize_json_value",
    "hashlib.sha256",
    "json.dumps",
}

_DISALLOWED_TEXT_SNIPPETS_BY_METHOD: dict[tuple[str, str], tuple[str, ...]] = {
    ("KnowledgeStore", "as_canonical_payload"): (
        "_stable_payload_hash(",
        "_canonicalize_json_value(",
        "hashlib.sha256(",
        "json.dumps(",
    ),
    ("KnowledgeStore", "from_canonical_payload"): (
        'payload_obj.get("snapshot_checksum"',
        "payload_obj.get('snapshot_checksum'",
        'payload_obj.setdefault("snapshot_checksum"',
        "payload_obj.setdefault('snapshot_checksum'",
        'payload_obj.pop("snapshot_checksum"',
        "payload_obj.pop('snapshot_checksum'",
        " or payload_obj['snapshot_checksum']",
        ' or payload_obj["snapshot_checksum"]',
        ".lower()",
        ".casefold()",
    ),
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


def _iter_if_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.If):
            yield node


def _iter_assign_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            yield node


def _iter_return_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Return):
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


def _is_name(node: ast.AST | None, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _is_literal_text(node: ast.AST | None, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _subscript_key_text(node: ast.Subscript) -> str | None:
    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _is_subscript_name_key(node: ast.AST, *, value_name: str, key: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and _is_name(node.value, value_name)
        and _subscript_key_text(node) == key
    )


def _literal_text_sequence(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    for entry in node.elts:
        if not isinstance(entry, ast.Constant) or not isinstance(entry.value, str):
            return None
        values.append(entry.value)
    return tuple(values)


def _dict_value_for_literal_key(node: ast.AST, key: str) -> ast.AST | None:
    if not isinstance(node, ast.Dict):
        return None
    for key_node, value_node in zip(node.keys, node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            return value_node
    return None


def _dict_literal_keys(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Dict):
        return None
    keys: list[str] = []
    for key_node in node.keys:
        if key_node is None:
            return None
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            return None
        keys.append(key_node.value)
    return tuple(keys)


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


def _contains_snapshot_checksum_reference(node: ast.AST) -> bool:
    for member in ast.walk(node):
        if isinstance(member, ast.Name) and member.id in {
            "snapshot_checksum",
            "expected_snapshot_checksum",
            "payload_without_checksum",
        }:
            return True
        if (
            isinstance(member, ast.Subscript)
            and _subscript_key_text(member) == "snapshot_checksum"
        ):
            return True
        if isinstance(member, ast.Constant) and isinstance(member.value, str):
            if "snapshot_checksum" in member.value:
                return True
    return False


def _is_payload_without_checksum_dictcomp(node: ast.AST) -> bool:
    if not isinstance(node, ast.DictComp):
        return False
    if not _is_name(node.key, "key"):
        return False
    if not _is_name(node.value, "value"):
        return False
    if len(node.generators) != 1:
        return False
    generator = node.generators[0]
    if generator.is_async != 0:
        return False
    if not (
        isinstance(generator.target, ast.Tuple)
        and len(generator.target.elts) == 2
        and _is_name(generator.target.elts[0], "key")
        and _is_name(generator.target.elts[1], "value")
    ):
        return False
    if not (
        isinstance(generator.iter, ast.Call)
        and _dotted_name(generator.iter.func) == "payload_obj.items"
        and not generator.iter.args
        and not generator.iter.keywords
    ):
        return False
    if len(generator.ifs) != 1:
        return False
    guard = generator.ifs[0]
    return (
        isinstance(guard, ast.Compare)
        and len(guard.ops) == 1
        and isinstance(guard.ops[0], ast.NotEq)
        and _is_name(guard.left, "key")
        and len(guard.comparators) == 1
        and _is_literal_text(guard.comparators[0], "snapshot_checksum")
    )


def _is_snapshot_checksum_mismatch_guard(if_node: ast.If) -> bool:
    test = if_node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.NotEq):
        return False
    if len(test.comparators) != 1:
        return False
    return (
        _is_name(test.left, "snapshot_checksum")
        and _is_name(test.comparators[0], "expected_snapshot_checksum")
    ) or (
        _is_name(test.left, "expected_snapshot_checksum")
        and _is_name(test.comparators[0], "snapshot_checksum")
    )


def test_store_snapshot_integrity_checksum_routes_through_canonical_paths() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)
    functions = _load_module_functions(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    checksum_helper = functions.get("_knowledge_store_snapshot_checksum")
    if checksum_helper is None:
        missing_targets.append("_knowledge_store_snapshot_checksum")
    else:
        canonical_json_calls = [
            call
            for call in _iter_call_nodes(checksum_helper)
            if _dotted_name(call.func) == "_canonical_json_text"
            and len(call.args) == 1
            and _is_name(call.args[0], "payload_without_checksum")
        ]
        if len(canonical_json_calls) != 1:
            failures.append(
                "_knowledge_store_snapshot_checksum routes canonical JSON staging through "
                f"_canonical_json_text(payload_without_checksum) {len(canonical_json_calls)} "
                "time(s); expected exactly 1"
            )

        helper_returns = list(_iter_return_nodes(checksum_helper))
        if len(helper_returns) != 1:
            failures.append(
                "_knowledge_store_snapshot_checksum has "
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
                    "_knowledge_store_snapshot_checksum return route drifted from "
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
            ):
                failures.append(
                    "_knowledge_store_snapshot_checksum hash route drifted from "
                    "hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()"
                )

    as_payload_key = ("KnowledgeStore", "as_canonical_payload")
    as_payload = methods.get(as_payload_key)
    if as_payload is None:
        missing_targets.append(_format_method_name(as_payload_key))
    else:
        checksum_assignment_calls = [
            assignment
            for assignment in _iter_assign_nodes(as_payload)
            if any(_is_name(target, "snapshot_checksum") for target in assignment.targets)
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == "_knowledge_store_snapshot_checksum"
            and len(assignment.value.args) == 1
            and _is_name(assignment.value.args[0], "payload_without_checksum")
            and not assignment.value.keywords
        ]
        if len(checksum_assignment_calls) != 1:
            failures.append(
                "KnowledgeStore.as_canonical_payload assigns snapshot_checksum via "
                "_knowledge_store_snapshot_checksum(payload_without_checksum) "
                f"{len(checksum_assignment_calls)} time(s); expected exactly 1"
            )

        payload_without_checksum_assignments = [
            assignment
            for assignment in _iter_assign_nodes(as_payload)
            if any(
                _is_name(target, "payload_without_checksum")
                for target in assignment.targets
            )
        ]
        if len(payload_without_checksum_assignments) != 1:
            failures.append(
                "KnowledgeStore.as_canonical_payload assigns payload_without_checksum "
                f"{len(payload_without_checksum_assignments)} time(s); expected exactly 1"
            )
        else:
            payload_without_checksum_value = payload_without_checksum_assignments[0].value
            observed_keys = _dict_literal_keys(payload_without_checksum_value)
            if observed_keys != _EXPECTED_SNAPSHOT_KEYS_WITHOUT_CHECKSUM:
                failures.append(
                    "KnowledgeStore.as_canonical_payload payload_without_checksum keyset "
                    f"drifted from canonical keys {_EXPECTED_SNAPSHOT_KEYS_WITHOUT_CHECKSUM!r}"
                )

        dict_returns = [
            return_node
            for return_node in _iter_return_nodes(as_payload)
            if isinstance(return_node.value, ast.Dict)
        ]
        if len(dict_returns) != 1:
            failures.append(
                "KnowledgeStore.as_canonical_payload returns dict payload "
                f"{len(dict_returns)} time(s); expected exactly 1 canonical payload return"
            )
        else:
            return_payload = dict_returns[0].value
            observed_keys = _dict_literal_keys(return_payload)
            if observed_keys != _EXPECTED_SNAPSHOT_KEYS_WITH_CHECKSUM:
                failures.append(
                    "KnowledgeStore.as_canonical_payload return payload keyset drifted "
                    f"from canonical keys {_EXPECTED_SNAPSHOT_KEYS_WITH_CHECKSUM!r}"
                )
            checksum_value = _dict_value_for_literal_key(return_payload, "snapshot_checksum")
            if not _is_name(checksum_value, "snapshot_checksum"):
                failures.append(
                    "KnowledgeStore.as_canonical_payload snapshot_checksum emit route "
                    "drifted from snapshot_checksum variable"
                )

    from_payload_key = ("KnowledgeStore", "from_canonical_payload")
    from_payload = methods.get(from_payload_key)
    if from_payload is None:
        missing_targets.append(_format_method_name(from_payload_key))
    else:
        exact_key_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "_expect_exact_keys"
            and len(call.args) >= 3
            and _is_name(call.args[0], "payload_obj")
            and _is_literal_text(call.args[1], "payload")
            and _literal_text_sequence(call.args[2]) == _EXPECTED_SNAPSHOT_KEYS_WITH_CHECKSUM
        ]
        if len(exact_key_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes strict top-level key-set "
                "validation through checksum-inclusive canonical keys "
                f"{len(exact_key_calls)} time(s); expected exactly 1"
            )

        checksum_expect_assignments = [
            assignment
            for assignment in _iter_assign_nodes(from_payload)
            if any(_is_name(target, "snapshot_checksum") for target in assignment.targets)
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == "_expect_sha256_hexdigest"
            and len(assignment.value.args) == 2
            and _is_subscript_name_key(
                assignment.value.args[0],
                value_name="payload_obj",
                key="snapshot_checksum",
            )
            and _is_literal_text(
                assignment.value.args[1],
                "payload.snapshot_checksum",
            )
        ]
        if len(checksum_expect_assignments) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes snapshot checksum ingestion "
                "through _expect_sha256_hexdigest(payload_obj['snapshot_checksum'], "
                "'payload.snapshot_checksum') "
                f"{len(checksum_expect_assignments)} time(s); expected exactly 1"
            )
        else:
            checksum_expect_call = checksum_expect_assignments[0].value
            if _get_keyword_argument(checksum_expect_call, name="default") is not None:
                failures.append(
                    "KnowledgeStore.from_canonical_payload checksum expectation route "
                    "reintroduced default fallback"
                )

        payload_without_checksum_assignments = [
            assignment
            for assignment in _iter_assign_nodes(from_payload)
            if any(
                _is_name(target, "payload_without_checksum")
                for target in assignment.targets
            )
            and _is_payload_without_checksum_dictcomp(assignment.value)
        ]
        if len(payload_without_checksum_assignments) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes checksum-stripped payload "
                "staging through dict-comp key != 'snapshot_checksum' "
                f"{len(payload_without_checksum_assignments)} time(s); expected exactly 1"
            )

        expected_checksum_assignments = [
            assignment
            for assignment in _iter_assign_nodes(from_payload)
            if any(
                _is_name(target, "expected_snapshot_checksum")
                for target in assignment.targets
            )
            and isinstance(assignment.value, ast.Call)
            and _dotted_name(assignment.value.func) == "_knowledge_store_snapshot_checksum"
            and len(assignment.value.args) == 1
            and _is_name(assignment.value.args[0], "payload_without_checksum")
            and not assignment.value.keywords
        ]
        if len(expected_checksum_assignments) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes checksum recomputation through "
                "_knowledge_store_snapshot_checksum(payload_without_checksum) "
                f"{len(expected_checksum_assignments)} time(s); expected exactly 1"
            )

        mismatch_guards = [
            if_node
            for if_node in _iter_if_nodes(from_payload)
            if _is_snapshot_checksum_mismatch_guard(if_node)
        ]
        if len(mismatch_guards) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload snapshot checksum mismatch guard "
                f"count is {len(mismatch_guards)}; expected exactly 1 fail-closed guard"
            )
        else:
            mismatch_guard = mismatch_guards[0]
            mismatch_error_calls = [
                call
                for call in _iter_call_nodes(mismatch_guard)
                if _dotted_name(call.func) == "_payload_validation_error"
                and len(call.args) >= 2
                and _is_literal_text(call.args[0], "payload.snapshot_checksum")
                and _is_literal_text(call.args[1], _EXPECTED_CHECKSUM_MISMATCH_MESSAGE)
            ]
            if len(mismatch_error_calls) != 1:
                failures.append(
                    "KnowledgeStore.from_canonical_payload checksum mismatch guard no "
                    "longer raises _payload_validation_error at payload.snapshot_checksum "
                    "with canonical fail-closed detail"
                )

    for class_name, method_name, route_name, route_arg_name in (
        (
            "KnowledgeStore",
            "from_canonical_json",
            "cls.from_canonical_payload",
            "payload",
        ),
        (
            "KnowledgeStore",
            "from_canonical_json_file",
            "cls.from_canonical_json",
            "canonical_json",
        ),
    ):
        target_key = (class_name, method_name)
        method = methods.get(target_key)
        if method is None:
            missing_targets.append(_format_method_name(target_key))
            continue
            route_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == route_name
            ]
            if len(route_calls) != 1:
                failures.append(
                    f"{_format_method_name(target_key)} routes through {route_name} "
                    f"{len(route_calls)} time(s); expected exactly 1"
                )
            else:
                route_call = route_calls[0]
                if route_call.keywords:
                    failures.append(
                        f"{_format_method_name(target_key)} {route_name} route "
                        "unexpectedly uses keyword arguments"
                    )
                if len(route_call.args) != 1 or not _is_name(
                    route_call.args[0],
                    route_arg_name,
                ):
                    failures.append(
                        f"{_format_method_name(target_key)} {route_name} route drifted "
                        f"from positional {route_arg_name}"
                    )

    assert not missing_targets, (
        "Store snapshot integrity guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot integrity checksum route drift detected "
        "in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_integrity_paths_reject_fallback_coercion_and_bypass_routes() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_CHECKSUM_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed checksum fallback snippet "
                    f"{snippet!r}"
                )

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_CHECKSUM_ACCESSORS
                and _contains_snapshot_checksum_reference(call.func.value)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive checksum accessor "
                    f"{call.func.attr!r} at line {call.lineno}"
                )

            if route_name in _DISALLOWED_CHECKSUM_COERCION_ROUTES and any(
                _contains_snapshot_checksum_reference(argument)
                for argument in call.args
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc checksum coercion route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if route_name == "_expect_sha256_hexdigest":
                if _get_keyword_argument(call, name="default") is not None:
                    failures.append(
                        f"{method_label} reintroduced _expect_sha256_hexdigest default "
                        f"fallback at line {call.lineno}"
                    )
                if any(_contains_snapshot_checksum_reference(argument) for argument in call.args):
                    if len(call.args) < 2 or not _is_literal_text(
                        call.args[1], "payload.snapshot_checksum"
                    ):
                        failures.append(
                            f"{method_label} checksum validation path drifted from "
                            "'payload.snapshot_checksum' at line {call.lineno}"
                        )

            if route_name in _DISALLOWED_HASH_BYPASS_ROUTES:
                failures.append(
                    f"{method_label} reintroduced disallowed checksum bypass route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if route_name == "_knowledge_store_snapshot_checksum" and method_key not in {
                ("KnowledgeStore", "as_canonical_payload"),
                ("KnowledgeStore", "from_canonical_payload"),
            }:
                failures.append(
                    f"{method_label} reintroduced direct checksum helper route "
                    f"{route_name!r} outside canonical payload serialization/validation "
                    f"at line {call.lineno}"
                )

        for bool_op in _iter_bool_ops(method):
            if not isinstance(bool_op.op, ast.Or):
                continue
            if any(
                _contains_snapshot_checksum_reference(value)
                for value in bool_op.values
            ):
                failures.append(
                    f"{method_label} reintroduced permissive checksum fallback `or` route "
                    f"at line {bool_op.lineno}"
                )

        for target in _iter_assign_targets(method):
            if not isinstance(target, ast.Subscript):
                continue
            if _subscript_key_text(target) != "snapshot_checksum":
                continue
            if _contains_snapshot_checksum_reference(target.value):
                failures.append(
                    f"{method_label} reintroduced direct payload mutation route for "
                    f"snapshot_checksum at line {target.lineno}"
                )

    assert not missing_methods, (
        "Store snapshot integrity fallback guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot integrity fallback/coercion/bypass drift "
        "detected in src/dks/core.py: "
        + "; ".join(failures)
    )
