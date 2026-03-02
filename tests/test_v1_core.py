from datetime import datetime, timezone

import itertools

import pytest

from dks import (
    ClaimCore,
    ConflictCode,
    KnowledgeStore,
    MergeResult,
    Provenance,
    RelationEdge,
    TransactionTime,
    ValidTime,
)


def dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def force_relation_id(edge: RelationEdge, relation_id: str) -> RelationEdge:
    object.__setattr__(edge, "relation_id", relation_id)
    return edge


class OneShotIterable:
    def __init__(self, values: tuple) -> None:
        self._values = values
        self._iterated = False

    def __iter__(self):
        if self._iterated:
            raise AssertionError("one-shot iterable was iterated more than once")
        self._iterated = True
        return iter(self._values)


def assert_summary_chunk_stream_one_shot_parity(summary_chunks: tuple) -> tuple:
    materialized_summary = MergeResult.stream_conflict_summary_from_chunks(summary_chunks)
    one_shot_summary = MergeResult.stream_conflict_summary_from_chunks(
        OneShotIterable(summary_chunks)
    )
    materialized_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(summary_chunks)
    )
    one_shot_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            OneShotIterable(summary_chunks)
        )
    )
    materialized_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
        summary_chunks
    )
    one_shot_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
        OneShotIterable(summary_chunks)
    )

    assert one_shot_summary == materialized_summary
    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    assert one_shot_summary == (one_shot_signature_counts, one_shot_code_counts)
    return one_shot_summary


def assert_projection_chunk_stream_one_shot_parity(
    signature_count_chunks: tuple,
    code_count_chunks: tuple,
) -> tuple:
    materialized_signature_counts = MergeResult.stream_conflict_signature_counts_from_chunks(
        signature_count_chunks
    )
    one_shot_signature_counts = MergeResult.stream_conflict_signature_counts_from_chunks(
        OneShotIterable(signature_count_chunks)
    )
    materialized_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
        code_count_chunks
    )
    one_shot_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
        OneShotIterable(code_count_chunks)
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    return (one_shot_signature_counts, one_shot_code_counts)


def assert_summary_chunk_projection_extension_one_shot_parity(
    *,
    base_signature_counts: tuple,
    base_code_counts: tuple,
    summary_chunks: tuple,
) -> tuple:
    materialized_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            summary_chunks,
        )
    )
    one_shot_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            OneShotIterable(summary_chunks),
        )
    )
    materialized_code_counts = MergeResult.extend_conflict_code_counts_from_summary_chunks(
        base_code_counts,
        summary_chunks,
    )
    one_shot_code_counts = MergeResult.extend_conflict_code_counts_from_summary_chunks(
        base_code_counts,
        OneShotIterable(summary_chunks),
    )

    materialized_projection_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            base_signature_counts,
            tuple(summary_chunk[0] for summary_chunk in summary_chunks),
        )
    )
    materialized_projection_code_counts = (
        MergeResult.extend_conflict_code_counts_from_chunks(
            base_code_counts,
            tuple(summary_chunk[1] for summary_chunk in summary_chunks),
        )
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    assert one_shot_signature_counts == materialized_projection_signature_counts
    assert one_shot_code_counts == materialized_projection_code_counts
    return (one_shot_signature_counts, one_shot_code_counts)


def assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
    *,
    base_signature_counts: tuple,
    base_code_counts: tuple,
    continuation_summary_chunks: tuple,
    continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    expected_continuation_signature_counts, expected_continuation_code_counts = (
        continuation_projection_counts
    )
    materialized_continuation_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            continuation_summary_chunks
        )
    )
    one_shot_continuation_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            OneShotIterable(continuation_summary_chunks)
        )
    )
    materialized_continuation_code_counts = (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(
            continuation_summary_chunks
        )
    )
    one_shot_continuation_code_counts = (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(
            OneShotIterable(continuation_summary_chunks)
        )
    )

    materialized_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            continuation_summary_chunks,
        )
    )
    one_shot_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            OneShotIterable(continuation_summary_chunks),
        )
    )
    precomposed_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_signature_counts,
            expected_continuation_signature_counts,
        )
    )
    materialized_extended_code_counts = MergeResult.extend_conflict_code_counts_from_summary_chunks(
        base_code_counts,
        continuation_summary_chunks,
    )
    one_shot_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_code_counts,
            OneShotIterable(continuation_summary_chunks),
        )
    )
    precomposed_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_code_counts,
            expected_continuation_code_counts,
        )
    )

    assert (
        materialized_continuation_signature_counts
        == expected_continuation_signature_counts
    )
    assert one_shot_continuation_signature_counts == expected_continuation_signature_counts
    assert materialized_continuation_code_counts == expected_continuation_code_counts
    assert one_shot_continuation_code_counts == expected_continuation_code_counts
    assert one_shot_extended_signature_counts == materialized_extended_signature_counts
    assert precomposed_extended_signature_counts == materialized_extended_signature_counts
    assert one_shot_extended_code_counts == materialized_extended_code_counts
    assert precomposed_extended_code_counts == materialized_extended_code_counts
    return (
        materialized_extended_signature_counts,
        materialized_extended_code_counts,
    )


def assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
    *,
    base_summary: tuple[tuple, tuple],
    continuation_summary_chunks: tuple,
    continuation_summary: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    materialized_continuation_summary = MergeResult.combine_conflict_summaries_from_chunks(
        continuation_summary_chunks
    )
    one_shot_continuation_summary = MergeResult.combine_conflict_summaries_from_chunks(
        OneShotIterable(continuation_summary_chunks)
    )
    materialized_extended_summary = MergeResult.extend_conflict_summary_from_chunks(
        base_summary,
        continuation_summary_chunks,
    )
    one_shot_extended_summary = MergeResult.extend_conflict_summary_from_chunks(
        base_summary,
        OneShotIterable(continuation_summary_chunks),
    )
    precomposed_extended_summary = (
        MergeResult.extend_conflict_summary_with_precomposed_continuation(
            base_summary,
            continuation_summary,
        )
    )

    assert materialized_continuation_summary == continuation_summary
    assert one_shot_continuation_summary == continuation_summary
    assert one_shot_extended_summary == materialized_extended_summary
    assert precomposed_extended_summary == materialized_extended_summary
    return materialized_extended_summary


def assert_merge_result_projection_extension_one_shot_parity(
    *,
    base_signature_counts: tuple,
    base_code_counts: tuple,
    merge_results: tuple,
    summary_chunks: tuple,
) -> tuple:
    materialized_signature_counts = MergeResult.extend_conflict_signature_counts(
        base_signature_counts,
        merge_results,
    )
    one_shot_signature_counts = MergeResult.extend_conflict_signature_counts(
        base_signature_counts,
        OneShotIterable(merge_results),
    )
    materialized_code_counts = MergeResult.extend_conflict_code_counts(
        base_code_counts,
        merge_results,
    )
    one_shot_code_counts = MergeResult.extend_conflict_code_counts(
        base_code_counts,
        OneShotIterable(merge_results),
    )

    materialized_summary_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            summary_chunks,
        )
    )
    one_shot_summary_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_signature_counts,
            OneShotIterable(summary_chunks),
        )
    )
    materialized_summary_code_counts = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_code_counts,
            summary_chunks,
        )
    )
    one_shot_summary_code_counts = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_code_counts,
            OneShotIterable(summary_chunks),
        )
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    assert one_shot_summary_signature_counts == materialized_summary_signature_counts
    assert one_shot_summary_code_counts == materialized_summary_code_counts
    assert one_shot_signature_counts == one_shot_summary_signature_counts
    assert one_shot_code_counts == one_shot_summary_code_counts
    return (one_shot_signature_counts, one_shot_code_counts)


def assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
    *,
    base_signature_counts: tuple,
    base_code_counts: tuple,
    continuation_results: tuple,
    continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    expected_continuation_signature_counts, expected_continuation_code_counts = (
        continuation_projection_counts
    )
    materialized_continuation_signature_counts = (
        MergeResult.stream_conflict_signature_counts(continuation_results)
    )
    one_shot_continuation_signature_counts = MergeResult.stream_conflict_signature_counts(
        OneShotIterable(continuation_results)
    )
    materialized_continuation_code_counts = MergeResult.stream_conflict_code_counts(
        continuation_results
    )
    one_shot_continuation_code_counts = MergeResult.stream_conflict_code_counts(
        OneShotIterable(continuation_results)
    )

    materialized_extended_signature_counts = MergeResult.extend_conflict_signature_counts(
        base_signature_counts,
        continuation_results,
    )
    one_shot_extended_signature_counts = MergeResult.extend_conflict_signature_counts(
        base_signature_counts,
        OneShotIterable(continuation_results),
    )
    precomposed_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_signature_counts,
            expected_continuation_signature_counts,
        )
    )
    materialized_extended_code_counts = MergeResult.extend_conflict_code_counts(
        base_code_counts,
        continuation_results,
    )
    one_shot_extended_code_counts = MergeResult.extend_conflict_code_counts(
        base_code_counts,
        OneShotIterable(continuation_results),
    )
    precomposed_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_code_counts,
            expected_continuation_code_counts,
        )
    )

    assert (
        materialized_continuation_signature_counts
        == expected_continuation_signature_counts
    )
    assert one_shot_continuation_signature_counts == expected_continuation_signature_counts
    assert materialized_continuation_code_counts == expected_continuation_code_counts
    assert one_shot_continuation_code_counts == expected_continuation_code_counts
    assert one_shot_extended_signature_counts == materialized_extended_signature_counts
    assert precomposed_extended_signature_counts == materialized_extended_signature_counts
    assert one_shot_extended_code_counts == materialized_extended_code_counts
    assert precomposed_extended_code_counts == materialized_extended_code_counts
    return (
        materialized_extended_signature_counts,
        materialized_extended_code_counts,
    )


def assert_merge_result_summary_extension_one_shot_parity(
    *,
    base_summary: tuple,
    merge_results: tuple,
    summary_chunks: tuple,
) -> tuple:
    materialized_summary = MergeResult.extend_conflict_summary(
        base_summary,
        merge_results,
    )
    one_shot_summary = MergeResult.extend_conflict_summary(
        base_summary,
        OneShotIterable(merge_results),
    )
    materialized_summary_from_chunks = MergeResult.extend_conflict_summary_from_chunks(
        base_summary,
        summary_chunks,
    )
    one_shot_summary_from_chunks = MergeResult.extend_conflict_summary_from_chunks(
        base_summary,
        OneShotIterable(summary_chunks),
    )

    assert one_shot_summary == materialized_summary
    assert one_shot_summary_from_chunks == materialized_summary_from_chunks
    assert one_shot_summary == one_shot_summary_from_chunks
    return one_shot_summary


def assert_merge_result_summary_stream_one_shot_parity(
    *,
    merge_results: tuple,
    summary_chunks: tuple,
) -> tuple:
    materialized_summary = MergeResult.stream_conflict_summary(merge_results)
    one_shot_summary = MergeResult.stream_conflict_summary(
        OneShotIterable(merge_results)
    )
    materialized_summary_from_chunks = MergeResult.stream_conflict_summary_from_chunks(
        summary_chunks
    )
    one_shot_summary_from_chunks = MergeResult.stream_conflict_summary_from_chunks(
        OneShotIterable(summary_chunks)
    )

    assert one_shot_summary == materialized_summary
    assert one_shot_summary_from_chunks == materialized_summary_from_chunks
    assert one_shot_summary == one_shot_summary_from_chunks
    return one_shot_summary


def assert_merge_result_summary_continuation_composition_one_shot_parity(
    *,
    prefix_results: tuple,
    continuation_results: tuple,
    full_results: tuple,
) -> tuple:
    empty_summary_chunk = (tuple(), tuple())
    prefix_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=prefix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
    )
    continuation_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=continuation_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(continuation_results),
    )
    full_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )
    composition_summary_chunks = (
        (empty_summary_chunk,)
        + (prefix_summary, continuation_summary)
        + (empty_summary_chunk,)
    )
    materialized_composed_summary = MergeResult.stream_conflict_summary_from_chunks(
        composition_summary_chunks
    )
    one_shot_composed_summary = MergeResult.stream_conflict_summary_from_chunks(
        OneShotIterable(composition_summary_chunks)
    )
    composed_summary = MergeResult.combine_conflict_summaries(
        prefix_summary,
        continuation_summary,
    )

    assert one_shot_composed_summary == materialized_composed_summary
    assert composed_summary == materialized_composed_summary
    assert composed_summary == full_summary
    return composed_summary


def assert_merge_result_summary_three_way_continuation_composition_one_shot_parity(
    *,
    prefix_results: tuple,
    middle_results: tuple,
    suffix_results: tuple,
    full_results: tuple,
) -> tuple:
    empty_summary_chunk = (tuple(), tuple())
    prefix_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=prefix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
    )
    middle_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=middle_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(middle_results),
    )
    suffix_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=suffix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(suffix_results),
    )
    full_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )
    composition_summary_chunks = (
        (empty_summary_chunk,)
        + (prefix_summary, middle_summary, suffix_summary)
        + (empty_summary_chunk,)
    )

    materialized_composed_summary = MergeResult.combine_conflict_summaries_from_chunks(
        composition_summary_chunks
    )
    one_shot_composed_summary = MergeResult.combine_conflict_summaries_from_chunks(
        OneShotIterable(composition_summary_chunks)
    )
    left_associative_summary = MergeResult.combine_conflict_summaries(
        MergeResult.combine_conflict_summaries(prefix_summary, middle_summary),
        suffix_summary,
    )
    right_associative_summary = MergeResult.combine_conflict_summaries(
        prefix_summary,
        MergeResult.combine_conflict_summaries(middle_summary, suffix_summary),
    )

    assert one_shot_composed_summary == materialized_composed_summary
    assert left_associative_summary == materialized_composed_summary
    assert right_associative_summary == materialized_composed_summary
    assert left_associative_summary == right_associative_summary
    assert left_associative_summary == full_summary
    return left_associative_summary


def assert_merge_result_projection_stream_one_shot_parity(
    *,
    merge_results: tuple,
    summary_chunks: tuple,
) -> tuple:
    materialized_signature_counts = MergeResult.stream_conflict_signature_counts(
        merge_results
    )
    one_shot_signature_counts = MergeResult.stream_conflict_signature_counts(
        OneShotIterable(merge_results)
    )
    materialized_code_counts = MergeResult.stream_conflict_code_counts(merge_results)
    one_shot_code_counts = MergeResult.stream_conflict_code_counts(
        OneShotIterable(merge_results)
    )
    materialized_signature_counts_from_summary_chunks = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(summary_chunks)
    )
    one_shot_signature_counts_from_summary_chunks = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            OneShotIterable(summary_chunks)
        )
    )
    materialized_code_counts_from_summary_chunks = (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(summary_chunks)
    )
    one_shot_code_counts_from_summary_chunks = (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(
            OneShotIterable(summary_chunks)
        )
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    assert (
        one_shot_signature_counts_from_summary_chunks
        == materialized_signature_counts_from_summary_chunks
    )
    assert (
        one_shot_code_counts_from_summary_chunks
        == materialized_code_counts_from_summary_chunks
    )
    assert one_shot_signature_counts == one_shot_signature_counts_from_summary_chunks
    assert one_shot_code_counts == one_shot_code_counts_from_summary_chunks
    return (one_shot_signature_counts, one_shot_code_counts)


def assert_merge_result_projection_three_way_continuation_composition_one_shot_parity(
    *,
    prefix_results: tuple,
    middle_results: tuple,
    suffix_results: tuple,
    full_results: tuple,
) -> tuple:
    empty_projection_chunk = tuple()
    prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=prefix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
    )
    middle_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=middle_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(middle_results),
    )
    suffix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=suffix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(suffix_results),
    )
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )
    signature_count_chunks = (
        (empty_projection_chunk,)
        + (
            prefix_projection_counts[0],
            middle_projection_counts[0],
            suffix_projection_counts[0],
        )
        + (empty_projection_chunk,)
    )
    code_count_chunks = (
        (empty_projection_chunk,)
        + (
            prefix_projection_counts[1],
            middle_projection_counts[1],
            suffix_projection_counts[1],
        )
        + (empty_projection_chunk,)
    )

    materialized_signature_counts = (
        MergeResult.combine_conflict_signature_counts_from_chunks(signature_count_chunks)
    )
    one_shot_signature_counts = MergeResult.combine_conflict_signature_counts_from_chunks(
        OneShotIterable(signature_count_chunks)
    )
    left_associative_signature_counts = MergeResult.combine_conflict_signature_counts(
        MergeResult.combine_conflict_signature_counts(
            prefix_projection_counts[0],
            middle_projection_counts[0],
        ),
        suffix_projection_counts[0],
    )
    right_associative_signature_counts = MergeResult.combine_conflict_signature_counts(
        prefix_projection_counts[0],
        MergeResult.combine_conflict_signature_counts(
            middle_projection_counts[0],
            suffix_projection_counts[0],
        ),
    )

    materialized_code_counts = MergeResult.combine_conflict_code_counts_from_chunks(
        code_count_chunks
    )
    one_shot_code_counts = MergeResult.combine_conflict_code_counts_from_chunks(
        OneShotIterable(code_count_chunks)
    )
    left_associative_code_counts = MergeResult.combine_conflict_code_counts(
        MergeResult.combine_conflict_code_counts(
            prefix_projection_counts[1],
            middle_projection_counts[1],
        ),
        suffix_projection_counts[1],
    )
    right_associative_code_counts = MergeResult.combine_conflict_code_counts(
        prefix_projection_counts[1],
        MergeResult.combine_conflict_code_counts(
            middle_projection_counts[1],
            suffix_projection_counts[1],
        ),
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert left_associative_signature_counts == materialized_signature_counts
    assert right_associative_signature_counts == materialized_signature_counts
    assert left_associative_signature_counts == right_associative_signature_counts
    assert left_associative_signature_counts == full_projection_counts[0]
    assert one_shot_code_counts == materialized_code_counts
    assert left_associative_code_counts == materialized_code_counts
    assert right_associative_code_counts == materialized_code_counts
    assert left_associative_code_counts == right_associative_code_counts
    assert left_associative_code_counts == full_projection_counts[1]
    return (
        left_associative_signature_counts,
        left_associative_code_counts,
    )


def assert_merge_result_projection_extension_three_way_continuation_associativity_one_shot_parity(
    *,
    prefix_results: tuple,
    middle_results: tuple,
    suffix_results: tuple,
    full_results: tuple,
) -> tuple:
    empty_summary_chunk = (tuple(), tuple())
    prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=prefix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
    )
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )
    continuation_results = middle_results + suffix_results
    continuation_summary_chunks = (
        (empty_summary_chunk,)
        + tuple(merge_result.conflict_summary() for merge_result in continuation_results)
        + (empty_summary_chunk,)
    )
    continuation_signature_count_chunks = (
        (tuple(),)
        + tuple(
            merge_result.conflict_signature_counts()
            for merge_result in continuation_results
        )
        + (tuple(),)
    )
    continuation_code_count_chunks = (
        (tuple(),)
        + tuple(merge_result.conflict_code_counts() for merge_result in continuation_results)
        + (tuple(),)
    )
    middle_summary_chunks = conflict_summary_chunks_with_empty_path(middle_results)
    suffix_summary_chunks = conflict_summary_chunks_with_empty_path(suffix_results)
    middle_signature_count_chunks = tuple(
        merge_result.conflict_signature_counts() for merge_result in middle_results
    )
    suffix_signature_count_chunks = tuple(
        merge_result.conflict_signature_counts() for merge_result in suffix_results
    )
    middle_code_count_chunks = tuple(
        merge_result.conflict_code_counts() for merge_result in middle_results
    )
    suffix_code_count_chunks = tuple(
        merge_result.conflict_code_counts() for merge_result in suffix_results
    )

    materialized_signature_counts = MergeResult.extend_conflict_signature_counts(
        prefix_projection_counts[0],
        continuation_results,
    )
    one_shot_signature_counts = MergeResult.extend_conflict_signature_counts(
        prefix_projection_counts[0],
        OneShotIterable(continuation_results),
    )
    left_associative_signature_counts = MergeResult.extend_conflict_signature_counts(
        MergeResult.extend_conflict_signature_counts(
            prefix_projection_counts[0],
            middle_results,
        ),
        suffix_results,
    )
    materialized_signature_counts_from_summary_chunks = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            prefix_projection_counts[0],
            continuation_summary_chunks,
        )
    )
    one_shot_signature_counts_from_summary_chunks = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            prefix_projection_counts[0],
            OneShotIterable(continuation_summary_chunks),
        )
    )
    left_associative_signature_counts_from_summary_chunks = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                prefix_projection_counts[0],
                middle_summary_chunks,
            ),
            suffix_summary_chunks,
        )
    )
    materialized_precomposed_continuation_signature_counts = (
        MergeResult.combine_conflict_signature_counts_from_chunks(
            continuation_signature_count_chunks
        )
    )
    one_shot_precomposed_continuation_signature_counts = (
        MergeResult.combine_conflict_signature_counts_from_chunks(
            OneShotIterable(continuation_signature_count_chunks),
        )
    )
    left_associative_precomposed_continuation_signature_counts = (
        MergeResult.combine_conflict_signature_counts(
            MergeResult.combine_conflict_signature_counts_from_chunks(
                middle_signature_count_chunks
            ),
            MergeResult.combine_conflict_signature_counts_from_chunks(
                suffix_signature_count_chunks
            ),
        )
    )
    materialized_precomposed_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            prefix_projection_counts[0],
            materialized_precomposed_continuation_signature_counts,
        )
    )
    one_shot_precomposed_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            prefix_projection_counts[0],
            one_shot_precomposed_continuation_signature_counts,
        )
    )
    left_associative_precomposed_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            prefix_projection_counts[0],
            left_associative_precomposed_continuation_signature_counts,
        )
    )

    materialized_code_counts = MergeResult.extend_conflict_code_counts(
        prefix_projection_counts[1],
        continuation_results,
    )
    one_shot_code_counts = MergeResult.extend_conflict_code_counts(
        prefix_projection_counts[1],
        OneShotIterable(continuation_results),
    )
    left_associative_code_counts = MergeResult.extend_conflict_code_counts(
        MergeResult.extend_conflict_code_counts(
            prefix_projection_counts[1],
            middle_results,
        ),
        suffix_results,
    )
    materialized_code_counts_from_summary_chunks = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            prefix_projection_counts[1],
            continuation_summary_chunks,
        )
    )
    one_shot_code_counts_from_summary_chunks = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            prefix_projection_counts[1],
            OneShotIterable(continuation_summary_chunks),
        )
    )
    left_associative_code_counts_from_summary_chunks = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            MergeResult.extend_conflict_code_counts_from_summary_chunks(
                prefix_projection_counts[1],
                middle_summary_chunks,
            ),
            suffix_summary_chunks,
        )
    )
    materialized_precomposed_continuation_code_counts = (
        MergeResult.combine_conflict_code_counts_from_chunks(
            continuation_code_count_chunks
        )
    )
    one_shot_precomposed_continuation_code_counts = (
        MergeResult.combine_conflict_code_counts_from_chunks(
            OneShotIterable(continuation_code_count_chunks),
        )
    )
    left_associative_precomposed_continuation_code_counts = (
        MergeResult.combine_conflict_code_counts(
            MergeResult.combine_conflict_code_counts_from_chunks(
                middle_code_count_chunks
            ),
            MergeResult.combine_conflict_code_counts_from_chunks(
                suffix_code_count_chunks
            ),
        )
    )
    materialized_precomposed_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            prefix_projection_counts[1],
            materialized_precomposed_continuation_code_counts,
        )
    )
    one_shot_precomposed_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            prefix_projection_counts[1],
            one_shot_precomposed_continuation_code_counts,
        )
    )
    left_associative_precomposed_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            prefix_projection_counts[1],
            left_associative_precomposed_continuation_code_counts,
        )
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert left_associative_signature_counts == materialized_signature_counts
    assert (
        one_shot_signature_counts_from_summary_chunks
        == materialized_signature_counts_from_summary_chunks
    )
    assert (
        left_associative_signature_counts_from_summary_chunks
        == materialized_signature_counts_from_summary_chunks
    )
    assert (
        one_shot_precomposed_continuation_signature_counts
        == materialized_precomposed_continuation_signature_counts
    )
    assert (
        left_associative_precomposed_continuation_signature_counts
        == materialized_precomposed_continuation_signature_counts
    )
    assert materialized_precomposed_extended_signature_counts == materialized_signature_counts
    assert one_shot_precomposed_extended_signature_counts == materialized_signature_counts
    assert (
        left_associative_precomposed_extended_signature_counts
        == materialized_signature_counts
    )
    assert materialized_signature_counts == materialized_signature_counts_from_summary_chunks
    assert materialized_signature_counts == full_projection_counts[0]
    assert one_shot_code_counts == materialized_code_counts
    assert left_associative_code_counts == materialized_code_counts
    assert one_shot_code_counts_from_summary_chunks == materialized_code_counts_from_summary_chunks
    assert (
        left_associative_code_counts_from_summary_chunks
        == materialized_code_counts_from_summary_chunks
    )
    assert (
        one_shot_precomposed_continuation_code_counts
        == materialized_precomposed_continuation_code_counts
    )
    assert (
        left_associative_precomposed_continuation_code_counts
        == materialized_precomposed_continuation_code_counts
    )
    assert materialized_precomposed_extended_code_counts == materialized_code_counts
    assert one_shot_precomposed_extended_code_counts == materialized_code_counts
    assert left_associative_precomposed_extended_code_counts == materialized_code_counts
    assert materialized_code_counts == materialized_code_counts_from_summary_chunks
    assert materialized_code_counts == full_projection_counts[1]
    return (
        materialized_signature_counts,
        materialized_code_counts,
    )


def assert_merge_result_summary_extension_three_way_continuation_associativity_one_shot_parity(
    *,
    prefix_results: tuple,
    middle_results: tuple,
    suffix_results: tuple,
    full_results: tuple,
) -> tuple:
    empty_summary_chunk = (tuple(), tuple())
    prefix_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=prefix_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
    )
    assert prefix_summary[0]
    assert prefix_summary[1]
    full_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )
    continuation_results = middle_results + suffix_results
    continuation_summary_chunks = (
        (empty_summary_chunk,)
        + tuple(merge_result.conflict_summary() for merge_result in continuation_results)
        + (empty_summary_chunk,)
    )
    middle_summary_chunks = conflict_summary_chunks_with_empty_path(middle_results)
    suffix_summary_chunks = conflict_summary_chunks_with_empty_path(suffix_results)
    middle_summary = MergeResult.stream_conflict_summary_from_chunks(middle_summary_chunks)
    suffix_summary = MergeResult.stream_conflict_summary_from_chunks(suffix_summary_chunks)

    materialized_summary = MergeResult.extend_conflict_summary(
        prefix_summary,
        continuation_results,
    )
    one_shot_summary = MergeResult.extend_conflict_summary(
        prefix_summary,
        OneShotIterable(continuation_results),
    )
    left_associative_summary = MergeResult.extend_conflict_summary(
        MergeResult.extend_conflict_summary(prefix_summary, middle_results),
        suffix_results,
    )
    materialized_summary_from_chunks = MergeResult.extend_conflict_summary_from_chunks(
        prefix_summary,
        continuation_summary_chunks,
    )
    one_shot_summary_from_chunks = MergeResult.extend_conflict_summary_from_chunks(
        prefix_summary,
        OneShotIterable(continuation_summary_chunks),
    )
    left_associative_summary_from_chunks = (
        MergeResult.extend_conflict_summary_from_chunks(
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                middle_summary_chunks,
            ),
            suffix_summary_chunks,
        )
    )
    materialized_precomposed_continuation_summary = (
        MergeResult.combine_conflict_summaries_from_chunks(continuation_summary_chunks)
    )
    one_shot_precomposed_continuation_summary = (
        MergeResult.combine_conflict_summaries_from_chunks(
            OneShotIterable(continuation_summary_chunks),
        )
    )
    left_associative_precomposed_continuation_summary = (
        MergeResult.combine_conflict_summaries(
            middle_summary,
            suffix_summary,
        )
    )
    right_associative_precomposed_continuation_summary = (
        MergeResult.combine_conflict_summaries(
            MergeResult.combine_conflict_summaries_from_chunks(middle_summary_chunks),
            MergeResult.combine_conflict_summaries_from_chunks(suffix_summary_chunks),
        )
    )
    materialized_precomposed_extended_summary = (
        MergeResult.extend_conflict_summary_with_precomposed_continuation(
            prefix_summary,
            materialized_precomposed_continuation_summary,
        )
    )
    one_shot_precomposed_extended_summary = (
        MergeResult.extend_conflict_summary_with_precomposed_continuation(
            prefix_summary,
            one_shot_precomposed_continuation_summary,
        )
    )
    left_associative_precomposed_extended_summary = (
        MergeResult.extend_conflict_summary_with_precomposed_continuation(
            prefix_summary,
            left_associative_precomposed_continuation_summary,
        )
    )
    right_associative_precomposed_extended_summary = (
        MergeResult.extend_conflict_summary_with_precomposed_continuation(
            prefix_summary,
            right_associative_precomposed_continuation_summary,
        )
    )

    assert one_shot_summary == materialized_summary
    assert left_associative_summary == materialized_summary
    assert one_shot_summary_from_chunks == materialized_summary_from_chunks
    assert left_associative_summary_from_chunks == materialized_summary_from_chunks
    assert (
        one_shot_precomposed_continuation_summary
        == materialized_precomposed_continuation_summary
    )
    assert (
        left_associative_precomposed_continuation_summary
        == materialized_precomposed_continuation_summary
    )
    assert (
        right_associative_precomposed_continuation_summary
        == materialized_precomposed_continuation_summary
    )
    assert materialized_precomposed_extended_summary == materialized_summary
    assert one_shot_precomposed_extended_summary == materialized_summary
    assert left_associative_precomposed_extended_summary == materialized_summary
    assert right_associative_precomposed_extended_summary == materialized_summary
    assert materialized_summary == materialized_summary_from_chunks
    assert materialized_summary == full_summary
    return materialized_summary


def conflict_summary_chunks_with_empty_path(merge_results: tuple) -> tuple:
    empty_summary_chunk = (tuple(), tuple())
    return (
        (empty_summary_chunk,)
        + tuple(merge_result.conflict_summary() for merge_result in merge_results)
        + (empty_summary_chunk,)
    )


def build_three_payload_relation_collision_replicas(
    *,
    tx_base: int,
) -> tuple[RelationEdge, tuple[KnowledgeStore, KnowledgeStore, KnowledgeStore]]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    evidence_revision = seed.assert_revision(
        core=evidence_core,
        assertion="Archive records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_doc"),
        confidence_bp=9000,
    )

    relation_supports = RelationEdge(
        relation_type="supports",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 10, recorded_at=dt(2024, 1, 5)),
    )
    relation_derived = force_relation_id(
        RelationEdge(
            relation_type="derived_from",
            from_revision_id=residence_revision.revision_id,
            to_revision_id=evidence_revision.revision_id,
            transaction_time=TransactionTime(
                tx_id=tx_base + 10,
                recorded_at=dt(2024, 1, 5),
            ),
        ),
        relation_supports.relation_id,
    )
    relation_canonical = force_relation_id(
        RelationEdge(
            relation_type="contradicts",
            from_revision_id=residence_revision.revision_id,
            to_revision_id=evidence_revision.revision_id,
            transaction_time=TransactionTime(
                tx_id=tx_base + 10,
                recorded_at=dt(2024, 1, 5),
            ),
        ),
        relation_supports.relation_id,
    )

    def payload_replica(relation: RelationEdge) -> KnowledgeStore:
        replica = KnowledgeStore()
        replica.assert_revision(
            core=residence_core,
            assertion="Ada lives in London",
            valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
            transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
            provenance=Provenance(source="source_a"),
            confidence_bp=7000,
        )
        replica.assert_revision(
            core=evidence_core,
            assertion="Archive records London residence",
            valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
            transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
            provenance=Provenance(source="source_doc"),
            confidence_bp=9000,
        )
        replica.relations[relation.relation_id] = relation
        return replica

    return (
        relation_canonical,
        (
            payload_replica(relation_supports),
            payload_replica(relation_derived),
            payload_replica(relation_canonical),
        ),
    )


def build_mixed_orphan_collision_checkpoint_replicas(
    *,
    tx_base: int,
) -> tuple[RelationEdge, list[KnowledgeStore]]:
    residence_core = ClaimCore(
        claim_type="residence",
        slots={"subject": "Ada Lovelace"},
    )
    evidence_core = ClaimCore(
        claim_type="document",
        slots={"id": f"archive-mixed-{tx_base}"},
    )

    seed = KnowledgeStore()
    residence_revision = seed.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    evidence_revision = seed.assert_revision(
        core=evidence_core,
        assertion="Archive records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_doc"),
        confidence_bp=9000,
    )

    relation_supports = RelationEdge(
        relation_type="supports",
        from_revision_id=residence_revision.revision_id,
        to_revision_id=evidence_revision.revision_id,
        transaction_time=TransactionTime(tx_id=tx_base + 10, recorded_at=dt(2024, 1, 5)),
    )
    relation_derived = force_relation_id(
        RelationEdge(
            relation_type="derived_from",
            from_revision_id=residence_revision.revision_id,
            to_revision_id=evidence_revision.revision_id,
            transaction_time=TransactionTime(
                tx_id=tx_base + 10,
                recorded_at=dt(2024, 1, 5),
            ),
        ),
        relation_supports.relation_id,
    )
    relation_canonical = force_relation_id(
        RelationEdge(
            relation_type="contradicts",
            from_revision_id=residence_revision.revision_id,
            to_revision_id=evidence_revision.revision_id,
            transaction_time=TransactionTime(
                tx_id=tx_base + 10,
                recorded_at=dt(2024, 1, 5),
            ),
        ),
        relation_supports.relation_id,
    )

    replica_endpoints = KnowledgeStore()
    replica_endpoints.assert_revision(
        core=residence_core,
        assertion="Ada lives in London",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base, recorded_at=dt(2024, 1, 2)),
        provenance=Provenance(source="source_a"),
        confidence_bp=7000,
    )
    replica_endpoints.assert_revision(
        core=evidence_core,
        assertion="Archive records London residence",
        valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
        transaction_time=TransactionTime(tx_id=tx_base + 1, recorded_at=dt(2024, 1, 3)),
        provenance=Provenance(source="source_doc"),
        confidence_bp=9000,
    )

    replica_orphan_supports = KnowledgeStore()
    replica_orphan_supports.relations[relation_supports.relation_id] = relation_supports

    replica_orphan_derived = KnowledgeStore()
    replica_orphan_derived.relations[relation_derived.relation_id] = relation_derived

    replica_canonical = replica_endpoints.copy()
    replica_canonical.relations[relation_canonical.relation_id] = relation_canonical

    return (
        relation_canonical,
        [
            replica_orphan_supports,
            replica_orphan_derived,
            replica_endpoints,
            replica_canonical,
            replica_orphan_supports.copy(),
        ],
    )


def build_mixed_orphan_collision_lifecycle_checkpoint_replicas(
    *,
    tx_base: int,
) -> tuple[ClaimCore, RelationEdge, list[KnowledgeStore]]:
    relation_canonical, relation_replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(
        tx_base=tx_base
    )

    lifecycle_core = ClaimCore(
        claim_type="residence-lifecycle",
        slots={
            "subject": "Ada Lovelace",
            "series": f"checkpoint-{tx_base}",
        },
    )
    lifecycle_tx = TransactionTime(tx_id=tx_base + 20, recorded_at=dt(2024, 1, 6))
    lifecycle_valid = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_lifecycle_asserted = KnowledgeStore()
    replica_lifecycle_asserted.assert_revision(
        core=lifecycle_core,
        assertion="Ada lives in London",
        valid_time=lifecycle_valid,
        transaction_time=lifecycle_tx,
        provenance=Provenance(source="lifecycle_source_asserted"),
        confidence_bp=6500,
        status="asserted",
    )

    replica_lifecycle_retracted = KnowledgeStore()
    replica_lifecycle_retracted.assert_revision(
        core=lifecycle_core,
        assertion="Ada lives in London",
        valid_time=lifecycle_valid,
        transaction_time=lifecycle_tx,
        provenance=Provenance(source="lifecycle_source_retracted"),
        confidence_bp=6500,
        status="retracted",
    )

    replay_sequence = [
        relation_replay_sequence[0],
        relation_replay_sequence[1],
        replica_lifecycle_asserted,
        relation_replay_sequence[2],
        relation_replay_sequence[3],
        replica_lifecycle_retracted,
    ]
    return lifecycle_core, relation_canonical, replay_sequence


def build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
    *,
    tx_base: int,
) -> tuple[ClaimCore, RelationEdge, list[KnowledgeStore]]:
    relation_canonical, relation_replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(
        tx_base=tx_base
    )

    lifecycle_core = ClaimCore(
        claim_type="residence-lifecycle",
        slots={
            "subject": "Ada Lovelace",
            "series": f"repeated-checkpoint-{tx_base}",
        },
    )
    lifecycle_tx = TransactionTime(tx_id=tx_base + 20, recorded_at=dt(2024, 1, 6))
    lifecycle_valid = ValidTime(start=dt(2024, 1, 1), end=None)

    replica_lifecycle_pair = KnowledgeStore()
    replica_lifecycle_pair.assert_revision(
        core=lifecycle_core,
        assertion="Ada lives in London",
        valid_time=lifecycle_valid,
        transaction_time=lifecycle_tx,
        provenance=Provenance(source="lifecycle_source_asserted"),
        confidence_bp=6500,
        status="asserted",
    )
    replica_lifecycle_pair.assert_revision(
        core=lifecycle_core,
        assertion="Ada lives in London",
        valid_time=lifecycle_valid,
        transaction_time=lifecycle_tx,
        provenance=Provenance(source="lifecycle_source_retracted"),
        confidence_bp=6500,
        status="retracted",
    )

    replay_sequence = [
        relation_replay_sequence[0],
        replica_lifecycle_pair,
        relation_replay_sequence[1],
        relation_replay_sequence[4],
        relation_replay_sequence[2],
        relation_replay_sequence[3],
    ]
    return lifecycle_core, relation_canonical, replay_sequence


def build_conflict_free_checkpoint_replicas(
    *,
    tx_base: int,
    count: int,
) -> list[KnowledgeStore]:
    replicas: list[KnowledgeStore] = []
    for offset in range(count):
        replica = KnowledgeStore()
        core = ClaimCore(
            claim_type="residence",
            slots={"subject": f"conflict-free-{tx_base}-{offset}"},
        )
        replica.assert_revision(
            core=core,
            assertion=f"Subject {offset} lives in London",
            valid_time=ValidTime(start=dt(2024, 1, 1), end=None),
            transaction_time=TransactionTime(
                tx_id=tx_base + offset,
                recorded_at=dt(2024, 1, 2),
            ),
            provenance=Provenance(source=f"clean_source_{offset}"),
            confidence_bp=7000,
            status="asserted",
        )
        replicas.append(replica)
    return replicas


def replay_stream(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    observed_conflicts = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        observed_conflicts.extend(merge_result.conflicts)
    return merged, tuple(observed_conflicts)


def replay_stream_with_results(
    replicas: list[KnowledgeStore],
    *,
    start: KnowledgeStore | None = None,
) -> tuple[KnowledgeStore, tuple]:
    merged = start if start is not None else KnowledgeStore()
    merge_results = []
    for replica in replicas:
        merge_result = merged.merge(replica)
        merged = merge_result.merged
        merge_results.append(merge_result)
    return merged, tuple(merge_results)


def replica_stream_tx_id(replica: KnowledgeStore) -> int:
    tx_ids = [revision.transaction_time.tx_id for revision in replica.revisions.values()]
    tx_ids.extend(relation.transaction_time.tx_id for relation in replica.relations.values())
    tx_ids.extend(
        relation.transaction_time.tx_id for relation in replica._pending_relations.values()
    )
    return max(tx_ids, default=0)


def test_merge_result_stream_conflict_reducers_match_flattened_conflicts() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1600
    )

    _, merge_results = replay_stream_with_results(replay_sequence)
    flattened_conflicts = tuple(
        conflict for merge_result in merge_results for conflict in merge_result.conflicts
    )

    assert MergeResult.stream_conflict_signature_counts(
        merge_results
    ) == KnowledgeStore.conflict_signature_counts(flattened_conflicts)
    assert MergeResult.stream_conflict_code_counts(
        merge_results
    ) == KnowledgeStore.conflict_code_counts(flattened_conflicts)
    assert MergeResult.stream_conflict_summary(merge_results) == (
        MergeResult.stream_conflict_signature_counts(merge_results),
        MergeResult.stream_conflict_code_counts(merge_results),
    )


def test_merge_result_stream_conflict_reducers_empty_stream_is_zero_summary() -> None:
    empty_results: tuple[MergeResult, ...] = ()
    assert MergeResult.stream_conflict_signature_counts(empty_results) == tuple()
    assert MergeResult.stream_conflict_code_counts(empty_results) == tuple()
    assert MergeResult.stream_conflict_summary(empty_results) == (tuple(), tuple())


def test_merge_result_stream_conflict_reducers_single_conflict_free_merge_is_zero_summary() -> None:
    conflict_free_replica = build_conflict_free_checkpoint_replicas(tx_base=1700, count=1)[0]
    merged, merge_results = replay_stream_with_results([conflict_free_replica])

    assert len(merge_results) == 1
    assert merge_results[0].conflicts == tuple()
    assert merge_results[0].conflict_summary() == (tuple(), tuple())
    assert MergeResult.stream_conflict_signature_counts(merge_results) == tuple()
    assert MergeResult.stream_conflict_code_counts(merge_results) == tuple()
    assert MergeResult.stream_conflict_summary(merge_results) == (tuple(), tuple())
    assert merged.revision_state_signatures() == conflict_free_replica.revision_state_signatures()


def test_merge_checkpoint_continuation_zero_conflict_suffix_stream_summary_is_stable() -> None:
    replay_sequence = build_conflict_free_checkpoint_replicas(tx_base=1750, count=6)
    split_index = 3
    prefix = replay_sequence[:split_index]
    suffix = replay_sequence[split_index:]

    prefix_merged, _ = replay_stream_with_results(prefix)
    unsplit_merged, unsplit_results = replay_stream_with_results(suffix, start=prefix_merged)
    resumed_merged, resumed_results = replay_stream_with_results(
        suffix,
        start=prefix_merged.checkpoint(),
    )

    assert all(result.conflicts == tuple() for result in unsplit_results)
    assert all(result.conflicts == tuple() for result in resumed_results)
    assert all(result.conflict_summary() == (tuple(), tuple()) for result in unsplit_results)
    assert all(result.conflict_summary() == (tuple(), tuple()) for result in resumed_results)
    assert MergeResult.stream_conflict_signature_counts(unsplit_results) == tuple()
    assert MergeResult.stream_conflict_signature_counts(resumed_results) == tuple()
    assert MergeResult.stream_conflict_code_counts(unsplit_results) == tuple()
    assert MergeResult.stream_conflict_code_counts(resumed_results) == tuple()
    assert MergeResult.stream_conflict_summary(unsplit_results) == (tuple(), tuple())
    assert MergeResult.stream_conflict_summary(resumed_results) == (tuple(), tuple())
    assert resumed_merged.revision_state_signatures() == unsplit_merged.revision_state_signatures()


def test_merge_result_stream_conflict_summary_ignores_conflict_free_suffix() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1800
    )
    conflict_prefix = replay_sequence[:3]
    conflict_free_suffix = build_conflict_free_checkpoint_replicas(tx_base=1810, count=4)

    prefix_merged, prefix_results = replay_stream_with_results(conflict_prefix)
    unsplit_merged, unsplit_suffix_results = replay_stream_with_results(
        conflict_free_suffix,
        start=prefix_merged,
    )
    resumed_merged, resumed_suffix_results = replay_stream_with_results(
        conflict_free_suffix,
        start=prefix_merged.checkpoint(),
    )

    prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
    unsplit_suffix_summary = MergeResult.stream_conflict_summary(unsplit_suffix_results)
    resumed_suffix_summary = MergeResult.stream_conflict_summary(resumed_suffix_results)

    assert prefix_summary != (tuple(), tuple())
    assert unsplit_suffix_summary == (tuple(), tuple())
    assert resumed_suffix_summary == (tuple(), tuple())
    assert MergeResult.combine_conflict_summaries(
        prefix_summary,
        unsplit_suffix_summary,
    ) == prefix_summary
    assert MergeResult.combine_conflict_summaries(
        prefix_summary,
        resumed_suffix_summary,
    ) == prefix_summary
    assert (
        MergeResult.stream_conflict_summary(prefix_results + unsplit_suffix_results)
        == prefix_summary
    )
    assert (
        MergeResult.stream_conflict_summary(prefix_results + resumed_suffix_results)
        == prefix_summary
    )
    assert resumed_merged.revision_state_signatures() == unsplit_merged.revision_state_signatures()


def test_merge_result_stream_conflict_summary_ignores_conflict_free_suffix_permutations() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1820
    )
    conflict_prefix = replay_sequence[:3]
    conflict_free_suffix = build_conflict_free_checkpoint_replicas(tx_base=1830, count=3)

    for order in itertools.permutations(range(len(conflict_prefix))):
        ordered_prefix = [conflict_prefix[index] for index in order]
        prefix_merged, prefix_results = replay_stream_with_results(ordered_prefix)
        unsplit_merged, unsplit_suffix_results = replay_stream_with_results(
            conflict_free_suffix,
            start=prefix_merged,
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            conflict_free_suffix,
            start=prefix_merged.checkpoint(),
        )

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        unsplit_suffix_summary = MergeResult.stream_conflict_summary(unsplit_suffix_results)
        resumed_suffix_summary = MergeResult.stream_conflict_summary(resumed_suffix_results)

        assert prefix_summary != (tuple(), tuple())
        assert unsplit_suffix_summary == (tuple(), tuple())
        assert resumed_suffix_summary == (tuple(), tuple())
        assert MergeResult.combine_conflict_summaries(
            prefix_summary,
            unsplit_suffix_summary,
        ) == prefix_summary
        assert MergeResult.combine_conflict_summaries(
            prefix_summary,
            resumed_suffix_summary,
        ) == prefix_summary
        assert (
            MergeResult.stream_conflict_summary(prefix_results + unsplit_suffix_results)
            == prefix_summary
        )
        assert (
            MergeResult.stream_conflict_summary(prefix_results + resumed_suffix_results)
            == prefix_summary
        )
        assert (
            resumed_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )


def test_merge_result_extend_conflict_summary_matches_full_stream_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1840
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary = MergeResult.stream_conflict_summary(merge_results)
    assert full_summary != (tuple(), tuple())

    for split_index in range(len(merge_results) + 1):
        prefix_summary = MergeResult.extend_conflict_summary(
            (tuple(), tuple()),
            merge_results[:split_index],
        )
        resumed_summary = MergeResult.extend_conflict_summary(
            prefix_summary,
            merge_results[split_index:],
        )
        assert resumed_summary == full_summary


def test_merge_result_extend_conflict_summary_checkpoint_chunks_match_unsplit_permutations() -> None:
    tx_base = 1860
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=tx_base
    )

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        unsplit_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged,
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        full_summary = MergeResult.stream_conflict_summary(full_results)

        assert MergeResult.extend_conflict_summary(
            prefix_summary,
            unsplit_suffix_results,
        ) == full_summary
        assert MergeResult.extend_conflict_summary(
            prefix_summary,
            resumed_suffix_results,
        ) == full_summary

        suffix_midpoint = len(resumed_suffix_results) // 2
        resumed_chunked_summary = MergeResult.extend_conflict_summary(
            MergeResult.extend_conflict_summary(
                prefix_summary,
                resumed_suffix_results[:suffix_midpoint],
            ),
            resumed_suffix_results[suffix_midpoint:],
        )
        assert resumed_chunked_summary == full_summary
        assert (
            resumed_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_extend_conflict_projection_helpers_match_stream_views_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1880
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_signature_counts = MergeResult.stream_conflict_signature_counts(merge_results)
    full_code_counts = MergeResult.stream_conflict_code_counts(merge_results)

    assert MergeResult.extend_conflict_signature_counts(
        tuple(),
        merge_results,
    ) == full_signature_counts
    assert MergeResult.extend_conflict_code_counts(
        tuple(),
        merge_results,
    ) == full_code_counts

    for split_index in range(len(merge_results) + 1):
        prefix_signature_counts = MergeResult.extend_conflict_signature_counts(
            tuple(),
            merge_results[:split_index],
        )
        resumed_signature_counts = MergeResult.extend_conflict_signature_counts(
            prefix_signature_counts,
            merge_results[split_index:],
        )
        assert resumed_signature_counts == full_signature_counts

        prefix_code_counts = MergeResult.extend_conflict_code_counts(
            tuple(),
            merge_results[:split_index],
        )
        resumed_code_counts = MergeResult.extend_conflict_code_counts(
            prefix_code_counts,
            merge_results[split_index:],
        )
        assert resumed_code_counts == full_code_counts


def test_merge_result_extend_conflict_projection_helpers_empty_continuation_is_identity_permutations() -> None:
    relation_canonical, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1890
    )

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        prefix_merged, prefix_results = replay_stream_with_results(ordered_replicas)
        unsplit_merged, unsplit_empty_results = replay_stream_with_results(
            [],
            start=prefix_merged,
        )
        resumed_merged, resumed_empty_results = replay_stream_with_results(
            [],
            start=prefix_merged.checkpoint(),
        )

        assert unsplit_empty_results == tuple()
        assert resumed_empty_results == tuple()

        base_signature_counts = MergeResult.stream_conflict_signature_counts(prefix_results)
        base_code_counts = MergeResult.stream_conflict_code_counts(prefix_results)
        base_summary = (base_signature_counts, base_code_counts)

        assert (
            MergeResult.extend_conflict_signature_counts(
                base_signature_counts,
                unsplit_empty_results,
            )
            == base_signature_counts
        )
        assert (
            MergeResult.extend_conflict_signature_counts(
                base_signature_counts,
                resumed_empty_results,
            )
            == base_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts(
                base_code_counts,
                unsplit_empty_results,
            )
            == base_code_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts(
                base_code_counts,
                resumed_empty_results,
            )
            == base_code_counts
        )
        assert (
            MergeResult.extend_conflict_summary(base_summary, unsplit_empty_results)
            == base_summary
        )
        assert (
            MergeResult.extend_conflict_summary(base_summary, resumed_empty_results)
            == base_summary
        )

        assert (
            resumed_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert resumed_merged.pending_relation_ids() == unsplit_merged.pending_relation_ids()
        assert resumed_merged.query_relations_as_of(
            tx_id=relation_canonical.transaction_time.tx_id
        ) == unsplit_merged.query_relations_as_of(
            tx_id=relation_canonical.transaction_time.tx_id
        )


def test_merge_result_combine_conflict_projection_helpers_match_summary_composition_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1900
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary = MergeResult.stream_conflict_summary(merge_results)
    assert full_summary != (tuple(), tuple())

    for split_index in range(len(merge_results) + 1):
        left_summary = MergeResult.stream_conflict_summary(merge_results[:split_index])
        right_summary = MergeResult.stream_conflict_summary(merge_results[split_index:])
        combined_summary = MergeResult.combine_conflict_summaries(
            left_summary,
            right_summary,
        )

        assert combined_summary == full_summary
        assert (
            MergeResult.combine_conflict_signature_counts(
                left_summary[0],
                right_summary[0],
            )
            == combined_summary[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                left_summary[1],
                right_summary[1],
            )
            == combined_summary[1]
        )


def test_merge_result_combine_conflict_projection_helpers_checkpoint_chunk_associativity_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=1910)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        unsplit_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged,
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        unsplit_suffix_summary = MergeResult.stream_conflict_summary(unsplit_suffix_results)
        resumed_suffix_summary = MergeResult.stream_conflict_summary(resumed_suffix_results)
        full_summary = MergeResult.stream_conflict_summary(full_results)

        assert MergeResult.combine_conflict_signature_counts(
            prefix_summary[0],
            unsplit_suffix_summary[0],
        ) == full_summary[0]
        assert MergeResult.combine_conflict_signature_counts(
            prefix_summary[0],
            resumed_suffix_summary[0],
        ) == full_summary[0]
        assert MergeResult.combine_conflict_code_counts(
            prefix_summary[1],
            unsplit_suffix_summary[1],
        ) == full_summary[1]
        assert MergeResult.combine_conflict_code_counts(
            prefix_summary[1],
            resumed_suffix_summary[1],
        ) == full_summary[1]

        suffix_midpoint = len(resumed_suffix_results) // 2
        left_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[:suffix_midpoint]
        )
        right_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[suffix_midpoint:]
        )

        summary_left_assoc = MergeResult.combine_conflict_summaries(
            MergeResult.combine_conflict_summaries(prefix_summary, left_suffix_summary),
            right_suffix_summary,
        )
        summary_right_assoc = MergeResult.combine_conflict_summaries(
            prefix_summary,
            MergeResult.combine_conflict_summaries(
                left_suffix_summary,
                right_suffix_summary,
            ),
        )
        assert summary_left_assoc == full_summary
        assert summary_right_assoc == full_summary

        signature_left_assoc = MergeResult.combine_conflict_signature_counts(
            MergeResult.combine_conflict_signature_counts(
                prefix_summary[0],
                left_suffix_summary[0],
            ),
            right_suffix_summary[0],
        )
        signature_right_assoc = MergeResult.combine_conflict_signature_counts(
            prefix_summary[0],
            MergeResult.combine_conflict_signature_counts(
                left_suffix_summary[0],
                right_suffix_summary[0],
            ),
        )
        code_left_assoc = MergeResult.combine_conflict_code_counts(
            MergeResult.combine_conflict_code_counts(
                prefix_summary[1],
                left_suffix_summary[1],
            ),
            right_suffix_summary[1],
        )
        code_right_assoc = MergeResult.combine_conflict_code_counts(
            prefix_summary[1],
            MergeResult.combine_conflict_code_counts(
                left_suffix_summary[1],
                right_suffix_summary[1],
            ),
        )

        assert signature_left_assoc == summary_left_assoc[0]
        assert signature_right_assoc == summary_right_assoc[0]
        assert code_left_assoc == summary_left_assoc[1]
        assert code_right_assoc == summary_right_assoc[1]
        assert signature_left_assoc == signature_right_assoc == full_summary[0]
        assert code_left_assoc == code_right_assoc == full_summary[1]
        assert (
            resumed_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_extend_conflict_projection_chunk_helpers_match_summary_composition_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1920
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary = MergeResult.stream_conflict_summary(merge_results)
    projection_signature_chunks = tuple(
        merge_result.conflict_summary()[0] for merge_result in merge_results
    )
    projection_code_chunks = tuple(
        merge_result.conflict_summary()[1] for merge_result in merge_results
    )

    assert (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            tuple(),
            projection_signature_chunks,
        )
        == full_summary[0]
    )
    assert (
        MergeResult.extend_conflict_code_counts_from_chunks(
            tuple(),
            projection_code_chunks,
        )
        == full_summary[1]
    )

    for split_index in range(len(merge_results) + 1):
        prefix_summary = MergeResult.stream_conflict_summary(merge_results[:split_index])
        suffix_summary = MergeResult.stream_conflict_summary(merge_results[split_index:])
        composed_summary = MergeResult.combine_conflict_summaries(
            prefix_summary,
            suffix_summary,
        )

        assert composed_summary == full_summary
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_summary[0],
                projection_signature_chunks[split_index:],
            )
            == composed_summary[0]
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_summary[1],
                projection_code_chunks[split_index:],
            )
            == composed_summary[1]
        )


def test_merge_result_extend_conflict_projection_chunk_helpers_checkpoint_replay_match_repeated_summary_composition_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=1930)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        full_summary = MergeResult.stream_conflict_summary(full_results)

        suffix_midpoint = len(resumed_suffix_results) // 2
        left_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[:suffix_midpoint]
        )
        right_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[suffix_midpoint:]
        )
        expected_summary = MergeResult.combine_conflict_summaries(
            prefix_summary,
            MergeResult.combine_conflict_summaries(
                left_suffix_summary,
                right_suffix_summary,
            ),
        )
        assert expected_summary == full_summary

        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_summary[0],
                (
                    left_suffix_summary[0],
                    right_suffix_summary[0],
                ),
            )
            == expected_summary[0]
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_summary[1],
                (
                    left_suffix_summary[1],
                    right_suffix_summary[1],
                ),
            )
            == expected_summary[1]
        )

        per_result_signature_chunks = tuple(
            merge_result.conflict_summary()[0]
            for merge_result in resumed_suffix_results
        )
        per_result_code_chunks = tuple(
            merge_result.conflict_summary()[1]
            for merge_result in resumed_suffix_results
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_summary[0],
                per_result_signature_chunks,
            )
            == full_summary[0]
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_summary[1],
                per_result_code_chunks,
            )
            == full_summary[1]
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_extend_conflict_summary_from_chunks_matches_summary_composition_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1940
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary = MergeResult.stream_conflict_summary(merge_results)
    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )
    assert (
        MergeResult.extend_conflict_summary_from_chunks(
            (tuple(), tuple()),
            summary_chunks,
        )
        == full_summary
    )

    for split_index in range(len(merge_results) + 1):
        prefix_summary = MergeResult.stream_conflict_summary(merge_results[:split_index])
        suffix_summary = MergeResult.stream_conflict_summary(merge_results[split_index:])
        composed_summary = MergeResult.combine_conflict_summaries(
            prefix_summary,
            suffix_summary,
        )
        assert composed_summary == full_summary
        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                summary_chunks[split_index:],
            )
            == composed_summary
        )
        assert (
            MergeResult.extend_conflict_summary(
                prefix_summary,
                merge_results[split_index:],
            )
            == composed_summary
        )


def test_merge_result_extend_conflict_summary_from_chunks_checkpoint_replay_associativity_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=1950)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        full_summary = MergeResult.stream_conflict_summary(full_results)

        suffix_midpoint = len(resumed_suffix_results) // 2
        left_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[:suffix_midpoint]
        )
        right_suffix_summary = MergeResult.stream_conflict_summary(
            resumed_suffix_results[suffix_midpoint:]
        )

        expected_right_assoc = MergeResult.combine_conflict_summaries(
            prefix_summary,
            MergeResult.combine_conflict_summaries(
                left_suffix_summary,
                right_suffix_summary,
            ),
        )
        expected_left_assoc = MergeResult.combine_conflict_summaries(
            MergeResult.combine_conflict_summaries(
                prefix_summary,
                left_suffix_summary,
            ),
            right_suffix_summary,
        )
        assert expected_right_assoc == expected_left_assoc == full_summary

        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                (left_suffix_summary, right_suffix_summary),
            )
            == expected_right_assoc
        )

        per_result_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in resumed_suffix_results
        )
        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                per_result_summary_chunks,
            )
            == full_summary
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_stream_conflict_summary_from_chunks_empty_and_empty_chunk_identity() -> None:
    empty_summary_chunk = (tuple(), tuple())

    assert MergeResult.stream_conflict_summary_from_chunks(()) == (tuple(), tuple())
    assert (
        MergeResult.stream_conflict_summary_from_chunks(
            (empty_summary_chunk, empty_summary_chunk),
        )
        == (tuple(), tuple())
    )

    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1960
    )
    _, merge_results = replay_stream_with_results(replay_sequence)
    split_index = len(merge_results) // 2

    base_summary = MergeResult.stream_conflict_summary(merge_results[:split_index])
    assert (
        MergeResult.extend_conflict_summary_from_chunks(
            base_summary,
            (empty_summary_chunk, empty_summary_chunk),
        )
        == base_summary
    )


def test_merge_result_stream_conflict_summary_from_chunks_matches_extend_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1970
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )
    full_summary = MergeResult.stream_conflict_summary(merge_results)

    assert MergeResult.stream_conflict_summary_from_chunks(summary_chunks) == full_summary
    assert (
        MergeResult.extend_conflict_summary_from_chunks(
            (tuple(), tuple()),
            summary_chunks,
        )
        == full_summary
    )

    for split_index in range(len(summary_chunks) + 1):
        prefix_summary = MergeResult.stream_conflict_summary_from_chunks(
            summary_chunks[:split_index]
        )
        expected_prefix_summary = MergeResult.stream_conflict_summary(
            merge_results[:split_index]
        )
        assert prefix_summary == expected_prefix_summary
        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                summary_chunks[split_index:],
            )
            == full_summary
        )


def test_merge_result_stream_conflict_summary_from_chunks_checkpoint_replay_permutations_with_empty_chunks() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=1980)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in prefix_results
        )
        resumed_suffix_chunks = tuple(
            merge_result.conflict_summary() for merge_result in resumed_suffix_results
        )
        full_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in full_results
        )

        prefix_summary = MergeResult.stream_conflict_summary_from_chunks(
            prefix_summary_chunks
        )
        full_summary = MergeResult.stream_conflict_summary_from_chunks(full_summary_chunks)
        assert prefix_summary == MergeResult.stream_conflict_summary(prefix_results)
        assert full_summary == MergeResult.stream_conflict_summary(full_results)

        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                (empty_summary_chunk,)
                + resumed_suffix_chunks
                + (empty_summary_chunk,),
            )
            == full_summary
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_stream_conflict_projection_from_chunks_empty_and_empty_chunk_identity() -> None:
    empty_projection_chunk = tuple()

    assert MergeResult.stream_conflict_signature_counts_from_chunks(()) == tuple()
    assert (
        MergeResult.stream_conflict_signature_counts_from_chunks(
            (empty_projection_chunk, empty_projection_chunk),
        )
        == tuple()
    )
    assert MergeResult.stream_conflict_code_counts_from_chunks(()) == tuple()
    assert (
        MergeResult.stream_conflict_code_counts_from_chunks(
            (empty_projection_chunk, empty_projection_chunk),
        )
        == tuple()
    )

    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=1990
    )
    _, merge_results = replay_stream_with_results(replay_sequence)
    split_index = len(merge_results) // 2

    base_signature_counts = MergeResult.stream_conflict_signature_counts(
        merge_results[:split_index]
    )
    base_code_counts = MergeResult.stream_conflict_code_counts(
        merge_results[:split_index]
    )
    assert (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            base_signature_counts,
            (empty_projection_chunk, empty_projection_chunk),
        )
        == base_signature_counts
    )
    assert (
        MergeResult.extend_conflict_code_counts_from_chunks(
            base_code_counts,
            (empty_projection_chunk, empty_projection_chunk),
        )
        == base_code_counts
    )


def test_merge_result_stream_conflict_projection_from_chunks_matches_extend_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2000
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    signature_count_chunks = tuple(
        merge_result.conflict_signature_counts() for merge_result in merge_results
    )
    code_count_chunks = tuple(
        merge_result.conflict_code_counts() for merge_result in merge_results
    )
    full_signature_counts = MergeResult.stream_conflict_signature_counts(merge_results)
    full_code_counts = MergeResult.stream_conflict_code_counts(merge_results)

    assert (
        MergeResult.stream_conflict_signature_counts_from_chunks(signature_count_chunks)
        == full_signature_counts
    )
    assert (
        MergeResult.stream_conflict_code_counts_from_chunks(code_count_chunks)
        == full_code_counts
    )
    assert (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            tuple(),
            signature_count_chunks,
        )
        == full_signature_counts
    )
    assert (
        MergeResult.extend_conflict_code_counts_from_chunks(
            tuple(),
            code_count_chunks,
        )
        == full_code_counts
    )

    for split_index in range(len(merge_results) + 1):
        prefix_signature_counts = MergeResult.stream_conflict_signature_counts_from_chunks(
            signature_count_chunks[:split_index]
        )
        prefix_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
            code_count_chunks[:split_index]
        )
        assert prefix_signature_counts == MergeResult.stream_conflict_signature_counts(
            merge_results[:split_index]
        )
        assert prefix_code_counts == MergeResult.stream_conflict_code_counts(
            merge_results[:split_index]
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_signature_counts,
                signature_count_chunks[split_index:],
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_code_counts,
                code_count_chunks[split_index:],
            )
            == full_code_counts
        )


def test_merge_result_stream_conflict_projection_from_chunks_checkpoint_replay_permutations_with_empty_chunks() -> None:
    empty_projection_chunk = tuple()
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2010)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_signature_chunks = tuple(
            merge_result.conflict_signature_counts() for merge_result in prefix_results
        )
        resumed_suffix_signature_chunks = tuple(
            merge_result.conflict_signature_counts()
            for merge_result in resumed_suffix_results
        )
        full_signature_chunks = tuple(
            merge_result.conflict_signature_counts() for merge_result in full_results
        )
        prefix_code_chunks = tuple(
            merge_result.conflict_code_counts() for merge_result in prefix_results
        )
        resumed_suffix_code_chunks = tuple(
            merge_result.conflict_code_counts() for merge_result in resumed_suffix_results
        )
        full_code_chunks = tuple(
            merge_result.conflict_code_counts() for merge_result in full_results
        )

        prefix_signature_counts = (
            MergeResult.stream_conflict_signature_counts_from_chunks(
                prefix_signature_chunks
            )
        )
        full_signature_counts = MergeResult.stream_conflict_signature_counts_from_chunks(
            full_signature_chunks
        )
        prefix_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
            prefix_code_chunks
        )
        full_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
            full_code_chunks
        )

        assert prefix_signature_counts == MergeResult.stream_conflict_signature_counts(
            prefix_results
        )
        assert full_signature_counts == MergeResult.stream_conflict_signature_counts(
            full_results
        )
        assert prefix_code_counts == MergeResult.stream_conflict_code_counts(
            prefix_results
        )
        assert full_code_counts == MergeResult.stream_conflict_code_counts(full_results)
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_signature_counts,
                (empty_projection_chunk,)
                + resumed_suffix_signature_chunks
                + (empty_projection_chunk,),
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_code_counts,
                (empty_projection_chunk,)
                + resumed_suffix_code_chunks
                + (empty_projection_chunk,),
            )
            == full_code_counts
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_from_summary_chunks_empty_and_empty_chunk_identity() -> None:
    empty_summary_chunk = (tuple(), tuple())

    assert MergeResult.stream_conflict_signature_counts_from_summary_chunks(()) == tuple()
    assert (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            (empty_summary_chunk, empty_summary_chunk),
        )
        == tuple()
    )
    assert MergeResult.stream_conflict_code_counts_from_summary_chunks(()) == tuple()
    assert (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(
            (empty_summary_chunk, empty_summary_chunk),
        )
        == tuple()
    )

    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2020
    )
    _, merge_results = replay_stream_with_results(replay_sequence)
    split_index = len(merge_results) // 2
    base_summary = MergeResult.stream_conflict_summary(merge_results[:split_index])

    assert (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_summary[0],
            (empty_summary_chunk, empty_summary_chunk),
        )
        == base_summary[0]
    )
    assert (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_summary[1],
            (empty_summary_chunk, empty_summary_chunk),
        )
        == base_summary[1]
    )


def test_merge_result_projection_from_summary_chunks_matches_projection_chunk_reducers_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2030
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )
    signature_count_chunks = tuple(summary_chunk[0] for summary_chunk in summary_chunks)
    code_count_chunks = tuple(summary_chunk[1] for summary_chunk in summary_chunks)
    full_signature_counts = MergeResult.stream_conflict_signature_counts_from_chunks(
        signature_count_chunks
    )
    full_code_counts = MergeResult.stream_conflict_code_counts_from_chunks(
        code_count_chunks
    )

    assert (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(summary_chunks)
        == full_signature_counts
    )
    assert (
        MergeResult.stream_conflict_code_counts_from_summary_chunks(summary_chunks)
        == full_code_counts
    )
    assert (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            tuple(),
            summary_chunks,
        )
        == full_signature_counts
    )
    assert (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            tuple(),
            summary_chunks,
        )
        == full_code_counts
    )

    for split_index in range(len(summary_chunks) + 1):
        prefix_signature_counts = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                summary_chunks[:split_index]
            )
        )
        prefix_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
            summary_chunks[:split_index]
        )
        assert prefix_signature_counts == (
            MergeResult.stream_conflict_signature_counts_from_chunks(
                signature_count_chunks[:split_index]
            )
        )
        assert prefix_code_counts == MergeResult.stream_conflict_code_counts_from_chunks(
            code_count_chunks[:split_index]
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                prefix_signature_counts,
                summary_chunks[split_index:],
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_summary_chunks(
                prefix_code_counts,
                summary_chunks[split_index:],
            )
            == full_code_counts
        )


def test_merge_result_projection_from_summary_chunks_checkpoint_replay_permutations_with_empty_chunks() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2040)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in prefix_results
        )
        resumed_suffix_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in resumed_suffix_results
        )
        full_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in full_results
        )

        prefix_signature_counts = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                prefix_summary_chunks
            )
        )
        full_signature_counts = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                full_summary_chunks
            )
        )
        prefix_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
            prefix_summary_chunks
        )
        full_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
            full_summary_chunks
        )

        assert prefix_signature_counts == (
            MergeResult.stream_conflict_signature_counts_from_chunks(
                tuple(summary_chunk[0] for summary_chunk in prefix_summary_chunks)
            )
        )
        assert full_signature_counts == (
            MergeResult.stream_conflict_signature_counts_from_chunks(
                tuple(summary_chunk[0] for summary_chunk in full_summary_chunks)
            )
        )
        assert prefix_code_counts == MergeResult.stream_conflict_code_counts_from_chunks(
            tuple(summary_chunk[1] for summary_chunk in prefix_summary_chunks)
        )
        assert full_code_counts == MergeResult.stream_conflict_code_counts_from_chunks(
            tuple(summary_chunk[1] for summary_chunk in full_summary_chunks)
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                prefix_signature_counts,
                (empty_summary_chunk,)
                + resumed_suffix_summary_chunks
                + (empty_summary_chunk,),
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_summary_chunks(
                prefix_code_counts,
                (empty_summary_chunk,)
                + resumed_suffix_summary_chunks
                + (empty_summary_chunk,),
            )
            == full_code_counts
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_reducers_match_summary_chunk_projection_paths_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2050
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )
    full_signature_counts = MergeResult.stream_conflict_signature_counts(merge_results)
    full_code_counts = MergeResult.stream_conflict_code_counts(merge_results)

    assert (
        full_signature_counts
        == MergeResult.stream_conflict_signature_counts_from_summary_chunks(summary_chunks)
    )
    assert (
        full_code_counts
        == MergeResult.stream_conflict_code_counts_from_summary_chunks(summary_chunks)
    )
    assert (
        MergeResult.extend_conflict_signature_counts(tuple(), merge_results)
        == full_signature_counts
    )
    assert MergeResult.extend_conflict_code_counts(tuple(), merge_results) == full_code_counts

    for split_index in range(len(merge_results) + 1):
        prefix_signature_counts = MergeResult.stream_conflict_signature_counts(
            merge_results[:split_index]
        )
        prefix_code_counts = MergeResult.stream_conflict_code_counts(
            merge_results[:split_index]
        )
        expected_prefix_signature_counts = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                summary_chunks[:split_index]
            )
        )
        expected_prefix_code_counts = (
            MergeResult.stream_conflict_code_counts_from_summary_chunks(
                summary_chunks[:split_index]
            )
        )

        assert prefix_signature_counts == expected_prefix_signature_counts
        assert prefix_code_counts == expected_prefix_code_counts
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_signature_counts,
                merge_results[split_index:],
            )
            == MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                expected_prefix_signature_counts,
                summary_chunks[split_index:],
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts(
                prefix_code_counts,
                merge_results[split_index:],
            )
            == MergeResult.extend_conflict_code_counts_from_summary_chunks(
                expected_prefix_code_counts,
                summary_chunks[split_index:],
            )
            == full_code_counts
        )


def test_merge_result_projection_reducers_checkpoint_replay_permutations_match_summary_chunk_projection_paths() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2060)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in prefix_results
        )
        resumed_suffix_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in resumed_suffix_results
        )
        full_summary_chunks = tuple(
            merge_result.conflict_summary() for merge_result in full_results
        )

        prefix_signature_counts = MergeResult.stream_conflict_signature_counts(
            prefix_results
        )
        full_signature_counts = MergeResult.stream_conflict_signature_counts(full_results)
        prefix_code_counts = MergeResult.stream_conflict_code_counts(prefix_results)
        full_code_counts = MergeResult.stream_conflict_code_counts(full_results)

        assert prefix_signature_counts == (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                prefix_summary_chunks
            )
        )
        assert full_signature_counts == (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                full_summary_chunks
            )
        )
        assert prefix_code_counts == MergeResult.stream_conflict_code_counts_from_summary_chunks(
            prefix_summary_chunks
        )
        assert full_code_counts == MergeResult.stream_conflict_code_counts_from_summary_chunks(
            full_summary_chunks
        )
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_signature_counts,
                resumed_suffix_results,
            )
            == MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                prefix_signature_counts,
                resumed_suffix_summary_chunks,
            )
            == full_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts(
                prefix_code_counts,
                resumed_suffix_results,
            )
            == MergeResult.extend_conflict_code_counts_from_summary_chunks(
                prefix_code_counts,
                resumed_suffix_summary_chunks,
            )
            == full_code_counts
        )
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_signature_counts,
                resumed_suffix_results,
            )
            == MergeResult.extend_conflict_signature_counts_from_summary_chunks(
                prefix_signature_counts,
                (empty_summary_chunk,)
                + resumed_suffix_summary_chunks
                + (empty_summary_chunk,),
            )
        )
        assert (
            MergeResult.extend_conflict_code_counts(
                prefix_code_counts,
                resumed_suffix_results,
            )
            == MergeResult.extend_conflict_code_counts_from_summary_chunks(
                prefix_code_counts,
                (empty_summary_chunk,)
                + resumed_suffix_summary_chunks
                + (empty_summary_chunk,),
            )
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_stream_conflict_summary_matches_projection_stream_reducers_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2070
    )
    _, merge_results = replay_stream_with_results(replay_sequence)
    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )

    full_summary = MergeResult.stream_conflict_summary(merge_results)
    assert full_summary == (
        MergeResult.stream_conflict_signature_counts(merge_results),
        MergeResult.stream_conflict_code_counts(merge_results),
    )
    assert full_summary == MergeResult.stream_conflict_summary_from_chunks(summary_chunks)

    for split_index in range(len(merge_results) + 1):
        prefix_results = merge_results[:split_index]
        suffix_results = merge_results[split_index:]
        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        suffix_summary = MergeResult.stream_conflict_summary(suffix_results)

        assert prefix_summary == (
            MergeResult.stream_conflict_signature_counts(prefix_results),
            MergeResult.stream_conflict_code_counts(prefix_results),
        )
        assert suffix_summary == (
            MergeResult.stream_conflict_signature_counts(suffix_results),
            MergeResult.stream_conflict_code_counts(suffix_results),
        )
        assert prefix_summary == MergeResult.stream_conflict_summary_from_chunks(
            summary_chunks[:split_index]
        )
        assert suffix_summary == MergeResult.stream_conflict_summary_from_chunks(
            summary_chunks[split_index:]
        )

        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, suffix_summary)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_summary(prefix_summary, suffix_results)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_summary[0],
                suffix_results,
            ),
            MergeResult.extend_conflict_code_counts(
                prefix_summary[1],
                suffix_results,
            ),
        ) == full_summary


def test_merge_result_stream_conflict_summary_matches_projection_stream_reducers_checkpoint_replay_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2080)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        unsplit_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged,
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        unsplit_suffix_summary = MergeResult.stream_conflict_summary(unsplit_suffix_results)
        resumed_suffix_summary = MergeResult.stream_conflict_summary(resumed_suffix_results)
        full_summary = MergeResult.stream_conflict_summary(full_results)

        assert prefix_summary == (
            MergeResult.stream_conflict_signature_counts(prefix_results),
            MergeResult.stream_conflict_code_counts(prefix_results),
        )
        assert unsplit_suffix_summary == (
            MergeResult.stream_conflict_signature_counts(unsplit_suffix_results),
            MergeResult.stream_conflict_code_counts(unsplit_suffix_results),
        )
        assert resumed_suffix_summary == (
            MergeResult.stream_conflict_signature_counts(resumed_suffix_results),
            MergeResult.stream_conflict_code_counts(resumed_suffix_results),
        )
        assert full_summary == (
            MergeResult.stream_conflict_signature_counts(full_results),
            MergeResult.stream_conflict_code_counts(full_results),
        )
        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, unsplit_suffix_summary)
            == full_summary
        )
        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, resumed_suffix_summary)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_summary(prefix_summary, unsplit_suffix_results)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_summary(prefix_summary, resumed_suffix_results)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_summary[0],
                unsplit_suffix_results,
            ),
            MergeResult.extend_conflict_code_counts(
                prefix_summary[1],
                unsplit_suffix_results,
            ),
        ) == full_summary
        assert (
            MergeResult.extend_conflict_signature_counts(
                prefix_summary[0],
                resumed_suffix_results,
            ),
            MergeResult.extend_conflict_code_counts(
                prefix_summary[1],
                resumed_suffix_results,
            ),
        ) == full_summary
        assert (
            resumed_merged.relation_state_signatures()
            == unsplit_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == unsplit_merged.revision_state_signatures()
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_chunk_stream_one_shot_parity_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2090
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    summary_chunks = tuple(
        merge_result.conflict_summary() for merge_result in merge_results
    )
    full_chunks = (empty_summary_chunk,) + summary_chunks + (empty_summary_chunk,)
    full_summary = assert_summary_chunk_stream_one_shot_parity(full_chunks)

    for split_index in range(len(summary_chunks) + 1):
        prefix_chunks = (
            (empty_summary_chunk,)
            + summary_chunks[:split_index]
            + (empty_summary_chunk,)
        )
        suffix_chunks = (
            (empty_summary_chunk,)
            + summary_chunks[split_index:]
            + (empty_summary_chunk,)
        )
        prefix_summary = assert_summary_chunk_stream_one_shot_parity(prefix_chunks)
        suffix_summary = assert_summary_chunk_stream_one_shot_parity(suffix_chunks)

        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, suffix_summary)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                OneShotIterable(suffix_chunks),
            )
            == full_summary
        )


def test_merge_result_summary_chunk_stream_one_shot_parity_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2100)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        resumed_suffix_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        full_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in full_results)
            + (empty_summary_chunk,)
        )

        prefix_summary = assert_summary_chunk_stream_one_shot_parity(prefix_chunks)
        resumed_suffix_summary = assert_summary_chunk_stream_one_shot_parity(
            resumed_suffix_chunks
        )
        full_summary = assert_summary_chunk_stream_one_shot_parity(full_chunks)

        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, resumed_suffix_summary)
            == full_summary
        )
        assert (
            MergeResult.extend_conflict_summary_from_chunks(
                prefix_summary,
                OneShotIterable(resumed_suffix_chunks),
            )
            == full_summary
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_chunk_stream_one_shot_parity_across_splits() -> None:
    empty_projection_chunk = tuple()
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2110
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    signature_count_chunks = tuple(
        merge_result.conflict_signature_counts() for merge_result in merge_results
    )
    code_count_chunks = tuple(
        merge_result.conflict_code_counts() for merge_result in merge_results
    )

    full_signature_chunks = (
        (empty_projection_chunk,)
        + signature_count_chunks
        + (empty_projection_chunk,)
    )
    full_code_chunks = (empty_projection_chunk,) + code_count_chunks + (empty_projection_chunk,)
    full_projection = assert_projection_chunk_stream_one_shot_parity(
        full_signature_chunks,
        full_code_chunks,
    )

    assert full_projection == (
        MergeResult.stream_conflict_signature_counts(merge_results),
        MergeResult.stream_conflict_code_counts(merge_results),
    )

    for split_index in range(len(merge_results) + 1):
        prefix_signature_chunks = (
            (empty_projection_chunk,)
            + signature_count_chunks[:split_index]
            + (empty_projection_chunk,)
        )
        suffix_signature_chunks = (
            (empty_projection_chunk,)
            + signature_count_chunks[split_index:]
            + (empty_projection_chunk,)
        )
        prefix_code_chunks = (
            (empty_projection_chunk,) + code_count_chunks[:split_index] + (empty_projection_chunk,)
        )
        suffix_code_chunks = (
            (empty_projection_chunk,) + code_count_chunks[split_index:] + (empty_projection_chunk,)
        )

        prefix_projection = assert_projection_chunk_stream_one_shot_parity(
            prefix_signature_chunks,
            prefix_code_chunks,
        )
        suffix_projection = assert_projection_chunk_stream_one_shot_parity(
            suffix_signature_chunks,
            suffix_code_chunks,
        )

        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection[0],
                suffix_projection[0],
            )
            == full_projection[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection[1],
                suffix_projection[1],
            )
            == full_projection[1]
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_projection[0],
                OneShotIterable(suffix_signature_chunks),
            )
            == full_projection[0]
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_projection[1],
                OneShotIterable(suffix_code_chunks),
            )
            == full_projection[1]
        )


def test_merge_result_projection_chunk_stream_one_shot_parity_checkpoint_permutations() -> None:
    empty_projection_chunk = tuple()
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2120)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_signature_chunks = (
            (empty_projection_chunk,)
            + tuple(
                merge_result.conflict_signature_counts() for merge_result in prefix_results
            )
            + (empty_projection_chunk,)
        )
        resumed_suffix_signature_chunks = (
            (empty_projection_chunk,)
            + tuple(
                merge_result.conflict_signature_counts()
                for merge_result in resumed_suffix_results
            )
            + (empty_projection_chunk,)
        )
        full_signature_chunks = (
            (empty_projection_chunk,)
            + tuple(merge_result.conflict_signature_counts() for merge_result in full_results)
            + (empty_projection_chunk,)
        )
        prefix_code_chunks = (
            (empty_projection_chunk,)
            + tuple(merge_result.conflict_code_counts() for merge_result in prefix_results)
            + (empty_projection_chunk,)
        )
        resumed_suffix_code_chunks = (
            (empty_projection_chunk,)
            + tuple(
                merge_result.conflict_code_counts() for merge_result in resumed_suffix_results
            )
            + (empty_projection_chunk,)
        )
        full_code_chunks = (
            (empty_projection_chunk,)
            + tuple(merge_result.conflict_code_counts() for merge_result in full_results)
            + (empty_projection_chunk,)
        )

        prefix_projection = assert_projection_chunk_stream_one_shot_parity(
            prefix_signature_chunks,
            prefix_code_chunks,
        )
        resumed_suffix_projection = assert_projection_chunk_stream_one_shot_parity(
            resumed_suffix_signature_chunks,
            resumed_suffix_code_chunks,
        )
        full_projection = assert_projection_chunk_stream_one_shot_parity(
            full_signature_chunks,
            full_code_chunks,
        )

        assert full_projection == (
            MergeResult.stream_conflict_signature_counts(full_results),
            MergeResult.stream_conflict_code_counts(full_results),
        )
        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection[0],
                resumed_suffix_projection[0],
            )
            == full_projection[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection[1],
                resumed_suffix_projection[1],
            )
            == full_projection[1]
        )
        assert (
            MergeResult.extend_conflict_signature_counts_from_chunks(
                prefix_projection[0],
                OneShotIterable(resumed_suffix_signature_chunks),
            )
            == full_projection[0]
        )
        assert (
            MergeResult.extend_conflict_code_counts_from_chunks(
                prefix_projection[1],
                OneShotIterable(resumed_suffix_code_chunks),
            )
            == full_projection[1]
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_from_summary_chunk_extension_one_shot_parity_nonempty_base_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2130
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    summary_chunks = tuple(merge_result.conflict_summary() for merge_result in merge_results)
    full_summary_chunks = (
        (empty_summary_chunk,) + summary_chunks + (empty_summary_chunk,)
    )
    full_projection = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(full_summary_chunks),
        MergeResult.stream_conflict_code_counts_from_summary_chunks(full_summary_chunks),
    )

    nonempty_base_split_count = 0
    for split_index in range(len(summary_chunks) + 1):
        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + summary_chunks[:split_index]
            + (empty_summary_chunk,)
        )
        suffix_summary_chunks = (
            (empty_summary_chunk,)
            + summary_chunks[split_index:]
            + (empty_summary_chunk,)
        )
        prefix_projection = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                prefix_summary_chunks
            ),
            MergeResult.stream_conflict_code_counts_from_summary_chunks(
                prefix_summary_chunks
            ),
        )
        if not prefix_projection[0] or not prefix_projection[1]:
            continue

        nonempty_base_split_count += 1
        extended_projection = assert_summary_chunk_projection_extension_one_shot_parity(
            base_signature_counts=prefix_projection[0],
            base_code_counts=prefix_projection[1],
            summary_chunks=suffix_summary_chunks,
        )
        assert extended_projection == full_projection

    assert nonempty_base_split_count > 0


def test_merge_result_projection_from_summary_chunk_extension_one_shot_parity_nonempty_base_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2140)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        prefix_projection = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                prefix_summary_chunks
            ),
            MergeResult.stream_conflict_code_counts_from_summary_chunks(
                prefix_summary_chunks
            ),
        )
        if not prefix_projection[0] or not prefix_projection[1]:
            for fallback_split_index in range(1, len(ordered_replicas)):
                if fallback_split_index == split_index:
                    continue
                fallback_prefix_merged, fallback_prefix_results = replay_stream_with_results(
                    ordered_replicas[:fallback_split_index]
                )
                fallback_prefix_summary_chunks = (
                    (empty_summary_chunk,)
                    + tuple(
                        merge_result.conflict_summary()
                        for merge_result in fallback_prefix_results
                    )
                    + (empty_summary_chunk,)
                )
                fallback_prefix_projection = (
                    MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                        fallback_prefix_summary_chunks
                    ),
                    MergeResult.stream_conflict_code_counts_from_summary_chunks(
                        fallback_prefix_summary_chunks
                    ),
                )
                if fallback_prefix_projection[0] and fallback_prefix_projection[1]:
                    split_index = fallback_split_index
                    prefix_merged = fallback_prefix_merged
                    prefix_projection = fallback_prefix_projection
                    break

        assert prefix_projection[0]
        assert prefix_projection[1]

        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        resumed_suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        full_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in full_results)
            + (empty_summary_chunk,)
        )
        full_projection = (
            MergeResult.stream_conflict_signature_counts_from_summary_chunks(
                full_summary_chunks
            ),
            MergeResult.stream_conflict_code_counts_from_summary_chunks(full_summary_chunks),
        )

        resumed_projection = assert_summary_chunk_projection_extension_one_shot_parity(
            base_signature_counts=prefix_projection[0],
            base_code_counts=prefix_projection[1],
            summary_chunks=resumed_suffix_summary_chunks,
        )

        assert resumed_projection == full_projection
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_extension_api_one_shot_parity_nonempty_base_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2150
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_projection = (
        MergeResult.stream_conflict_signature_counts(merge_results),
        MergeResult.stream_conflict_code_counts(merge_results),
    )

    nonempty_base_split_count = 0
    for split_index in range(len(merge_results) + 1):
        prefix_results = merge_results[:split_index]
        suffix_results = merge_results[split_index:]
        prefix_projection = (
            MergeResult.stream_conflict_signature_counts(prefix_results),
            MergeResult.stream_conflict_code_counts(prefix_results),
        )

        if not prefix_projection[0] or not prefix_projection[1]:
            continue

        nonempty_base_split_count += 1
        suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in suffix_results)
            + (empty_summary_chunk,)
        )
        extended_projection = assert_merge_result_projection_extension_one_shot_parity(
            base_signature_counts=prefix_projection[0],
            base_code_counts=prefix_projection[1],
            merge_results=suffix_results,
            summary_chunks=suffix_summary_chunks,
        )
        assert extended_projection == full_projection

    assert nonempty_base_split_count > 0


def test_merge_result_projection_extension_api_one_shot_parity_nonempty_base_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2160)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        prefix_projection = (
            MergeResult.stream_conflict_signature_counts(prefix_results),
            MergeResult.stream_conflict_code_counts(prefix_results),
        )
        if not prefix_projection[0] or not prefix_projection[1]:
            for fallback_split_index in range(1, len(ordered_replicas)):
                if fallback_split_index == split_index:
                    continue
                fallback_prefix_merged, fallback_prefix_results = replay_stream_with_results(
                    ordered_replicas[:fallback_split_index]
                )
                fallback_prefix_projection = (
                    MergeResult.stream_conflict_signature_counts(
                        fallback_prefix_results
                    ),
                    MergeResult.stream_conflict_code_counts(fallback_prefix_results),
                )
                if fallback_prefix_projection[0] and fallback_prefix_projection[1]:
                    split_index = fallback_split_index
                    prefix_merged = fallback_prefix_merged
                    prefix_projection = fallback_prefix_projection
                    break

        assert prefix_projection[0]
        assert prefix_projection[1]

        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        resumed_suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        resumed_projection = assert_merge_result_projection_extension_one_shot_parity(
            base_signature_counts=prefix_projection[0],
            base_code_counts=prefix_projection[1],
            merge_results=resumed_suffix_results,
            summary_chunks=resumed_suffix_summary_chunks,
        )

        full_projection = (
            MergeResult.stream_conflict_signature_counts(full_results),
            MergeResult.stream_conflict_code_counts(full_results),
        )
        assert resumed_projection == full_projection
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_extension_api_one_shot_parity_nonempty_base_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2170
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary = MergeResult.stream_conflict_summary(merge_results)

    nonempty_base_split_count = 0
    for split_index in range(len(merge_results) + 1):
        prefix_results = merge_results[:split_index]
        suffix_results = merge_results[split_index:]
        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        if not prefix_summary[0] or not prefix_summary[1]:
            continue

        nonempty_base_split_count += 1
        suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in suffix_results)
            + (empty_summary_chunk,)
        )
        extended_summary = assert_merge_result_summary_extension_one_shot_parity(
            base_summary=prefix_summary,
            merge_results=suffix_results,
            summary_chunks=suffix_summary_chunks,
        )
        assert extended_summary == full_summary

    assert nonempty_base_split_count > 0


def test_merge_result_summary_extension_api_one_shot_parity_nonempty_base_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2180)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        prefix_summary = MergeResult.stream_conflict_summary(prefix_results)
        if not prefix_summary[0] or not prefix_summary[1]:
            for fallback_split_index in range(1, len(ordered_replicas)):
                if fallback_split_index == split_index:
                    continue
                fallback_prefix_merged, fallback_prefix_results = replay_stream_with_results(
                    ordered_replicas[:fallback_split_index]
                )
                fallback_prefix_summary = MergeResult.stream_conflict_summary(
                    fallback_prefix_results
                )
                if fallback_prefix_summary[0] and fallback_prefix_summary[1]:
                    split_index = fallback_split_index
                    prefix_merged = fallback_prefix_merged
                    prefix_summary = fallback_prefix_summary
                    break

        assert prefix_summary[0]
        assert prefix_summary[1]

        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        resumed_suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        resumed_summary = assert_merge_result_summary_extension_one_shot_parity(
            base_summary=prefix_summary,
            merge_results=resumed_suffix_results,
            summary_chunks=resumed_suffix_summary_chunks,
        )

        full_summary = MergeResult.stream_conflict_summary(full_results)
        assert resumed_summary == full_summary
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_stream_api_one_shot_parity_with_empty_chunk_path_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2190
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary_chunks = (
        (empty_summary_chunk,)
        + tuple(merge_result.conflict_summary() for merge_result in merge_results)
        + (empty_summary_chunk,)
    )
    full_summary = assert_merge_result_summary_stream_one_shot_parity(
        merge_results=merge_results,
        summary_chunks=full_summary_chunks,
    )

    for split_index in range(len(merge_results) + 1):
        prefix_results = merge_results[:split_index]
        suffix_results = merge_results[split_index:]
        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in suffix_results)
            + (empty_summary_chunk,)
        )
        prefix_summary = assert_merge_result_summary_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=prefix_summary_chunks,
        )
        suffix_summary = assert_merge_result_summary_stream_one_shot_parity(
            merge_results=suffix_results,
            summary_chunks=suffix_summary_chunks,
        )

        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, suffix_summary)
            == full_summary
        )


def test_merge_result_summary_stream_api_one_shot_parity_with_empty_chunk_path_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2200)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        resumed_suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        full_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in full_results)
            + (empty_summary_chunk,)
        )

        prefix_summary = assert_merge_result_summary_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=prefix_summary_chunks,
        )
        resumed_suffix_summary = assert_merge_result_summary_stream_one_shot_parity(
            merge_results=resumed_suffix_results,
            summary_chunks=resumed_suffix_summary_chunks,
        )
        full_summary = assert_merge_result_summary_stream_one_shot_parity(
            merge_results=full_results,
            summary_chunks=full_summary_chunks,
        )

        assert (
            MergeResult.combine_conflict_summaries(prefix_summary, resumed_suffix_summary)
            == full_summary
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_composition_api_one_shot_continuation_composition_with_empty_chunk_path_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2210
    )
    full_merged, full_results = replay_stream_with_results(replay_sequence)

    for split_index in range(1, len(replay_sequence)):
        prefix_merged, prefix_results = replay_stream_with_results(
            replay_sequence[:split_index]
        )
        unsplit_merged, unsplit_continuation_results = replay_stream_with_results(
            replay_sequence[split_index:],
            start=prefix_merged,
        )

        assert_merge_result_summary_continuation_composition_one_shot_parity(
            prefix_results=prefix_results,
            continuation_results=unsplit_continuation_results,
            full_results=full_results,
        )
        assert (
            unsplit_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_composition_api_one_shot_continuation_composition_with_empty_chunk_path_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2220)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        unsplit_merged, unsplit_continuation_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged,
        )
        resumed_merged, resumed_continuation_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        unsplit_composed_summary = (
            assert_merge_result_summary_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                continuation_results=unsplit_continuation_results,
                full_results=full_results,
            )
        )
        resumed_composed_summary = (
            assert_merge_result_summary_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                continuation_results=resumed_continuation_results,
                full_results=full_results,
            )
        )

        assert unsplit_composed_summary == resumed_composed_summary
        assert (
            unsplit_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_summary_composition_api_one_shot_three_way_continuation_associativity_with_empty_chunk_path_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2250
    )
    full_merged, full_results = replay_stream_with_results(replay_sequence)

    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )

            composed_summary = (
                assert_merge_result_summary_three_way_continuation_composition_one_shot_parity(
                    prefix_results=prefix_results,
                    middle_results=middle_results,
                    suffix_results=suffix_results,
                    full_results=full_results,
                )
            )

            assert composed_summary == MergeResult.stream_conflict_summary(full_results)
            assert (
                suffix_merged.relation_state_signatures()
                == full_merged.relation_state_signatures()
            )
            assert (
                suffix_merged.revision_state_signatures()
                == full_merged.revision_state_signatures()
            )


def test_merge_result_summary_composition_api_one_shot_three_way_continuation_associativity_with_empty_chunk_path_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2260)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        unsplit_composed_summary = (
            assert_merge_result_summary_three_way_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=unsplit_middle_results,
                suffix_results=unsplit_suffix_results,
                full_results=full_results,
            )
        )
        resumed_composed_summary = (
            assert_merge_result_summary_three_way_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=resumed_middle_results,
                suffix_results=resumed_suffix_results,
                full_results=full_results,
            )
        )

        assert unsplit_composed_summary == resumed_composed_summary
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_stream_api_one_shot_parity_with_empty_chunk_path_across_splits() -> None:
    empty_summary_chunk = (tuple(), tuple())
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2210
    )
    _, merge_results = replay_stream_with_results(replay_sequence)

    full_summary_chunks = (
        (empty_summary_chunk,)
        + tuple(merge_result.conflict_summary() for merge_result in merge_results)
        + (empty_summary_chunk,)
    )
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=merge_results,
        summary_chunks=full_summary_chunks,
    )

    for split_index in range(len(merge_results) + 1):
        prefix_results = merge_results[:split_index]
        suffix_results = merge_results[split_index:]
        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in suffix_results)
            + (empty_summary_chunk,)
        )
        prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=prefix_summary_chunks,
        )
        suffix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=suffix_results,
            summary_chunks=suffix_summary_chunks,
        )

        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection_counts[0],
                suffix_projection_counts[0],
            )
            == full_projection_counts[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection_counts[1],
                suffix_projection_counts[1],
            )
            == full_projection_counts[1]
        )


def test_merge_result_projection_stream_api_one_shot_parity_with_empty_chunk_path_checkpoint_permutations() -> None:
    empty_summary_chunk = (tuple(), tuple())
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2220)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        resumed_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in prefix_results)
            + (empty_summary_chunk,)
        )
        resumed_suffix_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(
                merge_result.conflict_summary() for merge_result in resumed_suffix_results
            )
            + (empty_summary_chunk,)
        )
        full_summary_chunks = (
            (empty_summary_chunk,)
            + tuple(merge_result.conflict_summary() for merge_result in full_results)
            + (empty_summary_chunk,)
        )

        prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=prefix_summary_chunks,
        )
        resumed_suffix_projection_counts = (
            assert_merge_result_projection_stream_one_shot_parity(
                merge_results=resumed_suffix_results,
                summary_chunks=resumed_suffix_summary_chunks,
            )
        )
        full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=full_results,
            summary_chunks=full_summary_chunks,
        )

        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection_counts[0],
                resumed_suffix_projection_counts[0],
            )
            == full_projection_counts[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection_counts[1],
                resumed_suffix_projection_counts[1],
            )
            == full_projection_counts[1]
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_stream_api_one_shot_continuation_composition_with_empty_chunk_path_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2230
    )
    full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )

    for split_index in range(1, len(replay_sequence)):
        prefix_merged, prefix_results = replay_stream_with_results(
            replay_sequence[:split_index]
        )
        unsplit_merged, unsplit_continuation_results = replay_stream_with_results(
            replay_sequence[split_index:],
            start=prefix_merged,
        )

        prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
        )
        unsplit_continuation_projection_counts = (
            assert_merge_result_projection_stream_one_shot_parity(
                merge_results=unsplit_continuation_results,
                summary_chunks=conflict_summary_chunks_with_empty_path(
                    unsplit_continuation_results
                ),
            )
        )

        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection_counts[0],
                unsplit_continuation_projection_counts[0],
            )
            == full_projection_counts[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection_counts[1],
                unsplit_continuation_projection_counts[1],
            )
            == full_projection_counts[1]
        )
        assert (
            unsplit_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_stream_api_one_shot_continuation_composition_with_empty_chunk_path_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2240)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        split_index = len(ordered_replicas) // 2
        if split_index == 0:
            split_index = 1

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:split_index]
        )
        unsplit_merged, unsplit_continuation_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged,
        )
        resumed_merged, resumed_continuation_results = replay_stream_with_results(
            ordered_replicas[split_index:],
            start=prefix_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        prefix_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=prefix_results,
            summary_chunks=conflict_summary_chunks_with_empty_path(prefix_results),
        )
        unsplit_continuation_projection_counts = (
            assert_merge_result_projection_stream_one_shot_parity(
                merge_results=unsplit_continuation_results,
                summary_chunks=conflict_summary_chunks_with_empty_path(
                    unsplit_continuation_results
                ),
            )
        )
        resumed_continuation_projection_counts = (
            assert_merge_result_projection_stream_one_shot_parity(
                merge_results=resumed_continuation_results,
                summary_chunks=conflict_summary_chunks_with_empty_path(
                    resumed_continuation_results
                ),
            )
        )
        full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
            merge_results=full_results,
            summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
        )

        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection_counts[0],
                unsplit_continuation_projection_counts[0],
            )
            == full_projection_counts[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection_counts[1],
                unsplit_continuation_projection_counts[1],
            )
            == full_projection_counts[1]
        )
        assert (
            MergeResult.combine_conflict_signature_counts(
                prefix_projection_counts[0],
                resumed_continuation_projection_counts[0],
            )
            == full_projection_counts[0]
        )
        assert (
            MergeResult.combine_conflict_code_counts(
                prefix_projection_counts[1],
                resumed_continuation_projection_counts[1],
            )
            == full_projection_counts[1]
        )
        assert (
            unsplit_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert (
            unsplit_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_stream_api_one_shot_three_way_continuation_associativity_with_empty_chunk_path_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2270
    )
    full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )

    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )

            composed_projection_counts = (
                assert_merge_result_projection_three_way_continuation_composition_one_shot_parity(
                    prefix_results=prefix_results,
                    middle_results=middle_results,
                    suffix_results=suffix_results,
                    full_results=full_results,
                )
            )

            assert composed_projection_counts == full_projection_counts
            assert (
                suffix_merged.relation_state_signatures()
                == full_merged.relation_state_signatures()
            )
            assert (
                suffix_merged.revision_state_signatures()
                == full_merged.revision_state_signatures()
            )


def test_merge_result_projection_stream_api_one_shot_three_way_continuation_associativity_with_empty_chunk_path_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2280)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        unsplit_projection_counts = (
            assert_merge_result_projection_three_way_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=unsplit_middle_results,
                suffix_results=unsplit_suffix_results,
                full_results=full_results,
            )
        )
        resumed_projection_counts = (
            assert_merge_result_projection_three_way_continuation_composition_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=resumed_middle_results,
                suffix_results=resumed_suffix_results,
                full_results=full_results,
            )
        )

        assert unsplit_projection_counts == resumed_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def test_merge_result_projection_extension_api_one_shot_three_way_continuation_associativity_with_nonempty_base_prefix_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2290
    )
    full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = assert_merge_result_projection_stream_one_shot_parity(
        merge_results=full_results,
        summary_chunks=conflict_summary_chunks_with_empty_path(full_results),
    )

    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )

            extended_projection_counts = (
                assert_merge_result_projection_extension_three_way_continuation_associativity_one_shot_parity(
                    prefix_results=prefix_results,
                    middle_results=middle_results,
                    suffix_results=suffix_results,
                    full_results=full_results,
                )
            )

            assert extended_projection_counts == full_projection_counts
            assert (
                suffix_merged.relation_state_signatures()
                == full_merged.relation_state_signatures()
            )
            assert (
                suffix_merged.revision_state_signatures()
                == full_merged.revision_state_signatures()
            )


def test_merge_result_projection_extension_api_one_shot_three_way_continuation_associativity_with_nonempty_base_prefix_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2300)

    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        unsplit_projection_counts = (
            assert_merge_result_projection_extension_three_way_continuation_associativity_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=unsplit_middle_results,
                suffix_results=unsplit_suffix_results,
                full_results=full_results,
            )
        )
        resumed_projection_counts = (
            assert_merge_result_projection_extension_three_way_continuation_associativity_one_shot_parity(
                prefix_results=prefix_results,
                middle_results=resumed_middle_results,
                suffix_results=resumed_suffix_results,
                full_results=full_results,
            )
        )

        assert unsplit_projection_counts == resumed_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )


def precompose_projection_continuation_with_empty_chunks(
    continuation_results: tuple,
) -> tuple[tuple, tuple]:
    signature_count_chunks = (
        (tuple(),)
        + tuple(
            merge_result.conflict_signature_counts()
            for merge_result in continuation_results
        )
        + (tuple(),)
    )
    code_count_chunks = (
        (tuple(),)
        + tuple(merge_result.conflict_code_counts() for merge_result in continuation_results)
        + (tuple(),)
    )

    materialized_signature_counts = MergeResult.combine_conflict_signature_counts_from_chunks(
        signature_count_chunks
    )
    one_shot_signature_counts = MergeResult.combine_conflict_signature_counts_from_chunks(
        OneShotIterable(signature_count_chunks)
    )
    materialized_code_counts = MergeResult.combine_conflict_code_counts_from_chunks(
        code_count_chunks
    )
    one_shot_code_counts = MergeResult.combine_conflict_code_counts_from_chunks(
        OneShotIterable(code_count_chunks)
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    return (
        materialized_signature_counts,
        materialized_code_counts,
    )


def precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
    continuation_results: tuple,
) -> tuple[tuple, tuple]:
    summary_chunks = conflict_summary_chunks_with_empty_path(continuation_results)
    materialized_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(summary_chunks)
    )
    one_shot_signature_counts = (
        MergeResult.stream_conflict_signature_counts_from_summary_chunks(
            OneShotIterable(summary_chunks)
        )
    )
    materialized_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
        summary_chunks
    )
    one_shot_code_counts = MergeResult.stream_conflict_code_counts_from_summary_chunks(
        OneShotIterable(summary_chunks)
    )
    materialized_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            tuple(),
            summary_chunks,
        )
    )
    one_shot_extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            tuple(),
            OneShotIterable(summary_chunks),
        )
    )
    materialized_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            tuple(),
            summary_chunks,
        )
    )
    one_shot_extended_code_counts = (
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            tuple(),
            OneShotIterable(summary_chunks),
        )
    )

    assert one_shot_signature_counts == materialized_signature_counts
    assert one_shot_code_counts == materialized_code_counts
    assert materialized_extended_signature_counts == materialized_signature_counts
    assert one_shot_extended_signature_counts == materialized_signature_counts
    assert materialized_extended_code_counts == materialized_code_counts
    assert one_shot_extended_code_counts == materialized_code_counts
    return (materialized_signature_counts, materialized_code_counts)


def precompose_summary_continuation_with_empty_chunks(
    continuation_results: tuple,
) -> tuple[tuple, tuple]:
    summary_chunks = conflict_summary_chunks_with_empty_path(continuation_results)
    materialized_summary = MergeResult.combine_conflict_summaries_from_chunks(
        summary_chunks
    )
    one_shot_summary = MergeResult.combine_conflict_summaries_from_chunks(
        OneShotIterable(summary_chunks)
    )
    assert one_shot_summary == materialized_summary
    return materialized_summary


def test_merge_result_projection_precomposed_extension_empty_continuation_identity_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2330
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_signature_counts = MergeResult.stream_conflict_signature_counts(full_results)
    full_code_counts = MergeResult.stream_conflict_code_counts(full_results)

    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            base_signature_counts = MergeResult.stream_conflict_signature_counts(
                prefix_results
            )
            base_code_counts = MergeResult.stream_conflict_code_counts(prefix_results)
            if not base_signature_counts or not base_code_counts:
                continue

            nonempty_base_split_count += 1
            continuation_signature_counts, continuation_code_counts = (
                precompose_projection_continuation_with_empty_chunks(
                    continuation_results
                )
            )
            middle_signature_counts, middle_code_counts = (
                precompose_projection_continuation_with_empty_chunks(middle_results)
            )
            suffix_signature_counts, suffix_code_counts = (
                precompose_projection_continuation_with_empty_chunks(suffix_results)
            )

            recomposed_continuation_signature_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_signature_counts,
                    suffix_signature_counts,
                )
            )
            recomposed_continuation_code_counts = MergeResult.combine_conflict_code_counts(
                middle_code_counts,
                suffix_code_counts,
            )

            assert (
                recomposed_continuation_signature_counts
                == continuation_signature_counts
            )
            assert recomposed_continuation_code_counts == continuation_code_counts

            extended_signature_counts = (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    base_signature_counts,
                    continuation_signature_counts,
                )
            )
            recomposed_extended_signature_counts = (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    base_signature_counts,
                    recomposed_continuation_signature_counts,
                )
            )
            extended_code_counts = (
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    base_code_counts,
                    continuation_code_counts,
                )
            )
            recomposed_extended_code_counts = (
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    base_code_counts,
                    recomposed_continuation_code_counts,
                )
            )

            assert extended_signature_counts == recomposed_extended_signature_counts
            assert extended_code_counts == recomposed_extended_code_counts
            assert extended_signature_counts == full_signature_counts
            assert extended_code_counts == full_code_counts
            assert (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    base_signature_counts,
                    tuple(),
                )
                == base_signature_counts
            )
            assert (
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    base_code_counts,
                    tuple(),
                )
                == base_code_counts
            )
            assert (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    extended_signature_counts,
                    tuple(),
                )
                == extended_signature_counts
            )
            assert (
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    extended_code_counts,
                    tuple(),
                )
                == extended_code_counts
            )

    assert nonempty_base_split_count > 0


def test_merge_result_projection_precomposed_extension_empty_continuation_identity_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2340)

    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_signature_counts = MergeResult.stream_conflict_signature_counts(prefix_results)
        base_code_counts = MergeResult.stream_conflict_code_counts(prefix_results)
        if not base_signature_counts or not base_code_counts:
            continue
        nonempty_base_permutation_count += 1

        full_signature_counts = MergeResult.stream_conflict_signature_counts(full_results)
        full_code_counts = MergeResult.stream_conflict_code_counts(full_results)
        unsplit_continuation_signature_counts, unsplit_continuation_code_counts = (
            precompose_projection_continuation_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_signature_counts, resumed_continuation_code_counts = (
            precompose_projection_continuation_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )

        unsplit_extended_signature_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_signature_counts,
                unsplit_continuation_signature_counts,
            )
        )
        resumed_extended_signature_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_signature_counts,
                resumed_continuation_signature_counts,
            )
        )
        unsplit_extended_code_counts = (
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_code_counts,
                unsplit_continuation_code_counts,
            )
        )
        resumed_extended_code_counts = (
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_code_counts,
                resumed_continuation_code_counts,
            )
        )

        assert unsplit_extended_signature_counts == resumed_extended_signature_counts
        assert unsplit_extended_code_counts == resumed_extended_code_counts
        assert unsplit_extended_signature_counts == full_signature_counts
        assert unsplit_extended_code_counts == full_code_counts
        assert (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_signature_counts,
                tuple(),
            )
            == base_signature_counts
        )
        assert (
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_code_counts,
                tuple(),
            )
            == base_code_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_base_permutation_count > 0


def assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
    *,
    base_projection_counts: tuple[tuple, tuple],
    continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_projection_chunk = tuple()
    base_signature_counts, base_code_counts = base_projection_counts
    continuation_signature_counts, continuation_code_counts = (
        continuation_projection_counts
    )

    signature_composition_chunks = (
        (empty_projection_chunk,)
        + (base_signature_counts, continuation_signature_counts)
        + (empty_projection_chunk,)
    )
    signature_extension_chunks = (
        empty_projection_chunk,
        continuation_signature_counts,
        empty_projection_chunk,
    )
    code_composition_chunks = (
        (empty_projection_chunk,)
        + (base_code_counts, continuation_code_counts)
        + (empty_projection_chunk,)
    )
    code_extension_chunks = (
        empty_projection_chunk,
        continuation_code_counts,
        empty_projection_chunk,
    )

    composed_signature_counts = MergeResult.combine_conflict_signature_counts(
        base_signature_counts,
        continuation_signature_counts,
    )
    materialized_composed_signature_counts_from_chunks = (
        MergeResult.combine_conflict_signature_counts_from_chunks(
            signature_composition_chunks
        )
    )
    one_shot_composed_signature_counts_from_chunks = (
        MergeResult.combine_conflict_signature_counts_from_chunks(
            OneShotIterable(signature_composition_chunks)
        )
    )
    extended_signature_counts = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_signature_counts,
            continuation_signature_counts,
        )
    )
    materialized_extended_signature_counts_from_chunks = (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            base_signature_counts,
            signature_extension_chunks,
        )
    )
    one_shot_extended_signature_counts_from_chunks = (
        MergeResult.extend_conflict_signature_counts_from_chunks(
            base_signature_counts,
            OneShotIterable(signature_extension_chunks),
        )
    )

    composed_code_counts = MergeResult.combine_conflict_code_counts(
        base_code_counts,
        continuation_code_counts,
    )
    materialized_composed_code_counts_from_chunks = (
        MergeResult.combine_conflict_code_counts_from_chunks(code_composition_chunks)
    )
    one_shot_composed_code_counts_from_chunks = (
        MergeResult.combine_conflict_code_counts_from_chunks(
            OneShotIterable(code_composition_chunks)
        )
    )
    extended_code_counts = (
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_code_counts,
            continuation_code_counts,
        )
    )
    materialized_extended_code_counts_from_chunks = (
        MergeResult.extend_conflict_code_counts_from_chunks(
            base_code_counts,
            code_extension_chunks,
        )
    )
    one_shot_extended_code_counts_from_chunks = (
        MergeResult.extend_conflict_code_counts_from_chunks(
            base_code_counts,
            OneShotIterable(code_extension_chunks),
        )
    )

    assert materialized_composed_signature_counts_from_chunks == composed_signature_counts
    assert one_shot_composed_signature_counts_from_chunks == composed_signature_counts
    assert extended_signature_counts == composed_signature_counts
    assert materialized_extended_signature_counts_from_chunks == composed_signature_counts
    assert one_shot_extended_signature_counts_from_chunks == composed_signature_counts
    assert materialized_composed_code_counts_from_chunks == composed_code_counts
    assert one_shot_composed_code_counts_from_chunks == composed_code_counts
    assert extended_code_counts == composed_code_counts
    assert materialized_extended_code_counts_from_chunks == composed_code_counts
    assert one_shot_extended_code_counts_from_chunks == composed_code_counts
    return (
        extended_signature_counts,
        extended_code_counts,
    )


def test_merge_result_projection_precomposed_extension_equals_pair_combine_across_splits_with_empty_endpoints() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2390
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        MergeResult.stream_conflict_signature_counts(full_results),
        MergeResult.stream_conflict_code_counts(full_results),
    )
    full_precomposed_projection_counts = precompose_projection_continuation_with_empty_chunks(
        full_results
    )
    assert full_precomposed_projection_counts == full_projection_counts
    empty_projection_counts = precompose_projection_continuation_with_empty_chunks(tuple())

    split_count = 0
    nonempty_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            base_projection_counts = precompose_projection_continuation_with_empty_chunks(
                prefix_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_with_empty_chunks(continuation_results)
            )
            middle_projection_counts = precompose_projection_continuation_with_empty_chunks(
                middle_results
            )
            suffix_projection_counts = precompose_projection_continuation_with_empty_chunks(
                suffix_results
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )

            split_count += 1
            if (
                continuation_projection_counts[0]
                or continuation_projection_counts[1]
            ):
                nonempty_continuation_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            direct_extended_projection_counts = (
                assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert direct_extended_projection_counts == recomposed_extended_projection_counts
            assert direct_extended_projection_counts == full_projection_counts

    assert (
        assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
            base_projection_counts=empty_projection_counts,
            continuation_projection_counts=full_precomposed_projection_counts,
        )
        == full_projection_counts
    )
    assert (
        assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
            base_projection_counts=full_precomposed_projection_counts,
            continuation_projection_counts=empty_projection_counts,
        )
        == full_projection_counts
    )
    assert split_count > 0
    assert nonempty_continuation_split_count > 0


def test_merge_result_projection_precomposed_extension_equals_pair_combine_checkpoint_permutations_with_empty_endpoints() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2400)
    empty_projection_counts = precompose_projection_continuation_with_empty_chunks(tuple())

    nonempty_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = precompose_projection_continuation_with_empty_chunks(
            prefix_results
        )
        full_projection_counts = precompose_projection_continuation_with_empty_chunks(
            full_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(unsplit_middle_results)
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(unsplit_suffix_results)
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(resumed_middle_results)
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_with_empty_chunks(resumed_suffix_results)
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert (
            unsplit_continuation_projection_counts
            == resumed_continuation_projection_counts
        )

        unsplit_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=full_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=full_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0


def test_merge_result_projection_precomposed_extension_summary_derived_continuation_equals_pair_combine_across_splits_with_empty_endpoints() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2410
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = precompose_projection_continuation_with_empty_chunks(full_results)
    full_summary_derived_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )
    assert full_summary_derived_projection_counts == full_projection_counts
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )

            split_count += 1
            if (
                continuation_projection_counts[0]
                or continuation_projection_counts[1]
            ):
                nonempty_continuation_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            direct_extended_projection_counts = (
                assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert direct_extended_projection_counts == recomposed_extended_projection_counts
            assert direct_extended_projection_counts == full_projection_counts

    assert (
        assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
            base_projection_counts=empty_projection_counts,
            continuation_projection_counts=full_summary_derived_projection_counts,
        )
        == full_projection_counts
    )
    assert (
        assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
            base_projection_counts=full_summary_derived_projection_counts,
            continuation_projection_counts=empty_projection_counts,
        )
        == full_projection_counts
    )
    assert split_count > 0
    assert nonempty_continuation_split_count > 0


def test_merge_result_projection_precomposed_extension_summary_derived_continuation_equals_pair_combine_checkpoint_permutations_with_empty_endpoints() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2420)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    nonempty_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert (
            unsplit_continuation_projection_counts
            == resumed_continuation_projection_counts
        )

        unsplit_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=full_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_equals_pair_combine_one_shot_parity(
                base_projection_counts=full_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0


def test_merge_result_projection_from_summary_chunk_extension_equals_precomposed_continuation_nonempty_base_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2430
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            if not base_projection_counts[0] or not base_projection_counts[1]:
                continue
            nonempty_base_split_count += 1

            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )

            direct_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert direct_extended_projection_counts == recomposed_extended_projection_counts
            assert direct_extended_projection_counts == full_projection_counts

    assert nonempty_base_split_count > 0


def test_merge_result_projection_from_summary_chunk_extension_equals_precomposed_continuation_nonempty_base_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2440)

    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        if not base_projection_counts[0] or not base_projection_counts[1]:
            continue
        nonempty_base_permutation_count += 1

        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_base_permutation_count > 0


def test_merge_result_summary_from_chunk_extension_equals_precomposed_continuation_nonempty_base_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2450
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_summary = precompose_summary_continuation_with_empty_chunks(full_results)

    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            base_summary = precompose_summary_continuation_with_empty_chunks(prefix_results)
            if not base_summary[0] or not base_summary[1]:
                continue
            nonempty_base_split_count += 1

            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_summary = precompose_summary_continuation_with_empty_chunks(
                continuation_results
            )
            middle_summary = precompose_summary_continuation_with_empty_chunks(
                middle_results
            )
            suffix_summary = precompose_summary_continuation_with_empty_chunks(
                suffix_results
            )
            recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
                middle_summary,
                suffix_summary,
            )
            assert recomposed_continuation_summary == continuation_summary

            direct_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=base_summary,
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_summary=continuation_summary,
                )
            )
            recomposed_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=base_summary,
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_summary=recomposed_continuation_summary,
                )
            )

            assert direct_extended_summary == recomposed_extended_summary
            assert direct_extended_summary == full_summary

    assert nonempty_base_split_count > 0


def test_merge_result_summary_from_chunk_extension_equals_precomposed_continuation_nonempty_base_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2460)

    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_summary = precompose_summary_continuation_with_empty_chunks(prefix_results)
        if not base_summary[0] or not base_summary[1]:
            continue
        nonempty_base_permutation_count += 1

        full_summary = precompose_summary_continuation_with_empty_chunks(full_results)
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_continuation_results
        )
        resumed_continuation_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_continuation_results
        )
        unsplit_middle_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_middle_results
        )
        unsplit_suffix_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_suffix_results
        )
        resumed_middle_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_middle_results
        )
        resumed_suffix_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_suffix_results
        )
        unsplit_recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
            unsplit_middle_summary,
            unsplit_suffix_summary,
        )
        resumed_recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
            resumed_middle_summary,
            resumed_suffix_summary,
        )

        assert unsplit_recomposed_continuation_summary == unsplit_continuation_summary
        assert resumed_recomposed_continuation_summary == resumed_continuation_summary
        assert unsplit_continuation_summary == resumed_continuation_summary

        unsplit_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=base_summary,
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_summary=unsplit_continuation_summary,
            )
        )
        unsplit_recomposed_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=base_summary,
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_summary=unsplit_recomposed_continuation_summary,
            )
        )
        resumed_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=base_summary,
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_summary=resumed_continuation_summary,
            )
        )
        resumed_recomposed_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=base_summary,
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_summary=resumed_recomposed_continuation_summary,
            )
        )

        assert unsplit_extended_summary == unsplit_recomposed_extended_summary
        assert unsplit_extended_summary == resumed_extended_summary
        assert unsplit_extended_summary == resumed_recomposed_extended_summary
        assert unsplit_extended_summary == full_summary
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_base_permutation_count > 0


def test_merge_result_summary_from_chunk_extension_equals_precomposed_continuation_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2470
    )
    empty_summary = precompose_summary_continuation_with_empty_chunks(tuple())
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_summary = precompose_summary_continuation_with_empty_chunks(
                continuation_results
            )
            middle_summary = precompose_summary_continuation_with_empty_chunks(
                middle_results
            )
            suffix_summary = precompose_summary_continuation_with_empty_chunks(
                suffix_results
            )
            recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
                middle_summary,
                suffix_summary,
            )
            base_summary = precompose_summary_continuation_with_empty_chunks(prefix_results)

            if continuation_summary[0] or continuation_summary[1]:
                nonempty_continuation_split_count += 1
            if base_summary[0] or base_summary[1]:
                nonempty_base_split_count += 1

            assert recomposed_continuation_summary == continuation_summary
            empty_base_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=empty_summary,
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_summary=continuation_summary,
                )
            )
            empty_base_recomposed_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=empty_summary,
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_summary=recomposed_continuation_summary,
                )
            )
            empty_continuation_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=base_summary,
                    continuation_summary_chunks=empty_continuation_summary_chunks,
                    continuation_summary=empty_summary,
                )
            )
            repeated_empty_continuation_extended_summary = (
                assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                    base_summary=empty_continuation_extended_summary,
                    continuation_summary_chunks=empty_continuation_summary_chunks,
                    continuation_summary=empty_summary,
                )
            )

            assert empty_base_extended_summary == empty_base_recomposed_extended_summary
            assert empty_base_extended_summary == continuation_summary
            assert empty_continuation_extended_summary == base_summary
            assert repeated_empty_continuation_extended_summary == base_summary

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_summary_from_chunk_extension_equals_precomposed_continuation_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2480)
    empty_summary = precompose_summary_continuation_with_empty_chunks(tuple())
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, _full_results = replay_stream_with_results(ordered_replicas)

        base_summary = precompose_summary_continuation_with_empty_chunks(prefix_results)
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_continuation_results
        )
        resumed_continuation_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_continuation_results
        )
        unsplit_middle_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_middle_results
        )
        unsplit_suffix_summary = precompose_summary_continuation_with_empty_chunks(
            unsplit_suffix_results
        )
        resumed_middle_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_middle_results
        )
        resumed_suffix_summary = precompose_summary_continuation_with_empty_chunks(
            resumed_suffix_results
        )
        unsplit_recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
            unsplit_middle_summary,
            unsplit_suffix_summary,
        )
        resumed_recomposed_continuation_summary = MergeResult.combine_conflict_summaries(
            resumed_middle_summary,
            resumed_suffix_summary,
        )

        if unsplit_continuation_summary[0] or unsplit_continuation_summary[1]:
            nonempty_continuation_permutation_count += 1
        if base_summary[0] or base_summary[1]:
            nonempty_base_permutation_count += 1

        assert unsplit_recomposed_continuation_summary == unsplit_continuation_summary
        assert resumed_recomposed_continuation_summary == resumed_continuation_summary
        assert unsplit_continuation_summary == resumed_continuation_summary

        unsplit_empty_base_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=empty_summary,
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_summary=unsplit_continuation_summary,
            )
        )
        unsplit_recomposed_empty_base_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=empty_summary,
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_summary=unsplit_recomposed_continuation_summary,
            )
        )
        resumed_empty_base_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=empty_summary,
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_summary=resumed_continuation_summary,
            )
        )
        resumed_recomposed_empty_base_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=empty_summary,
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_summary=resumed_recomposed_continuation_summary,
            )
        )
        empty_continuation_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=base_summary,
                continuation_summary_chunks=empty_continuation_summary_chunks,
                continuation_summary=empty_summary,
            )
        )
        repeated_empty_continuation_extended_summary = (
            assert_summary_chunk_extension_equals_precomposed_continuation_one_shot_parity(
                base_summary=empty_continuation_extended_summary,
                continuation_summary_chunks=empty_continuation_summary_chunks,
                continuation_summary=empty_summary,
            )
        )

        assert (
            unsplit_empty_base_extended_summary
            == unsplit_recomposed_empty_base_extended_summary
        )
        assert unsplit_empty_base_extended_summary == resumed_empty_base_extended_summary
        assert (
            unsplit_empty_base_extended_summary
            == resumed_recomposed_empty_base_extended_summary
        )
        assert unsplit_empty_base_extended_summary == unsplit_continuation_summary
        assert empty_continuation_extended_summary == base_summary
        assert repeated_empty_continuation_extended_summary == base_summary
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


def test_merge_result_projection_from_summary_chunk_extension_equals_precomposed_continuation_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2490
    )
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            empty_base_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_projection_counts[0],
                    base_code_counts=empty_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            empty_base_recomposed_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_projection_counts[0],
                    base_code_counts=empty_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )
            empty_continuation_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_summary_chunks=empty_continuation_summary_chunks,
                    continuation_projection_counts=empty_projection_counts,
                )
            )
            repeated_empty_continuation_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_continuation_extended_projection_counts[
                        0
                    ],
                    base_code_counts=empty_continuation_extended_projection_counts[1],
                    continuation_summary_chunks=empty_continuation_summary_chunks,
                    continuation_projection_counts=empty_projection_counts,
                )
            )

            assert (
                empty_base_extended_projection_counts
                == empty_base_recomposed_extended_projection_counts
            )
            assert empty_base_extended_projection_counts == continuation_projection_counts
            assert empty_continuation_extended_projection_counts == base_projection_counts
            assert (
                repeated_empty_continuation_extended_projection_counts
                == base_projection_counts
            )

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_projection_from_summary_chunk_extension_equals_precomposed_continuation_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2500)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, _full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_empty_base_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_empty_base_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_empty_base_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_empty_base_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )
        empty_continuation_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=empty_continuation_summary_chunks,
                continuation_projection_counts=empty_projection_counts,
            )
        )
        repeated_empty_continuation_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_continuation_extended_projection_counts[0],
                base_code_counts=empty_continuation_extended_projection_counts[1],
                continuation_summary_chunks=empty_continuation_summary_chunks,
                continuation_projection_counts=empty_projection_counts,
            )
        )

        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert empty_continuation_extended_projection_counts == base_projection_counts
        assert (
            repeated_empty_continuation_extended_projection_counts
            == base_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


def test_merge_result_projection_extension_api_equals_summary_chunk_extension_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2510
    )
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            empty_base_extended_projection_counts = (
                assert_merge_result_projection_extension_one_shot_parity(
                    base_signature_counts=empty_projection_counts[0],
                    base_code_counts=empty_projection_counts[1],
                    merge_results=continuation_results,
                    summary_chunks=continuation_summary_chunks,
                )
            )
            empty_base_recomposed_extended_projection_counts = (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    empty_projection_counts[0],
                    recomposed_continuation_projection_counts[0],
                ),
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    empty_projection_counts[1],
                    recomposed_continuation_projection_counts[1],
                ),
            )
            empty_continuation_extended_projection_counts = (
                assert_merge_result_projection_extension_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    merge_results=tuple(),
                    summary_chunks=empty_continuation_summary_chunks,
                )
            )
            repeated_empty_continuation_extended_projection_counts = (
                assert_merge_result_projection_extension_one_shot_parity(
                    base_signature_counts=empty_continuation_extended_projection_counts[
                        0
                    ],
                    base_code_counts=empty_continuation_extended_projection_counts[1],
                    merge_results=tuple(),
                    summary_chunks=empty_continuation_summary_chunks,
                )
            )

            assert (
                empty_base_extended_projection_counts
                == empty_base_recomposed_extended_projection_counts
            )
            assert empty_base_extended_projection_counts == continuation_projection_counts
            assert empty_continuation_extended_projection_counts == base_projection_counts
            assert (
                repeated_empty_continuation_extended_projection_counts
                == base_projection_counts
            )

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_projection_extension_api_equals_summary_chunk_extension_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2520)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )
    empty_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(tuple())

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, _full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                merge_results=unsplit_continuation_results,
                summary_chunks=unsplit_continuation_summary_chunks,
            )
        )
        unsplit_recomposed_empty_base_extended_projection_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                empty_projection_counts[0],
                unsplit_recomposed_continuation_projection_counts[0],
            ),
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                empty_projection_counts[1],
                unsplit_recomposed_continuation_projection_counts[1],
            ),
        )
        resumed_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                merge_results=resumed_continuation_results,
                summary_chunks=resumed_continuation_summary_chunks,
            )
        )
        resumed_recomposed_empty_base_extended_projection_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                empty_projection_counts[0],
                resumed_recomposed_continuation_projection_counts[0],
            ),
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                empty_projection_counts[1],
                resumed_recomposed_continuation_projection_counts[1],
            ),
        )
        empty_continuation_extended_projection_counts = (
            assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                merge_results=tuple(),
                summary_chunks=empty_continuation_summary_chunks,
            )
        )
        repeated_empty_continuation_extended_projection_counts = (
            assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=empty_continuation_extended_projection_counts[0],
                base_code_counts=empty_continuation_extended_projection_counts[1],
                merge_results=tuple(),
                summary_chunks=empty_continuation_summary_chunks,
            )
        )

        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert empty_continuation_extended_projection_counts == base_projection_counts
        assert (
            repeated_empty_continuation_extended_projection_counts
            == base_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


def test_merge_result_projection_extension_api_equals_precomposed_continuation_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2530
    )
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            empty_base_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_projection_counts[0],
                    base_code_counts=empty_projection_counts[1],
                    continuation_results=continuation_results,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            empty_base_recomposed_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_projection_counts[0],
                    base_code_counts=empty_projection_counts[1],
                    continuation_results=continuation_results,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )
            empty_continuation_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_results=tuple(),
                    continuation_projection_counts=empty_projection_counts,
                )
            )
            repeated_empty_continuation_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=empty_continuation_extended_projection_counts[
                        0
                    ],
                    base_code_counts=empty_continuation_extended_projection_counts[1],
                    continuation_results=tuple(),
                    continuation_projection_counts=empty_projection_counts,
                )
            )

            assert (
                empty_base_extended_projection_counts
                == empty_base_recomposed_extended_projection_counts
            )
            assert empty_base_extended_projection_counts == continuation_projection_counts
            assert empty_continuation_extended_projection_counts == base_projection_counts
            assert (
                repeated_empty_continuation_extended_projection_counts
                == base_projection_counts
            )

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_projection_extension_api_equals_precomposed_continuation_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2540)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, _full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_results=unsplit_continuation_results,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_results=unsplit_continuation_results,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_results=resumed_continuation_results,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_empty_base_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_projection_counts[0],
                base_code_counts=empty_projection_counts[1],
                continuation_results=resumed_continuation_results,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )
        empty_continuation_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_results=tuple(),
                continuation_projection_counts=empty_projection_counts,
            )
        )
        repeated_empty_continuation_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=empty_continuation_extended_projection_counts[0],
                base_code_counts=empty_continuation_extended_projection_counts[1],
                continuation_results=tuple(),
                continuation_projection_counts=empty_projection_counts,
            )
        )

        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert empty_continuation_extended_projection_counts == base_projection_counts
        assert (
            repeated_empty_continuation_extended_projection_counts
            == base_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


def test_merge_result_projection_extension_api_equals_precomposed_continuation_nonempty_base_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2550
    )
    _full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    nonempty_base_and_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            if not (base_projection_counts[0] or base_projection_counts[1]):
                continue
            if not (continuation_projection_counts[0] or continuation_projection_counts[1]):
                continue
            nonempty_base_and_continuation_split_count += 1

            direct_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_results=continuation_results,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_results=continuation_results,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert (
                direct_extended_projection_counts
                == recomposed_extended_projection_counts
            )
            assert direct_extended_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0
    assert nonempty_base_and_continuation_split_count > 0


def test_merge_result_projection_extension_api_equals_precomposed_continuation_nonempty_base_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2560)

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    nonempty_base_and_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        if not (base_projection_counts[0] or base_projection_counts[1]):
            continue
        if not (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            continue
        nonempty_base_and_continuation_permutation_count += 1

        unsplit_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_results=unsplit_continuation_results,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_results=unsplit_continuation_results,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_results=resumed_continuation_results,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            assert_merge_result_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_results=resumed_continuation_results,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0
    assert nonempty_base_and_continuation_permutation_count > 0


def test_merge_result_projection_extension_api_equals_summary_chunk_extension_nonempty_base_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2570
    )
    _full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    nonempty_base_and_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_signature_counts(
                    middle_projection_counts[0],
                    suffix_projection_counts[0],
                ),
                MergeResult.combine_conflict_code_counts(
                    middle_projection_counts[1],
                    suffix_projection_counts[1],
                ),
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            if not (base_projection_counts[0] or base_projection_counts[1]):
                continue
            if not (continuation_projection_counts[0] or continuation_projection_counts[1]):
                continue
            nonempty_base_and_continuation_split_count += 1

            extended_projection_counts = assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                merge_results=continuation_results,
                summary_chunks=continuation_summary_chunks,
            )
            recomposed_extended_projection_counts = (
                MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                    base_projection_counts[0],
                    recomposed_continuation_projection_counts[0],
                ),
                MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                    base_projection_counts[1],
                    recomposed_continuation_projection_counts[1],
                ),
            )

            assert extended_projection_counts == recomposed_extended_projection_counts
            assert extended_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0
    assert nonempty_base_and_continuation_split_count > 0


def test_merge_result_projection_extension_api_equals_summary_chunk_extension_nonempty_base_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2580)

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    nonempty_base_and_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                unsplit_middle_projection_counts[0],
                unsplit_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                unsplit_middle_projection_counts[1],
                unsplit_suffix_projection_counts[1],
            ),
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_signature_counts(
                resumed_middle_projection_counts[0],
                resumed_suffix_projection_counts[0],
            ),
            MergeResult.combine_conflict_code_counts(
                resumed_middle_projection_counts[1],
                resumed_suffix_projection_counts[1],
            ),
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        if not (base_projection_counts[0] or base_projection_counts[1]):
            continue
        if not (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            continue
        nonempty_base_and_continuation_permutation_count += 1

        unsplit_extended_projection_counts = (
            assert_merge_result_projection_extension_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                merge_results=unsplit_continuation_results,
                summary_chunks=unsplit_continuation_summary_chunks,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_projection_counts[0],
                unsplit_recomposed_continuation_projection_counts[0],
            ),
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_projection_counts[1],
                unsplit_recomposed_continuation_projection_counts[1],
            ),
        )
        resumed_extended_projection_counts = assert_merge_result_projection_extension_one_shot_parity(
            base_signature_counts=base_projection_counts[0],
            base_code_counts=base_projection_counts[1],
            merge_results=resumed_continuation_results,
            summary_chunks=resumed_continuation_summary_chunks,
        )
        resumed_recomposed_extended_projection_counts = (
            MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
                base_projection_counts[0],
                resumed_recomposed_continuation_projection_counts[0],
            ),
            MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
                base_projection_counts[1],
                resumed_recomposed_continuation_projection_counts[1],
            ),
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0
    assert nonempty_base_and_continuation_permutation_count > 0


def test_summary_chunk_projection_extension_api_equals_precomposed_continuation_nonempty_base_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2590
    )
    _full_merged, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    nonempty_base_and_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
                continuation_results
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            recomposed_continuation_projection_counts = (
                MergeResult.combine_conflict_summaries(
                    middle_projection_counts,
                    suffix_projection_counts,
                )
            )
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )

            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )

            if not (base_projection_counts[0] or base_projection_counts[1]):
                continue
            if not (continuation_projection_counts[0] or continuation_projection_counts[1]):
                continue
            nonempty_base_and_continuation_split_count += 1

            direct_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                    base_signature_counts=base_projection_counts[0],
                    base_code_counts=base_projection_counts[1],
                    continuation_summary_chunks=continuation_summary_chunks,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert direct_extended_projection_counts == recomposed_extended_projection_counts
            assert direct_extended_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0
    assert nonempty_base_and_continuation_split_count > 0


def test_summary_chunk_projection_extension_api_equals_precomposed_continuation_nonempty_base_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2600)

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    nonempty_base_and_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        unsplit_continuation_results = unsplit_middle_results + unsplit_suffix_results
        resumed_continuation_results = resumed_middle_results + resumed_suffix_results
        unsplit_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            unsplit_continuation_results
        )
        resumed_continuation_summary_chunks = conflict_summary_chunks_with_empty_path(
            resumed_continuation_results
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_continuation_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_continuation_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )
        unsplit_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_summaries(
                unsplit_middle_projection_counts,
                unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            MergeResult.combine_conflict_summaries(
                resumed_middle_projection_counts,
                resumed_suffix_projection_counts,
            )
        )

        if unsplit_continuation_projection_counts[0] or unsplit_continuation_projection_counts[1]:
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        if not (base_projection_counts[0] or base_projection_counts[1]):
            continue
        if not (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            continue
        nonempty_base_and_continuation_permutation_count += 1

        unsplit_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=unsplit_continuation_summary_chunks,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            assert_summary_chunk_projection_extension_equals_precomposed_continuation_one_shot_parity(
                base_signature_counts=base_projection_counts[0],
                base_code_counts=base_projection_counts[1],
                continuation_summary_chunks=resumed_continuation_summary_chunks,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0
    assert nonempty_base_and_continuation_permutation_count > 0


def assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
    *,
    left_projection_counts: tuple[tuple, tuple],
    right_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_projection_chunk = tuple()
    signature_count_chunks = (
        empty_projection_chunk,
        left_projection_counts[0],
        empty_projection_chunk,
        right_projection_counts[0],
        empty_projection_chunk,
    )
    code_count_chunks = (
        empty_projection_chunk,
        left_projection_counts[1],
        empty_projection_chunk,
        right_projection_counts[1],
        empty_projection_chunk,
    )

    pair_composed_projection_counts = (
        MergeResult.combine_conflict_signature_counts(
            left_projection_counts[0],
            right_projection_counts[0],
        ),
        MergeResult.combine_conflict_code_counts(
            left_projection_counts[1],
            right_projection_counts[1],
        ),
    )
    materialized_chunk_composed_projection_counts = (
        MergeResult.combine_conflict_signature_counts_from_chunks(signature_count_chunks),
        MergeResult.combine_conflict_code_counts_from_chunks(code_count_chunks),
    )
    one_shot_chunk_composed_projection_counts = (
        MergeResult.combine_conflict_signature_counts_from_chunks(
            OneShotIterable(signature_count_chunks)
        ),
        MergeResult.combine_conflict_code_counts_from_chunks(
            OneShotIterable(code_count_chunks)
        ),
    )

    assert materialized_chunk_composed_projection_counts == pair_composed_projection_counts
    assert one_shot_chunk_composed_projection_counts == pair_composed_projection_counts
    return pair_composed_projection_counts


def test_merge_result_projection_pair_combine_api_equals_chunk_combine_across_splits_with_empty_chunks() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2630
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            if (
                continuation_projection_counts[0]
                or continuation_projection_counts[1]
            ):
                nonempty_continuation_split_count += 1

            recomposed_continuation_projection_counts = (
                assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                    left_projection_counts=middle_projection_counts,
                    right_projection_counts=suffix_projection_counts,
                )
            )
            direct_full_projection_counts = (
                assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                    left_projection_counts=base_projection_counts,
                    right_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_full_projection_counts = (
                assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                    left_projection_counts=base_projection_counts,
                    right_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            assert direct_full_projection_counts == recomposed_full_projection_counts
            assert direct_full_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0


def test_merge_result_projection_pair_combine_api_equals_chunk_combine_checkpoint_permutations_with_empty_chunks() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2640)

    nonempty_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1

        unsplit_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=unsplit_middle_projection_counts,
                right_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=resumed_middle_projection_counts,
                right_projection_counts=resumed_suffix_projection_counts,
            )
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_full_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_chunk_combine_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert unsplit_full_projection_counts == unsplit_recomposed_full_projection_counts
        assert unsplit_full_projection_counts == resumed_full_projection_counts
        assert unsplit_full_projection_counts == resumed_recomposed_full_projection_counts
        assert unsplit_full_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0


def assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
    *,
    left_projection_counts: tuple[tuple, tuple],
    right_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_summary_chunk = (tuple(), tuple())
    summary_chunks = (
        empty_summary_chunk,
        left_projection_counts,
        empty_summary_chunk,
        right_projection_counts,
        empty_summary_chunk,
    )

    pair_composed_projection_counts = (
        MergeResult.combine_conflict_signature_counts(
            left_projection_counts[0],
            right_projection_counts[0],
        ),
        MergeResult.combine_conflict_code_counts(
            left_projection_counts[1],
            right_projection_counts[1],
        ),
    )
    summary_pair_projection_counts = (
        MergeResult.combine_conflict_projection_counts_via_summary_pair(
            left_projection_counts,
            right_projection_counts,
        )
    )
    materialized_summary_chunk_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(summary_chunks)
    )
    one_shot_summary_chunk_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(
            OneShotIterable(summary_chunks)
        )
    )

    assert summary_pair_projection_counts == pair_composed_projection_counts
    assert (
        materialized_summary_chunk_projection_counts == pair_composed_projection_counts
    )
    assert one_shot_summary_chunk_projection_counts == pair_composed_projection_counts
    return pair_composed_projection_counts


def test_merge_result_projection_pair_combine_outputs_equal_summary_pair_projections_across_splits_with_empty_chunks() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2650
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1

            recomposed_continuation_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=middle_projection_counts,
                    right_projection_counts=suffix_projection_counts,
                )
            )
            direct_full_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=base_projection_counts,
                    right_projection_counts=continuation_projection_counts,
                )
            )
            recomposed_full_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=base_projection_counts,
                    right_projection_counts=recomposed_continuation_projection_counts,
                )
            )

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            assert direct_full_projection_counts == recomposed_full_projection_counts
            assert direct_full_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0


def test_merge_result_projection_pair_combine_outputs_equal_summary_pair_projections_checkpoint_permutations_with_empty_chunks() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2660)

    nonempty_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1

        unsplit_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=unsplit_middle_projection_counts,
                right_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=resumed_middle_projection_counts,
                right_projection_counts=resumed_suffix_projection_counts,
            )
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_full_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_full_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=base_projection_counts,
                right_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )

        assert unsplit_full_projection_counts == unsplit_recomposed_full_projection_counts
        assert unsplit_full_projection_counts == resumed_full_projection_counts
        assert unsplit_full_projection_counts == resumed_recomposed_full_projection_counts
        assert unsplit_full_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0


def assert_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_one_shot_parity(
    *,
    base_projection_counts: tuple[tuple, tuple],
    left_continuation_projection_counts: tuple[tuple, tuple],
    right_continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_summary_chunk = (tuple(), tuple())
    continuation_summary_chunks = (
        empty_summary_chunk,
        left_continuation_projection_counts,
        empty_summary_chunk,
        right_continuation_projection_counts,
        empty_summary_chunk,
    )
    pair_composed_continuation_projection_counts = (
        MergeResult.combine_conflict_signature_counts(
            left_continuation_projection_counts[0],
            right_continuation_projection_counts[0],
        ),
        MergeResult.combine_conflict_code_counts(
            left_continuation_projection_counts[1],
            right_continuation_projection_counts[1],
        ),
    )
    summary_pair_composed_continuation_projection_counts = (
        MergeResult.combine_conflict_projection_counts_via_summary_pair(
            left_continuation_projection_counts,
            right_continuation_projection_counts,
        )
    )
    materialized_summary_chunk_composed_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(continuation_summary_chunks)
    )
    one_shot_summary_chunk_composed_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(
            OneShotIterable(continuation_summary_chunks)
        )
    )

    assert (
        summary_pair_composed_continuation_projection_counts
        == pair_composed_continuation_projection_counts
    )
    assert (
        materialized_summary_chunk_composed_continuation_projection_counts
        == pair_composed_continuation_projection_counts
    )
    assert (
        one_shot_summary_chunk_composed_continuation_projection_counts
        == pair_composed_continuation_projection_counts
    )

    direct_extended_projection_counts = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            pair_composed_continuation_projection_counts,
        )
    )
    summary_pair_extended_projection_counts = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            summary_pair_composed_continuation_projection_counts,
        )
    )
    materialized_summary_chunk_extended_projection_counts = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            materialized_summary_chunk_composed_continuation_projection_counts,
        )
    )
    one_shot_summary_chunk_extended_projection_counts = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            one_shot_summary_chunk_composed_continuation_projection_counts,
        )
    )

    assert summary_pair_extended_projection_counts == direct_extended_projection_counts
    assert (
        materialized_summary_chunk_extended_projection_counts
        == direct_extended_projection_counts
    )
    assert (
        one_shot_summary_chunk_extended_projection_counts
        == direct_extended_projection_counts
    )
    return direct_extended_projection_counts


def test_merge_result_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_across_splits_with_empty_chunks() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2670
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1

            recomposed_continuation_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=middle_projection_counts,
                    right_projection_counts=suffix_projection_counts,
                )
            )
            summary_pair_extended_projection_counts = (
                assert_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_one_shot_parity(
                    base_projection_counts=base_projection_counts,
                    left_continuation_projection_counts=middle_projection_counts,
                    right_continuation_projection_counts=suffix_projection_counts,
                )
            )
            direct_extended_projection_counts = (
                MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                    base_projection_counts,
                    continuation_projection_counts,
                )
            )
            recomposed_extended_projection_counts = (
                MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                    base_projection_counts,
                    recomposed_continuation_projection_counts,
                )
            )

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )
            assert summary_pair_extended_projection_counts == direct_extended_projection_counts
            assert (
                summary_pair_extended_projection_counts
                == recomposed_extended_projection_counts
            )
            assert summary_pair_extended_projection_counts == full_projection_counts

    assert split_count > 0
    assert nonempty_continuation_split_count > 0


def test_merge_result_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_checkpoint_permutations_with_empty_chunks() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2680)

    nonempty_continuation_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1

        unsplit_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=unsplit_middle_projection_counts,
                right_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=resumed_middle_projection_counts,
                right_projection_counts=resumed_suffix_projection_counts,
            )
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_extended_projection_counts = (
            assert_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_one_shot_parity(
                base_projection_counts=base_projection_counts,
                left_continuation_projection_counts=unsplit_middle_projection_counts,
                right_continuation_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        unsplit_direct_extended_projection_counts = (
            MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                base_projection_counts,
                unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_extended_projection_counts = (
            MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                base_projection_counts,
                unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_extended_projection_counts = (
            assert_projection_precomposed_extension_api_outputs_equal_summary_pair_derived_continuation_one_shot_parity(
                base_projection_counts=base_projection_counts,
                left_continuation_projection_counts=resumed_middle_projection_counts,
                right_continuation_projection_counts=resumed_suffix_projection_counts,
            )
        )
        resumed_direct_extended_projection_counts = (
            MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                base_projection_counts,
                resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_extended_projection_counts = (
            MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
                base_projection_counts,
                resumed_recomposed_continuation_projection_counts,
            )
        )

        assert unsplit_extended_projection_counts == unsplit_direct_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == unsplit_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == resumed_extended_projection_counts
        assert unsplit_extended_projection_counts == resumed_direct_extended_projection_counts
        assert (
            unsplit_extended_projection_counts
            == resumed_recomposed_extended_projection_counts
        )
        assert unsplit_extended_projection_counts == full_projection_counts
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0


def assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
    *,
    base_projection_counts: tuple[tuple, tuple],
    continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_summary_chunk = (tuple(), tuple())
    continuation_summary_chunks = (
        empty_summary_chunk,
        continuation_projection_counts,
        empty_summary_chunk,
    )
    materialized_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(continuation_summary_chunks)
    )
    one_shot_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(
            OneShotIterable(continuation_summary_chunks)
        )
    )

    assert (
        materialized_continuation_projection_counts
        == continuation_projection_counts
    )
    assert one_shot_continuation_projection_counts == continuation_projection_counts

    direct_projection_extension = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            continuation_projection_counts,
        )
    )
    materialized_projection_extension = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            materialized_continuation_projection_counts,
        )
    )
    one_shot_projection_extension = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            one_shot_continuation_projection_counts,
        )
    )
    direct_explicit_fan_out_extension = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_projection_counts[0],
            continuation_projection_counts[0],
        ),
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_projection_counts[1],
            continuation_projection_counts[1],
        ),
    )
    materialized_explicit_fan_out_extension = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_projection_counts[0],
            materialized_continuation_projection_counts[0],
        ),
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_projection_counts[1],
            materialized_continuation_projection_counts[1],
        ),
    )
    one_shot_explicit_fan_out_extension = (
        MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(
            base_projection_counts[0],
            one_shot_continuation_projection_counts[0],
        ),
        MergeResult.extend_conflict_code_counts_with_precomposed_continuation(
            base_projection_counts[1],
            one_shot_continuation_projection_counts[1],
        ),
    )

    assert direct_projection_extension == direct_explicit_fan_out_extension
    assert materialized_projection_extension == direct_explicit_fan_out_extension
    assert one_shot_projection_extension == direct_explicit_fan_out_extension
    assert (
        materialized_explicit_fan_out_extension
        == direct_explicit_fan_out_extension
    )
    assert one_shot_explicit_fan_out_extension == direct_explicit_fan_out_extension
    return direct_projection_extension


def test_merge_result_projection_precomposed_extension_api_equals_explicit_fan_out_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2690
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            recomposed_continuation_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=middle_projection_counts,
                    right_projection_counts=suffix_projection_counts,
                )
            )

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )

            empty_base_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            empty_base_recomposed_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )
            empty_continuation_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
            )
            repeated_empty_continuation_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=empty_continuation_extended_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
            )

            assert (
                empty_base_extended_projection_counts
                == empty_base_recomposed_extended_projection_counts
            )
            assert empty_base_extended_projection_counts == continuation_projection_counts
            assert empty_continuation_extended_projection_counts == base_projection_counts
            assert (
                repeated_empty_continuation_extended_projection_counts
                == base_projection_counts
            )
            assert (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=full_projection_counts,
                )
                == full_projection_counts
            )
            assert (
                assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                    base_projection_counts=full_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
                == full_projection_counts
            )

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_projection_precomposed_extension_api_equals_explicit_fan_out_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2700)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        unsplit_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=unsplit_middle_projection_counts,
                right_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=resumed_middle_projection_counts,
                right_projection_counts=resumed_suffix_projection_counts,
            )
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )
        empty_continuation_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
        )
        repeated_empty_continuation_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_continuation_extended_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
        )

        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert empty_continuation_extended_projection_counts == base_projection_counts
        assert (
            repeated_empty_continuation_extended_projection_counts
            == base_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=full_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_api_equals_explicit_projection_fan_out_one_shot_endpoint_parity(
                base_projection_counts=full_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


def assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
    *,
    base_projection_counts: tuple[tuple, tuple],
    continuation_projection_counts: tuple[tuple, tuple],
) -> tuple[tuple, tuple]:
    empty_summary_chunk = (tuple(), tuple())
    continuation_summary_chunks = (
        empty_summary_chunk,
        continuation_projection_counts,
        empty_summary_chunk,
    )
    materialized_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(continuation_summary_chunks)
    )
    one_shot_continuation_projection_counts = (
        MergeResult.combine_conflict_summaries_from_chunks(
            OneShotIterable(continuation_summary_chunks)
        )
    )

    assert (
        materialized_continuation_projection_counts
        == continuation_projection_counts
    )
    assert one_shot_continuation_projection_counts == continuation_projection_counts

    direct_projection_extension = (
        MergeResult.extend_conflict_projection_counts_with_precomposed_continuation(
            base_projection_counts,
            continuation_projection_counts,
        )
    )
    materialized_projection_extension = (
        MergeResult.extend_conflict_projection_counts_from_summary_chunks(
            base_projection_counts,
            continuation_summary_chunks,
        )
    )
    one_shot_projection_extension = (
        MergeResult.extend_conflict_projection_counts_from_summary_chunks(
            base_projection_counts,
            OneShotIterable(continuation_summary_chunks),
        )
    )
    materialized_explicit_summary_chunk_extension = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_projection_counts[0],
            continuation_summary_chunks,
        ),
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_projection_counts[1],
            continuation_summary_chunks,
        ),
    )
    one_shot_explicit_summary_chunk_extension = (
        MergeResult.extend_conflict_signature_counts_from_summary_chunks(
            base_projection_counts[0],
            OneShotIterable(continuation_summary_chunks),
        ),
        MergeResult.extend_conflict_code_counts_from_summary_chunks(
            base_projection_counts[1],
            OneShotIterable(continuation_summary_chunks),
        ),
    )

    assert materialized_projection_extension == direct_projection_extension
    assert one_shot_projection_extension == direct_projection_extension
    assert materialized_explicit_summary_chunk_extension == direct_projection_extension
    assert one_shot_explicit_summary_chunk_extension == direct_projection_extension
    return direct_projection_extension


def test_merge_result_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_empty_endpoints_across_splits() -> None:
    (
        _lifecycle_core,
        _relation_canonical,
        replay_sequence,
    ) = build_repeated_lifecycle_pair_mixed_orphan_collision_checkpoint_replicas(
        tx_base=2710
    )
    _, full_results = replay_stream_with_results(replay_sequence)
    full_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
            full_results
        )
    )
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    split_count = 0
    nonempty_continuation_split_count = 0
    nonempty_base_split_count = 0
    for first_split in range(1, len(replay_sequence)):
        for second_split in range(first_split + 1, len(replay_sequence) + 1):
            prefix_merged, prefix_results = replay_stream_with_results(
                replay_sequence[:first_split]
            )
            middle_merged, middle_results = replay_stream_with_results(
                replay_sequence[first_split:second_split],
                start=prefix_merged,
            )
            _suffix_merged, suffix_results = replay_stream_with_results(
                replay_sequence[second_split:],
                start=middle_merged,
            )
            continuation_results = middle_results + suffix_results

            split_count += 1
            base_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    prefix_results
                )
            )
            continuation_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    continuation_results
                )
            )
            middle_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    middle_results
                )
            )
            suffix_projection_counts = (
                precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                    suffix_results
                )
            )
            if continuation_projection_counts[0] or continuation_projection_counts[1]:
                nonempty_continuation_split_count += 1
            if base_projection_counts[0] or base_projection_counts[1]:
                nonempty_base_split_count += 1

            recomposed_continuation_projection_counts = (
                assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                    left_projection_counts=middle_projection_counts,
                    right_projection_counts=suffix_projection_counts,
                )
            )

            assert (
                recomposed_continuation_projection_counts
                == continuation_projection_counts
            )

            empty_base_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=continuation_projection_counts,
                )
            )
            empty_base_recomposed_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=recomposed_continuation_projection_counts,
                )
            )
            empty_continuation_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=base_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
            )
            repeated_empty_continuation_extended_projection_counts = (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=empty_continuation_extended_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
            )

            assert (
                empty_base_extended_projection_counts
                == empty_base_recomposed_extended_projection_counts
            )
            assert empty_base_extended_projection_counts == continuation_projection_counts
            assert empty_continuation_extended_projection_counts == base_projection_counts
            assert (
                repeated_empty_continuation_extended_projection_counts
                == base_projection_counts
            )
            assert (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=empty_projection_counts,
                    continuation_projection_counts=full_projection_counts,
                )
                == full_projection_counts
            )
            assert (
                assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                    base_projection_counts=full_projection_counts,
                    continuation_projection_counts=empty_projection_counts,
                )
                == full_projection_counts
            )

    assert split_count > 0
    assert nonempty_continuation_split_count > 0
    assert nonempty_base_split_count > 0


def test_merge_result_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_empty_endpoints_checkpoint_permutations() -> None:
    _, replay_sequence = build_mixed_orphan_collision_checkpoint_replicas(tx_base=2720)
    empty_projection_counts = (
        precompose_projection_continuation_from_summary_chunks_with_empty_chunks(tuple())
    )

    nonempty_continuation_permutation_count = 0
    nonempty_base_permutation_count = 0
    for order in itertools.permutations(range(len(replay_sequence))):
        ordered_replicas = [replay_sequence[index] for index in order]
        first_split = len(ordered_replicas) // 3
        if first_split == 0:
            first_split = 1
        second_split = (2 * len(ordered_replicas)) // 3
        if second_split <= first_split:
            second_split = first_split + 1
        if second_split > len(ordered_replicas):
            second_split = len(ordered_replicas)

        prefix_merged, prefix_results = replay_stream_with_results(
            ordered_replicas[:first_split]
        )
        unsplit_middle_merged, unsplit_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged,
        )
        unsplit_suffix_merged, unsplit_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=unsplit_middle_merged,
        )
        resumed_middle_merged, resumed_middle_results = replay_stream_with_results(
            ordered_replicas[first_split:second_split],
            start=prefix_merged.checkpoint(),
        )
        resumed_suffix_merged, resumed_suffix_results = replay_stream_with_results(
            ordered_replicas[second_split:],
            start=resumed_middle_merged.checkpoint(),
        )
        full_merged, full_results = replay_stream_with_results(ordered_replicas)

        base_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                prefix_results
            )
        )
        full_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                full_results
            )
        )
        unsplit_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results + unsplit_suffix_results
            )
        )
        resumed_continuation_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results + resumed_suffix_results
            )
        )
        unsplit_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_middle_results
            )
        )
        unsplit_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                unsplit_suffix_results
            )
        )
        resumed_middle_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_middle_results
            )
        )
        resumed_suffix_projection_counts = (
            precompose_projection_continuation_from_summary_chunks_with_empty_chunks(
                resumed_suffix_results
            )
        )

        if (
            unsplit_continuation_projection_counts[0]
            or unsplit_continuation_projection_counts[1]
        ):
            nonempty_continuation_permutation_count += 1
        if base_projection_counts[0] or base_projection_counts[1]:
            nonempty_base_permutation_count += 1

        unsplit_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=unsplit_middle_projection_counts,
                right_projection_counts=unsplit_suffix_projection_counts,
            )
        )
        resumed_recomposed_continuation_projection_counts = (
            assert_projection_pair_combine_api_equals_summary_pair_projection_one_shot_parity(
                left_projection_counts=resumed_middle_projection_counts,
                right_projection_counts=resumed_suffix_projection_counts,
            )
        )

        assert (
            unsplit_recomposed_continuation_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert (
            resumed_recomposed_continuation_projection_counts
            == resumed_continuation_projection_counts
        )
        assert unsplit_continuation_projection_counts == resumed_continuation_projection_counts

        unsplit_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=unsplit_continuation_projection_counts,
            )
        )
        unsplit_recomposed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=unsplit_recomposed_continuation_projection_counts,
            )
        )
        resumed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=resumed_continuation_projection_counts,
            )
        )
        resumed_recomposed_empty_base_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=resumed_recomposed_continuation_projection_counts,
            )
        )
        empty_continuation_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=base_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
        )
        repeated_empty_continuation_extended_projection_counts = (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_continuation_extended_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
        )

        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == resumed_recomposed_empty_base_extended_projection_counts
        )
        assert (
            unsplit_empty_base_extended_projection_counts
            == unsplit_continuation_projection_counts
        )
        assert empty_continuation_extended_projection_counts == base_projection_counts
        assert (
            repeated_empty_continuation_extended_projection_counts
            == base_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=empty_projection_counts,
                continuation_projection_counts=full_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            assert_projection_precomposed_extension_api_equals_summary_chunk_projection_extension_reducers_one_shot_endpoint_parity(
                base_projection_counts=full_projection_counts,
                continuation_projection_counts=empty_projection_counts,
            )
            == full_projection_counts
        )
        assert (
            unsplit_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            unsplit_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )
        assert (
            resumed_suffix_merged.relation_state_signatures()
            == full_merged.relation_state_signatures()
        )
        assert (
            resumed_suffix_merged.revision_state_signatures()
            == full_merged.revision_state_signatures()
        )

    assert nonempty_continuation_permutation_count > 0
    assert nonempty_base_permutation_count > 0


