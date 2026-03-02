from __future__ import annotations

import ast
from pathlib import Path


_TESTS_DIR = Path(__file__).resolve().parent
_TARGET_PATH = _TESTS_DIR / "test_v1_store_snapshot_surface_parity_replay_restart.py"

_DEF_OR_ASYNC = ast.FunctionDef | ast.AsyncFunctionDef


def _load_module() -> ast.Module:
    source = _TARGET_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(_TARGET_PATH))


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
                    yield target.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield node.target.id, node.value


def _get_function(module: ast.Module, *, name: str) -> _DEF_OR_ASYNC:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(
        "Replay/restart runtime-guard target missing from tests/"
        "test_v1_store_snapshot_surface_parity_replay_restart.py: "
        f"{name}"
    )


def _get_keyword_argument(call: ast.Call, *, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _int_tuple_literal(node: ast.AST) -> tuple[int, ...] | None:
    if not isinstance(node, ast.Tuple):
        return None
    values: list[int] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant):
            return None
        if not isinstance(element.value, int) or isinstance(element.value, bool):
            return None
        values.append(element.value)
    return tuple(values)


def _is_len_assert(test: ast.AST, *, name: str, expected: int) -> bool:
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or comparator.value != expected:
        return False

    left = test.left
    return (
        isinstance(left, ast.Call)
        and isinstance(left.func, ast.Name)
        and left.func.id == "len"
        and len(left.args) == 1
        and isinstance(left.args[0], ast.Name)
        and left.args[0].id == name
        and not left.keywords
    )


def _extract_replay_descriptor(call: ast.Call) -> tuple[tuple[int, ...] | None, bool]:
    assert _dotted_name(call.func) == "_replay_replicas"
    assert len(call.args) == 1
    assert isinstance(call.args[0], ast.Name)
    assert call.args[0].id == "replicas_by_tx"

    boundaries: tuple[int, ...] | None = None
    duplicate_payloads = False
    for keyword in call.keywords:
        if keyword.arg == "boundaries":
            boundaries = _int_tuple_literal(keyword.value)
            if boundaries is None:
                raise AssertionError(
                    "_replay_replicas boundaries must remain a tuple[int, ...] literal"
                )
            continue
        if keyword.arg == "duplicate_payloads":
            if not isinstance(keyword.value, ast.Constant) or not isinstance(
                keyword.value.value, bool
            ):
                raise AssertionError(
                    "_replay_replicas duplicate_payloads must remain a bool literal"
                )
            duplicate_payloads = keyword.value.value
            continue
        if keyword.arg is None:
            raise AssertionError(
                "_replay_replicas call should not include variadic **kwargs in runtime guard path"
            )
        raise AssertionError(
            f"_replay_replicas call uses unexpected keyword {keyword.arg!r} in runtime guard path"
        )

    return boundaries, duplicate_payloads


def test_surface_parity_replay_restart_permutation_matrix_budget_guard() -> None:
    module = _load_module()
    function = _get_function(module, name="_assert_permutation_invariance")
    failures: list[str] = []

    permutation_tuple_calls: list[ast.Call] = []
    for call in _iter_call_nodes(function):
        if _dotted_name(call.func) != "tuple":
            continue
        if len(call.args) != 1 or call.keywords:
            continue
        permutations_call = call.args[0]
        if not isinstance(permutations_call, ast.Call):
            continue
        if _dotted_name(permutations_call.func) != "itertools.permutations":
            continue

        permutation_tuple_calls.append(call)
        if (
            len(permutations_call.args) != 1
            or permutations_call.keywords
            or not isinstance(permutations_call.args[0], ast.Name)
            or permutations_call.args[0].id != "replicas_by_tx"
        ):
            failures.append(
                "Permutation matrix route drifted from tuple(itertools.permutations(replicas_by_tx))"
            )

    if len(permutation_tuple_calls) != 1:
        failures.append(
            "_assert_permutation_invariance should build exactly one permutation tuple; "
            f"observed {len(permutation_tuple_calls)}"
        )

    permutation_len_asserts = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assert)
        and _is_len_assert(node.test, name="permutation_orders", expected=24)
    ]
    if len(permutation_len_asserts) != 1:
        failures.append(
            "_assert_permutation_invariance should enforce len(permutation_orders) == 24 "
            f"exactly once; observed {len(permutation_len_asserts)}"
        )

    assert not failures, (
        "Replay/restart permutation runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_replay_restart.py: "
        + "; ".join(failures)
    )


def test_surface_parity_replay_restart_checkpoint_split_budget_guard() -> None:
    module = _load_module()
    function = _get_function(module, name="_assert_segmented_duplicate_restart_invariance")
    failures: list[str] = []

    replay_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_replay_replicas"
    ]
    if len(replay_calls) != 4:
        failures.append(
            "_assert_segmented_duplicate_restart_invariance should keep exactly four "
            f"_replay_replicas call sites (baseline + 3 variants); observed {len(replay_calls)}"
        )

    replay_variant_assignments = [
        value
        for name, value in _iter_named_assignments(function)
        if name == "replay_variants"
    ]
    if len(replay_variant_assignments) != 1:
        failures.append(
            "_assert_segmented_duplicate_restart_invariance should define replay_variants "
            f"exactly once; observed {len(replay_variant_assignments)}"
        )
    else:
        replay_variants = replay_variant_assignments[0]
        if not isinstance(replay_variants, ast.Tuple) or len(replay_variants.elts) != 4:
            failures.append(
                "replay_variants should remain a 4-entry tuple "
                "(baseline, segmented, duplicate, segmented+duplicate)"
            )
        else:
            first_variant = replay_variants.elts[0]
            if not isinstance(first_variant, ast.Name) or first_variant.id != "baseline_store":
                failures.append("replay_variants[0] should remain baseline_store")

            descriptors: list[tuple[tuple[int, ...] | None, bool]] = []
            for variant in replay_variants.elts[1:]:
                if not isinstance(variant, ast.Call) or _dotted_name(variant.func) != "_replay_replicas":
                    failures.append(
                        "replay_variants entries after baseline_store should all call _replay_replicas"
                    )
                    continue
                try:
                    descriptors.append(_extract_replay_descriptor(variant))
                except AssertionError as exc:
                    failures.append(str(exc))

            expected_descriptors = {
                ((1, 3), False),
                (None, True),
                ((1, 3), True),
            }
            observed_descriptors = set(descriptors)
            if observed_descriptors != expected_descriptors:
                failures.append(
                    "replay_variants runtime-budget descriptors drifted; observed "
                    f"{sorted(observed_descriptors)} expected {sorted(expected_descriptors)}"
                )

    assert not failures, (
        "Replay/restart checkpoint-split runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_replay_restart.py: "
        + "; ".join(failures)
    )


def test_surface_parity_replay_restart_cycle_budget_guard() -> None:
    module = _load_module()
    function = _get_function(module, name="_assert_segmented_duplicate_restart_invariance")
    failures: list[str] = []

    restart_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_apply_restart_cycles"
    ]
    if len(restart_calls) != 1:
        failures.append(
            "_assert_segmented_duplicate_restart_invariance should include exactly one "
            f"_apply_restart_cycles call site; observed {len(restart_calls)}"
        )
    else:
        restart_call = restart_calls[0]
        if len(restart_call.args) != 1:
            failures.append("_apply_restart_cycles should keep replay_store as the single positional argument")
        elif not isinstance(restart_call.args[0], ast.Name) or restart_call.args[0].id != "replay_store":
            failures.append("_apply_restart_cycles should keep replay_store as its positional input")

        restart_cycles = _get_keyword_argument(restart_call, name="restart_cycles")
        if not isinstance(restart_cycles, ast.Constant) or restart_cycles.value != 2:
            failures.append("_apply_restart_cycles restart_cycles should remain fixed at 2")

        snapshot_path = _get_keyword_argument(restart_call, name="snapshot_path")
        if not isinstance(snapshot_path, ast.Name) or snapshot_path.id != "snapshot_path":
            failures.append("_apply_restart_cycles should keep snapshot_path passthrough routing")

    assert not failures, (
        "Replay/restart cycle runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_replay_restart.py: "
        + "; ".join(failures)
    )
