# Failure Modes

Track failure classes and mitigations for the data structure design.

> **Note:** The original catalog contained 276 entries (FM-001 through FM-276). Entries FM-021 through FM-276 covered governance-layer extensions (retention, caching, tiering, attestation, federation, etc.) that were never implemented in V1. Only the 20 core failure modes are retained below.
>
> **Scope:** FM-001 through FM-009 are directly mitigated in the current implementation. FM-010 through FM-020 describe risks from the original design spec whose mitigations (independence-key grouping, witness-basis qualifiers, interval surgery, schema epochs, migration) are *design intent* not yet implemented in V1.

## FM-001: Semantic Collision

- Description:
Different propositions map to the same `core_id`.
- Trigger:
Over-broad normalization, missing role typing, or wildcard handling of unknown values.
- Consequence:
False merges, corrupted contradiction logic, and unreliable retrieval.
- Detection signal:
`core_id` contains multiple incompatible canonical forms or mutually exclusive role constraints.
- Mitigation:
`INV-S1..INV-S3`, explicit `UNK::<role>` sentinel, strict role schema validation.
- Residual risk:
Ontology mistakes can still collapse distinct predicates.

## FM-002: Semantic Fragmentation

- Description:
Equivalent propositions get different `core_id`s.
- Trigger:
Alias resolution misses, inconsistent unit normalization, or parser variance upstream.
- Consequence:
Recall loss and duplicate memory fragments.
- Detection signal:
High lexical similarity and shared evidence but disjoint `core_id`s.
- Mitigation:
Versioned canonicalization policy, alias dictionaries, scalar normalization rules, periodic dedupe audits.
- Residual risk:
Ambiguous entity mentions remain difficult without stronger entity grounding.

## FM-003: Polarity Leak

- Description:
Affirmed and negated claims collapse due to omitted polarity in identity hash.
- Trigger:
Identity schema omission or migration bug.
- Consequence:
Contradiction edges cannot be computed correctly.
- Detection signal:
Same `core_id` observed with both affirmed and negated states.
- Mitigation:
`INV-S4` requires polarity in `core_id` input bytes; migration tests block incompatible schema changes.
- Residual risk:
Complex modal negation still may need richer representation.

## FM-004: Ontology Drift Identity Split

- Description:
Ontology version updates cause unstable claim typing across replicas.
- Trigger:
Unversioned predicate IDs or non-deterministic schema migration.
- Consequence:
Non-convergent identity assignment and cross-node mismatches.
- Detection signal:
Replica disagreement on `claim_type_id` for same canonical candidate.
- Mitigation:
Versioned `claim_type_id` in hash input (`predicate@vN`) and explicit migration mappings.
- Residual risk:
Long migration chains may increase operational complexity.

## FM-005: Symmetry Duplicate Edge

- Description:
Equivalent symmetric relations are duplicated because endpoint order differs (`A,B` vs `B,A`).
- Trigger:
Relation insertion uses caller order instead of canonical ordering for symmetric signatures.
- Consequence:
Replica divergence in graph topology and query-count inflation.
- Detection signal:
Multiple contradiction edges connect the same two `core_id`s with reversed endpoint order.
- Mitigation:
`INV-R2` enforces lexicographic endpoint sorting before `relation_id` hash for symmetric relation types.
- Residual risk:
If endpoint canonicalization code diverges by version across replicas, duplicates can still appear.

## FM-006: Temporal Blind Derivation

- Description:
Inference lineage is recorded at `ClaimCore` level, dropping which premise revisions were actually used.
- Trigger:
`derived_from` relation keyed by semantic cores rather than revision IDs.
- Consequence:
Rollback and supersession cannot deterministically determine which derived revisions to invalidate.
- Detection signal:
Derived claim remains justified even after premise revision retraction because lineage is ambiguous.
- Mitigation:
`INV-R6` requires derivation/support edges to reference `ClaimRevision`.
`derived_from` identity includes sorted unique premise revision IDs and `rule_id`.
- Residual risk:
Cross-rule equivalence (different rules yielding same conclusion) may still require explicit policy for collapse or coexistence.

## FM-007: Retroactive Ghost Fact

- Description:
A fact appears in historical query results before it was actually recorded.
- Trigger:
Lookup filters only on valid time and ignores transaction visibility.
- Consequence:
Non-reproducible historical views and audit failure.
- Detection signal:
`query_as_of(core, v, tx_old)` includes a revision whose assert transaction is not visible at `tx_old`.
- Mitigation:
`INV-T9` enforces two-dimensional filtering (`valid_at` + `tx_asof`) before ranking.
`tx_visible` function excludes uncommitted/voided transactions at query time.
- Residual risk:
Clock skew impacts human-readable wall-clock interpretation, though tuple-ordered `tx_id` remains deterministic.

## FM-008: Rollback Cascade Non-Determinism

- Description:
Derived/support-dependent revisions retract differently across replicas after rollback.
- Trigger:
Traversal-order-dependent propagation over dependency graph.
- Consequence:
Replica divergence and non-reproducible lineage state.
- Detection signal:
Same rollback input produces different `auto_retracted` revision sets or event orders on different nodes.
- Mitigation:
`void_transaction` recomputes impacted revisions in deterministic fixpoint order (ascending `revision_id`) and appends canonical `auto_retracted` events.
- Residual risk:
Large dependency closures may increase recomputation cost without incremental indexing.

## FM-009: Partial-Interval Supersession Overreach

- Description:
A new revision with partially overlapping valid interval incorrectly deactivates the old revision globally.
- Trigger:
Supersession rule uses only `core_id` match and ignores interval equality.
- Consequence:
Historical segment loss and incorrect as-of answers.
- Detection signal:
Query in non-overlapping old interval segment returns null after overlap update.
- Mitigation:
`INV-T5` restricts automatic supersession to exact `(core_id, valid_interval)` matches only.
Partial-overlap cases are resolved via deterministic interval surgery projection (`INV-I1..INV-I9`) instead of destructive mutation.
- Residual risk:
If surgery is not applied, strict queries over overlap components remain intentionally ambiguous.

## FM-010: Evidence Echo Inflation

- Description:
Confidence is spuriously amplified by many near-duplicate supports from the same underlying source.
- Trigger:
Support aggregation sums or noisy-or folds raw support edges without dependence control.
- Consequence:
Overconfident observed revisions and unstable ranking under ingestion duplication.
- Detection signal:
Adding duplicate spans from one document monotonically increases confidence with no new independent source.
- Mitigation:
Group supports by `independence_key`, take `max` per group, combine groups only.
Enforced by `INV-P3`.
- Residual risk:
`independence_key` assignment quality is critical; poor source grouping can still misclassify dependence.

## FM-011: Assertion-Kind Boundary Collapse

- Description:
Observed and inferred evidence paths mix within one revision, obscuring provenance semantics.
- Trigger:
Allowing `supports` on inferred conclusions or `derived_from` conclusions on observed revisions.
- Consequence:
Non-auditable confidence explanations and policy ambiguity in rollback re-evaluation.
- Detection signal:
A revision has active incoming `supports` and active incoming `derived_from` as conclusion at the same `tx_asof`.
- Mitigation:
`INV-P4` and `INV-P5` enforce hard boundary by assertion kind.
Model dual-nature facts as separate revisions under the same `core_id`.
- Residual risk:
Operational overhead increases due additional revisions representing the same semantic core.

## FM-012: Cyclic Inference Confidence Instability

- Description:
Inference confidence depends on recursive cycles and becomes order-sensitive or non-terminating.
- Trigger:
Naive recursive confidence evaluation over `derived_from` graph with cycles.
- Consequence:
Replica divergence in confidence values and unpredictable justification state.
- Detection signal:
Confidence output differs across evaluation orders or does not reach a stable result.
- Mitigation:
Use bounded integer lattice with monotone operators and deterministic least-fixpoint iteration (`INV-P8`).
Pure unanchored cycles converge to zero confidence.
- Residual risk:
Fixpoint recomputation cost may grow with dense inference graphs unless incremental indexing is introduced.

## FM-013: Same-Rule Bridge Undercount

- Description:
Witnesses that are partly overlapping can bridge disjoint witness families into one dependence component, causing conservative under-counting.
- Trigger:
Overlap-connectivity dependence policy under one `rule_id` (`{A}`, `{A,B}`, `{B}` becomes one component).
- Consequence:
Lower confidence than epistemically warranted in bridge-heavy inference graphs.
- Detection signal:
Adding a bridge witness decreases marginal gain from otherwise disjoint witness families under one rule.
- Mitigation:
`v0.8` witness-basis qualifiers plus component-level `max` (`INV-P7`, `INV-P11..INV-P14`) prevent inflation while allowing disjoint components to accumulate.
- Residual risk:
Transitive overlap coupling can still undercount independence in dense witness graphs.

## FM-014: Arrival-Order Replica Divergence

- Description:
Replicas produce different admitted states from the same logical updates because merge/admission depends on network delivery order.
- Trigger:
Procedural replay that applies incoming updates as received, without deterministic reducer ordering.
- Consequence:
Non-convergent visibility, confidence, and query answers across replicas.
- Detection signal:
Two replicas with identical op sets compute different state digests or different `query_as_of` outputs at same `tx_asof`.
- Mitigation:
`INV-C2` + `INV-C3`: union-plus-reduce merge with deterministic reducer order (`op_id ASC`) and canonical admission precedence.
- Residual risk:
If replicas run different policy code under same declared epoch, divergence can still occur; this is an implementation governance risk.

## FM-015: Schema Epoch Split-Brain

- Description:
Cross-replica canonicalization policy mismatch silently fragments semantic identity.
- Trigger:
Ops from different normalization/invariant policy versions are merged without explicit epoch gating.
- Consequence:
Equivalent facts diverge into incompatible IDs with no explicit conflict signal.
- Detection signal:
Correlated claims/evidence cluster around near-duplicate semantic content but remain disconnected by epoch-specific IDs.
- Mitigation:
Bind every op to `schema_epoch_id` (`INV-C1`) and quarantine unsupported epochs via `CF-02` (`INV-C4`).
- Residual risk:
Backlog can accumulate if migration protocol is delayed; quarantined ops require explicit migration handling.

## FM-016: Same-ID Payload Mismatch Poison Cascade

- Description:
A key appears with divergent payload bytes (tamper, bug, or hash collision), and dependent operations become unstable.
- Trigger:
Incoming replica delta contains pre-existing ID with conflicting payload.
- Consequence:
Silent acceptance would corrupt determinism; naive overwrite would make history non-auditable.
- Detection signal:
Multiple payload fingerprints observed for one identity key.
- Mitigation:
`CF-03` deterministic poison + conflict record; dependent ops are rejected or kept pending until resolution.
- Residual risk:
Manual/operator workflow is required to resolve poisoned keys and may temporarily reduce recall.

## FM-017: Dangling Dependency Admission

- Description:
Relations/status updates are admitted before required endpoints exist.
- Trigger:
Out-of-order replication with immediate admission and no dependency gate.
- Consequence:
Broken lineage closure, unstable confidence, and non-replayable query behavior.
- Detection signal:
Admitted relation references missing or poisoned `revision_id`/`evidence_id`/`core_id`.
- Mitigation:
`CF-04` pending dependency queue with deterministic retry order and all-or-nothing admission (`INV-C6`).
- Residual risk:
Large pending queues can increase synchronization latency under heavy causal skew.

## FM-018: Stale Interval Surgery Admission

- Description:
An interval surgery plan is applied against an outdated overlap component snapshot.
- Trigger:
Component membership/interval boundaries change after planning but before surgery admission.
- Consequence:
Deterministic yet incorrect segment projection (newly admitted revisions can be clipped out).
- Detection signal:
Applied surgery references component members that do not match currently visible overlap component at admission boundary.
- Mitigation:
`apply_interval_surgery` uses compare-and-swap `basis_hash`; mismatch is rejected as `CF-09`.
- Residual risk:
High overlap churn can force repeated replanning before a surgery op is admitted.

## FM-019: Post-Surgery Winner Invalidation Hole

- Description:
Top segment winner selected by surgery later becomes unjustified/voided, potentially creating apparent gaps.
- Trigger:
Rollback or support/derivation collapse after surgery admission.
- Consequence:
Naive fixed-winner projection would return null despite valid lower-ranked alternatives.
- Detection signal:
Segment has inactive top winner while lower-ranked covering candidates remain active.
- Mitigation:
`INV-I8` requires deterministic ranked fallback to first lifecycle-active + justified candidate at query time.
- Residual risk:
If all ranked candidates become inactive, the segment legitimately resolves to null until new evidence/revision arrives.

## FM-020: Migration Chronology Inversion

- Description:
Older foreign-epoch facts migrated at a later local transaction incorrectly outrank newer local facts.
- Trigger:
Winner ranking uses migration assertion tx recency instead of preserved source chronology.
- Consequence:
Temporal precedence is distorted; exact-slot and overlap winners become semantically incorrect despite deterministic replay.
- Detection signal:
After migration, a revision with older source tx displaces a newer local revision only because migration tx is later.
- Mitigation:
`precedence_tx_id` ranking key (`INV-T10`, `INV-C15`) with optional migrated `origin_tx_id` (`INV-M10`).
Visibility remains migration-tx gated (`INV-M9`) to avoid retroactive appearance.
- Residual risk:
If source tx clocks are badly governed, chronology may still reflect upstream clock pathologies even though replay stays deterministic.
