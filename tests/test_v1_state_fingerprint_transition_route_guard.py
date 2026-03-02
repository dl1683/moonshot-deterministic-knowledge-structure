from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_PATH = _REPO_ROOT / "src" / "dks" / "core.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef

_TARGET_FINGERPRINT_TRANSITION_METHOD = (
    "KnowledgeStore",
    "query_state_fingerprint_transition_for_tx_window",
)

_REQUIRED_TRANSITION_BUCKET_ROUTES: dict[str, tuple[str, str, str]] = {
    "revision_active": (
        "revision_lifecycle.active",
        "KnowledgeStore._revision_projection_sort_key",
        "KnowledgeStore._ordered_revision_bucket",
    ),
    "revision_retracted": (
        "revision_lifecycle.retracted",
        "KnowledgeStore._revision_projection_sort_key",
        "KnowledgeStore._ordered_revision_bucket",
    ),
    "relation_resolution_active": (
        "relation_resolution.active",
        "KnowledgeStore._relation_projection_sort_key",
        "KnowledgeStore._ordered_relation_bucket",
    ),
    "relation_resolution_pending": (
        "relation_resolution.pending",
        "KnowledgeStore._relation_projection_sort_key",
        "KnowledgeStore._ordered_relation_bucket",
    ),
    "relation_lifecycle_active": (
        "relation_lifecycle.active",
        "KnowledgeStore._relation_projection_sort_key",
        "KnowledgeStore._ordered_relation_bucket",
    ),
    "relation_lifecycle_pending": (
        "relation_lifecycle.pending",
        "KnowledgeStore._relation_projection_sort_key",
        "KnowledgeStore._ordered_relation_bucket",
    ),
    "relation_lifecycle_signature_active": (
        "relation_lifecycle_signatures.active",
        "KnowledgeStore._identity_transition_key",
        "KnowledgeStore._ordered_identity_bucket",
    ),
    "relation_lifecycle_signature_pending": (
        "relation_lifecycle_signatures.pending",
        "KnowledgeStore._identity_transition_key",
        "KnowledgeStore._ordered_identity_bucket",
    ),
    "merge_conflict_signature_counts": (
        "merge_conflict_projection.signature_counts",
        "KnowledgeStore._identity_transition_key",
        "KnowledgeStore._ordered_merge_conflict_signature_bucket",
    ),
    "merge_conflict_code_counts": (
        "merge_conflict_projection.code_counts",
        "KnowledgeStore._identity_transition_key",
        "KnowledgeStore._ordered_merge_conflict_code_bucket",
    ),
}

_DISALLOWED_HELPER_BYPASS_ROUTES = {
    "self._select_revision_winner_as_of",
    "self._query_as_of_buckets_via_projection",
    "KnowledgeStore._query_as_of_buckets_via_projection",
    "self._query_tx_window_buckets_via_as_of_projection",
    "KnowledgeStore._query_tx_window_buckets_via_as_of_projection",
    "KnowledgeStore._query_transition_buckets_via_as_of_diff",
    "self.query_state_fingerprint_for_tx_window",
    "self.query_revision_lifecycle_as_of",
    "self.query_relation_resolution_as_of",
    "self.query_relation_lifecycle_as_of",
    "self.query_relation_lifecycle_signatures_as_of",
    "KnowledgeStore.query_merge_conflict_projection_as_of",
    "self.query_revision_lifecycle_for_tx_window",
    "self.query_relation_resolution_for_tx_window",
    "self.query_relation_lifecycle_for_tx_window",
    "self.query_relation_lifecycle_signatures_for_tx_window",
    "KnowledgeStore.query_merge_conflict_projection_for_tx_window",
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


def _iter_compare_nodes(function_node: _DEF_OR_ASYNC):
    for node in ast.walk(function_node):
        if isinstance(node, ast.Compare):
            yield node


def _is_sort_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "sorted"
        or isinstance(call.func, ast.Attribute)
        and call.func.attr == "sort"
    )


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _names_in_node(node: ast.AST) -> set[str]:
    return {
        name_node.id
        for name_node in ast.walk(node)
        if isinstance(name_node, ast.Name)
    }


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _attribute_path_from_base(node: ast.AST, *, base_name: str) -> str | None:
    if isinstance(node, ast.Name):
        return "" if node.id == base_name else None
    if isinstance(node, ast.Attribute):
        prefix = _attribute_path_from_base(node.value, base_name=base_name)
        if prefix is None:
            return None
        if not prefix:
            return node.attr
        return f"{prefix}.{node.attr}"
    return None


def _transition_bucket_lookup_key(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "transition_buckets":
        return None

    key_node = node.slice
    if isinstance(key_node, ast.Index):  # pragma: no cover - py<3.9 compatibility
        key_node = key_node.value
    return _string_literal(key_node)


def test_state_fingerprint_transition_routes_through_canonical_helpers() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_TRANSITION_METHOD)
    assert method is not None, (
        "State fingerprint transition route guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_TRANSITION_METHOD[0]}.{_TARGET_FINGERPRINT_TRANSITION_METHOD[1]}"
    )

    failures: list[str] = []

    as_of_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "self.query_state_fingerprint_as_of"
    ]
    if len(as_of_calls) != 2:
        failures.append(
            "query_state_fingerprint_transition_for_tx_window routes through "
            f"self.query_state_fingerprint_as_of {len(as_of_calls)} time(s); "
            "expected exactly 2"
        )
    else:
        observed_tx_id_routes: list[str] = []
        for call in as_of_calls:
            if call.args:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    "query_state_fingerprint_as_of route uses positional arguments; "
                    "expected keyword-only routing"
                )
            tx_id_value = _get_keyword_argument(call, name="tx_id")
            if isinstance(tx_id_value, ast.Name):
                observed_tx_id_routes.append(tx_id_value.id)
            else:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    "query_state_fingerprint_as_of tx_id routing is not a direct "
                    "name reference"
                )
            valid_at_value = _get_keyword_argument(call, name="valid_at")
            if not isinstance(valid_at_value, ast.Name) or valid_at_value.id != "valid_at":
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    "query_state_fingerprint_as_of valid_at routing drifted from "
                    "valid_at"
                )
            core_id_value = _get_keyword_argument(call, name="core_id")
            if not isinstance(core_id_value, ast.Name) or core_id_value.id != "core_id":
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    "query_state_fingerprint_as_of core_id routing drifted from "
                    "core_id"
                )
            merge_results_by_tx_value = _get_keyword_argument(
                call,
                name="merge_results_by_tx",
            )
            if (
                not isinstance(merge_results_by_tx_value, ast.Name)
                or merge_results_by_tx_value.id != "merge_results_by_tx"
            ):
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    "query_state_fingerprint_as_of merge_results_by_tx routing "
                    "drifted from merge_results_by_tx"
                )

        if sorted(observed_tx_id_routes) != ["tx_from", "tx_to"]:
            failures.append(
                "query_state_fingerprint_transition_for_tx_window "
                "query_state_fingerprint_as_of tx_id routes drifted from "
                "{tx_from, tx_to}"
            )

    transition_helper_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "self._query_transition_buckets_via_as_of_diff"
    ]
    if len(transition_helper_calls) != 1:
        failures.append(
            "query_state_fingerprint_transition_for_tx_window routes through "
            f"self._query_transition_buckets_via_as_of_diff "
            f"{len(transition_helper_calls)} time(s); expected exactly 1"
        )
    else:
        transition_helper_call = transition_helper_calls[0]
        if transition_helper_call.args:
            failures.append(
                "query_state_fingerprint_transition_for_tx_window "
                "transition helper route uses positional arguments; expected "
                "keyword-only routing"
            )

        expected_helper_keywords = {
            "tx_from": "tx_from",
            "tx_to": "tx_to",
            "projection_from": "from_fingerprint",
            "projection_to": "to_fingerprint",
            "bucket_routes": "<dict>",
        }
        for keyword_name, expected_name in expected_helper_keywords.items():
            value = _get_keyword_argument(transition_helper_call, name=keyword_name)
            if keyword_name == "bucket_routes":
                if not isinstance(value, ast.Dict):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        "helper bucket_routes routing drifted from dict literal"
                    )
                continue

            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window transition "
                    f"helper {keyword_name} routing drifted from {expected_name}"
                )

        projection_as_of_value = _get_keyword_argument(
            transition_helper_call,
            name="projection_as_of",
        )
        if _dotted_name(projection_as_of_value) != "KnowledgeStore._identity_transition_key":
            failures.append(
                "query_state_fingerprint_transition_for_tx_window transition helper "
                "projection_as_of routing drifted from "
                "KnowledgeStore._identity_transition_key"
            )

        bucket_routes_value = _get_keyword_argument(transition_helper_call, name="bucket_routes")
        if isinstance(bucket_routes_value, ast.Dict):
            observed_bucket_keys: set[str] = set()
            for key_node, value_node in zip(
                bucket_routes_value.keys,
                bucket_routes_value.values,
            ):
                bucket_key = _string_literal(key_node)
                if bucket_key is None:
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        "helper bucket_routes contains a non-string key"
                    )
                    continue

                observed_bucket_keys.add(bucket_key)
                expected_route = _REQUIRED_TRANSITION_BUCKET_ROUTES.get(bucket_key)
                if expected_route is None:
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes contains unexpected key {bucket_key!r}"
                    )
                    continue

                if not isinstance(value_node, ast.Tuple) or len(value_node.elts) != 3:
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] drifted from "
                        "(projection, sort_key, ordered_bucket) tuple"
                    )
                    continue

                projection_node, sort_key_node, ordered_bucket_node = value_node.elts
                expected_projection_path, expected_sort_key, expected_ordered_bucket = (
                    expected_route
                )

                if not isinstance(projection_node, ast.Lambda):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] projection route "
                        "drifted from lambda fingerprint projection"
                    )
                else:
                    lambda_args = projection_node.args.args
                    if len(lambda_args) != 1 or lambda_args[0].arg != "fingerprint":
                        failures.append(
                            "query_state_fingerprint_transition_for_tx_window transition "
                            f"helper bucket_routes[{bucket_key!r}] projection lambda "
                            "argument drifted from fingerprint"
                        )
                    projection_path = _attribute_path_from_base(
                        projection_node.body,
                        base_name="fingerprint",
                    )
                    if projection_path != expected_projection_path:
                        failures.append(
                            "query_state_fingerprint_transition_for_tx_window transition "
                            f"helper bucket_routes[{bucket_key!r}] projection path "
                            f"drifted from {expected_projection_path}"
                        )

                if isinstance(sort_key_node, ast.Lambda):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] reintroduced inline "
                        "lambda sort-key routing"
                    )
                    if isinstance(sort_key_node.body, ast.Tuple):
                        failures.append(
                            "query_state_fingerprint_transition_for_tx_window transition "
                            f"helper bucket_routes[{bucket_key!r}] reintroduced inline "
                            "tuple lambda sort-key routing"
                        )
                elif isinstance(sort_key_node, ast.Tuple):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] reintroduced inline "
                        "tuple sort-key routing"
                    )

                sort_key_route = _dotted_name(sort_key_node)
                if sort_key_route != expected_sort_key:
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] sort-key route drifted "
                        f"from {expected_sort_key}"
                    )

                ordered_bucket_route = _dotted_name(ordered_bucket_node)
                if ordered_bucket_route != expected_ordered_bucket:
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"helper bucket_routes[{bucket_key!r}] ordered bucket route "
                        f"drifted from {expected_ordered_bucket}"
                    )

            missing_bucket_keys = sorted(
                set(_REQUIRED_TRANSITION_BUCKET_ROUTES) - observed_bucket_keys
            )
            if missing_bucket_keys:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window transition helper "
                    f"bucket_routes missing key(s) {missing_bucket_keys}"
                )

    transition_build_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "DeterministicStateFingerprintTransition"
    ]
    if len(transition_build_calls) != 1:
        failures.append(
            "query_state_fingerprint_transition_for_tx_window constructs "
            f"DeterministicStateFingerprintTransition {len(transition_build_calls)} "
            "time(s); expected exactly 1"
        )
    else:
        transition_build_call = transition_build_calls[0]
        if transition_build_call.args:
            failures.append(
                "query_state_fingerprint_transition_for_tx_window "
                "DeterministicStateFingerprintTransition construction unexpectedly "
                "uses positional arguments"
            )

        simple_keyword_expectations = {
            "tx_from": "tx_from",
            "tx_to": "tx_to",
        }
        for keyword_name, expected_name in simple_keyword_expectations.items():
            value = _get_keyword_argument(transition_build_call, name=keyword_name)
            if not isinstance(value, ast.Name) or value.id != expected_name:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    f"DeterministicStateFingerprintTransition {keyword_name} routing "
                    f"drifted from {expected_name}"
                )

        from_digest_value = _get_keyword_argument(transition_build_call, name="from_digest")
        if _dotted_name(from_digest_value) != "from_fingerprint.digest":
            failures.append(
                "query_state_fingerprint_transition_for_tx_window "
                "DeterministicStateFingerprintTransition from_digest routing drifted "
                "from from_fingerprint.digest"
            )

        to_digest_value = _get_keyword_argument(transition_build_call, name="to_digest")
        if _dotted_name(to_digest_value) != "to_fingerprint.digest":
            failures.append(
                "query_state_fingerprint_transition_for_tx_window "
                "DeterministicStateFingerprintTransition to_digest routing drifted "
                "from to_fingerprint.digest"
            )

        expected_bucket_keywords = {
            f"entered_{bucket_name}": f"entered_{bucket_name}"
            for bucket_name in _REQUIRED_TRANSITION_BUCKET_ROUTES
        }
        expected_bucket_keywords.update(
            {
                f"exited_{bucket_name}": f"exited_{bucket_name}"
                for bucket_name in _REQUIRED_TRANSITION_BUCKET_ROUTES
            }
        )
        for keyword_name, expected_bucket_key in expected_bucket_keywords.items():
            value = _get_keyword_argument(transition_build_call, name=keyword_name)
            observed_bucket_key = _transition_bucket_lookup_key(value) if value is not None else None
            if observed_bucket_key != expected_bucket_key:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window "
                    f"DeterministicStateFingerprintTransition {keyword_name} routing "
                    f"drifted from transition_buckets[{expected_bucket_key!r}]"
                )

    assert not failures, (
        "Deterministic state fingerprint transition helper-route drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )


def test_state_fingerprint_transition_query_rejects_inline_bypass_diff_filter_and_sort_drift() -> None:
    methods = _load_class_methods(_CORE_PATH)
    method = methods.get(_TARGET_FINGERPRINT_TRANSITION_METHOD)
    assert method is not None, (
        "State fingerprint transition bypass guard target missing from src/dks/core.py: "
        f"{_TARGET_FINGERPRINT_TRANSITION_METHOD[0]}.{_TARGET_FINGERPRINT_TRANSITION_METHOD[1]}"
    )

    failures: list[str] = []

    for call in _iter_call_nodes(method):
        route_name = _dotted_name(call.func)
        if route_name in _DISALLOWED_HELPER_BYPASS_ROUTES:
            failures.append(
                "query_state_fingerprint_transition_for_tx_window reintroduced "
                f"non-canonical helper-bypass route {route_name!r} at line {call.lineno}"
            )
        if route_name == "set":
            failures.append(
                "query_state_fingerprint_transition_for_tx_window reintroduced ad-hoc "
                f"set(...) diff staging at line {call.lineno}"
            )
        if isinstance(call.func, ast.Attribute) and call.func.attr == "difference":
            failures.append(
                "query_state_fingerprint_transition_for_tx_window reintroduced ad-hoc "
                f".difference(...) diff staging at line {call.lineno}"
            )

        if _is_sort_call(call):
            failures.append(
                "query_state_fingerprint_transition_for_tx_window reintroduced inline "
                f"sort/sorted routing at line {call.lineno}"
            )
            key_argument = _get_keyword_argument(call, name="key")
            if isinstance(key_argument, ast.Lambda):
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window reintroduced "
                    f"inline lambda sort-key routing at line {call.lineno}"
                )
                if isinstance(key_argument.body, ast.Tuple):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window reintroduced "
                        f"inline tuple lambda sort-key routing at line {call.lineno}"
                    )
            elif isinstance(key_argument, ast.Tuple):
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window reintroduced "
                    f"inline tuple sort-key routing at line {call.lineno}"
                )
            elif key_argument is not None:
                failures.append(
                    "query_state_fingerprint_transition_for_tx_window reintroduced "
                    f"explicit sort-key routing at line {call.lineno}"
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
            "query_state_fingerprint_transition_for_tx_window reintroduced ad-hoc "
            f"subtraction diff routing at lines {subtraction_lines}"
        )

    filter_lines = sorted(
        {
            compare.lineno
            for compare in _iter_compare_nodes(method)
            if {
                "tx_id",
                "cutoff_tx_id",
                "_tx_id",
                "tx_start",
                "tx_end",
            }
            & _names_in_node(compare)
        }
    )
    if filter_lines:
        failures.append(
            "query_state_fingerprint_transition_for_tx_window reintroduced inline tx "
            f"boundary filtering at lines {filter_lines}"
        )

    transition_helper_calls = [
        call
        for call in _iter_call_nodes(method)
        if _dotted_name(call.func) == "self._query_transition_buckets_via_as_of_diff"
    ]
    if len(transition_helper_calls) == 1:
        bucket_routes_value = _get_keyword_argument(
            transition_helper_calls[0],
            name="bucket_routes",
        )
        if isinstance(bucket_routes_value, ast.Dict):
            for key_node, value_node in zip(
                bucket_routes_value.keys,
                bucket_routes_value.values,
            ):
                bucket_key = _string_literal(key_node)
                if not isinstance(value_node, ast.Tuple) or len(value_node.elts) < 2:
                    continue
                sort_key_node = value_node.elts[1]
                if isinstance(sort_key_node, ast.Lambda):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"bucket {bucket_key!r} reintroduced inline lambda sort-key "
                        "routing"
                    )
                    if isinstance(sort_key_node.body, ast.Tuple):
                        failures.append(
                            "query_state_fingerprint_transition_for_tx_window transition "
                            f"bucket {bucket_key!r} reintroduced inline tuple lambda "
                            "sort-key routing"
                        )
                elif isinstance(sort_key_node, ast.Tuple):
                    failures.append(
                        "query_state_fingerprint_transition_for_tx_window transition "
                        f"bucket {bucket_key!r} reintroduced inline tuple sort-key "
                        "routing"
                    )

    assert not failures, (
        "Deterministic state fingerprint transition helper bypass drift detected in "
        "src/dks/core.py: "
        + "; ".join(failures)
    )
