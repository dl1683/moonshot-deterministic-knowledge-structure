from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_STRICT_METHODS = (
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "from_canonical_json"),
    ("KnowledgeStore", "from_canonical_json_file"),
)

_EXPECTED_TOP_LEVEL_KEYS = (
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

_TOP_LEVEL_ARRAY_PARSE_ROUTES = (
    ("cores", "_claim_core_from_payload"),
    ("revisions", "_claim_revision_from_payload"),
    ("active_relations", "_relation_edge_from_store_snapshot_payload"),
    ("pending_relations", "_relation_edge_from_store_snapshot_payload"),
    ("merge_conflict_journal", "_merge_result_by_tx_from_store_snapshot_payload"),
)

_TOP_LEVEL_LIST_EXPECTATIONS = (
    "relation_variants",
    "relation_collision_metadata",
)

_DISALLOWED_DESERIALIZATION_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_DESERIALIZATION_COERCION_ROUTES = {
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
        " or {}",
        " or []",
        " or ()",
    ),
    ("KnowledgeStore", "from_canonical_json"): (
        "payload.get(",
        "payload.setdefault(",
        "payload.pop(",
        " or {}",
        " or []",
        " or ()",
    ),
    ("KnowledgeStore", "from_canonical_json_file"): (
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
        "merge_conflict_journal",
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


def _literal_text_sequence(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    for entry in node.elts:
        if not isinstance(entry, ast.Constant) or not isinstance(entry.value, str):
            return None
        values.append(entry.value)
    return tuple(values)


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


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


def _is_zero_arg_call_route(node: ast.AST | None, route_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and _dotted_name(node.func) == route_name
        and not node.args
        and not node.keywords
    )


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


def _method_source(source: str, method: _DEF_OR_ASYNC) -> str:
    segment = ast.get_source_segment(source, method)
    return segment or ""


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def test_store_snapshot_deserialization_routes_through_strict_validation_helpers() -> None:
    _source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    from_payload_key = ("KnowledgeStore", "from_canonical_payload")
    from_payload = methods.get(from_payload_key)
    if from_payload is None:
        missing_methods.append(_format_method_name(from_payload_key))
    else:
        payload_mapping_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "_expect_mapping"
            and len(call.args) == 2
            and _is_name(call.args[0], "payload")
            and _is_literal_text(call.args[1], "payload")
        ]
        if len(payload_mapping_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes payload-object validation "
                f"through _expect_mapping(payload, 'payload') {len(payload_mapping_calls)} "
                "time(s); expected exactly 1"
            )

        top_level_key_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "_expect_exact_keys"
            and len(call.args) >= 3
            and _is_name(call.args[0], "payload_obj")
            and _is_literal_text(call.args[1], "payload")
            and _literal_text_sequence(call.args[2]) == _EXPECTED_TOP_LEVEL_KEYS
        ]
        if len(top_level_key_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes top-level snapshot key-set "
                f"validation through canonical keys {len(top_level_key_calls)} time(s); "
                "expected exactly 1"
            )

        for field_name, parse_route in _TOP_LEVEL_ARRAY_PARSE_ROUTES:
            matching_calls = [
                call
                for call in _iter_call_nodes(from_payload)
                if _dotted_name(call.func) == "_parse_payload_array"
                and len(call.args) == 3
                and _is_subscript_name_key(
                    call.args[0],
                    value_name="payload_obj",
                    key=field_name,
                )
                and _is_literal_text(call.args[1], f"payload.{field_name}")
                and _dotted_name(call.args[2]) == parse_route
            ]
            if len(matching_calls) != 1:
                failures.append(
                    "KnowledgeStore.from_canonical_payload routes payload."
                    f"{field_name} through {parse_route} {len(matching_calls)} time(s); "
                    "expected exactly 1 strict array parser route"
                )

        for field_name in _TOP_LEVEL_LIST_EXPECTATIONS:
            matching_calls = [
                call
                for call in _iter_call_nodes(from_payload)
                if _dotted_name(call.func) == "_expect_list"
                and len(call.args) >= 2
                and _is_subscript_name_key(
                    call.args[0],
                    value_name="payload_obj",
                    key=field_name,
                )
                and _is_literal_text(call.args[1], f"payload.{field_name}")
            ]
            if len(matching_calls) != 1:
                failures.append(
                    "KnowledgeStore.from_canonical_payload routes payload."
                    f"{field_name} through _expect_list {len(matching_calls)} time(s); "
                    "expected exactly 1 strict list validation route"
                )

        dynamic_key_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "_expect_exact_dynamic_key_set"
        ]
        if len(dynamic_key_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes relation_id dynamic key-set "
                f"validation through _expect_exact_dynamic_key_set {len(dynamic_key_calls)} "
                "time(s); expected exactly 1"
            )
        else:
            dynamic_key_call = dynamic_key_calls[0]
            observed_keys = _get_keyword_argument(dynamic_key_call, name="observed_keys")
            expected_keys = _get_keyword_argument(dynamic_key_call, name="expected_keys")
            if not _is_zero_arg_call_route(
                observed_keys,
                "store._relation_collision_pairs.keys",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_payload dynamic observed_keys route "
                    "drifted from store._relation_collision_pairs.keys()"
                )
            if not _is_zero_arg_call_route(
                expected_keys,
                "store._relation_variants.keys",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_payload dynamic expected_keys route "
                    "drifted from store._relation_variants.keys()"
                )
            path_arg = _get_keyword_argument(dynamic_key_call, name="path")
            if not _is_literal_text(path_arg, "payload.relation_collision_metadata"):
                failures.append(
                    "KnowledgeStore.from_canonical_payload dynamic key-set path drifted "
                    "from payload.relation_collision_metadata"
                )
            key_label_arg = _get_keyword_argument(dynamic_key_call, name="key_label")
            if not _is_literal_text(key_label_arg, "relation_id"):
                failures.append(
                    "KnowledgeStore.from_canonical_payload dynamic key-set key_label "
                    "drifted from relation_id"
                )

    from_json_key = ("KnowledgeStore", "from_canonical_json")
    from_json = methods.get(from_json_key)
    if from_json is None:
        missing_methods.append(_format_method_name(from_json_key))
    else:
        expect_str_calls = [
            call
            for call in _iter_call_nodes(from_json)
            if _dotted_name(call.func) == "_expect_str"
            and len(call.args) == 2
            and _is_name(call.args[0], "canonical_json")
            and _is_literal_text(call.args[1], "canonical_json")
        ]
        if len(expect_str_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json routes canonical_json validation "
                f"through _expect_str {len(expect_str_calls)} time(s); expected exactly 1"
            )

        json_load_calls = [
            call
            for call in _iter_call_nodes(from_json)
            if _dotted_name(call.func) == "json.loads"
            and len(call.args) == 1
            and _is_name(call.args[0], "json_text")
        ]
        if len(json_load_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json routes JSON parsing through "
                f"json.loads(json_text) {len(json_load_calls)} time(s); expected exactly 1"
            )
        elif json_load_calls[0].keywords:
            failures.append(
                "KnowledgeStore.from_canonical_json json.loads route unexpectedly uses "
                "keyword overrides"
            )

        mapping_type_checks = [
            call
            for call in _iter_call_nodes(from_json)
            if _dotted_name(call.func) == "isinstance"
            and len(call.args) == 2
            and _is_name(call.args[0], "payload")
            and _is_name(call.args[1], "Mapping")
        ]
        if not mapping_type_checks:
            failures.append(
                "KnowledgeStore.from_canonical_json no longer validates parsed payload "
                "type with isinstance(payload, Mapping)"
            )

        from_payload_calls = [
            call
            for call in _iter_call_nodes(from_json)
            if _dotted_name(call.func) == "cls.from_canonical_payload"
        ]
        if len(from_payload_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json routes through "
                f"cls.from_canonical_payload {len(from_payload_calls)} time(s); expected "
                "exactly 1"
            )
        else:
            from_payload_call = from_payload_calls[0]
            if from_payload_call.keywords:
                failures.append(
                    "KnowledgeStore.from_canonical_json cls.from_canonical_payload route "
                    "unexpectedly uses keyword arguments"
                )
            if len(from_payload_call.args) != 1 or not _is_name(
                from_payload_call.args[0],
                "payload",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_json cls.from_canonical_payload route "
                    "drifted from positional payload"
                )

    from_json_file_key = ("KnowledgeStore", "from_canonical_json_file")
    from_json_file = methods.get(from_json_file_key)
    if from_json_file is None:
        missing_methods.append(_format_method_name(from_json_file_key))
    else:
        path_calls = [
            call
            for call in _iter_call_nodes(from_json_file)
            if _dotted_name(call.func) == "cls._canonical_json_file_path"
        ]
        if len(path_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json_file routes path validation through "
                f"cls._canonical_json_file_path {len(path_calls)} time(s); expected exactly 1"
            )
        else:
            path_call = path_calls[0]
            if len(path_call.args) != 1 or not _is_name(
                path_call.args[0],
                "canonical_json_path",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_json_file path route drifted from "
                    "canonical_json_path"
                )
            path_arg = _get_keyword_argument(path_call, name="path_arg")
            if not _is_literal_text(path_arg, "canonical_json_path"):
                failures.append(
                    "KnowledgeStore.from_canonical_json_file path_arg route drifted from "
                    "canonical_json_path"
                )

        read_bytes_calls = [
            call
            for call in _iter_call_nodes(from_json_file)
            if _dotted_name(call.func) == "path.read_bytes"
        ]
        if len(read_bytes_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json_file routes bytes loading through "
                f"path.read_bytes() {len(read_bytes_calls)} time(s); expected exactly 1"
            )

        decode_calls = [
            call
            for call in _iter_call_nodes(from_json_file)
            if _dotted_name(call.func) == "canonical_json_bytes.decode"
        ]
        if len(decode_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json_file routes UTF-8 decode through "
                f"canonical_json_bytes.decode(...) {len(decode_calls)} time(s); expected "
                "exactly 1"
            )
        else:
            decode_call = decode_calls[0]
            if len(decode_call.args) != 1 or not _is_literal_text(
                decode_call.args[0],
                "utf-8",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_json_file decode route drifted from "
                    "decode('utf-8', errors='strict')"
                )
            errors_arg = _get_keyword_argument(decode_call, name="errors")
            if not _is_literal_text(errors_arg, "strict"):
                failures.append(
                    "KnowledgeStore.from_canonical_json_file decode route drifted from "
                    "errors='strict'"
                )

        from_json_calls = [
            call
            for call in _iter_call_nodes(from_json_file)
            if _dotted_name(call.func) == "cls.from_canonical_json"
        ]
        if len(from_json_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_json_file routes through "
                f"cls.from_canonical_json {len(from_json_calls)} time(s); expected exactly 1"
            )
        else:
            from_json_call = from_json_calls[0]
            if from_json_call.keywords:
                failures.append(
                    "KnowledgeStore.from_canonical_json_file cls.from_canonical_json route "
                    "unexpectedly uses keyword arguments"
                )
            if len(from_json_call.args) != 1 or not _is_name(
                from_json_call.args[0],
                "canonical_json",
            ):
                failures.append(
                    "KnowledgeStore.from_canonical_json_file cls.from_canonical_json route "
                    "drifted from positional canonical_json"
                )

    assert not missing_methods, (
        "Store snapshot strict-deserialization guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot strict-deserialization route drift "
        "detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_deserialization_paths_reject_permissive_defaults_and_coercion_routes() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_STRICT_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        sensitive_names = _SENSITIVE_NAMES_BY_METHOD[method_key]

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed permissive text snippet "
                    f"{snippet!r}"
                )

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_DESERIALIZATION_ACCESSORS
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive accessor "
                    f"{call.func.attr!r} in deserialization path at line {call.lineno}"
                )

            if route_name in _DISALLOWED_DESERIALIZATION_COERCION_ROUTES and any(
                _contains_sensitive_reference(argument, sensitive_names)
                for argument in call.args
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc coercion route "
                    f"{route_name!r} over deserialization inputs at line {call.lineno}"
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

        for bool_op in _iter_bool_ops(method):
            if not isinstance(bool_op.op, ast.Or):
                continue
            if any(
                _contains_sensitive_reference(value, sensitive_names)
                for value in bool_op.values
            ):
                failures.append(
                    f"{method_label} reintroduced permissive fallback `or` route at "
                    f"line {bool_op.lineno}"
                )

        for target in _iter_assign_targets(method):
            if not isinstance(target, ast.Subscript):
                continue
            if _contains_sensitive_reference(target.value, sensitive_names):
                failures.append(
                    f"{method_label} reintroduced payload mutation assignment route at "
                    f"line {target.lineno}"
                )

    assert not missing_methods, (
        "Store snapshot strict-deserialization fallback guard targets missing from "
        "src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot strict-deserialization fallback/coercion "
        "drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
