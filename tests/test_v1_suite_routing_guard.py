from __future__ import annotations

import ast
from pathlib import Path


_TESTS_DIR = Path(__file__).resolve().parent
_CORE_SUITE_PATH = _TESTS_DIR / "test_v1_core.py"

_MERGE_CONFLICT_QUERY_SYMBOLS = (
    "query_merge_conflict_projection_as_of",
    "query_merge_conflict_projection_for_tx_window",
)
_LIFECYCLE_SIGNATURE_QUERY_SYMBOLS = (
    "query_relation_lifecycle_signatures_as_of",
    "query_relation_lifecycle_signatures_for_tx_window",
    "query_relation_lifecycle_signature_transition_for_tx_window",
)

_MERGE_CONFLICT_DEDICATED_SUITES = (
    "tests/test_v1_merge_conflict_projection.py",
    "tests/test_v1_merge_conflict_projection_permutations.py",
)
_LIFECYCLE_SIGNATURE_DEDICATED_SUITES = (
    "tests/test_v1_relation_lifecycle_signatures.py",
    "tests/test_v1_relation_lifecycle_signatures_permutations.py",
)


def _load_test_function_sources(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path))
    test_sources: dict[str, str] = {}

    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue

        source_segment = ast.get_source_segment(source, node)
        if source_segment is None:
            source_lines = source.splitlines()
            source_segment = "\n".join(source_lines[node.lineno - 1 : node.end_lineno])

        test_sources[node.name] = source_segment

    return test_sources


def _find_symbol_usages(
    *,
    test_sources: dict[str, str],
    symbols: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    usages: dict[str, tuple[str, ...]] = {}
    for test_name, test_source in test_sources.items():
        matched_symbols = tuple(symbol for symbol in symbols if symbol in test_source)
        if matched_symbols:
            usages[test_name] = matched_symbols
    return usages


def _format_usages(usages: dict[str, tuple[str, ...]]) -> str:
    return ", ".join(
        f"{test_name} -> {', '.join(symbols)}"
        for test_name, symbols in sorted(usages.items())
    )


def test_v1_core_does_not_reintroduce_merge_conflict_projection_query_tests() -> None:
    core_test_sources = _load_test_function_sources(_CORE_SUITE_PATH)
    merge_query_usages = _find_symbol_usages(
        test_sources=core_test_sources,
        symbols=_MERGE_CONFLICT_QUERY_SYMBOLS,
    )

    assert not merge_query_usages, (
        "Merge-conflict projection query tests drifted back into tests/test_v1_core.py: "
        f"{_format_usages(merge_query_usages)}. Route these tests to "
        f"{', '.join(_MERGE_CONFLICT_DEDICATED_SUITES)}."
    )


def test_v1_core_does_not_reintroduce_lifecycle_signature_query_tests() -> None:
    core_test_sources = _load_test_function_sources(_CORE_SUITE_PATH)
    lifecycle_query_usages = _find_symbol_usages(
        test_sources=core_test_sources,
        symbols=_LIFECYCLE_SIGNATURE_QUERY_SYMBOLS,
    )

    assert not lifecycle_query_usages, (
        "Lifecycle-signature query tests drifted back into tests/test_v1_core.py: "
        f"{_format_usages(lifecycle_query_usages)}. Route these tests to "
        f"{', '.join(_LIFECYCLE_SIGNATURE_DEDICATED_SUITES)}."
    )
