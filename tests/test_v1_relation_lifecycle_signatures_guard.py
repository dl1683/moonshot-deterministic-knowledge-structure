from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_PROJECTION_METHODS = {
    ("KnowledgeStore", "query_relation_lifecycle_signatures_as_of"): {
        "projection_route": "self.query_relation_lifecycle_as_of",
        "projection_kwargs": {
            "tx_id": "tx_id",
            "valid_at": "valid_at",
            "revision_id": "revision_id",
        },
    },
    ("KnowledgeStore", "query_relation_lifecycle_signatures_for_tx_window"): {
        "projection_route": "self.query_relation_lifecycle_for_tx_window",
        "projection_kwargs": {
            "tx_start": "tx_start",
            "tx_end": "tx_end",
            "valid_at": "valid_at",
            "revision_id": "revision_id",
        },
    },
}

_TARGET_TRANSITION_METHOD = (
    "KnowledgeStore",
    "query_relation_lifecycle_signature_transition_for_tx_window",
)

_FORBIDDEN_TRANSITION_ROUTES = (
    "self.query_relation_lifecycle_as_of",
    "self.query_relation_lifecycle_for_tx_window",
    "self.query_relation_lifecycle_transition_for_tx_window",
)

_EXPECTED_TRANSITION_SET_STAGING = {
    "from_active": ("from_projection", "active"),
    "to_active": ("to_projection", "active"),
    "from_pending": ("from_projection", "pending"),
    "to_pending": ("to_projection", "pending"),
}

_EXPECTED_TRANSITION_BUCKET_DIFFS = {
    "entered_active": ("to_active", "from_active"),
    "exited_active": ("from_active", "to_active"),
    "entered_pending": ("to_pending", "from_pending"),
    "exited_pending": ("from_pending", "to_pending"),
}


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


def _is_sorted_call(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Name) and call.func.id == "sorted"


def _is_tuple_call_of(value: ast.AST | None, *, func_name: str) -> ast.Call | None:
    if not isinstance(value, ast.Call):
        return None
    if not isinstance(value.func, ast.Name) or value.func.id != "tuple":
        return None
    if len(value.args) != 1:
        return None
    inner = value.args[0]
    if not isinstance(inner, ast.Call):
        return None
    if not isinstance(inner.func, ast.Name) or inner.func.id != func_name:
        return None
    return inner


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_name_subtraction(node: ast.AST, *, left: str, right: str) -> bool:
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Sub)
        and isinstance(node.left, ast.Name)
        and node.left.id == left
        and isinstance(node.right, ast.Name)
        and node.right.id == right
    )


def _assert_no_inline_sorted_key_drift(*, sorted_call: ast.Call, bucket_name: str, failures: list[str]) -> None:
    key_argument = _get_keyword_argument(sorted_call, name="key")
    if key_argument is None:
        return
    if isinstance(key_argument, ast.Lambda):
        failures.append(
            f"{bucket_name} reintroduced inline lambda sort-key routing at line "
            f"{sorted_call.lineno}"
        )
        if isinstance(key_argument.body, ast.Tuple):
            failures.append(
                f"{bucket_name} reintroduced inline tuple lambda sort-key routing at "
                f"line {sorted_call.lineno}"
            )
        return
    if isinstance(key_argument, ast.Tuple):
        failures.append(
            f"{bucket_name} reintroduced inline tuple sort-key routing at line "
            f"{sorted_call.lineno}"
        )
        return
    failures.append(
        f"{bucket_name} uses non-canonical explicit key routing at line {sorted_call.lineno}"
    )


def _assert_projection_signature_bucket_route(
    *,
    sorted_call: ast.Call,
    bucket_name: str,
    failures: list[str],
) -> None:
    _assert_no_inline_sorted_key_drift(
        sorted_call=sorted_call,
        bucket_name=bucket_name,
        failures=failures,
    )
    if len(sorted_call.args) != 1:
        failures.append(
            f"{bucket_name} sorted(...) call has unexpected positional arguments"
        )
        return

    source = sorted_call.args[0]
    if not isinstance(source, ast.GeneratorExp):
        failures.append(
            f"{bucket_name} no longer stages signatures through sorted(generator)"
        )
        return

    if len(source.generators) != 1:
        failures.append(
            f"{bucket_name} signature generator has unexpected comprehension shape"
        )
        return

    generator = source.generators[0]
    if generator.ifs:
        failures.append(
            f"{bucket_name} signature generator unexpectedly adds in-line filtering"
        )
    if generator.is_async:
        failures.append(
            f"{bucket_name} signature generator unexpectedly became async"
        )

    if not isinstance(generator.target, ast.Name):
        failures.append(
            f"{bucket_name} signature generator target is no longer a named relation"
        )
        return

    relation_name = generator.target.id
    relation_iter = generator.iter
    if not isinstance(relation_iter, ast.Attribute):
        failures.append(
            f"{bucket_name} signature generator no longer iterates projection.{bucket_name}"
        )
        return
    if not isinstance(relation_iter.value, ast.Name) or relation_iter.value.id != "projection":
        failures.append(
            f"{bucket_name} signature generator no longer reads from projection"
        )
        return
    if relation_iter.attr != bucket_name:
        failures.append(
            f"{bucket_name} signature generator iterates projection.{relation_iter.attr}; "
            f"expected projection.{bucket_name}"
        )

    signature_call = source.elt
    if not isinstance(signature_call, ast.Call):
        failures.append(
            f"{bucket_name} signature generator no longer calls _relation_state_signature"
        )
        return
    if _dotted_name(signature_call.func) != "self._relation_state_signature":
        failures.append(
            f"{bucket_name} signature generator uses non-canonical signature helper route "
            f"{_dotted_name(signature_call.func)!r}"
        )
        return
    if signature_call.args:
        failures.append(
            f"{bucket_name} _relation_state_signature call now uses positional arguments"
        )

    keyword_names = {keyword.arg for keyword in signature_call.keywords if keyword.arg is not None}
    expected_keyword_names = {"bucket", "relation_id", "relation"}
    if keyword_names != expected_keyword_names:
        failures.append(
            f"{bucket_name} _relation_state_signature keyword routing drifted; observed "
            f"{sorted(keyword_names)} expected {sorted(expected_keyword_names)}"
        )

    bucket_argument = _get_keyword_argument(signature_call, name="bucket")
    if not isinstance(bucket_argument, ast.Constant) or bucket_argument.value != bucket_name:
        failures.append(
            f"{bucket_name} _relation_state_signature bucket argument drifted from "
            f"{bucket_name!r}"
        )

    relation_id_argument = _get_keyword_argument(signature_call, name="relation_id")
    if not (
        isinstance(relation_id_argument, ast.Attribute)
        and isinstance(relation_id_argument.value, ast.Name)
        and relation_id_argument.value.id == relation_name
        and relation_id_argument.attr == "relation_id"
    ):
        failures.append(
            f"{bucket_name} _relation_state_signature relation_id argument drifted from "
            f"{relation_name}.relation_id"
        )

    relation_argument = _get_keyword_argument(signature_call, name="relation")
    if not (
        isinstance(relation_argument, ast.Name)
        and relation_argument.id == relation_name
    ):
        failures.append(
            f"{bucket_name} _relation_state_signature relation argument drifted from "
            f"{relation_name}"
        )


def test_relation_lifecycle_signature_projections_use_canonical_signature_helper_route() -> None:
    methods = _load_class_methods(_CORE_PATH)
    missing_methods: list[str] = []
    failures: list[str] = []

    for method_key in sorted(_TARGET_PROJECTION_METHODS):
        requirement = _TARGET_PROJECTION_METHODS[method_key]
        method = methods.get(method_key)
        method_label = f"{method_key[0]}.{method_key[1]}"
        if method is None:
            missing_methods.append(method_label)
            continue

        sorted_calls = [call for call in _iter_call_nodes(method) if _is_sorted_call(call)]
        if len(sorted_calls) != 2:
            failures.append(
                f"{method_label} has {len(sorted_calls)} sorted call(s); expected exactly 2"
            )

        projection_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func) == requirement["projection_route"]
        ]
        if len(projection_calls) != 1:
            failures.append(
                f"{method_label} routes through {requirement['projection_route']} "
                f"{len(projection_calls)} time(s); expected 1"
            )
        elif projection_calls[0].args:
            failures.append(
                f"{method_label} uses positional arguments when routing through "
                f"{requirement['projection_route']}"
            )
        else:
            for keyword_name, expected_name in requirement["projection_kwargs"].items():
                value = _get_keyword_argument(projection_calls[0], name=keyword_name)
                if not isinstance(value, ast.Name) or value.id != expected_name:
                    failures.append(
                        f"{method_label} {keyword_name} routing drifted from "
                        f"{expected_name}"
                    )

        projection_build_calls = [
            call
            for call in _iter_call_nodes(method)
            if _dotted_name(call.func) == "RelationLifecycleSignatureProjection"
        ]
        if len(projection_build_calls) != 1:
            failures.append(
                f"{method_label} constructs RelationLifecycleSignatureProjection "
                f"{len(projection_build_calls)} time(s); expected 1"
            )
            continue

        projection_build = projection_build_calls[0]
        keyword_values = {
            keyword.arg: keyword.value
            for keyword in projection_build.keywords
            if keyword.arg is not None
        }

        for bucket_name in ("active", "pending"):
            bucket_value = keyword_values.get(bucket_name)
            if bucket_value is None:
                failures.append(
                    f"{method_label} RelationLifecycleSignatureProjection missing "
                    f"{bucket_name} bucket"
                )
                continue
            sorted_call = _is_tuple_call_of(bucket_value, func_name="sorted")
            if sorted_call is None:
                failures.append(
                    f"{method_label} {bucket_name} bucket no longer routes through "
                    "tuple(sorted(...))"
                )
                continue
            _assert_projection_signature_bucket_route(
                sorted_call=sorted_call,
                bucket_name=bucket_name,
                failures=failures,
            )

    assert not missing_methods, (
        "Lifecycle-signature projection guard targets missing from src/dks/core.py: "
        f"{', '.join(sorted(missing_methods))}"
    )
    assert not failures, (
        "Lifecycle-signature projection ordering-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )


def test_relation_lifecycle_signature_transition_uses_canonical_window_diff_route() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_TRANSITION_METHOD)
    assert method is not None, (
        "Lifecycle-signature transition guard target missing from src/dks/core.py: "
        f"{_TARGET_TRANSITION_METHOD[0]}.{_TARGET_TRANSITION_METHOD[1]}"
    )

    failures: list[str] = []

    def _is_subscript_lookup(value: ast.AST, *, source_name: str, key: str) -> bool:
        return (
            isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id == source_name
            and isinstance(value.slice, ast.Constant)
            and value.slice.value == key
        )

    helper_calls: list[ast.Call] = []
    projection_calls: list[ast.Call] = []
    forbidden_route_hits: list[str] = []
    sorted_calls = 0
    for call in _iter_call_nodes(method):
        route = _dotted_name(call.func)
        if route == "self._query_transition_buckets_via_as_of_diff":
            helper_calls.append(call)
        if route == "self.query_relation_lifecycle_signatures_for_tx_window":
            projection_calls.append(call)
        if route in _FORBIDDEN_TRANSITION_ROUTES:
            forbidden_route_hits.append(f"{route} (line {call.lineno})")
        if _is_sorted_call(call):
            sorted_calls += 1

    if sorted_calls:
        failures.append(
            "query_relation_lifecycle_signature_transition_for_tx_window reintroduced "
            f"direct sorted(...) routing {sorted_calls} time(s)"
        )

    if forbidden_route_hits:
        failures.append(
            "relation lifecycle signature transition path uses non-canonical ad-hoc route(s): "
            + ", ".join(sorted(forbidden_route_hits))
        )

    if len(helper_calls) != 1:
        failures.append(
            "query_relation_lifecycle_signature_transition_for_tx_window routes through "
            "self._query_transition_buckets_via_as_of_diff "
            f"{len(helper_calls)} time(s); expected 1"
        )
    else:
        helper_call = helper_calls[0]
        if helper_call.args:
            failures.append(
                "canonical transition helper call unexpectedly uses positional arguments"
            )

        expected_name_keywords = {
            "tx_from": "tx_start",
            "tx_to": "tx_end",
            "projection_from": "valid_from",
            "projection_to": "valid_to",
        }
        for keyword_name, expected_name in expected_name_keywords.items():
            value = _get_keyword_argument(helper_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    f"canonical transition helper {keyword_name} routing drifted from "
                    f"{expected_name}"
                )

        label_expectations = {
            "tx_from_label": "tx_start",
            "tx_to_label": "tx_end",
        }
        for keyword_name, expected_value in label_expectations.items():
            value = _get_keyword_argument(helper_call, name=keyword_name)
            if not isinstance(value, ast.Constant) or value.value != expected_value:
                failures.append(
                    f"canonical transition helper {keyword_name} literal drifted from "
                    f"{expected_value!r}"
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
                        "self.query_relation_lifecycle_signatures_for_tx_window"
                    )
                else:
                    if _dotted_name(projection_call.func) != "self.query_relation_lifecycle_signatures_for_tx_window":
                        failures.append(
                            "projection_as_of lambda uses non-canonical signature window route "
                            f"{_dotted_name(projection_call.func)!r}"
                        )
                    if projection_call.args:
                        failures.append(
                            "projection_as_of lambda uses positional arguments for "
                            "query_relation_lifecycle_signatures_for_tx_window"
                        )
                    for keyword_name, expected_name in {
                        "tx_start": "tx_start",
                        "tx_end": "tx_end",
                        "revision_id": "revision_id",
                    }.items():
                        value = _get_keyword_argument(projection_call, name=keyword_name)
                        if not isinstance(value, ast.Name) or value.id != expected_name:
                            failures.append(
                                "projection_as_of lambda "
                                f"{keyword_name} routing drifted from {expected_name}"
                            )
                    valid_at = _get_keyword_argument(projection_call, name="valid_at")
                    if not isinstance(valid_at, ast.Name) or valid_at.id != projection_arg_name:
                        failures.append(
                            "projection_as_of lambda valid_at routing drifted from lambda argument"
                        )

        bucket_routes = _get_keyword_argument(helper_call, name="bucket_routes")
        if not isinstance(bucket_routes, ast.Dict):
            failures.append(
                "canonical transition helper bucket_routes is no longer a dictionary literal"
            )
        else:
            expected_order_route = "KnowledgeStore._ordered_identity_bucket"
            observed_bucket_names: set[str] = set()
            for key_node, value_node in zip(bucket_routes.keys, bucket_routes.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    failures.append(
                        "canonical transition helper bucket_routes contains non-string key"
                    )
                    continue

                bucket_name = key_node.value
                observed_bucket_names.add(bucket_name)
                if bucket_name not in {"active", "pending"}:
                    failures.append(
                        f"canonical transition helper bucket_routes includes unexpected key {bucket_name!r}"
                    )
                    continue

                if not (isinstance(value_node, ast.Tuple) and len(value_node.elts) == 3):
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] is no longer a 3-tuple route descriptor"
                    )
                    continue

                projection_lambda, key_route_node, order_route_node = value_node.elts
                if not isinstance(projection_lambda, ast.Lambda):
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] projection route is no longer a lambda"
                    )
                else:
                    if len(projection_lambda.args.args) != 1:
                        failures.append(
                            f"bucket_routes[{bucket_name!r}] projection lambda has unexpected arity"
                        )
                    else:
                        projection_name = projection_lambda.args.args[0].arg
                        if not (
                            isinstance(projection_lambda.body, ast.Attribute)
                            and isinstance(projection_lambda.body.value, ast.Name)
                            and projection_lambda.body.value.id == projection_name
                            and projection_lambda.body.attr == bucket_name
                        ):
                            failures.append(
                                f"bucket_routes[{bucket_name!r}] projection lambda no longer routes through "
                                f"projection.{bucket_name}"
                            )

                key_route = _dotted_name(key_route_node)
                if key_route != "KnowledgeStore._identity_transition_key":
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] uses non-canonical key route "
                        f"{key_route!r}"
                    )

                order_route = _dotted_name(order_route_node)
                if order_route != expected_order_route:
                    failures.append(
                        f"bucket_routes[{bucket_name!r}] uses non-canonical order route "
                        f"{order_route!r}; expected {expected_order_route}"
                    )

            if observed_bucket_names != {"active", "pending"}:
                failures.append(
                    "canonical transition helper bucket_routes keys drifted; observed "
                    f"{sorted(observed_bucket_names)} expected ['active', 'pending']"
                )

    if len(projection_calls) != 1:
        failures.append(
            "query_relation_lifecycle_signature_transition_for_tx_window should reference "
            "self.query_relation_lifecycle_signatures_for_tx_window only via projection lambda; "
            f"observed {len(projection_calls)} call(s)"
        )

    assignments = {name: value for name, value, _ in _iter_named_assignments(method)}
    transition_buckets_assignment = assignments.get("transition_buckets")
    if not isinstance(transition_buckets_assignment, ast.Call) or _dotted_name(
        transition_buckets_assignment.func
    ) != "self._query_transition_buckets_via_as_of_diff":
        failures.append(
            "transition_buckets staging no longer routes from canonical transition helper"
        )

    transition_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "RelationLifecycleSignatureTransition"
    ]
    if len(transition_calls) != 1:
        failures.append(
            "query_relation_lifecycle_signature_transition_for_tx_window no longer constructs "
            "exactly one RelationLifecycleSignatureTransition"
        )
    else:
        transition_call = transition_calls[0]
        keyword_values = {
            keyword.arg: keyword.value
            for keyword in transition_call.keywords
            if keyword.arg is not None
        }

        for scalar_name in ("valid_from", "valid_to"):
            value = keyword_values.get(scalar_name)
            if not isinstance(value, ast.Name) or value.id != scalar_name:
                failures.append(
                    f"RelationLifecycleSignatureTransition {scalar_name} routing drifted"
                )

        for bucket_name in (
            "entered_active",
            "exited_active",
            "entered_pending",
            "exited_pending",
        ):
            value = keyword_values.get(bucket_name)
            if value is None:
                failures.append(
                    f"RelationLifecycleSignatureTransition missing {bucket_name} bucket"
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
        "Lifecycle-signature transition ordering-route drift detected in src/dks/core.py: "
        + "; ".join(failures)
    )
