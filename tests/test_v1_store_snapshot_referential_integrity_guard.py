from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_REFERENTIAL_BYPASS_METHODS = (
    ("KnowledgeStore", "from_canonical_payload"),
    ("KnowledgeStore", "validate_canonical_payload"),
    ("KnowledgeStore", "validate_canonical_json"),
    ("KnowledgeStore", "validate_canonical_json_file"),
)

_UPSTREAM_REFERENTIAL_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("KnowledgeStore", "from_canonical_json"): ("cls.from_canonical_payload", "payload"),
    ("KnowledgeStore", "from_canonical_json_file"): ("cls.from_canonical_json", "canonical_json"),
    ("KnowledgeStore", "validate_canonical_payload"): ("cls.from_canonical_payload", "payload"),
    ("KnowledgeStore", "validate_canonical_json"): ("cls.from_canonical_json", "canonical_json"),
    ("KnowledgeStore", "validate_canonical_json_file"): (
        "cls.from_canonical_json_file",
        "canonical_json_path",
    ),
}

_DISALLOWED_REFERENTIAL_ACCESSORS = {"get", "setdefault", "pop"}
_DISALLOWED_REFERENTIAL_COERCION_ROUTES = {
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
_DISALLOWED_REFERENTIAL_BYPASS_ROUTES = {
    "_missing_relation_endpoints",
    "cls._missing_relation_endpoints",
    "self._missing_relation_endpoints",
    "KnowledgeStore._missing_relation_endpoints",
}
_DISALLOWED_DIRECT_VALIDATION_ERROR_ROUTES = {
    "SnapshotValidationError",
    "SnapshotValidationError.from_value_error",
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
        "store.cores.get(",
        "store.revisions.get(",
        "missing_endpoints or",
        "or missing_endpoints",
        "if not missing_endpoints",
        "missing_endpoints = ()",
        "missing_endpoints = []",
        "default=",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or {}",
        " or []",
        " or ()",
    ),
    ("KnowledgeStore", "validate_canonical_payload"): (
        "payload.get(",
        "payload.setdefault(",
        "payload.pop(",
        "json.loads(",
        "json.dumps(",
        "_payload_validation_error(",
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
        "_payload_validation_error(",
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
        "_payload_validation_error(",
        "SnapshotValidationError(",
        "SnapshotValidationError.from_value_error(",
        "except ValueError",
        " or b\"\"",
        " or \"\"",
        " or None",
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
        "missing_endpoints",
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


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _iter_call_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Call):
            yield member


def _iter_if_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.If):
            yield member


def _iter_return_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Return):
            yield member


def _iter_assign_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Assign):
            yield member


def _iter_assign_targets(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.Assign):
            for target in member.targets:
                yield target
        if isinstance(member, ast.AnnAssign):
            yield member.target
        if isinstance(member, ast.AugAssign):
            yield member.target


def _iter_bool_ops(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.BoolOp):
            yield member


def _iter_ifexp_nodes(node: ast.AST):
    for member in ast.walk(node):
        if isinstance(member, ast.IfExp):
            yield member


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_name(node: ast.AST | None, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _method_source(source: str, method: _DEF_OR_ASYNC) -> str:
    segment = ast.get_source_segment(source, method)
    return segment or ""


def _format_method_name(method_key: tuple[str, str]) -> str:
    return f"{method_key[0]}.{method_key[1]}"


def _contains_text_fragment(node: ast.AST | None, fragment: str) -> bool:
    if node is None:
        return False
    for member in ast.walk(node):
        if isinstance(member, ast.Constant) and isinstance(member.value, str):
            if fragment in member.value:
                return True
    return False


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
            if "missing_endpoints" in member.value:
                return True
    return False


def _is_revision_core_reference_guard(if_node: ast.If) -> bool:
    test = if_node.test
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.NotIn)
        and len(test.comparators) == 1
        and _dotted_name(test.left) == "revision.core_id"
        and _dotted_name(test.comparators[0]) == "store.cores"
    )


def _is_relation_id_in_active_relation_index_guard(if_node: ast.If) -> bool:
    test = if_node.test
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.In)
        and len(test.comparators) == 1
        and _is_name(test.left, "relation_id")
        and _dotted_name(test.comparators[0]) == "store.relations"
    )


def _contains_missing_endpoints_join(node: ast.AST | None) -> bool:
    if node is None:
        return False
    for member in ast.walk(node):
        if (
            isinstance(member, ast.Call)
            and isinstance(member.func, ast.Attribute)
            and isinstance(member.func.value, ast.Constant)
            and member.func.value.value == ", "
            and member.func.attr == "join"
            and len(member.args) == 1
            and _is_name(member.args[0], "missing_endpoints")
            and not member.keywords
        ):
            return True
    return False


def test_store_snapshot_referential_integrity_routes_through_canonical_helpers() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    from_payload_key = ("KnowledgeStore", "from_canonical_payload")
    from_payload = methods.get(from_payload_key)
    if from_payload is None:
        missing_targets.append(_format_method_name(from_payload_key))
    else:
        decorators = [_dotted_name(decorator) for decorator in from_payload.decorator_list]
        if decorators.count("classmethod") != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload classmethod decoration count is "
                f"{decorators.count('classmethod')}; expected exactly 1"
            )
        if decorators.count("_route_snapshot_validation_error") != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload _route_snapshot_validation_error "
                f"decoration count is {decorators.count('_route_snapshot_validation_error')}; "
                "expected exactly 1"
            )

        missing_endpoint_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "cls._missing_relation_endpoints_from_index"
        ]
        if len(missing_endpoint_calls) != 2:
            failures.append(
                "KnowledgeStore.from_canonical_payload routes endpoint referential checks "
                "through cls._missing_relation_endpoints_from_index "
                f"{len(missing_endpoint_calls)} time(s); expected exactly 2"
            )
        for call in missing_endpoint_calls:
            if call.args:
                failures.append(
                    "KnowledgeStore.from_canonical_payload referential helper route "
                    "unexpectedly uses positional arguments"
                )
            if len(call.keywords) != 2:
                failures.append(
                    "KnowledgeStore.from_canonical_payload referential helper route "
                    "keyword set drifted from revision_ids/incoming_relation"
                )
            revision_ids_arg = _get_keyword_argument(call, name="revision_ids")
            incoming_relation_arg = _get_keyword_argument(call, name="incoming_relation")
            if _dotted_name(revision_ids_arg) != "store.revisions":
                failures.append(
                    "KnowledgeStore.from_canonical_payload referential helper route drifted "
                    "from revision_ids=store.revisions"
                )
            if not _is_name(incoming_relation_arg, "relation"):
                failures.append(
                    "KnowledgeStore.from_canonical_payload referential helper route drifted "
                    "from incoming_relation=relation"
                )

        bypass_helper_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) in _DISALLOWED_REFERENTIAL_BYPASS_ROUTES
        ]
        if bypass_helper_calls:
            failures.append(
                "KnowledgeStore.from_canonical_payload reintroduced non-canonical "
                "referential helper routing via _missing_relation_endpoints"
            )

        revision_core_guards = [
            if_node
            for if_node in _iter_if_nodes(from_payload)
            if _is_revision_core_reference_guard(if_node)
        ]
        if len(revision_core_guards) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload revision->core referential guard "
                f"count is {len(revision_core_guards)}; expected exactly 1"
            )

        relation_id_active_guards = [
            if_node
            for if_node in _iter_if_nodes(from_payload)
            if _is_relation_id_in_active_relation_index_guard(if_node)
        ]
        if len(relation_id_active_guards) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload relation-variant endpoint guard "
                "no longer gates referential checks via `if relation_id in store.relations` "
                f"(observed {len(relation_id_active_guards)})"
            )
        else:
            nested_helper_calls = [
                call
                for call in _iter_call_nodes(relation_id_active_guards[0])
                if _dotted_name(call.func) == "cls._missing_relation_endpoints_from_index"
            ]
            if len(nested_helper_calls) != 1:
                failures.append(
                    "KnowledgeStore.from_canonical_payload active relation-variant guard "
                    "no longer contains exactly one endpoint referential helper call"
                )

        payload_validation_calls = [
            call
            for call in _iter_call_nodes(from_payload)
            if _dotted_name(call.func) == "_payload_validation_error" and len(call.args) >= 2
        ]

        revision_core_error_calls = [
            call
            for call in payload_validation_calls
            if _contains_text_fragment(call.args[0], "payload.revisions[")
            and _contains_text_fragment(call.args[0], "].core_id")
            and _contains_text_fragment(call.args[1], "unknown core_id ")
        ]
        if len(revision_core_error_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload revision->core referential failure "
                "routing drifted from _payload_validation_error(payload.revisions[i].core_id, "
                "'unknown core_id ...')"
            )

        active_relation_error_calls = [
            call
            for call in payload_validation_calls
            if _contains_text_fragment(call.args[0], "payload.active_relations[")
            and _contains_text_fragment(
                call.args[1],
                "active relation references missing revision endpoints: ",
            )
            and _contains_missing_endpoints_join(call.args[1])
        ]
        if len(active_relation_error_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload active relation referential failure "
                "routing drifted from canonical missing-endpoints payload validation path"
            )

        relation_variant_error_calls = [
            call
            for call in payload_validation_calls
            if _contains_text_fragment(call.args[0], ".relation")
            and _contains_text_fragment(
                call.args[1],
                "relation variant references missing revision endpoints: ",
            )
            and _contains_missing_endpoints_join(call.args[1])
        ]
        if len(relation_variant_error_calls) != 1:
            failures.append(
                "KnowledgeStore.from_canonical_payload relation-variant referential failure "
                "routing drifted from canonical missing-endpoints payload validation path"
            )

        method_source = _method_source(source, from_payload)
        for required_snippet in (
            "if revision.core_id not in store.cores:",
            "if relation_id in store.relations:",
            "active relation references missing revision endpoints: ",
            "relation variant references missing revision endpoints: ",
        ):
            if required_snippet not in method_source:
                failures.append(
                    "KnowledgeStore.from_canonical_payload missing required referential "
                    f"integrity snippet {required_snippet!r}"
                )

    for method_key, (upstream_route, upstream_arg_name) in _UPSTREAM_REFERENTIAL_ROUTES.items():
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
                    f"{method_label} {upstream_route} route unexpectedly uses keyword "
                    "arguments"
                )
            if len(upstream_call.args) != 1 or not _is_name(
                upstream_call.args[0], upstream_arg_name
            ):
                failures.append(
                    f"{method_label} {upstream_route} route drifted from positional "
                    f"{upstream_arg_name}"
                )

        if method_key[1].startswith("validate_"):
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
                    f"{method_label} has {len(return_nodes)} return statement(s); "
                    "expected exactly 1"
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
        "Store snapshot referential-integrity guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot referential-integrity route drift detected "
        "in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_referential_integrity_paths_reject_fallback_and_default_coercion_bypass() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_REFERENTIAL_BYPASS_METHODS:
        method = methods.get(method_key)
        method_label = _format_method_name(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed referential bypass snippet "
                    f"{snippet!r}"
                )

        sensitive_names = _SENSITIVE_NAMES_BY_METHOD[method_key]
        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)

            if route_name in _DISALLOWED_REFERENTIAL_BYPASS_ROUTES:
                failures.append(
                    f"{method_label} reintroduced non-canonical referential route "
                    f"{route_name!r} at line {call.lineno}"
                )

            if route_name in _DISALLOWED_DIRECT_VALIDATION_ERROR_ROUTES:
                failures.append(
                    f"{method_label} reintroduced direct SnapshotValidationError route "
                    f"{route_name!r} at line {call.lineno}; expected centralized decorator "
                    "conversion"
                )

            if (
                method_key != ("KnowledgeStore", "from_canonical_payload")
                and route_name == "cls._missing_relation_endpoints_from_index"
            ):
                failures.append(
                    f"{method_label} reintroduced inline referential endpoint validation "
                    f"route {route_name!r} at line {call.lineno}; expected canonical "
                    "delegation through from_canonical_payload"
                )

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in _DISALLOWED_REFERENTIAL_ACCESSORS
                and _contains_sensitive_reference(call.func.value, sensitive_names)
            ):
                failures.append(
                    f"{method_label} reintroduced permissive accessor "
                    f".{call.func.attr}(...) at line {call.lineno}"
                )

            if route_name in _DISALLOWED_REFERENTIAL_COERCION_ROUTES and any(
                _contains_sensitive_reference(argument, sensitive_names)
                for argument in call.args
            ):
                failures.append(
                    f"{method_label} reintroduced ad-hoc coercion route "
                    f"{route_name!r} at line {call.lineno}"
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
                    f"{method_label} reintroduced payload/path mutation assignment route "
                    f"at line {target.lineno}"
                )

    assert not missing_targets, (
        "Store snapshot referential-integrity fallback guard targets missing from "
        "src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot referential-integrity fallback/coercion "
        "bypass drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
