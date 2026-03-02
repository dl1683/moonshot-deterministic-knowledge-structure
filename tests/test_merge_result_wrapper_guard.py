import hashlib
import inspect

from dks import MergeResult

_WRAPPER_PREFIXES = (
    "extend_conflict_projection_counts_from_summary_chunks_via_",
    "_extend_conflict_projection_counts_from_summary_chunks_via_",
    "_extend_conflict_projection_counts_from_pre_fanned_component_chunks",
)

_EXPECTED_WRAPPER_SURFACE_COUNT = 53
_EXPECTED_WRAPPER_SURFACE_SHA256 = (
    "7e008edc722ff1543a8e13f4945ceb4535800d8a42e6b298ffd807802992d704"
)

_EXPECTED_ROUTE_SHIM_COUNTS = {
    "summary": 26,
    "pre_fanned": 27,
}


def _projection_wrapper_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in MergeResult.__dict__
            if name.startswith(_WRAPPER_PREFIXES)
        )
    )


def _unwrap_staticmethod(name: str):
    descriptor = MergeResult.__dict__[name]
    assert isinstance(descriptor, staticmethod), (
        f"{name} is expected to be a staticmethod shim descriptor"
    )
    return descriptor.__func__


def test_merge_result_projection_wrappers_route_to_canonical_targets() -> None:
    summary_route = _unwrap_staticmethod(
        "_extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components"
    )
    pre_fanned_route = _unwrap_staticmethod(
        "_extend_conflict_projection_counts_from_pre_fanned_component_chunks"
    )

    for name in _projection_wrapper_names():
        target = _unwrap_staticmethod(name)
        assert target in {summary_route, pre_fanned_route}, (
            f"{name} no longer routes to a canonical projection extension target"
        )


def test_merge_result_projection_wrappers_have_no_delegation_chain_hops() -> None:
    summary_route = _unwrap_staticmethod(
        "_extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components"
    )
    pre_fanned_route = _unwrap_staticmethod(
        "_extend_conflict_projection_counts_from_pre_fanned_component_chunks"
    )

    summary_wrappers = 0
    pre_fanned_wrappers = 0

    for name in _projection_wrapper_names():
        target = _unwrap_staticmethod(name)
        arity = len(inspect.signature(target).parameters)
        assert arity in (2, 3), f"{name} drifted to unexpected wrapper arity: {arity}"

        if arity == 2:
            summary_wrappers += 1
            assert target is summary_route, (
                f"{name} drifted from direct canonical summary-chunk routing"
            )
        else:
            pre_fanned_wrappers += 1
            assert target is pre_fanned_route, (
                f"{name} drifted from direct canonical pre-fanned routing"
            )

    assert summary_wrappers == _EXPECTED_ROUTE_SHIM_COUNTS["summary"]
    assert pre_fanned_wrappers == _EXPECTED_ROUTE_SHIM_COUNTS["pre_fanned"]


def test_merge_result_projection_wrapper_shim_surface_is_stable() -> None:
    wrapper_names = _projection_wrapper_names()
    assert len(wrapper_names) == _EXPECTED_WRAPPER_SURFACE_COUNT

    wrapper_surface_hash = hashlib.sha256(
        "\n".join(wrapper_names).encode("utf-8")
    ).hexdigest()
    assert wrapper_surface_hash == _EXPECTED_WRAPPER_SURFACE_SHA256
