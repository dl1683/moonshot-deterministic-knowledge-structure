from __future__ import annotations

import ast
from pathlib import Path


_TESTS_DIR = Path(__file__).resolve().parent
_TARGET_PATH = _TESTS_DIR / "test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py"

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
        "Merge-conflict input-aware replay/restart runtime-guard target missing from tests/"
        "test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py: "
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


def _tuple_of_constant_strings(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, ast.Tuple):
        return None
    values: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.append(element.value)
    return tuple(values)


def _duplicate_start_descriptor(node: ast.AST | None) -> str | None:
    if node is None:
        return None

    dotted = _dotted_name(node)
    if dotted is not None:
        return dotted

    if isinstance(node, ast.Call) and not node.args and not node.keywords:
        return _dotted_name(node.func)

    return None


def test_merge_conflict_inputs_replay_restart_permutation_matrix_budget_guard() -> None:
    module = _load_module()
    function = _get_function(
        module,
        name="test_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart_invariant_for_ingestion_permutations",
    )
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
            or _dotted_name(permutations_call.args[0]) != "context.replicas_by_tx"
        ):
            failures.append(
                "Permutation matrix route drifted from tuple(itertools.permutations(context.replicas_by_tx))"
            )

    if len(permutation_tuple_calls) != 1:
        failures.append(
            "Merge-conflict input-aware permutation matrix should build exactly one permutation tuple; "
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
            "Merge-conflict input-aware permutation matrix should enforce len(permutation_orders) == 24 "
            f"exactly once; observed {len(permutation_len_asserts)}"
        )

    replay_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_replay_replicas"
    ]
    if len(replay_calls) != 3:
        failures.append(
            "Permutation invariance test should keep exactly three _replay_replicas call sites "
            f"(baseline + unsplit + segmented); observed {len(replay_calls)}"
        )
    else:
        segmented_calls = 0
        for call in replay_calls:
            boundaries = _get_keyword_argument(call, name="boundaries")
            if boundaries is None:
                continue

            segmented_calls += 1
            literal = _int_tuple_literal(boundaries)
            if literal != (1, 3):
                failures.append(
                    "_replay_replicas segmented permutation variant should keep boundaries=(1, 3)"
                )
            if len(call.args) != 1 or _dotted_name(call.args[0]) != "ordered_replicas":
                failures.append(
                    "_replay_replicas segmented permutation variant should keep ordered_replicas input routing"
                )

        if segmented_calls != 1:
            failures.append(
                "Permutation invariance test should keep exactly one segmented _replay_replicas variant; "
                f"observed {segmented_calls}"
            )

    assert not failures, (
        "Merge-conflict input-aware replay/restart permutation runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py: "
        + "; ".join(failures)
    )


def test_merge_conflict_inputs_replay_restart_checkpoint_duplicate_matrix_budget_guard() -> None:
    module = _load_module()
    function = _get_function(
        module,
        name="test_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart_invariant_for_segmented_duplicate_and_restarts",
    )
    failures: list[str] = []

    replay_variant_assignments = [
        value for name, value in _iter_named_assignments(function) if name == "replay_variants"
    ]
    if len(replay_variant_assignments) != 1:
        failures.append(
            "Segmented/duplicate replay test should define replay_variants exactly once; "
            f"observed {len(replay_variant_assignments)}"
        )
    else:
        replay_variants = replay_variant_assignments[0]
        if not isinstance(replay_variants, ast.Tuple) or len(replay_variants.elts) != 4:
            failures.append(
                "replay_variants should remain a 4-entry tuple "
                "(unsplit, segmented, duplicate, resumed-duplicate)"
            )
        else:
            expected_labels = ("unsplit", "segmented", "duplicate", "resumed-duplicate")
            label_nodes: list[ast.AST] = []
            for entry in replay_variants.elts:
                if not isinstance(entry, ast.Tuple) or len(entry.elts) != 3:
                    failures.append(
                        "each replay_variants entry should remain a 3-item tuple "
                        "(variant_name, replay_store, replay_stream)"
                    )
                    continue
                label_nodes.append(entry.elts[0])

            label_literals = _tuple_of_constant_strings(ast.Tuple(elts=label_nodes, ctx=ast.Load()))
            if label_literals != expected_labels:
                failures.append(
                    "replay_variants labels drifted from expected bounded matrix; "
                    f"observed {label_literals!r} expected {expected_labels!r}"
                )

    replay_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_replay_replicas"
    ]
    if len(replay_calls) != 2:
        failures.append(
            "Segmented/duplicate replay test should keep exactly two _replay_replicas call sites "
            f"(unsplit + segmented); observed {len(replay_calls)}"
        )
    else:
        segmented_calls = 0
        for call in replay_calls:
            boundaries = _get_keyword_argument(call, name="boundaries")
            if boundaries is None:
                continue
            segmented_calls += 1
            literal = _int_tuple_literal(boundaries)
            if literal != (1, 3):
                failures.append(
                    "_replay_replicas segmented replay variant should keep boundaries=(1, 3)"
                )
        if segmented_calls != 1:
            failures.append(
                "Segmented/duplicate replay test should keep exactly one segmented _replay_replicas variant; "
                f"observed {segmented_calls}"
            )

    duplicate_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_replay_duplicate_from"
    ]
    if len(duplicate_calls) != 2:
        failures.append(
            "Segmented/duplicate replay test should keep exactly two _replay_duplicate_from call sites; "
            f"observed {len(duplicate_calls)}"
        )
    else:
        duplicate_starts: set[str | None] = set()
        for call in duplicate_calls:
            start_value = _get_keyword_argument(call, name="start")
            duplicate_starts.add(_duplicate_start_descriptor(start_value))
        expected_starts = {"unsplit_store", "unsplit_store.checkpoint"}
        if duplicate_starts != expected_starts:
            observed_starts = sorted(duplicate_starts, key=lambda value: "" if value is None else value)
            expected_start_order = sorted(expected_starts)
            failures.append(
                "_replay_duplicate_from start routes drifted from bounded restart matrix; "
                f"observed {observed_starts} expected {expected_start_order}"
            )

    assert not failures, (
        "Merge-conflict input-aware replay/restart checkpoint/duplicate runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py: "
        + "; ".join(failures)
    )


def test_merge_conflict_inputs_replay_restart_cycle_budget_guard() -> None:
    module = _load_module()
    function = _get_function(
        module,
        name="test_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart_invariant_for_segmented_duplicate_and_restarts",
    )
    failures: list[str] = []

    restart_calls = [
        call for call in _iter_call_nodes(function) if _dotted_name(call.func) == "_apply_restart_cycles"
    ]
    if len(restart_calls) != 1:
        failures.append(
            "Segmented/duplicate replay test should include exactly one _apply_restart_cycles call site; "
            f"observed {len(restart_calls)}"
        )
    else:
        restart_call = restart_calls[0]
        if len(restart_call.args) != 1 or _dotted_name(restart_call.args[0]) != "replay_store":
            failures.append(
                "_apply_restart_cycles should keep replay_store as its single positional input"
            )

        restart_cycles = _get_keyword_argument(restart_call, name="restart_cycles")
        if not isinstance(restart_cycles, ast.Constant) or restart_cycles.value != 3:
            failures.append("_apply_restart_cycles restart_cycles should remain fixed at 3")

        snapshot_path = _get_keyword_argument(restart_call, name="snapshot_path")
        if snapshot_path is None:
            failures.append("_apply_restart_cycles should keep snapshot_path keyword routing")

    assert not failures, (
        "Merge-conflict input-aware replay/restart cycle runtime-budget guard drift detected in "
        "tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py: "
        + "; ".join(failures)
    )
