# Decision Log

This file records architectural decisions that changed code/test behavior.

> **Note:** The original decision log contained 178 entries (DEC-1 through DEC-178), all generated on 2026-02-17 by the autonomous Continuum loop. Every entry documented internal routing shim additions — forwarding methods in `MergeResult` that were subsequently removed during cleanup. No entries recorded real architectural decisions (those are captured in `DESIGN.md` and the git history). The log was reset during the post-Continuum cleanup.

## Architectural Decisions (Pre-Continuum)

The core architectural decisions are embedded in the V1 design itself:

1. **SHA-256 canonicalized identity** — All semantic identities are deterministic hashes of normalized inputs. Chosen over UUID/sequence-based IDs for replica convergence.

2. **Bitemporal model** — Separate `ValidTime` and `TransactionTime` dimensions. Chosen over single-time models for audit-safe historical queries.

3. **Append-only event model** — Status changes are events, not mutations. Chosen over mutable state for replay determinism.

4. **Deterministic merge with conflict records** — Conflicts are first-class records, not silent overwrite. Chosen over last-writer-wins for correctness.

5. **Sorted-key reducer ordering** — Merge applies operations in deterministic `op_id` order regardless of arrival order. Chosen over arrival-order processing for convergence.

6. **Independence-key evidence grouping** — Confidence aggregation groups evidence by `independence_key` and takes max per group. Chosen over naive sum/noisy-or for anti-inflation.

7. **Immutable witness-basis qualifiers** — Inference witnesses store assertion-time basis snapshots. Chosen over dynamic recomputation for rollback stability.

8. **Compare-and-swap admission** — Surgery and migration operations use basis-hash CAS. Chosen over unconditional apply for stale-plan rejection.

9. **Snapshot persistence** — Full store state serializable to canonical JSON/binary payload with round-trip validation. Chosen for checkpoint/restart determinism.

10. **Schema epoch gating** — Operations bound to `schema_epoch_id`; mismatched epochs quarantined. Chosen over implicit compatibility for cross-version safety.
