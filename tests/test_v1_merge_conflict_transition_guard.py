from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"
_TARGET_METHOD = (
    "KnowledgeStore",
    "query_merge_conflict_projection_transition_for_tx_window",
)

_FORBIDDEN_TRANSITION_ROUTES = (
    "KnowledgeStore.query_merge_conflict_projection_for_tx_window",
    "MergeResult.stream_conflict_summary",
    "KnowledgeStore.conflict_summary",
)

_EXPECTED_BUCKET_ORDER_ROUTES = {
    "signature_counts": "KnowledgeStore._ordered_merge_conflict_signature_bucket",
    "code_counts": "KnowledgeStore._ordered_merge_conflict_code_bucket",
}

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef


def _load_class_methods(path: Path) -> dict[tuple[str, str], _DEF_OR_ASYNC]:
    source = path.read_text(encoding="utf-8-sig")
    module = ast.parse(source, filename=str(path))
    methods: dict[tuple[str, str], _DEF_OR_ASYNC] = {}

    for node in module.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[(node.name, member.name)] = member

    return methods


def _target_method() -> _DEF_OR_ASYNC:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_METHOD)
    assert method is not None, (
        "Merge-conflict transition guard target missing from src/dks/core.py: "
        f"{_TARGET_METHOD[0]}.{_TARGET_METHOD[1]}"
    )
    return method


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


def _iter_named_assignments(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value, node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield node.target.id, node.value, node.lineno


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_subscript_lookup(value: ast.AST, *, source_name: str, key: str) -> bool:
    return (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Name)
        and value.value.id == source_name
        and isinstance(value.slice, ast.Constant)
        and value.slice.value == key
    )


def _assert_bucket_projection_lambda(
    *,
    projection_lambda: ast.AST,
    expected_attr: str,
    failures: list[str],
    bucket_name: str,
) -> None:
    if not isinstance(projection_lambda, ast.Lambda):
        failures.append(
            f"bucket_routes[{bucket_name!r}] projection route is no longer a lambda"
        )
        return

    if len(projection_lambda.args.args) != 1:
        failures.append(
            f"bucket_routes[{bucket_name!r}] projection lambda has unexpected arity"
        )
        return

    projection_arg_name = projection_lambda.args.args[0].arg
    body = projection_lambda.body
    if not (
        isinstance(body, ast.Attribute)
        and isinstance(body.value, ast.Name)
        and body.value.id == projection_arg_name
        and body.attr == expected_attr
    ):
        failures.append(
            f"bucket_routes[{bucket_name!r}] projection lambda no longer routes through "
            f"projection.{expected_attr}"
        )


def test_merge_conflict_transition_uses_canonical_shared_transition_helper_route() -> None:
    method = _target_method()
    failures: list[str] = []

    assignments = {name: value for name, value, _ in _iter_named_assignments(method)}

    stream_value = assignments.get("stream")
    if stream_value is None:
        failures.append("missing canonical stream staging assignment: stream = tuple(...)")
    elif not isinstance(stream_value, ast.Call) or _dotted_name(stream_value.func) != "tuple":
        failures.append("stream staging is no longer tuple(merge_results_by_tx)")
    elif len(stream_value.args) != 1:
        failures.append("stream staging tuple(...) call has unexpected arity")
    else:
        stream_arg = stream_value.args[0]
        if not isinstance(stream_arg, ast.Name) or stream_arg.id != "merge_results_by_tx":
            failures.append("stream staging drifted from tuple(merge_results_by_tx)")

    forbidden_route_hits: list[str] = []
    sorted_calls = 0
    helper_calls: list[ast.Call] = []
    projection_as_of_calls = 0
    for call in _iter_call_nodes(method):
        route = _dotted_name(call.func)
        if route in _FORBIDDEN_TRANSITION_ROUTES:
            forbidden_route_hits.append(f"{route} (line {call.lineno})")
        if isinstance(call.func, ast.Name) and call.func.id == "sorted":
            sorted_calls += 1
        if route == "KnowledgeStore._query_transition_buckets_via_as_of_diff":
            helper_calls.append(call)
        if route == "KnowledgeStore.query_merge_conflict_projection_as_of":
            projection_as_of_calls += 1

    if forbidden_route_hits:
        failures.append(
            "merge-conflict transition path uses non-canonical conflict-summary route(s): "
            + ", ".join(sorted(forbidden_route_hits))
        )

    if sorted_calls:
        failures.append(
            "query_merge_conflict_projection_transition_for_tx_window reintroduced direct "
            f"sorted(...) routing {sorted_calls} time(s)"
        )

    if len(helper_calls) != 1:
        failures.append(
            "query_merge_conflict_projection_transition_for_tx_window routes through "
            "KnowledgeStore._query_transition_buckets_via_as_of_diff "
            f"{len(helper_calls)} time(s); expected 1"
        )
    else:
        helper_call = helper_calls[0]
        if helper_call.args:
            failures.append(
                "canonical transition helper call unexpectedly uses positional arguments"
            )

        expected_name_keywords = {
            "tx_from": "tx_from",
            "tx_to": "tx_to",
            "projection_from": "tx_from",
            "projection_to": "tx_to",
        }
        for keyword_name, expected_name in expected_name_keywords.items():
            value = _get_keyword_argument(helper_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    f"canonical transition helper {keyword_name} routing drifted from "
                    f"{expected_name}"
                )

        projection_as_of = _get_keyword_argument(helper_call, name="projection_as_of")
        if not isinstance(projection_as_of, ast.Lambda):
            failures.append(
                "canonical transition helper projection_as_of route is no longer a lambda"
            )
        else:
            if len(projection_as_of.args.args) != 1:
                failures.append(
                    "projection_as_of lambda has unexpected arity"
                )
            else:
                projection_arg_name = projection_as_of.args.args[0].arg
                projection_call = projection_as_of.body
                if not isinstance(projection_call, ast.Call):
                    failures.append(
                        "projection_as_of lambda no longer calls "
                        "KnowledgeStore.query_merge_conflict_projection_as_of"
                    )
                else:
                    if _dotted_name(projection_call.func) != "KnowledgeStore.query_merge_conflict_projection_as_of":
                        failures.append(
                            "projection_as_of lambda uses non-canonical as-of route "
                            f"{_dotted_name(projection_call.func)!r}"
                        )
                    if not (
                        len(projection_call.args) == 1
                        and isinstance(projection_call.args[0], ast.Name)
                        and projection_call.args[0].id == "stream"
                    ):
                        failures.append(
                            "projection_as_of lambda no longer routes through canonical stream"
                        )
                    tx_id_arg = _get_keyword_argument(projection_call, name="tx_id")
                    if not isinstance(tx_id_arg, ast.Name) or tx_id_arg.id != projection_arg_name:
                        failures.append(
                            "projection_as_of lambda tx_id routing drifted from lambda argument"
                        )

        bucket_routes = _get_keyword_argument(helper_call, name="bucket_routes")
        if not isinstance(bucket_routes, ast.Dict):
            failures.append(
                "canonical transition helper bucket_routes is no longer a dictionary literal"
            )
        else:
            observed_bucket_names: set[str] = set()
            for key_node, value_node in zip(bucket_routes.keys, bucket_routes.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    failures.append(
                        "canonical transition helper bucket_routes contains non-string key"
                    )
                    continue
                bucket_name = key_node.value
                observed_bucket_names.add(bucket_name)

                if bucket_name not in _EXPECTED_BUCKET_ORDER_ROUTES:
                    failures.append(
                        f"canonical transition helper bucket_routes includes unexpected key {bucket_name!r}"
                    )
                    continue

                if not (
                    isinstance(value_node, ast.Tuple)
                    and len(value_node.elts) == 3
                ):
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] is no longer a 3-tuple route descriptor"
                    )
                    continue

                projection_lambda, key_route_node, order_route_node = value_node.elts
                _assert_bucket_projection_lambda(
                    projection_lambda=projection_lambda,
                    expected_attr=bucket_name,
                    failures=failures,
                    bucket_name=bucket_name,
                )

                key_route = _dotted_name(key_route_node)
                if key_route != "KnowledgeStore._identity_transition_key":
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] uses non-canonical key route "
                        f"{key_route!r}"
                    )

                order_route = _dotted_name(order_route_node)
                expected_order_route = _EXPECTED_BUCKET_ORDER_ROUTES[bucket_name]
                if order_route != expected_order_route:
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] uses non-canonical order route "
                        f"{order_route!r}; expected {expected_order_route}"
                    )

            if observed_bucket_names != set(_EXPECTED_BUCKET_ORDER_ROUTES):
                failures.append(
                    "canonical transition helper bucket_routes keys drifted; observed "
                    f"{sorted(observed_bucket_names)} expected "
                    f"{sorted(_EXPECTED_BUCKET_ORDER_ROUTES)}"
                )

    if projection_as_of_calls != 1:
        failures.append(
            "query_merge_conflict_projection_transition_for_tx_window should reference "
            "KnowledgeStore.query_merge_conflict_projection_as_of only inside the helper "
            f"projection lambda; observed {projection_as_of_calls} call(s)"
        )

    assert not failures, (
        "Merge-conflict transition helper-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_merge_conflict_transition_builds_output_buckets_from_helper_result() -> None:
    method = _target_method()
    failures: list[str] = []

    transition_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "MergeConflictProjectionTransition"
    ]
    if len(transition_calls) != 1:
        failures.append(
            "query_merge_conflict_projection_transition_for_tx_window no longer constructs "
            "exactly one MergeConflictProjectionTransition"
        )
    else:
        transition_call = transition_calls[0]
        keyword_values = {
            keyword.arg: keyword.value
            for keyword in transition_call.keywords
            if keyword.arg is not None
        }

        for scalar_name in ("tx_from", "tx_to"):
            value = keyword_values.get(scalar_name)
            if not isinstance(value, ast.Name) or value.id != scalar_name:
                failures.append(
                    f"MergeConflictProjectionTransition {scalar_name} routing drifted"
                )

        for bucket_name in (
            "entered_signature_counts",
            "exited_signature_counts",
            "entered_code_counts",
            "exited_code_counts",
        ):
            value = keyword_values.get(bucket_name)
            if value is None:
                failures.append(
                    f"MergeConflictProjectionTransition missing {bucket_name} bucket"
                )
                continue

            if not _is_subscript_lookup(
                value,
                source_name="transition_buckets",
                key=bucket_name,
            ):
                failures.append(
                    f"{bucket_name} no longer routes from transition_buckets[{bucket_name!r}]"
                )

    assert not failures, (
        "Merge-conflict transition output-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
