from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_FILE_IO_METHODS = (
    ("KnowledgeStore", "_canonical_json_file_path"),
    ("KnowledgeStore", "to_canonical_json_file"),
    ("KnowledgeStore", "write_canonical_json_file"),
    ("KnowledgeStore", "from_canonical_json_file"),
)

_REQUIRED_HELPER_MINIMUM_ROUTES: dict[tuple[str, str], dict[str, int]] = {
    ("KnowledgeStore", "_canonical_json_file_path"): {
        "_payload_validation_error": 1,
        "Path": 1,
    },
    ("KnowledgeStore", "to_canonical_json_file"): {
        "self._canonical_json_file_path": 1,
        "self.as_canonical_json": 1,
        "tempfile.mkstemp": 1,
        "os.fdopen": 1,
        "os.fsync": 1,
        "_replace_file_with_retry": 1,
    },
    ("KnowledgeStore", "write_canonical_json_file"): {
        "self.to_canonical_json_file": 1,
    },
    ("KnowledgeStore", "from_canonical_json_file"): {
        "cls._canonical_json_file_path": 1,
        "path.read_bytes": 1,
        "canonical_json_bytes.decode": 1,
        "cls.from_canonical_json": 1,
        "_payload_validation_error": 1,
    },
}

_DISALLOWED_JSON_ROUTES = {
    "json.dump",
    "json.dumps",
    "json.load",
    "json.loads",
}

_DISALLOWED_COERCION_ROUTES = {
    "dict",
    "list",
    "tuple",
    "set",
}

_DISALLOWED_TEXT_SNIPPETS_BY_METHOD: dict[tuple[str, str], tuple[str, ...]] = {
    ("KnowledgeStore", "to_canonical_json_file"): (
        ".write_text(",
        ".write_bytes(",
        ".replace(",
        ".rename(",
        "json.dump(",
        "json.dumps(",
        "json.load(",
        "json.loads(",
        "NamedTemporaryFile(",
    ),
    ("KnowledgeStore", "write_canonical_json_file"): (
        ".write_text(",
        ".write_bytes(",
        ".replace(",
        ".rename(",
        "json.dump(",
        "json.dumps(",
        "json.load(",
        "json.loads(",
    ),
    ("KnowledgeStore", "from_canonical_json_file"): (
        ".read_text(",
        "json.dump(",
        "json.dumps(",
        "json.load(",
        "json.loads(",
    ),
}

_DISALLOWED_IO_ATTRIBUTE_ROUTES = {
    "write_text",
    "write_bytes",
    "read_text",
    "rename",
    "replace",
}

_TARGET_ATOMIC_HELPER_FUNCTION = "_replace_file_with_retry"
_TARGET_LOCK_HELPER_FUNCTION = "_is_windows_lock_permission_error"


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


def _is_name(node: ast.AST, expected_name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected_name


def _is_literal_text(node: ast.AST, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _call_route_counts(function_node: _DEF_OR_ASYNC) -> dict[str, int]:
    route_counts: dict[str, int] = {}
    for call in _iter_call_nodes(function_node):
        route_name = _dotted_name(call.func)
        if route_name is None:
            continue
        route_counts[route_name] = route_counts.get(route_name, 0) + 1
    return route_counts


def _method_source(source: str, method: _DEF_OR_ASYNC) -> str:
    segment = ast.get_source_segment(source, method)
    return segment or ""


def test_store_snapshot_file_io_routes_through_canonical_json_and_atomic_helpers() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)
    functions = _load_module_functions(module)

    missing_targets: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_FILE_IO_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_targets.append(method_label)
            continue

        route_counts = _call_route_counts(method)
        for route_name, minimum_count in _REQUIRED_HELPER_MINIMUM_ROUTES[method_key].items():
            observed_count = route_counts.get(route_name, 0)
            if observed_count < minimum_count:
                failures.append(
                    f"{method_label} routes through {route_name} {observed_count} time(s); "
                    f"expected at least {minimum_count}"
                )

        if method_key == ("KnowledgeStore", "_canonical_json_file_path"):
            return_nodes = list(_iter_return_nodes(method))
            if len(return_nodes) != 1:
                failures.append(
                    f"{method_label} has {len(return_nodes)} return statement(s); "
                    "expected exactly 1 path coercion return"
                )
            else:
                return_value = return_nodes[0].value
                if not isinstance(return_value, ast.Call) or _dotted_name(return_value.func) != "Path":
                    failures.append(
                        f"{method_label} no longer returns Path(file_path)"
                    )
                elif len(return_value.args) != 1 or not _is_name(return_value.args[0], "file_path"):
                    failures.append(
                        f"{method_label} Path(...) route drifted from file_path"
                    )

        if method_key == ("KnowledgeStore", "to_canonical_json_file"):
            encode_calls = [
                call
                for call in _iter_call_nodes(method)
                if isinstance(call.func, ast.Attribute) and call.func.attr == "encode"
            ]
            canonical_encode_calls = [
                call
                for call in encode_calls
                if isinstance(call.func.value, ast.Call)
                and _dotted_name(call.func.value.func) == "self.as_canonical_json"
                and not call.func.value.args
                and not call.func.value.keywords
            ]
            if len(canonical_encode_calls) != 1:
                failures.append(
                    f"{method_label} routes canonical UTF-8 encoding through "
                    f"self.as_canonical_json().encode(...) {len(canonical_encode_calls)} "
                    "time(s); expected exactly 1"
                )
            else:
                encode_call = canonical_encode_calls[0]
                if len(encode_call.args) != 1 or not _is_literal_text(
                    encode_call.args[0], "utf-8"
                ):
                    failures.append(
                        f"{method_label} canonical encode route drifted from "
                        'encode("utf-8", ...)'
                    )
                errors_value = _get_keyword_argument(encode_call, name="errors")
                if not _is_literal_text(errors_value, "strict"):
                    failures.append(
                        f"{method_label} canonical encode error handling drifted "
                        'from errors="strict"'
                    )

            replace_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "_replace_file_with_retry"
            ]
            if len(replace_calls) != 1:
                failures.append(
                    f"{method_label} routes through _replace_file_with_retry "
                    f"{len(replace_calls)} time(s); expected exactly 1"
                )
            else:
                replace_call = replace_calls[0]
                if replace_call.keywords:
                    failures.append(
                        f"{method_label} _replace_file_with_retry route unexpectedly "
                        "uses keyword arguments"
                    )
                if len(replace_call.args) != 2:
                    failures.append(
                        f"{method_label} _replace_file_with_retry route no longer uses "
                        "exactly two positional arguments"
                    )
                else:
                    if not _is_name(replace_call.args[0], "temp_path"):
                        failures.append(
                            f"{method_label} _replace_file_with_retry source route "
                            "drifted from temp_path"
                        )
                    if not _is_name(replace_call.args[1], "path"):
                        failures.append(
                            f"{method_label} _replace_file_with_retry target route "
                            "drifted from path"
                        )

        if method_key == ("KnowledgeStore", "write_canonical_json_file"):
            to_file_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "self.to_canonical_json_file"
            ]
            if len(to_file_calls) != 1:
                failures.append(
                    f"{method_label} routes through self.to_canonical_json_file "
                    f"{len(to_file_calls)} time(s); expected exactly 1"
                )
            else:
                to_file_call = to_file_calls[0]
                if to_file_call.keywords:
                    failures.append(
                        f"{method_label} self.to_canonical_json_file route unexpectedly "
                        "uses keyword arguments"
                    )
                if len(to_file_call.args) != 1 or not _is_name(
                    to_file_call.args[0], "canonical_json_path"
                ):
                    failures.append(
                        f"{method_label} self.to_canonical_json_file route drifted "
                        "from canonical_json_path"
                    )

        if method_key == ("KnowledgeStore", "from_canonical_json_file"):
            decode_calls = [
                call
                for call in _iter_call_nodes(method)
                if _dotted_name(call.func) == "canonical_json_bytes.decode"
            ]
            if len(decode_calls) != 1:
                failures.append(
                    f"{method_label} routes canonical UTF-8 decoding through "
                    f"canonical_json_bytes.decode(...) {len(decode_calls)} time(s); "
                    "expected exactly 1"
                )
            else:
                decode_call = decode_calls[0]
                if len(decode_call.args) != 1 or not _is_literal_text(
                    decode_call.args[0], "utf-8"
                ):
                    failures.append(
                        f"{method_label} canonical decode route drifted from "
                        'decode("utf-8", ...)'
                    )
                errors_value = _get_keyword_argument(decode_call, name="errors")
                if not _is_literal_text(errors_value, "strict"):
                    failures.append(
                        f"{method_label} canonical decode error handling drifted "
                        'from errors="strict"'
                    )

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
                        f"{method_label} cls.from_canonical_json route unexpectedly "
                        "uses keyword arguments"
                    )
                if len(from_json_call.args) != 1 or not _is_name(
                    from_json_call.args[0], "canonical_json"
                ):
                    failures.append(
                        f"{method_label} cls.from_canonical_json route drifted from "
                        "canonical_json"
                    )

    atomic_helper = functions.get(_TARGET_ATOMIC_HELPER_FUNCTION)
    if atomic_helper is None:
        missing_targets.append(_TARGET_ATOMIC_HELPER_FUNCTION)
    else:
        helper_route_counts = _call_route_counts(atomic_helper)
        for route_name, minimum_count in (
            ("os.replace", 1),
            (f"{_TARGET_LOCK_HELPER_FUNCTION}", 1),
            ("time.sleep", 1),
        ):
            observed_count = helper_route_counts.get(route_name, 0)
            if observed_count < minimum_count:
                failures.append(
                    f"{_TARGET_ATOMIC_HELPER_FUNCTION} routes through {route_name} "
                    f"{observed_count} time(s); expected at least {minimum_count}"
                )

    lock_helper = functions.get(_TARGET_LOCK_HELPER_FUNCTION)
    if lock_helper is None:
        missing_targets.append(_TARGET_LOCK_HELPER_FUNCTION)
    else:
        helper_route_counts = _call_route_counts(lock_helper)
        if helper_route_counts.get("isinstance", 0) < 1:
            failures.append(
                f"{_TARGET_LOCK_HELPER_FUNCTION} no longer checks PermissionError "
                "using isinstance(...)"
            )
        if helper_route_counts.get("getattr", 0) < 1:
            failures.append(
                f"{_TARGET_LOCK_HELPER_FUNCTION} no longer routes through getattr(...) "
                "winerror access"
            )

    assert not missing_targets, (
        "Store snapshot file I/O route guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_targets))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot file I/O helper-route drift detected "
        "in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_store_snapshot_file_io_paths_reject_inline_json_non_atomic_write_and_coercion_drift() -> None:
    source, module = _load_module(_CORE_PATH)
    methods = _load_class_methods(module)

    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in _TARGET_FILE_IO_METHODS:
        method_label = _format_method_name(method_key)
        method = methods.get(method_key)
        if method is None:
            missing_methods.append(method_label)
            continue

        for call in _iter_call_nodes(method):
            route_name = _dotted_name(call.func)
            if route_name in _DISALLOWED_JSON_ROUTES:
                failures.append(
                    f"{method_label} reintroduced disallowed JSON route "
                    f"{route_name!r} at line {call.lineno}"
                )
            if route_name in _DISALLOWED_COERCION_ROUTES:
                failures.append(
                    f"{method_label} reintroduced ad-hoc coercion route "
                    f"{route_name!r} at line {call.lineno}"
                )
            if route_name == "os.replace":
                failures.append(
                    f"{method_label} reintroduced direct os.replace(...) routing at "
                    f"line {call.lineno}; expected _replace_file_with_retry helper route"
                )
            if route_name == "tempfile.NamedTemporaryFile":
                failures.append(
                    f"{method_label} reintroduced tempfile.NamedTemporaryFile(...) route "
                    f"at line {call.lineno}; expected tempfile.mkstemp(...) route"
                )
            if isinstance(call.func, ast.Attribute) and call.func.attr in _DISALLOWED_IO_ATTRIBUTE_ROUTES:
                failures.append(
                    f"{method_label} reintroduced non-canonical file I/O route "
                    f"{call.func.attr!r} at line {call.lineno}"
                )

            if _is_sort_call(call):
                failures.append(
                    f"{method_label} reintroduced inline sort/sorted routing at line "
                    f"{call.lineno}"
                )

        lambda_lines = sorted(
            {node.lineno for node in ast.walk(method) if isinstance(node, ast.Lambda)}
        )
        if lambda_lines:
            failures.append(
                f"{method_label} reintroduced inline lambda ordering/coercion routing "
                f"at lines {lambda_lines}"
            )

        method_source = _method_source(source, method)
        for snippet in _DISALLOWED_TEXT_SNIPPETS_BY_METHOD.get(method_key, ()):
            if snippet in method_source:
                failures.append(
                    f"{method_label} reintroduced disallowed file route snippet "
                    f"{snippet!r}"
                )

    assert not missing_methods, (
        "Store snapshot file I/O bypass guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Deterministic knowledge-store snapshot file I/O bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
