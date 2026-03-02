# Failure Modes

Track failure classes and mitigations for the data structure design.

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

## FM-021: Stale Migration Batch Admission

- Description:
A migration plan built on one quarantine snapshot is admitted after the source set changed.
- Trigger:
No compare-and-swap validation for migration source set at apply time.
- Consequence:
Partial or wrong source coverage, non-reproducible migration state across replicas.
- Detection signal:
Applied migration references source op IDs no longer in matching open `CF-02` state or with different payload hashes.
- Mitigation:
CAS-gated `source_set_hash` and `path_policy_hash` checks in `apply_epoch_migration`; mismatch yields `CF-11`/`CF-17` and rejects batch (`INV-M7`, `INV-M8`, `INV-C13`).
- Residual risk:
High quarantine churn can cause repeated basis mismatches and operational retry overhead.

## FM-022: Migrated Projection Drift

- Description:
The same root lineage projection version drifts to conflicting target payloads across attempts/replicas.
- Trigger:
Spec/code mismatch under one declared path/policy or corrupted projection implementation.
- Consequence:
Silent drift would fracture deterministic state and break convergence.
- Detection signal:
Same deterministic projection version key `(target_epoch_id, root_source_epoch_id, root_source_op_id, policy_seq)` appears with multiple payload fingerprints.
- Mitigation:
`CF-16` poison on projection version key plus blocked source conflict resolution until mismatch is resolved (`INV-M3`, `INV-M6`, `INV-M12`, `INV-C18`).
- Residual risk:
Operator intervention is required to retire/replace bad migration specs and replay affected batches.

## FM-023: Witness Basis Tamper or Divergence

- Description:
`derived_from` witness payload carries `witness_basis_keys`/`basis_hash` that do not match deterministic lineage-based recomputation.
- Trigger:
Malicious replica payload, buggy inference emitter, or inconsistent basis derivation code under one declared epoch.
- Consequence:
Silent acceptance would allow confidence inflation or replica divergence in same-rule dependence partitioning.
- Detection signal:
Recomputed witness basis at admission boundary differs from payload basis while endpoints and `rule_id` match.
- Mitigation:
Reject with `CF-14 witness_basis_mismatch`; enforce deterministic basis verification (`INV-P12`, `INV-C16`).
- Residual risk:
Frequent mismatch bursts can increase conflict backlog and delay witness admission until emitter/spec defects are fixed.

## FM-024: Rollback-Induced Dependence Repartition

- Description:
If witness basis is recomputed dynamically at query-time, rollback can split/merge same-rule dependence components and produce counterintuitive confidence jumps.
- Trigger:
Dependence classification derived from mutable current lineage instead of immutable witness assertion snapshot.
- Consequence:
Non-intuitive confidence trajectories and potential replay disagreement across partial states.
- Detection signal:
Voiding shared support causes component topology change for previously admitted unchanged witnesses.
- Mitigation:
`v0.8` stores immutable assertion-time witness basis qualifiers on `derived_from` and uses rollback to affect witness strength only through premise confidence.
- Residual risk:
Assertion-time snapshots do not retroactively capture newly discovered provenance overlap; this is a conservative modeling boundary.

## FM-025: Multi-Hop Path Selection Drift

- Description:
Replicas choose different migration paths for the same `(source_epoch_id, target_epoch_id, source_op_id)` under equivalent admitted data.
- Trigger:
Path selection depends on arrival order or non-canonical traversal instead of deterministic policy/ranking.
- Consequence:
Projection mismatch, non-convergent migration lineage, and divergent query outputs.
- Detection signal:
Equivalent replicas produce different path manifests or projected version keys for the same source batch.
- Mitigation:
`EpochPathPolicy` + deterministic selector (`hop_count`, `path_fingerprint`) and convergence invariant `INV-C17`.
- Residual risk:
Only one selector family (`shortest_path_spec_lex_v1`) is currently standardized.

## FM-026: Cross-Path Non-Confluent Projection

- Description:
Two admissible paths for the same root lineage and policy produce divergent projected payload bytes.
- Trigger:
Non-confluent projector composition across migration specs or spec implementation defect.
- Consequence:
Silent acceptance would fracture deterministic state and break source-conflict closure.
- Detection signal:
Same projection version key `(target_epoch_id, root_source_epoch_id, root_source_op_id, policy_seq)` appears with different payload hashes.
- Mitigation:
Deterministic poison conflict `CF-16`; keep linked source `CF-02` unresolved until operator/spec correction.
- Residual risk:
Resolution requires migration spec governance and replay of affected batches.

## FM-027: Policy Cutover Stale Admission

- Description:
Migration plan computed under one path policy is applied after policy cutover, admitting outdated path decisions.
- Trigger:
No policy snapshot CAS check at migration admission boundary.
- Consequence:
Mixed-policy projections and replay drift across replicas that observe policy updates at different times.
- Detection signal:
Applied migration record references path policy metadata that differs from active policy at apply tx.
- Mitigation:
`path_policy_hash` compare-and-swap gating with rejection conflict `CF-17`.
- Residual risk:
High policy churn can increase rejected-plan retries.

## FM-028: Compaction Semantic Mutation

- Description:
Compaction incorrectly alters effective fact winners instead of only cleaning migration metadata.
- Trigger:
Compaction rewrites or deletes active projection versions without deterministic winner-preservation checks.
- Consequence:
Query regressions and history-dependent visibility differences across replicas.
- Detection signal:
`query_as_of` outputs change after compaction tx despite no new revision/support/derivation admissions.
- Mitigation:
Metadata-only compaction invariant (`INV-M15`) plus CAS basis check (`CF-18`) and idempotence requirement (`INV-M17`).
- Residual risk:
Physical garbage-collection policy is still open; unsafe operational scripts could bypass compaction invariants if not constrained.

## FM-029: Interval Strategy Cutover Retroactive Drift

- Description:
New interval strategy policy appears to retroactively rewrite older query answers for overlap components.
- Trigger:
Candidate ranking is recomputed at query-time from latest policy instead of selecting an admitted surgery record bound to its original policy snapshot.
- Consequence:
Historical `query_as_of` outputs drift and replicas can disagree during policy propagation windows.
- Detection signal:
For fixed `tx_asof` before cutover tx, overlap winner changes after cutover policy is admitted.
- Mitigation:
Bind surgery records to immutable `policy_seq` and select winners by `(policy_seq DESC, tx_id DESC, surgery_id ASC)` only among tx-visible records (`INV-I7`, `INV-I15`, `INV-C11`, `INV-C21`).
- Residual risk:
Frequent cutovers increase operational complexity and re-surgery overhead for active overlap components.

## FM-030: Stale Interval Policy Plan Admission

- Description:
Surgery plan computed under one interval strategy policy is admitted after policy cutover.
- Trigger:
No policy snapshot compare-and-swap check at `apply_interval_surgery`.
- Consequence:
Mixed-policy overlap resolution and replay divergence across replicas with different policy-arrival timing.
- Detection signal:
Admitted surgery record references policy metadata that differs from active policy hash at admission boundary.
- Mitigation:
`strategy_policy_hash` CAS gate with deterministic rejection conflict `CF-19` (`INV-I12`, `INV-C22`).
- Residual risk:
High policy churn can cause repeated planning retries.

## FM-031: Inadmissible Interval Rank Inputs

- Description:
Interval strategy uses non-deterministic or unsupported rank inputs (for example model-only scores), breaking replay guarantees.
- Trigger:
Weak validation of `strategy_id`/rank tuple schema against admissibility profile.
- Consequence:
Replica-specific ranking divergence even with identical admitted base ops.
- Detection signal:
Equivalent replicas produce different segment rank tuples for one component and `plan_tx_asof`.
- Mitigation:
Deterministic admissibility validation against `deterministic_interval_rank_inputs_v1`; reject policy/surgery as `CF-20` (`INV-I11`, `INV-C23`).
- Residual risk:
Narrow admissibility profiles may limit domain-specific strategy expressiveness.

## FM-032: Non-Confluent Interval Strategy Projection

- Description:
Equivalent surgery signatures produce divergent `segment_plan` payloads across planners/replicas.
- Trigger:
Implementation drift or spec bug generates different plans for same `surgery_projection_key`.
- Consequence:
Silent dual-plan admission would create unstable overlap winners and audit ambiguity.
- Detection signal:
Same deterministic `surgery_projection_key` observed with multiple segment-plan hashes.
- Mitigation:
Deterministic poison conflict `CF-21`; block component resolution until confluence is restored (`INV-I14`, `INV-C24`).
- Residual risk:
Resolution requires strategy implementation governance and replay of affected surgery attempts.

## FM-033: Stale Retention Policy Apply

- Description:
Retention GC plan computed under one policy snapshot is applied after retention policy cutover.
- Trigger:
No policy-CAS validation at `apply_retention_gc`.
- Consequence:
Mixed-policy reclamation and replay drift across replicas with different policy-arrival timing.
- Detection signal:
Applied GC batch references policy metadata that differs from active policy hash at admission boundary.
- Mitigation:
`retention_policy_hash` compare-and-swap gate with deterministic rejection conflict `CF-22` (`INV-G5`, `INV-C26`).
- Residual risk:
High policy churn can increase rejected-plan retries.

## FM-034: Stale Retention Candidate Set Apply

- Description:
Retention plan admits after candidate eligibility changes (new supersession/compaction/rollback), reclaiming incorrect keys.
- Trigger:
No basis-CAS validation for candidate set at GC apply boundary.
- Consequence:
Partial or invalid reclamation, non-reproducible retention state across replicas.
- Detection signal:
Applied batch references keys whose deterministic eligibility no longer matches current visible state.
- Mitigation:
`gc_basis_hash` compare-and-swap gate with deterministic rejection conflict `CF-23` (`INV-G6`, `INV-C26`).
- Residual risk:
High churn in dominated/superseded sets can increase planning retries.

## FM-035: Non-Rehydratable Reclaim

- Description:
GC reclaims an artifact that cannot be deterministically reconstructed from retained lineage/spec state.
- Trigger:
Eligibility checks ignore proof-profile requirements or missing upstream dependencies.
- Consequence:
Historical replay/audit requests for reclaimed keys fail or require non-deterministic/manual reconstruction.
- Detection signal:
Reclaimed key has no valid deterministic rehydration manifest closure under current proof profile.
- Mitigation:
Mandatory proof-profile gating (`rehydratable_from_retained_lineage_v1`) at apply boundary; reject as `CF-24` (`INV-G7`).
- Residual risk:
Proof-profile scope is currently narrow and may need extension for additional artifact classes.

## FM-036: Rehydration Hash Drift

- Description:
On-demand rehydration for reclaimed artifact produces bytes that differ from stored canonical payload hash.
- Trigger:
Projector/strategy implementation drift, manifest tamper, or corrupted retained lineage input.
- Consequence:
Silent acceptance would break replay determinism and audit trust.
- Detection signal:
`H(rehydrated_payload_bytes) != artifact_payload_hash` for visible reclaim stub.
- Mitigation:
Deterministic poison conflict `CF-25`; block artifact key until corrected lineage/spec state is admitted (`INV-G8`, `INV-G11`, `INV-C27`).
- Residual risk:
Resolution requires operator/spec governance and potentially replay of affected retention batches.

## FM-037: Bridge-Coupled Witness Undercount

- Description:
Same-rule witness overlap connectivity can collapse partially independent families into one conservative bucket when bridge witnesses share anchors with both sides.
- Trigger:
Rule-local dependence modeled only as transitive overlap components with single component `max`.
- Consequence:
Inference confidence can be systematically under-sensitive even when anchor evidence families are partly independent.
- Detection signal:
Bridge chain (`{A}`, `{A,B}`, `{B}`) yields same contribution as one global `max` despite strong disjoint anchor support on both ends.
- Mitigation:
`v0.12` bridge-safe aggregation: deterministic witness anchor-mass split, per-anchor `max(alloc_bp)`, anchor noisy-or, and strongest-witness floor (`INV-P13..INV-P15`, `INV-C29`).
- Residual risk:
Quality depends on upstream `independence_key` fidelity; poor anchor keying can still misrepresent true dependence.

## FM-038: Multi-Anchor Dilution Regression

- Description:
Pure anchor-noisy-or aggregation can dilute a lone strong multi-anchor witness below its own witness confidence.
- Trigger:
Rule contribution computed only from split anchor masses without strongest-witness lower bound.
- Consequence:
Counterintuitive confidence regression for conclusions supported by one high-quality composite witness.
- Detection signal:
Single witness with basis `{A,B,C}` yields rule contribution lower than its `witness_bp`.
- Mitigation:
Strongest-witness floor:
`rule_bp = max(strongest_witness_bp, anchor_or_bp)` (`INV-P15`).
- Residual risk:
Composite witnesses remain conservative when mixed with sentinel witnesses due intentional fallback behavior.

## FM-039: Sentinel Leakage Inflation

- Description:
If sentinel-basis witnesses are combined with anchor-noisy-or, unknown-dependence witnesses can spuriously accumulate with anchored witnesses.
- Trigger:
Aggregation pipeline treats `RULE::<rule_id>::DEPENDENT` as a regular anchor instead of uncertainty lock.
- Consequence:
Confidence inflation under unknown-dependence conditions and reduced trust in provenance bounds.
- Detection signal:
Rule bucket containing any sentinel witness still returns contribution above bucket `max(witness_bp)`.
- Mitigation:
Sentinel lock rule:
presence of any sentinel witness forces conservative `max(witness_bp)` for that rule bucket (`INV-P16`).
- Residual risk:
Can undercount when sentinel appears alongside genuinely independent anchored witnesses; this is an intentional safety bias.

## FM-040: Base Semantic-Kernel Reclaim Drift

- Description:
Retention reclaims base-record fields that are part of deterministic semantic/inference kernels.
- Trigger:
Weak boundary between reclaimable payload surface and required kernel fields (`ClaimRevision`, `EvidenceAtom`, `RuleRecord`).
- Consequence:
`query_as_of` or inference outputs change after physical GC, violating replay invariants.
- Detection signal:
For equal admitted op/conflict sets, reclaiming one base key changes query/inference result before any rollback or new assertion.
- Mitigation:
Deterministic kernel-profile checks with immutable `semantic_kernel_hash`; reject violating candidates as `CF-26` (`INV-G13`, `INV-G15`, `INV-C30`).
- Residual risk:
Kernel profile updates require careful epoch governance to avoid accidental tightening/loosening during migrations.

## FM-041: Base Capsule Eligibility Mismatch

- Description:
Base payload candidate is reclaimed without a matching deterministic capsule lineage.
- Trigger:
Missing/divergent `BasePayloadCapsuleRecord` hash, manifest, or codec profile at apply boundary.
- Consequence:
Rehydration failures and replica divergence risk under asymmetric capsule visibility.
- Detection signal:
Retention plan/apply references base artifact whose capsule tuple does not match admitted capsule record.
- Mitigation:
Base capsule validation gate with deterministic rejection/conflict `CF-27`; convergence bound by `INV-G14`, `INV-C31`.
- Residual risk:
Current codec/profile family breadth is still narrow, which can constrain operational flexibility despite deterministic multi-profile governance.

## FM-042: Rule Execution Cold-Path Dependency

- Description:
Rule execution bytes are reclaimed, making inference evaluation depend on runtime rehydration instead of retained deterministic kernel state.
- Trigger:
Treating entire `RuleRecord` as reclaimable payload.
- Consequence:
Inference may fail/open conflicts under payload residency variation despite identical admitted op sets.
- Detection signal:
Inference result changes when rule payload is physically reclaimed but no logical admissions changed.
- Mitigation:
Pin rule execution fields (`rule_logic_hash`, `rule_dsl_ast_hash`, reliability metadata) inside non-reclaimable kernel (`INV-G15`, `INV-C30`); reject violations as `CF-26`.
- Residual risk:
Large executable kernels can still pressure hot storage until rule-kernel compaction strategy is specified.

## FM-043: Capsule Orphaning by Void

- Description:
A capsule referenced by visible reclaimed base payload keys is voided, orphaning retention stubs.
- Trigger:
Rollback of capsule transaction without dependency pin checks.
- Consequence:
Deterministic rehydration becomes impossible for affected keys and historical reads degrade to conflict/error state.
- Detection signal:
Visible reclaimed base key has no visible matching capsule lineage at `tx_asof`.
- Mitigation:
Capsule pinning invariant (`INV-G17`) rejects orphaning void attempts via invariant gate (`CF-05`); read-time mismatch still surfaces as `CF-27`.
- Residual risk:
Operator workflows need explicit tooling for safe capsule lifecycle management and pin-aware rollback inspection.

## FM-044: Cache Policy Drift Reclaim Admission

- Description:
Base payload GC plan is admitted under a stale cache policy snapshot, so reclaimed keys may not have valid bounded-latency lease guarantees.
- Trigger:
`apply_retention_gc` or cache-lease apply does not CAS-check active `CapsuleCachePolicy` hash at admission boundary.
- Consequence:
Replica-dependent cache prerequisites and inconsistent bounded-latency behavior for equal admitted data state.
- Detection signal:
Applied base-class reclaim references `cache_policy_hash` different from active policy at same `tx_asof`.
- Mitigation:
Policy CAS gate with deterministic rejection `CF-28`; convergence bound by `INV-C33`, `INV-C34`, `INV-G21`.
- Residual risk:
Frequent policy churn can increase rejected plan retries and operational planning overhead.

## FM-045: Nondeterministic Eviction of Pinned Capsules

- Description:
Cache eviction removes a capsule still needed by visible reclaimed base payload keys.
- Trigger:
Local runtime eviction (LRU/pressure-based) bypasses deterministic pinned-key eligibility checks.
- Consequence:
One replica may violate bounded-latency contract while another keeps warm residency, creating operational divergence despite identical logical state.
- Detection signal:
Visible reclaimed key references capsule whose effective lease state is evicted under active bounded profile.
- Mitigation:
Deterministic pin-safe eviction guard (`pin_if_reclaimed_v1`) with explicit rejection `CF-30`; protected by `INV-G20`, `INV-C36`.
- Residual risk:
Warm-tier memory pressure can grow; requires future deterministic tiering profiles.

## FM-046: Lease Image Confluence Break

- Description:
Equivalent cache lease identity is admitted with divergent warm image bytes/hashes.
- Trigger:
Missing confluence checks for `(capsule_id, policy_seq, lease_seq)` or weak hash verification for warm-tier payload bytes.
- Consequence:
Replica-specific rehydration bytes, audit instability, and potential silent corruption of reclaimed read path.
- Detection signal:
Same lease identity appears with multiple `cache_image_hash` values or warm bytes fail hash check against capsule payload hash.
- Mitigation:
Deterministic poison conflict `CF-31` plus hash-verification invariant gates (`INV-C35`, `INV-G22`).
- Residual risk:
Recovery requires corrective lease lineage admission and may temporarily block affected reclaimed reads.

## FM-047: Capsule Profile Policy Drift Admission

- Description:
Base retention/cache/rotation operation is admitted under a stale capsule profile policy snapshot.
- Trigger:
Missing `profile_policy_hash` CAS checks at `upsert_base_payload_capsule`, `apply_retention_gc`, `apply_capsule_cache_lease`, or `apply_capsule_profile_rotation`.
- Consequence:
Replica-dependent codec/key admissibility decisions and non-reproducible rehydrate behavior.
- Detection signal:
Admitted operation references profile metadata that differs from active `CapsuleProfilePolicy` hash at admission boundary.
- Mitigation:
Profile policy CAS gate with deterministic rejection `CF-32`; convergence bound by `INV-C38`, `INV-G26`.
- Residual risk:
Frequent profile cutovers can increase rejected-plan retries and coordination overhead.

## FM-048: Stale Capsule Rotation Basis Apply

- Description:
Capsule profile rotation plan is applied after reclaimed-key binding set changes.
- Trigger:
No deterministic `rotation_basis_hash` verification at apply boundary.
- Consequence:
Partial rebinding, order-dependent effective capsule tuples, and replay drift.
- Detection signal:
Rotation apply tuple set differs from recomputed visible candidate set at same `tx_asof`.
- Mitigation:
Basis CAS gate with deterministic rejection `CF-33` (`INV-C39`, `INV-G27`).
- Residual risk:
High reclaim/rollback churn can increase replanning frequency.

## FM-049: Inadmissible Codec/Key Tuple Admission

- Description:
Capsule or lease path uses codec/key tuple outside active compatibility set.
- Trigger:
Weak validation of `(codec_profile_id, key_epoch_seq)` against active profile `read_compat_tuples`.
- Consequence:
Reads fail or diverge by replica depending on local codec/key availability.
- Detection signal:
Visible effective capsule tuple is absent from active compatibility set.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-34` rejection/conflict (`INV-C40`, `INV-G29`).
- Residual risk:
Narrow profile catalogs can force conservative compatibility windows and slower retirement.

## FM-050: Capsule Rotation Confluence Break

- Description:
Equivalent rotation projection identity is admitted with divergent target capsule payload bytes.
- Trigger:
Missing confluence checks for `rotation_projection_key` or nondeterministic transcode/rewrap implementation.
- Consequence:
Replica-specific effective capsule bindings and rehydration drift.
- Detection signal:
Same `rotation_projection_key` appears with multiple target payload hashes/capsule tuples.
- Mitigation:
Deterministic poison conflict `CF-35` with payload-hash-preservation checks (`INV-C41`, `INV-G30`).
- Residual risk:
Recovery requires corrective rotation lineage and may block affected reclaimed reads until resolved.

## FM-051: Premature Compatibility Retirement

- Description:
Profile cutover retires a codec/key compatibility tuple still referenced by visible reclaimed keys or active warm leases.
- Trigger:
No retirement guard on `upsert_capsule_profile_policy` when shrinking compatibility set.
- Consequence:
Reclaimed-key reads fail after cutover despite unchanged logical admitted fact state.
- Detection signal:
New active policy excludes tuple that still appears in effective binding or lease state.
- Mitigation:
Deterministic retirement guard with explicit rejection `CF-36` (`INV-C42`, `INV-G31`).
- Residual risk:
Long-lived pinned keys can delay key-epoch retirement and increase warm-tier pressure.

## FM-052: Tier-Family Policy Drift Admission

- Description:
Tier-governed retention/cache/profile operation is admitted under a stale workload-tier family snapshot.
- Trigger:
Missing `tier_family_policy_hash` CAS checks at tier assignment or tier-governed apply boundaries.
- Consequence:
Replica-dependent effective member policy selection for reclaimed keys and non-reproducible operational behavior.
- Detection signal:
Admitted operation references tier family metadata that differs from active `CapsuleTierPolicyFamily` hash at admission boundary.
- Mitigation:
Tier-family policy CAS gate with deterministic rejection `CF-37`; convergence bounded by `INV-C44`, `INV-C45`, `INV-G34`.
- Residual risk:
Frequent family cutovers can increase planning retries and operational coordination overhead.

## FM-053: Stale Tier Assignment Basis Apply

- Description:
Tier assignment plan is applied after reclaimed-key candidate set or selector features changed.
- Trigger:
No deterministic `tier_basis_hash` and `assignment_seq` verification at apply boundary.
- Consequence:
Partial or order-dependent effective tier placement and replay drift in member-policy bindings.
- Detection signal:
Assignment apply tuples differ from recomputed candidate/feature set at same `tx_asof`.
- Mitigation:
Basis CAS gate with deterministic rejection `CF-38` (`INV-C45`, `INV-G34`, `INV-G35`).
- Residual risk:
High reclaim/rollback churn can increase replanning frequency.

## FM-054: Inadmissible Tier/Member-Policy Binding

- Description:
Reclaimed key is assigned to a tier whose referenced member cache/profile policies are missing or selector/admissibility constraints are violated.
- Trigger:
Weak validation of `tier_id` assignment against selector/admissibility profiles and visible member-policy lineage.
- Consequence:
Incorrect effective policy binding, potential incompatible tuple use, and operational divergence.
- Detection signal:
Visible assignment tuple fails selector predicate proof or points to unknown/incompatible member policy hashes.
- Mitigation:
Deterministic assignment admissibility enforcement with explicit `CF-39` rejection/conflict (`INV-C46`, `INV-G36`).
- Residual risk:
Current admissibility family breadth is narrow and may require richer profiles for complex domains.

## FM-055: Tier Cost Overflow Heuristic Drift

- Description:
Budget overflow is resolved by runtime-local heuristics instead of canonical bounded placement.
- Trigger:
No deterministic enforcement of per-tier `max_warm_bytes`, `max_rotate_bytes`, `max_rehydrate_ops`.
- Consequence:
Replica-dependent demotion/eviction decisions under pressure for identical admitted state.
- Detection signal:
Equivalent admitted op/conflict sets show different effective tier assignments or budget utilization without explicit conflicts.
- Mitigation:
Deterministic bounded placement profile with explicit overflow-tier rule or deterministic rejection `CF-40`; no local heuristic fallback (`INV-C47`, `INV-G37`).
- Residual risk:
Tight budgets may increase conflict rates and require policy tuning cadence.

## FM-056: Tier Assignment Confluence Break

- Description:
Equivalent tier projection identity is admitted with divergent assignment payload bytes.
- Trigger:
Missing confluence checks for `tier_projection_key` or nondeterministic selector/cost serialization.
- Consequence:
Replica-specific effective tier/member-policy history and unstable audit replay.
- Detection signal:
Same `tier_projection_key` appears with multiple `(tier_id, utility, predicted_costs)` payload variants.
- Mitigation:
Deterministic poison conflict `CF-41` plus confluence invariants (`INV-C48`, `INV-G38`).
- Residual risk:
Recovery requires corrected assignment lineage and may temporarily block affected reclaimed keys.

## FM-057: Tier Telemetry Policy Drift Admission

- Description:
Telemetry-governed tier operation is admitted under a stale telemetry policy snapshot.
- Trigger:
Missing `tier_telemetry_policy_hash` CAS checks at telemetry/utility/assignment/retention apply boundaries.
- Consequence:
Replica-dependent utility derivation and assignment outcomes for identical admitted logical state.
- Detection signal:
Admitted operation references telemetry policy metadata that differs from active `CapsuleTierTelemetryPolicy` hash at admission boundary.
- Mitigation:
Telemetry-policy CAS gate with deterministic rejection `CF-42`; convergence bounded by `INV-C50`, `INV-C51`, `INV-G40`, `INV-G41`.
- Residual risk:
Frequent telemetry-policy cutovers can increase replanning frequency and operational coordination overhead.

## FM-058: Stale Tier Telemetry/Utility Basis Apply

- Description:
Telemetry or utility plan is applied after canonical telemetry window aggregates changed.
- Trigger:
No deterministic `telemetry_basis_hash`/`utility_basis_hash` verification at apply boundary.
- Consequence:
Partial or order-dependent utility state and replay drift in tier placement.
- Detection signal:
Telemetry/utility apply tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-43` (`INV-C51`, `INV-G41`).
- Residual risk:
Late-arriving admissible telemetry rows can increase invalidated plans during high-ingest windows.

## FM-059: Inadmissible Tier Telemetry Ingestion

- Description:
Telemetry aggregates with invalid windows, observer buckets, or request dedupe serialization are admitted.
- Trigger:
Weak telemetry admissibility validation during `apply_capsule_tier_telemetry`/`apply_capsule_tier_utility`.
- Consequence:
Utility derives from non-canonical evidence and can diverge across replicas.
- Detection signal:
Admitted telemetry tuple fails active window/admissibility profile checks or deterministic dedupe replay.
- Mitigation:
Deterministic telemetry admissibility enforcement with explicit `CF-44` rejection/conflict (`INV-C52`, `INV-G42`).
- Residual risk:
Upstream instrumentation bugs can temporarily reduce telemetry coverage and force conservative utility fallback.

## FM-060: Tier Utility Confluence Break

- Description:
Equivalent utility projection identity is admitted with divergent utility payload bytes.
- Trigger:
Missing confluence checks for `utility_projection_key` or nondeterministic utility serialization.
- Consequence:
Replica-specific utility ordering and unstable tier assignment history.
- Detection signal:
Same `utility_projection_key` appears with multiple `(utility_bp, anti_gaming_penalty_bp, observer-share)` payload variants.
- Mitigation:
Deterministic poison conflict `CF-45` plus utility confluence invariants (`INV-C53`, `INV-G45`).
- Residual risk:
Recovery requires corrected utility lineage and may temporarily block affected keys from telemetry-backed reassignment.

## FM-061: Utility Gaming Through Observer Dominance

- Description:
One observer (or effectively one canonical observer bucket) inflates utility to capture scarce high-tier budget.
- Trigger:
Utility derivation omits deterministic per-observer cap, dominant-share cap, or distinct-observer floor checks.
- Consequence:
Deterministic but unfair starvation of broad workload keys; operational regressions under adversarial traffic.
- Detection signal:
High utility keys show dominant observer share above profile cap or diversity below profile floor after normalization.
- Mitigation:
Deterministic anti-gaming guard enforcement with explicit rejection `CF-46` and capped utility normalization (`INV-C54`, `INV-G44`).
- Residual risk:
Anti-gaming strength depends on upstream observer identity canonicalization quality and Sybil resistance at source.

## FM-062: Global Budget Policy Drift Admission

- Description:
Budget-governed apply operations are admitted under a stale global policy snapshot.
- Trigger:
Missing `global_budget_policy_hash` CAS checks at `apply_capsule_global_budget_arbitration`, `apply_capsule_tier_assignment`, `apply_capsule_cache_lease`, `apply_capsule_profile_rotation`, or `apply_retention_gc`.
- Consequence:
Replica-dependent class envelope interpretation and non-reproducible cross-class allocation outcomes.
- Detection signal:
Admitted operation references global budget policy metadata that differs from active `CapsuleGlobalBudgetPolicy` hash at admission boundary.
- Mitigation:
Global-budget policy CAS gate with deterministic rejection `CF-47`; convergence bounded by `INV-C56`, `INV-C57`, `INV-G47`, `INV-G48`.
- Residual risk:
Frequent policy cutovers can increase replanning churn and coordination overhead.

## FM-063: Stale Global Budget Basis Apply

- Description:
Global arbitration or budget-governed class transition is applied after class demand summary changed.
- Trigger:
No deterministic `global_budget_basis_hash` and `arbitration_seq` verification at apply boundary.
- Consequence:
Order-dependent class envelopes and replay drift in downstream tier/cache/profile/reclaim decisions.
- Detection signal:
Arbitration/apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-48` (`INV-C57`, `INV-G48`, `INV-G49`).
- Residual risk:
Late utility updates can invalidate plans at high cadence.

## FM-064: Inadmissible Global Budget Payload

- Description:
Global budget policy or arbitration payload with invalid class tuples is admitted.
- Trigger:
Weak validation of class weight tables, SLA floors, or profile IDs.
- Consequence:
Impossible or ambiguous envelope math and divergent allocation behavior across replicas.
- Detection signal:
Policy/arbitration tuple violates cap/floor constraints or uses unsupported profile IDs but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-49` rejection (`INV-C58`, `INV-G50`).
- Residual risk:
Profile family breadth is narrow and may force conservative policies.

## FM-065: Global Budget Projection Confluence Break

- Description:
Equivalent class envelope projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `global_budget_projection_key` or nondeterministic arbitration serialization.
- Consequence:
Replica-specific class envelopes and unstable downstream assignment/lease/rotation history.
- Detection signal:
Same `global_budget_projection_key` appears with multiple allocation payload variants.
- Mitigation:
Deterministic poison conflict `CF-50` plus confluence invariants (`INV-C59`, `INV-G52`).
- Residual risk:
Recovery requires corrected arbitration lineage and may temporarily block affected classes.

## FM-066: Cross-Class Envelope Starvation or Oversubscription

- Description:
Class/global budget envelopes are violated or SLA floors are starved during concurrent class transitions.
- Trigger:
Tier/lease/rotation/reclaim admission ignores active class/global envelope totals or floor precedence.
- Consequence:
Deterministic but unfair starvation, or overcommitted budgets that force runtime-local clipping.
- Detection signal:
Effective class/global utilization exceeds allocated envelope, or lower-priority classes consume budget while higher-priority SLA floors are unmet.
- Mitigation:
Deterministic envelope guard with explicit rejection `CF-51`; enforced by `INV-C60`, `INV-C65`, `INV-G51`, `INV-G53`, and `INV-G60`.
- Residual risk:
Short-window envelopes can still oscillate if utilization summaries are noisy or delayed despite long-horizon memory controls.

## FM-067: Global Budget Memory Policy Drift Admission

- Description:
Budget-memory-governed apply operations are admitted under a stale long-horizon memory policy snapshot.
- Trigger:
Missing `global_budget_memory_policy_hash` CAS checks at `apply_capsule_global_budget_memory`, `apply_capsule_global_budget_arbitration`, or budget-governed tier/cache/profile/retention apply boundaries.
- Consequence:
Replica-dependent debt/credit interpretation and non-reproducible cross-window arbitration outcomes.
- Detection signal:
Admitted operation references memory policy metadata that differs from active `CapsuleGlobalBudgetMemoryPolicy` hash at admission boundary.
- Mitigation:
Memory-policy CAS gate with deterministic rejection `CF-52`; convergence bounded by `INV-C61`, `INV-C62`, `INV-G54`, `INV-G55`.
- Residual risk:
Frequent memory-policy cutovers can increase replanning churn and coordination overhead.

## FM-068: Stale Global Budget Memory Basis Apply

- Description:
Memory or memory-aware arbitration plan is applied after canonical transition inputs changed.
- Trigger:
No deterministic `global_budget_memory_basis_hash` + `memory_seq` verification at apply boundary.
- Consequence:
Order-dependent debt/credit tuples and replay drift in downstream class envelope priorities.
- Detection signal:
Memory/arbitration apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-53` (`INV-C62`, `INV-G55`, `INV-G56`).
- Residual risk:
Late utilization updates can invalidate plans at high cadence.

## FM-069: Inadmissible Global Budget Memory Payload

- Description:
Long-horizon memory policy or record payload with invalid caps/decay tuples is admitted.
- Trigger:
Weak validation of cap ranges, decay ratios, supported profile IDs, or canonical tuple serialization.
- Consequence:
Ambiguous/unstable memory transitions and divergent long-horizon arbitration behavior across replicas.
- Detection signal:
Memory policy/record tuple violates profile constraints or canonical encoding but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-54` rejection (`INV-C63`, `INV-G57`).
- Residual risk:
Memory profile family breadth is narrow and may force conservative tuning.

## FM-070: Global Budget Memory Projection Confluence Break

- Description:
Equivalent memory projection identity is admitted with divergent debt/credit payload bytes.
- Trigger:
Missing confluence checks for `memory_projection_key` or nondeterministic memory serialization.
- Consequence:
Replica-specific memory tuples and unstable long-horizon class priority history.
- Detection signal:
Same `memory_projection_key` appears with multiple `(deficit_carry_bp, burst_credit_bp, sla_debt_bp)` payload variants.
- Mitigation:
Deterministic poison conflict `CF-55` plus memory confluence invariants (`INV-C64`, `INV-G58`).
- Residual risk:
Recovery requires corrected memory lineage and may temporarily block affected class arbitration paths.

## FM-071: Invalid Long-Horizon Transition or Rollback

- Description:
Applied memory/arbitration transitions violate deterministic carryover/decay/repayment equations or rollback precedence restoration.
- Trigger:
Transition validation omits deterministic equation checks, cap clamps, or rollback lineage constraints.
- Consequence:
Deterministic but incorrect debt/credit accumulation, unfair starvation/burst capture, or rollback divergence.
- Detection signal:
Observed next memory tuple cannot be derived from prior tuple + canonical transition inputs under active memory policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-56`; enforced by `INV-C63`, `INV-C65`, `INV-G57`, `INV-G59`, `INV-G60`.
- Residual risk:
Transition quality still depends on upstream utilization summarization fidelity and late-window reconciliation quality.

## FM-072: Utilization Attestation Policy Drift Admission

- Description:
Utilization-governed operations are admitted under a stale utilization-attestation policy snapshot.
- Trigger:
Missing `utilization_attestation_policy_hash` CAS checks at utilization/memory/arbitration or budget-governed apply boundaries.
- Consequence:
Replica-dependent utilization lineage and non-reproducible memory/arbitration transitions.
- Detection signal:
Admitted operation references utilization policy metadata that differs from active `CapsuleUtilizationAttestationPolicy` hash at admission boundary.
- Mitigation:
Utilization-policy CAS gate with deterministic rejection `CF-57`; convergence bounded by `INV-C66`, `INV-C67`, `INV-G61`, `INV-G62`.
- Residual risk:
Frequent utilization-policy cutovers can increase replanning churn and coordination overhead.

## FM-073: Stale Utilization Attestation/Reconciliation Basis Apply

- Description:
Utilization attestation, reconciliation, or utilization-aware memory/arbitration plan is applied after canonical attestation evidence changed.
- Trigger:
No deterministic `utilization_basis_hash`/`reconciliation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent utilization tuples and replay drift in downstream debt/credit/envelope state.
- Detection signal:
Attestation/reconciliation/memory/arbitration apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-58` (`INV-C67`, `INV-G62`, `INV-G64`).
- Residual risk:
Late admissible evidence bursts can invalidate plans at high cadence.

## FM-074: Inadmissible Utilization Attestation Payload

- Description:
Utilization attestation/reconciliation payload with invalid window, quorum proof, or tuple encoding is admitted.
- Trigger:
Weak validation of window closure constraints, attester quorum proofs, supported profile IDs, or canonical serialization.
- Consequence:
Tamperable utilization lineage and divergent memory/arbitration outcomes across replicas.
- Detection signal:
Attestation tuple violates active policy constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-59` rejection (`INV-C68`, `INV-G63`).
- Residual risk:
Attester identity canonicalization and signing infrastructure quality still bound operational robustness.

## FM-075: Utilization Projection Confluence Break

- Description:
Equivalent attestation/reconciliation projection identity is admitted with divergent utilization payload bytes.
- Trigger:
Missing confluence checks for `attestation_projection_key`/`reconciliation_projection_key` or nondeterministic utilization serialization.
- Consequence:
Replica-specific effective utilization tuples and unstable memory/arbitration histories.
- Detection signal:
Same projection key appears with multiple utilization payload variants.
- Mitigation:
Deterministic poison conflict `CF-60` plus confluence invariants (`INV-C69`, `INV-G65`).
- Residual risk:
Recovery requires corrected utilization lineage and may temporarily block affected class budgeting paths.

## FM-076: Late-Window Reconciliation Guard Violation

- Description:
Late reconciliation is applied outside policy grace bounds or with duplicate/non-monotonic carry-forward lineage.
- Trigger:
Reconciliation admission omits deterministic grace-window checks, carry-forward monotonicity checks, or delta-cap enforcement.
- Consequence:
Double-counted or stale corrections, unfair debt/credit drift, and replay divergence under rollback.
- Detection signal:
Reconciliation tuple cannot be derived from active policy and prior lineage, or applies to window beyond allowed grace horizon.
- Mitigation:
Deterministic late-window guard with explicit rejection `CF-61`; enforced by `INV-C68`, `INV-C70`, `INV-G66`, `INV-G67`.
- Residual risk:
Aggressive grace windows can increase conflict volume during delayed ingestion periods.

## FM-077: Attester Trust Policy Drift Admission

- Description:
Attester-governed utilization/memory/arbitration operations are admitted under a stale attester-trust policy snapshot.
- Trigger:
Missing `attester_trust_policy_hash` CAS checks at attester rotation/continuity, utilization attestation, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent attester roster semantics and non-reproducible quorum/cutover outcomes.
- Detection signal:
Admitted operation references attester-trust policy metadata that differs from active `CapsuleAttesterTrustPolicy` hash at admission boundary.
- Mitigation:
Attester-policy CAS gate with deterministic rejection `CF-62`; convergence bounded by `INV-C71`, `INV-C72`, `INV-G68`, `INV-G69`.
- Residual risk:
Frequent attester-policy cutovers can increase replanning churn and coordination overhead.

## FM-078: Stale Attester Set/Continuity Basis Apply

- Description:
Attester rotation/continuity or utilization-governed plan is applied after canonical attester lineage changed.
- Trigger:
No deterministic `attester_set_basis_hash`/`attester_continuity_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent quorum/cutover interpretation and replay drift in downstream utilization/memory/arbitration lineage.
- Detection signal:
Rotation/continuity/utilization apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-63` (`INV-C72`, `INV-G69`, `INV-G71`).
- Residual risk:
Late admissible continuity evidence can invalidate queued plans at high cadence.

## FM-079: Inadmissible Attester Rotation/Continuity Payload

- Description:
Attester policy/rotation/continuity payload with invalid identity binding, trust-tier tuple, key epoch, or proof envelope is admitted.
- Trigger:
Weak validation of attester roster canonicalization, trust-tier bounds, profile IDs, key monotonicity, or continuity proof encoding.
- Consequence:
Tamperable trust lineage and divergent quorum acceptance outcomes across replicas.
- Detection signal:
Rotation/continuity tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-64` rejection (`INV-C73`, `INV-G70`).
- Residual risk:
Identity binding quality still depends on upstream principal infrastructure.

## FM-080: Attester Projection Confluence Break

- Description:
Equivalent attester rotation/continuity projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `rotation_projection_key`/`continuity_projection_key` or nondeterministic attester serialization.
- Consequence:
Replica-specific effective attester lineage and unstable cutover history.
- Detection signal:
Same rotation/continuity projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-65` plus confluence invariants (`INV-C74`, `INV-G72`).
- Residual risk:
Recovery requires corrected attester lineage and may temporarily block utilization ingestion for affected windows.

## FM-081: Trust-Tiered Cutover Quorum Violation

- Description:
Attestations are accepted during cutover despite failing deterministic dual-quorum overlap/continuity constraints.
- Trigger:
Admission omits deterministic cutover profile checks (`dual_quorum_windows`, overlap threshold, trust-weight threshold, continuity coverage).
- Consequence:
Deterministic but incorrect trust transitions, unfair attester dominance, and replay divergence under rollback.
- Detection signal:
Accepted attestation cannot be derived from active cutover policy and visible rotation/continuity lineage.
- Mitigation:
Deterministic cutover guard with explicit rejection `CF-66`; enforced by `INV-C73`, `INV-C75`, `INV-G73`, `INV-G74`.
- Residual risk:
Conservative cutover thresholds can increase rejected-attestation churn during planned rotation windows.

## FM-082: Attester Accountability Policy Drift Admission

- Description:
Accountability-governed utilization/memory/arbitration operations are admitted under a stale attester-accountability policy snapshot.
- Trigger:
Missing `attester_accountability_policy_hash` CAS checks at accountability/reinstatement, utilization attestation/reconciliation, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent slashing/reputation interpretation and non-reproducible trust-weight lineage.
- Detection signal:
Admitted operation references accountability policy metadata that differs from active `CapsuleAttesterAccountabilityPolicy` hash at admission boundary.
- Mitigation:
Accountability-policy CAS gate with deterministic rejection `CF-67`; convergence bounded by `INV-C76`, `INV-C77`, `INV-G75`, `INV-G76`.
- Residual risk:
Frequent accountability-policy cutovers can increase replanning churn and coordination overhead.

## FM-083: Stale Accountability/Reinstatement Basis Apply

- Description:
Accountability/reinstatement or utilization-governed plan is applied after canonical accountability lineage changed.
- Trigger:
No deterministic `accountability_basis_hash`/`reinstatement_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent slash/debt/reputation tuples and replay drift in downstream utilization/memory/arbitration lineage.
- Detection signal:
Accountability/reinstatement/utilization apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-68` (`INV-C77`, `INV-G76`, `INV-G78`).
- Residual risk:
Late admissible fault evidence can invalidate queued plans at high cadence.

## FM-084: Inadmissible Attester Accountability Payload

- Description:
Accountability policy/record payload with invalid fault evidence, slash/debt tuple, decay tuple, or reinstatement tuple is admitted.
- Trigger:
Weak validation of fault class catalog, evidence serialization, slash/debt bounds, decay bounds, probation windows, or reinstatement tuple encoding.
- Consequence:
Tamperable accountability lineage and divergent trust-weight outcomes across replicas.
- Detection signal:
Accountability/reinstatement tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-69` rejection (`INV-C78`, `INV-G77`).
- Residual risk:
Fault evidence quality still depends on upstream attester identity and evidence signing infrastructure.

## FM-085: Accountability Projection Confluence Break

- Description:
Equivalent accountability/reinstatement projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `accountability_projection_key`/`reinstatement_projection_key` or nondeterministic serialization.
- Consequence:
Replica-specific effective slash/debt/reputation lineage and unstable downstream utilization admissibility.
- Detection signal:
Same accountability/reinstatement projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-70` plus confluence invariants (`INV-C79`, `INV-G79`).
- Residual risk:
Recovery requires corrected accountability lineage and may temporarily block utilization ingestion for affected windows.

## FM-086: Slash/Decay/Reinstatement Transition Violation

- Description:
Applied accountability transitions violate deterministic slash/debt/reputation equations, probation bounds, reinstatement eligibility, or rollback precedence restoration.
- Trigger:
Transition validation omits deterministic equation checks, cap clamps, probation gating, or recovered-trust threshold checks.
- Consequence:
Deterministic but incorrect trust penalties/recoveries, unfair attester suppression or inflation, and replay divergence under rollback.
- Detection signal:
Observed next accountability tuple cannot be derived from prior tuple + canonical fault/recovery inputs under active accountability policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-71`; enforced by `INV-C78`, `INV-C80`, `INV-G80`, `INV-G81`.
- Residual risk:
Transition quality still depends on deterministic fault-evidence ingestion fidelity and cross-domain adjudication policy maturity.

## FM-087: Attester Adjudication Policy Drift Admission

- Description:
Adjudication-governed accountability/utilization/memory/arbitration operations are admitted under a stale attester-adjudication policy snapshot.
- Trigger:
Missing `attester_adjudication_policy_hash` CAS checks at adjudication/appeal, accountability/reinstatement, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent dispute verdict/finality interpretation and non-reproducible downstream trust-weight lineage.
- Detection signal:
Admitted operation references adjudication policy metadata that differs from active `CapsuleAttesterAdjudicationPolicy` hash at admission boundary.
- Mitigation:
Adjudication-policy CAS gate with deterministic rejection `CF-72`; convergence bounded by `INV-C81`, `INV-C82`, `INV-G82`, `INV-G83`.
- Residual risk:
Frequent adjudication-policy cutovers can increase replanning churn and operational latency.

## FM-088: Stale Adjudication/Appeal Basis Apply

- Description:
Fault adjudication/appeal or adjudication-governed accountability/utilization plan is applied after canonical dispute lineage changed.
- Trigger:
No deterministic `adjudication_basis_hash`/`appeal_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent verdict/finality tuples and replay drift in downstream accountability/utilization/memory/arbitration lineage.
- Detection signal:
Adjudication/appeal/accountability apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-73` (`INV-C82`, `INV-G83`, `INV-G85`).
- Residual risk:
Late admissible appeal evidence can invalidate queued plans at high cadence.

## FM-089: Inadmissible Attester Adjudication Payload

- Description:
Adjudication policy/record payload with invalid jurisdiction tuple, verdict envelope, evidence-root lineage, or appeal tuple is admitted.
- Trigger:
Weak validation of jurisdiction membership/weights, verdict serialization, evidence-root hashes, appeal-round bounds, or profile IDs.
- Consequence:
Tamperable dispute lineage and divergent accountability outcomes across replicas.
- Detection signal:
Adjudication/appeal tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-74` rejection (`INV-C83`, `INV-G84`).
- Residual risk:
Evidence-root integrity still depends on upstream signing and canonical evidence packaging.

## FM-090: Adjudication Projection Confluence Break

- Description:
Equivalent adjudication/appeal projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `adjudication_projection_key`/`appeal_projection_key` or nondeterministic adjudication serialization.
- Consequence:
Replica-specific effective verdict/finality lineage and unstable downstream accountability eligibility.
- Detection signal:
Same adjudication/appeal projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-75` plus confluence invariants (`INV-C84`, `INV-G86`).
- Residual risk:
Recovery requires corrected dispute lineage and may temporarily block accountability and utilization admission for affected windows.

## FM-091: Appeal-Finality Transition Violation

- Description:
Applied appeal/finality transitions violate deterministic state machine bounds (appeal-after-close, non-monotonic rounds, or premature final closure).
- Trigger:
Transition validation omits appeal-window checks, round monotonicity checks, finality delay checks, or closure immutability checks.
- Consequence:
Deterministic but incorrect dispute closure, unfair penalties/restorations, and replay divergence under rollback.
- Detection signal:
Observed dispute state cannot be derived from prior state + canonical appeal inputs under active adjudication policy.
- Mitigation:
Deterministic finality guard with explicit rejection `CF-76`; enforced by `INV-C83`, `INV-C85`, `INV-G87`, `INV-G88`.
- Residual risk:
Finality quality still depends on canonical cross-domain evidence ingestion and jurisdiction profile maturity.

## FM-092: Adjudication Portability Policy Drift Admission

- Description:
Portability-governed adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale adjudication-portability policy snapshot.
- Trigger:
Missing `attester_adjudication_portability_policy_hash` CAS checks at portability/review-mux, adjudication/appeal, accountability/reinstatement, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent jurisdiction weighting, envelope normalization, and review-lane routing with non-reproducible downstream trust/allocation lineage.
- Detection signal:
Admitted operation references portability policy metadata that differs from active `CapsuleAttesterAdjudicationPortabilityPolicy` hash at admission boundary.
- Mitigation:
Portability-policy CAS gate with deterministic rejection `CF-77`; convergence bounded by `INV-C86`, `INV-C87`, `INV-G89`, `INV-G90`.
- Residual risk:
Frequent portability-policy cutovers can increase replanning churn and coordination overhead.

## FM-093: Stale Portability/Review-Mux Basis Apply

- Description:
Portability normalization/review-mux or portability-governed adjudication/utilization plan is applied after canonical portability lineage changed.
- Trigger:
No deterministic `portability_basis_hash`/`review_mux_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent jurisdiction weights/evidence normalization/review-lane tuples and replay drift in downstream adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Portability/review-mux/adjudication apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-78` (`INV-C87`, `INV-G90`, `INV-G91`).
- Residual risk:
Late admissible jurisdiction or evidence-normalization inputs can invalidate queued plans at high cadence.

## FM-094: Inadmissible Adjudication Portability Payload

- Description:
Portability policy/record payload with invalid jurisdiction weight vector, malformed evidence-envelope normalization tuple, or invalid appeal review-lane tuple is admitted.
- Trigger:
Weak validation of jurisdiction canonicalization, weight bounds/diversity thresholds, envelope normalization profile constraints, review-lane profile IDs, or tuple encoding.
- Consequence:
Tamperable portability lineage and divergent verdict weighting/review outcomes across replicas.
- Detection signal:
Portability or review-mux tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-79` rejection (`INV-C88`, `INV-G92`).
- Residual risk:
Normalization quality still depends on upstream evidence packaging and jurisdiction identity binding.

## FM-095: Portability Projection Confluence Break

- Description:
Equivalent portability/review-mux projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `portability_projection_key`/`review_mux_projection_key` or nondeterministic portability serialization.
- Consequence:
Replica-specific effective jurisdiction weight/evidence-normalization/review-lane lineage and unstable downstream adjudication/accountability eligibility.
- Detection signal:
Same portability/review-mux projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-80` plus confluence invariants (`INV-C89`, `INV-G93`).
- Residual risk:
Recovery requires corrected portability lineage and may temporarily block adjudication/accountability admission for affected disputes.

## FM-096: Review-Mux Transition/Finality Coupling Violation

- Description:
Applied review-mux transitions violate deterministic lane state-machine bounds (non-monotonic appeal lane rounds, invalid lane diversity/quorum transitions, or post-finality review insertion).
- Trigger:
Transition validation omits review-lane monotonicity checks, lane diversity constraints, cross-lane quorum checks, finality-coupling checks, or rollback precedence checks.
- Consequence:
Deterministic but incorrect appeal review closure, unfair verdict weighting, and replay divergence under rollback.
- Detection signal:
Observed review-mux state cannot be derived from prior state + canonical portability and appeal inputs under active portability policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-81`; enforced by `INV-C88`, `INV-C90`, `INV-G94`, `INV-G95`.
- Residual risk:
Review-lane quality still depends on canonical cross-domain evidence normalization and adjudication portability profile maturity.

## FM-097: Portability-Disclosure Policy Drift Admission

- Description:
Disclosure-governed portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale portability-disclosure policy snapshot.
- Trigger:
Missing `attester_portability_disclosure_policy_hash` CAS checks at disclosure/review-attestation, portability/review-mux, adjudication/appeal, accountability/reinstatement, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent redaction/reveal admissibility and non-reproducible downstream trust/allocation lineage.
- Detection signal:
Admitted operation references disclosure policy metadata that differs from active `CapsuleAttesterPortabilityDisclosurePolicy` hash at admission boundary.
- Mitigation:
Disclosure-policy CAS gate with deterministic rejection `CF-82`; convergence bounded by `INV-C91`, `INV-C92`, `INV-G96`, `INV-G97`.
- Residual risk:
Frequent disclosure-policy cutovers can increase replanning churn and operational latency.

## FM-098: Stale Disclosure/Review-Attestation Basis Apply

- Description:
Disclosure/review-attestation or disclosure-governed portability/adjudication/utilization plan is applied after canonical disclosure lineage changed.
- Trigger:
No deterministic `disclosure_basis_hash`/`review_attestation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent commitment/reveal/attestation tuples and replay drift in downstream portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Disclosure/review-attestation/portability/adjudication apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-83` (`INV-C92`, `INV-G97`, `INV-G98`).
- Residual risk:
Late admissible disclosure evidence can invalidate queued plans at high cadence.

## FM-099: Inadmissible Portability-Disclosure Payload

- Description:
Disclosure policy/record payload with invalid redaction commitment path, malformed selective-reveal proof tuple, invalid review-attestation tuple, or privacy-budget overflow is admitted.
- Trigger:
Weak validation of redaction path canonicalization, commitment tree profile constraints, reveal proof encoding, attestation tuple encoding, privacy-budget caps, or profile IDs.
- Consequence:
Tamperable disclosure lineage and divergent review admissibility outcomes across replicas.
- Detection signal:
Disclosure/review-attestation tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-84` rejection (`INV-C93`, `INV-G99`).
- Residual risk:
Cryptographic proof quality still depends on upstream commitment/proof tooling integrity.

## FM-100: Portability-Disclosure Projection Confluence Break

- Description:
Equivalent disclosure/review-attestation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `portability_disclosure_projection_key`/`review_attestation_projection_key` or nondeterministic disclosure serialization.
- Consequence:
Replica-specific effective commitment/reveal/attestation lineage and unstable downstream portability/adjudication/accountability eligibility.
- Detection signal:
Same disclosure/review-attestation projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-85` plus confluence invariants (`INV-C94`, `INV-G100`).
- Residual risk:
Recovery requires corrected disclosure lineage and may temporarily block portability/adjudication admission for affected disputes.

## FM-101: Review-Attestation Transition/Finality Coupling Violation

- Description:
Applied disclosure/review-attestation transitions violate deterministic state-machine bounds (non-monotonic sequence, commitment-root mismatch, reveal-set expansion after closure, or post-finality attestation insertion).
- Trigger:
Transition validation omits sequence monotonicity checks, commitment-binding checks, reveal-budget checks, finality-coupling checks, or nonce replay exclusion checks.
- Consequence:
Deterministic but incorrect privacy disclosure closure, unfair review weighting, and replay divergence under rollback.
- Detection signal:
Observed disclosure/review-attestation state cannot be derived from prior state + canonical portability/appeal inputs under active disclosure policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-86`; enforced by `INV-C93`, `INV-C95`, `INV-G101`, `INV-G102`.
- Residual risk:
Policy quality still depends on calibrated privacy-budget and commitment-agility profiles.

## FM-102: Disclosure-Lifecycle Policy Drift Admission

- Description:
Lifecycle-governed disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale disclosure-lifecycle policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_policy_hash` CAS checks at replenishment/revocation/agility, disclosure/review-attestation, portability/review-mux, adjudication/appeal, accountability/reinstatement, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent replenishment/revocation/agility interpretation and non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references lifecycle policy metadata that differs from active `CapsuleAttesterDisclosureLifecyclePolicy` hash at admission boundary.
- Mitigation:
Lifecycle-policy CAS gate with deterministic rejection `CF-87`; convergence bounded by `INV-C96`, `INV-C97`, `INV-G103`, `INV-G104`.
- Residual risk:
Frequent lifecycle-policy cutovers can increase replanning churn and operational latency.

## FM-103: Stale Lifecycle Basis Apply

- Description:
Replenishment/revocation/agility or lifecycle-governed disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle lineage changed.
- Trigger:
No deterministic `replenishment_basis_hash`/`revocation_basis_hash`/`commitment_agility_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent lifecycle tuples and replay drift in downstream disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Lifecycle/disclosure/apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-88` (`INV-C97`, `INV-G104`, `INV-G105`).
- Residual risk:
Late admissible lifecycle evidence can invalidate queued plans at high cadence.

## FM-104: Inadmissible Disclosure-Lifecycle Payload

- Description:
Lifecycle policy/record payload with invalid replenishment tuple, malformed revocation scope, unsupported commitment migration tuple, or cap overflow is admitted.
- Trigger:
Weak validation of cadence windows, replenish cap/floor bounds, revocation-scope encoding, commitment migration profile IDs, root-rebind proof envelope, or tuple serialization.
- Consequence:
Tamperable lifecycle lineage and divergent reveal-budget/revocation/cutover outcomes across replicas.
- Detection signal:
Lifecycle tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-89` rejection (`INV-C98`, `INV-G106`).
- Residual risk:
Cryptographic migration-proof quality still depends on upstream commitment tooling integrity.

## FM-105: Disclosure-Lifecycle Projection Confluence Break

- Description:
Equivalent replenishment/revocation/agility projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `budget_replenishment_projection_key`/`disclosure_revocation_projection_key`/`commitment_agility_projection_key` or nondeterministic lifecycle serialization.
- Consequence:
Replica-specific effective lifecycle lineage and unstable downstream disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same lifecycle projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-90` plus confluence invariants (`INV-C99`, `INV-G107`).
- Residual risk:
Recovery requires corrected lifecycle lineage and may temporarily block disclosure-governed admission for affected disputes.

## FM-106: Disclosure-Lifecycle Transition Violation

- Description:
Applied replenishment/revocation/agility transitions violate deterministic state-machine bounds (cadence violation, revocation-scope regression, missing commitment rebind proof, or rollback-precedence breach).
- Trigger:
Transition validation omits replenish cadence checks, revocation monotonicity checks, cutover proof binding checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect reveal-budget/revocation/commitment state and replay divergence under rollback.
- Detection signal:
Observed lifecycle state cannot be derived from prior state + canonical lifecycle inputs under active lifecycle policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-91`; enforced by `INV-C98`, `INV-C100`, `INV-G108`, `INV-G109`.
- Residual risk:
Policy quality still depends on calibrated lifecycle profile diversity and commitment compatibility catalogs.

## FM-107: Disclosure-Lifecycle-Calibration Policy Drift Admission

- Description:
Calibration-governed lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-calibration policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_calibration_policy_hash` CAS checks at envelope/granularity/matrix calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent profile-class selection and non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references calibration policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleCalibrationPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-calibration-policy CAS gate with deterministic rejection `CF-92`; convergence bounded by `INV-C101`, `INV-C102`, `INV-G110`, `INV-G111`.
- Residual risk:
Frequent calibration-policy cutovers can increase replanning churn and operational latency.

## FM-108: Stale Lifecycle-Calibration Basis Apply

- Description:
Envelope/granularity/matrix calibration or calibration-governed lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-calibration lineage changed.
- Trigger:
No deterministic `replenishment_envelope_basis_hash`/`revocation_granularity_basis_hash`/`compatibility_matrix_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent calibration tuples and replay drift in downstream lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Calibration/lifecycle/disclosure apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-93` (`INV-C102`, `INV-G111`, `INV-G112`).
- Residual risk:
Late admissible calibration evidence can invalidate queued plans at high cadence.

## FM-109: Inadmissible Disclosure-Lifecycle-Calibration Payload

- Description:
Lifecycle-calibration policy/record payload with invalid envelope-class bounds, malformed revocation-granularity tuple, unsupported compatibility-matrix tuple, or selector-profile mismatch is admitted.
- Trigger:
Weak validation of calibration class catalogs, tuple bounds, required matrix closure/symmetry flags, selector-profile IDs, or tuple serialization.
- Consequence:
Tamperable calibration lineage and divergent lifecycle/disclosure admissibility outcomes across replicas.
- Detection signal:
Calibration tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-94` rejection (`INV-C103`, `INV-G113`).
- Residual risk:
Calibration profile quality still depends on upstream dispute-pressure signal integrity.

## FM-110: Disclosure-Lifecycle-Calibration Projection Confluence Break

- Description:
Equivalent envelope/granularity/matrix calibration projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `replenishment_envelope_projection_key`/`revocation_granularity_projection_key`/`commitment_compatibility_projection_key` or nondeterministic calibration serialization.
- Consequence:
Replica-specific effective calibration lineage and unstable downstream lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same calibration projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-95` plus confluence invariants (`INV-C104`, `INV-G114`).
- Residual risk:
Recovery requires corrected calibration lineage and may temporarily block lifecycle-governed admission for affected disputes.

## FM-111: Disclosure-Lifecycle-Calibration Transition Violation

- Description:
Applied envelope/granularity/matrix calibration transitions violate deterministic coupling bounds (envelope-class oscillation, granularity downgrade after closure, compatibility asymmetry, missing lifecycle binding, or rollback-precedence breach).
- Trigger:
Transition validation omits bounded class-delta checks, granularity closure monotonicity checks, required matrix symmetry/closure checks, lifecycle-binding checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect calibration state and replay divergence under rollback.
- Detection signal:
Observed calibration state cannot be derived from prior state + canonical calibration inputs under active calibration policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-96`; enforced by `INV-C103`, `INV-C105`, `INV-G115`, `INV-G116`.
- Residual risk:
Selector-objective profile breadth and hysteresis calibration remain limited.

## FM-112: Disclosure-Lifecycle-Objective Policy Drift Admission

- Description:
Objective-governed calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-objective policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_objective_policy_hash` CAS checks at objective-weight/hysteresis, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent objective weighting and selector-family cutover decisions with non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references objective policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleObjectivePolicy` hash at admission boundary.
- Mitigation:
Lifecycle-objective-policy CAS gate with deterministic rejection `CF-97`; convergence bounded by `INV-C106`, `INV-C107`, `INV-G117`, `INV-G118`.
- Residual risk:
Frequent objective-policy cutovers can increase replanning churn and operational latency.

## FM-113: Stale Lifecycle-Objective Basis Apply

- Description:
Objective-weight/hysteresis or objective-governed calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-objective lineage changed.
- Trigger:
No deterministic `objective_weight_basis_hash`/`hysteresis_cutover_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent objective tuples and replay drift in downstream calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Objective/calibration/lifecycle/disclosure apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-98` (`INV-C107`, `INV-G118`, `INV-G119`).
- Residual risk:
Late admissible objective evidence can invalidate queued plans at high cadence.

## FM-114: Inadmissible Disclosure-Lifecycle-Objective Payload

- Description:
Lifecycle-objective policy/record payload with invalid weight normalization, fairness-floor inversion, cost-ceiling inversion, malformed hysteresis tuple, or selector-family profile mismatch is admitted.
- Trigger:
Weak validation of objective vector algebra, fairness/cost guard tuples, hysteresis margin/hold/cooldown bounds, profile IDs, or tuple serialization.
- Consequence:
Tamperable objective lineage and divergent selector-family cutover outcomes across replicas.
- Detection signal:
Objective tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-99` rejection (`INV-C108`, `INV-G120`).
- Residual risk:
Objective profile quality still depends on upstream privacy/fairness/cost signal integrity.

## FM-115: Disclosure-Lifecycle-Objective Projection Confluence Break

- Description:
Equivalent objective-weight/hysteresis projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `objective_weight_projection_key`/`hysteresis_projection_key` or nondeterministic objective serialization.
- Consequence:
Replica-specific effective objective lineage and unstable downstream calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same objective projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-100` plus confluence invariants (`INV-C109`, `INV-G121`).
- Residual risk:
Recovery requires corrected objective lineage and may temporarily block objective-governed admission for affected disputes.

## FM-116: Disclosure-Lifecycle-Objective Transition Violation

- Description:
Applied objective-weight/hysteresis transitions violate deterministic coupling bounds (selector-family flapping, hold/cooldown breach, fairness-floor breach, cost-ceiling bypass, missing calibration/lifecycle binding, or rollback-precedence breach).
- Trigger:
Transition validation omits hysteresis band checks, hold/cooldown sequencing, fairness/cost guard enforcement, coupling integrity checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect objective state and replay divergence under rollback.
- Detection signal:
Observed objective state cannot be derived from prior state + canonical objective inputs under active objective policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-101`; enforced by `INV-C108`, `INV-C110`, `INV-G122`, `INV-G123`.
- Residual risk:
Signal-attestation integrity and lag-compensation family breadth remain limited.

## FM-117: Disclosure-Lifecycle-Signal-Integrity Policy Drift Admission

- Description:
Signal-governed objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-integrity policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_integrity_policy_hash` CAS checks at signal-attestation/lag-normalization/manipulation, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent objective signal inputs and non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references signal-integrity policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalIntegrityPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-integrity-policy CAS gate with deterministic rejection `CF-102`; convergence bounded by `INV-C111`, `INV-C112`, `INV-G124`, `INV-G125`.
- Residual risk:
Frequent signal-policy cutovers can increase replanning churn and operational latency.

## FM-118: Stale Lifecycle-Signal-Integrity Basis Apply

- Description:
Signal-attestation/lag-normalization/manipulation or signal-governed objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-integrity lineage changed.
- Trigger:
No deterministic `objective_signal_basis_hash`/`lag_normalization_basis_hash`/`manipulation_verdict_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent signal tuples and replay drift in downstream objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-103` (`INV-C112`, `INV-G125`, `INV-G126`).
- Residual risk:
Late admissible signal evidence can invalidate queued plans at high cadence.

## FM-119: Inadmissible Disclosure-Lifecycle-Signal-Integrity Payload

- Description:
Lifecycle-signal-integrity policy/record payload with malformed evidence-attestation roots, invalid lag windows/weights, unsupported manipulation class tuples, or signal-profile mismatch is admitted.
- Trigger:
Weak validation of attestation-root lineage, observer quorum tuples, lag-normalization bounds, manipulation severity/freeze tuples, profile IDs, or tuple serialization.
- Consequence:
Tamperable signal-integrity lineage and divergent objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Signal tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-104` rejection (`INV-C113`, `INV-G127`).
- Residual risk:
Signal profile quality still depends on upstream observer identity and attestation root hygiene.

## FM-120: Disclosure-Lifecycle-Signal-Integrity Projection Confluence Break

- Description:
Equivalent signal-attestation/lag-normalization/manipulation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `objective_signal_projection_key`/`lag_normalization_projection_key`/`manipulation_verdict_projection_key` or nondeterministic signal serialization.
- Consequence:
Replica-specific effective signal-integrity lineage and unstable downstream objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same signal projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-105` plus confluence invariants (`INV-C114`, `INV-G128`).
- Residual risk:
Recovery requires corrected signal lineage and may temporarily block signal-governed admission for affected disputes.

## FM-121: Disclosure-Lifecycle-Signal-Integrity Transition Violation

- Description:
Applied signal-attestation/lag-normalization/manipulation transitions violate deterministic coupling bounds (lag-window regression, normalization rebase drift, manipulation-severity downgrade after freeze, penalty bypass, or rollback-precedence breach).
- Trigger:
Transition validation omits lag monotonicity checks, normalization rebasing guards, manipulation closure monotonicity checks, coupling integrity checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect signal state and replay divergence under rollback.
- Detection signal:
Observed signal-integrity state cannot be derived from prior state + canonical signal inputs under active signal-integrity policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-106`; enforced by `INV-C113`, `INV-C115`, `INV-G129`, `INV-G130`.
- Residual risk:
Cross-domain signal federation, stale-feed quarantine, and observer-diversity escrow families remain limited.

## FM-122: Disclosure-Lifecycle-Signal-Federation Policy Drift Admission

- Description:
Federation-governed signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_policy_hash` CAS checks at federation-attestation/diversity-escrow/quarantine, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent cross-domain feed eligibility and non-reproducible downstream objective/privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references federation policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-policy CAS gate with deterministic rejection `CF-107`; convergence bounded by `INV-C116`, `INV-C117`, `INV-G131`, `INV-G132`.
- Residual risk:
Frequent federation-policy cutovers can increase replanning churn and operational latency.

## FM-123: Stale Lifecycle-Signal-Federation Basis Apply

- Description:
Federation-attestation/diversity-escrow/stale-feed-quarantine or federation-governed signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation lineage changed.
- Trigger:
No deterministic `federation_attestation_basis_hash`/`observer_diversity_escrow_basis_hash`/`stale_feed_quarantine_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent federation tuples and replay drift in downstream signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-108` (`INV-C117`, `INV-G132`, `INV-G133`).
- Residual risk:
Late admissible federation evidence can invalidate queued plans at high cadence.

## FM-124: Inadmissible Disclosure-Lifecycle-Signal-Federation Payload

- Description:
Lifecycle-signal-federation policy/record payload with unknown source-domain/feed tuples, invalid federation-weight normalization, malformed diversity-escrow tuples, unsupported stale-feed quarantine tuples, or federation-profile mismatch is admitted.
- Trigger:
Weak validation of domain/feed catalogs, weight-normalization constraints, escrow bounds, quarantine reopen conditions, profile IDs, or tuple serialization.
- Consequence:
Tamperable signal-federation lineage and divergent signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Federation tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-109` rejection (`INV-C118`, `INV-G134`).
- Residual risk:
Federation profile quality still depends on upstream domain identity binding and feed freshness telemetry hygiene.

## FM-125: Disclosure-Lifecycle-Signal-Federation Projection Confluence Break

- Description:
Equivalent federation-attestation/diversity-escrow/stale-feed-quarantine projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `signal_federation_projection_key`/`observer_diversity_escrow_projection_key`/`stale_feed_quarantine_projection_key` or nondeterministic federation serialization.
- Consequence:
Replica-specific effective signal-federation lineage and unstable downstream signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same federation projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-110` plus confluence invariants (`INV-C119`, `INV-G135`).
- Residual risk:
Recovery requires corrected federation lineage and may temporarily block federation-governed admission for affected disputes.

## FM-126: Disclosure-Lifecycle-Signal-Federation Transition Violation

- Description:
Applied federation-attestation/diversity-escrow/stale-feed-quarantine transitions violate deterministic coupling bounds (domain-window regression, diversity-escrow unlock before threshold satisfaction, stale-feed quarantine downgrade without reopen proof, federated stale-feed bypass, or rollback-precedence breach).
- Trigger:
Transition validation omits domain monotonicity checks, escrow lock/release guards, quarantine closure monotonicity checks, stale-feed coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect federation state and replay divergence under rollback.
- Detection signal:
Observed signal-federation state cannot be derived from prior state + canonical federation inputs under active signal-federation policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-111`; enforced by `INV-C118`, `INV-C120`, `INV-G136`, `INV-G137`.
- Residual risk:
Federation rehabilitation, quarantine release proof quality, and cross-domain clock-skew compensation families remain limited.

## FM-127: Disclosure-Lifecycle-Signal-Federation-Rehabilitation Policy Drift Admission

- Description:
Rehabilitation-governed federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_policy_hash` CAS checks at quarantine-release/escrow-unlock/skew-compensation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent rehabilitation eligibility and non-reproducible downstream objective/privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references rehabilitation policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-policy CAS gate with deterministic rejection `CF-112`; convergence bounded by `INV-C121`, `INV-C122`, `INV-G138`, `INV-G139`.
- Residual risk:
Frequent rehabilitation-policy cutovers can increase replanning churn and operational latency.

## FM-128: Stale Lifecycle-Signal-Federation-Rehabilitation Basis Apply

- Description:
Quarantine-release/escrow-unlock/clock-skew-compensation or rehabilitation-governed federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation lineage changed.
- Trigger:
No deterministic `quarantine_release_basis_hash`/`escrow_unlock_basis_hash`/`clock_skew_compensation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent rehabilitation tuples and replay drift in downstream federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-113` (`INV-C122`, `INV-G139`, `INV-G140`).
- Residual risk:
Late admissible rehabilitation evidence can invalidate queued plans at high cadence.

## FM-129: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation Payload

- Description:
Lifecycle-signal-federation-rehabilitation policy/record payload with invalid release proof lineage, malformed unlock fairness tuples, out-of-bounds skew compensation, unsupported rehabilitation profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of release-proof root lineage, fairness unlock constraints, skew drift bounds, profile IDs, or tuple serialization.
- Consequence:
Tamperable rehabilitation lineage and divergent federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Rehabilitation tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-114` rejection (`INV-C123`, `INV-G141`).
- Residual risk:
Rehabilitation profile quality still depends on upstream proof attestation and clock offset measurement hygiene.

## FM-130: Disclosure-Lifecycle-Signal-Federation-Rehabilitation Projection Confluence Break

- Description:
Equivalent quarantine-release/escrow-unlock/clock-skew-compensation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `quarantine_release_projection_key`/`escrow_unlock_projection_key`/`clock_skew_compensation_projection_key` or nondeterministic rehabilitation serialization.
- Consequence:
Replica-specific effective rehabilitation lineage and unstable downstream federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same rehabilitation projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-115` plus confluence invariants (`INV-C124`, `INV-G142`).
- Residual risk:
Recovery requires corrected rehabilitation lineage and may temporarily block rehabilitation-governed admission for affected disputes.

## FM-131: Disclosure-Lifecycle-Signal-Federation-Rehabilitation Transition Violation

- Description:
Applied quarantine-release/escrow-unlock/clock-skew-compensation transitions violate deterministic coupling bounds (release proof replay/regression, unlock fairness undercut, skew compensation overshoot, unlock-before-release bypass, or rollback-precedence breach).
- Trigger:
Transition validation omits release monotonicity checks, fairness coupling guards, skew drift bounds, quarantine/release coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect rehabilitation state and replay divergence under rollback.
- Detection signal:
Observed signal-federation-rehabilitation state cannot be derived from prior state + canonical rehabilitation inputs under active rehabilitation policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-116`; enforced by `INV-C123`, `INV-C125`, `INV-G143`, `INV-G144`.
- Residual risk:
Rehabilitation objective coupling, fairness backpressure tuning, and skew-hysteresis profile breadth remain limited.

## FM-132: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling Policy Drift Admission

- Description:
Coupling-governed rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_policy_hash` CAS checks at selector-clamp/unlock-backpressure/skew-hysteresis, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent objective selector clamps and non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references coupling policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-policy CAS gate with deterministic rejection `CF-117`; convergence bounded by `INV-C126`, `INV-C127`, `INV-G145`, `INV-G146`.
- Residual risk:
Frequent coupling-policy cutovers can increase replanning churn and operational latency.

## FM-133: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling Basis Apply

- Description:
Selector-clamp/unlock-backpressure/skew-hysteresis or coupling-governed rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling lineage changed.
- Trigger:
No deterministic `selector_clamp_basis_hash`/`unlock_backpressure_basis_hash`/`skew_hysteresis_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent coupling tuples and replay drift in downstream rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-118` (`INV-C127`, `INV-G146`, `INV-G147`).
- Residual risk:
Late admissible coupling evidence can invalidate queued plans at high cadence.

## FM-134: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling policy/record payload with invalid selector-clamp bounds, malformed unlock-backpressure tuples, out-of-bounds skew-hysteresis windows, unsupported coupling profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of clamp tuple bounds, fairness backpressure constraints, skew hysteresis guardrails, profile IDs, or tuple serialization.
- Consequence:
Tamperable coupling lineage and divergent rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Coupling tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-119` rejection (`INV-C128`, `INV-G148`).
- Residual risk:
Coupling profile quality still depends on upstream fairness quantile and skew telemetry hygiene.

## FM-135: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling Projection Confluence Break

- Description:
Equivalent selector-clamp/unlock-backpressure/skew-hysteresis projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `selector_clamp_projection_key`/`unlock_backpressure_projection_key`/`skew_hysteresis_projection_key` or nondeterministic coupling serialization.
- Consequence:
Replica-specific effective coupling lineage and unstable downstream rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same coupling projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-120` plus confluence invariants (`INV-C129`, `INV-G149`).
- Residual risk:
Recovery requires corrected coupling lineage and may temporarily block coupling-governed admission for affected disputes.

## FM-136: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling Transition Violation

- Description:
Applied selector-clamp/unlock-backpressure/skew-hysteresis transitions violate deterministic coupling bounds (clamp downgrade during active rehabilitation, unlock-backpressure fairness bypass, skew-hysteresis hold/cooldown breach, cutover flapping, or rollback-precedence breach).
- Trigger:
Transition validation omits clamp monotonicity checks, fairness-preserving backpressure guards, skew hysteresis hold/cooldown guards, rehabilitation coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect coupling state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling state cannot be derived from prior state + canonical coupling inputs under active coupling policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-121`; enforced by `INV-C128`, `INV-C130`, `INV-G150`, `INV-G151`.
- Residual risk:
Multi-family coupling portfolio governance and deterministic family-upgrade breadth remain limited.

## FM-137: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile Policy Drift Admission

- Description:
Coupling-profile-governed coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_policy_hash` CAS checks at profile-portfolio/family-upgrade/fallback, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent profile-family selection and non-reproducible downstream privacy/trust/allocation lineage.
- Detection signal:
Admitted operation references coupling-profile policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfilePolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-policy CAS gate with deterministic rejection `CF-122`; convergence bounded by `INV-C131`, `INV-C132`, `INV-G152`, `INV-G153`.
- Residual risk:
Frequent coupling-profile policy cutovers can increase replanning churn and operational latency.

## FM-138: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile Basis Apply

- Description:
Coupling-profile-portfolio/family-upgrade/fallback or profile-governed coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile lineage changed.
- Trigger:
No deterministic `coupling_profile_portfolio_basis_hash`/`coupling_family_upgrade_basis_hash`/`coupling_fallback_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent profile tuples and replay drift in downstream coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-123` (`INV-C132`, `INV-G153`, `INV-G154`).
- Residual risk:
Late admissible profile evidence can invalidate queued plans at high cadence.

## FM-139: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile policy/record payload with portfolio-cap overflow, unknown family IDs, malformed upgrade dwell/guard tuples, fallback non-regression floor inversion, unsupported profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of bounded-portfolio membership, family catalog references, upgrade guards, fallback floor constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable coupling-profile lineage and divergent coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Coupling-profile tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-124` rejection (`INV-C133`, `INV-G155`).
- Residual risk:
Coupling-profile quality still depends on upstream fairness/cost/skew signal quality and profile-family curation hygiene.

## FM-140: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile Projection Confluence Break

- Description:
Equivalent coupling-profile-portfolio/family-upgrade/fallback projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_profile_portfolio_projection_key`/`coupling_family_upgrade_projection_key`/`coupling_fallback_projection_key` or nondeterministic profile serialization.
- Consequence:
Replica-specific effective coupling-profile lineage and unstable downstream coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same coupling-profile projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-125` plus confluence invariants (`INV-C134`, `INV-G156`).
- Residual risk:
Recovery requires corrected coupling-profile lineage and may temporarily block profile-governed admission for affected disputes.

## FM-141: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile Transition Violation

- Description:
Applied coupling-profile-portfolio/family-upgrade/fallback transitions violate deterministic profile coupling bounds (portfolio cap bypass, non-deterministic upgrade oscillation, fallback below non-regression floor, fallback-before-guard satisfaction, or rollback-precedence breach).
- Trigger:
Transition validation omits bounded-portfolio checks, upgrade guard/dwell monotonicity, non-regressive fallback guards, coupling/profile coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect coupling-profile state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile state cannot be derived from prior state + canonical profile inputs under active profile policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-126`; enforced by `INV-C133`, `INV-C135`, `INV-G157`, `INV-G158`.
- Residual risk:
Coupling-profile evidence integrity and stale-signal tolerance governance remain limited.

## FM-142: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity Policy Drift Admission

- Description:
Coupling-profile-evidence-governed coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_policy_hash` CAS checks at upgrade-signal-attestation/stale-signal-tolerance/anti-regression-proof, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent evidence admissibility and non-reproducible downstream coupling-family upgrade/fallback lineage.
- Detection signal:
Admitted operation references evidence-integrity policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-policy CAS gate with deterministic rejection `CF-127`; convergence bounded by `INV-C136`, `INV-C137`, `INV-G159`, `INV-G160`.
- Residual risk:
Frequent evidence-policy cutovers can increase replanning churn and operational latency.

## FM-143: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity Basis Apply

- Description:
Upgrade-signal-attestation/stale-signal-tolerance/anti-regression-proof or evidence-governed coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity lineage changed.
- Trigger:
No deterministic `upgrade_signal_attestation_basis_hash`/`stale_signal_tolerance_basis_hash`/`anti_regression_proof_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent evidence tuples and replay drift in downstream coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-128` (`INV-C137`, `INV-G160`, `INV-G161`).
- Residual risk:
Late admissible evidence can invalidate queued plans at high cadence.

## FM-144: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity policy/record payload with malformed upgrade-signal attestation roots, stale-signal tolerance bound inversion, anti-regression proof lineage mismatch, unsupported evidence profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of attestation root integrity, stale-signal tolerance constraints, anti-regression proof lineage, profile IDs, or tuple serialization.
- Consequence:
Tamperable evidence-integrity lineage and divergent coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Evidence-integrity tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-129` rejection (`INV-C138`, `INV-G162`).
- Residual risk:
Evidence-integrity quality still depends on upstream signal-root canonicalization and proof-generation hygiene.

## FM-145: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity Projection Confluence Break

- Description:
Equivalent upgrade-signal-attestation/stale-signal-tolerance/anti-regression-proof projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `upgrade_signal_attestation_projection_key`/`stale_signal_tolerance_projection_key`/`anti_regression_proof_projection_key` or nondeterministic evidence serialization.
- Consequence:
Replica-specific effective evidence-integrity lineage and unstable downstream coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same evidence-integrity projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-130` plus confluence invariants (`INV-C139`, `INV-G163`).
- Residual risk:
Recovery requires corrected evidence lineage and may temporarily block evidence-governed admission for affected disputes.

## FM-146: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity Transition Violation

- Description:
Applied upgrade-signal-attestation/stale-signal-tolerance/anti-regression-proof transitions violate deterministic evidence-integrity bounds (attestation replay regression, stale-signal tolerance widening beyond policy cap, anti-regression proof downgrade, fallback-before-proof satisfaction, or rollback-precedence breach).
- Trigger:
Transition validation omits attestation freshness monotonicity checks, stale-signal tolerance cap guards, anti-regression proof monotonicity checks, coupling/profile evidence coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect evidence-integrity state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity state cannot be derived from prior state + canonical evidence inputs under active evidence policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-131`; enforced by `INV-C138`, `INV-C140`, `INV-G164`, `INV-G165`.
- Residual risk:
Evidence-trust calibration, tolerance-band diversity, and proof-expiry governance remain limited.

## FM-147: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration Policy Drift Admission

- Description:
Trust-calibration-governed evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_policy_hash` CAS checks at coupling-evidence-weight/proof-expiry-cutover/dispute-tolerance-band, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent trust calibration and non-reproducible downstream coupling-family upgrade/fallback lineage.
- Detection signal:
Admitted operation references trust-calibration policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-policy CAS gate with deterministic rejection `CF-132`; convergence bounded by `INV-C141`, `INV-C142`, `INV-G166`, `INV-G167`.
- Residual risk:
Frequent trust-calibration policy cutovers can increase replanning churn and operational latency.

## FM-148: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration Basis Apply

- Description:
Coupling-evidence-weight/proof-expiry-cutover/dispute-tolerance-band or trust-governed evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration lineage changed.
- Trigger:
No deterministic `coupling_evidence_weight_basis_hash`/`coupling_proof_expiry_cutover_basis_hash`/`coupling_dispute_tolerance_band_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent trust tuples and replay drift in downstream evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-133` (`INV-C142`, `INV-G167`, `INV-G168`).
- Residual risk:
Late admissible trust evidence can invalidate queued plans at high cadence.

## FM-149: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration policy/record payload with attester-weight normalization failure, weight-cap/floor inversion, proof-expiry window inversion, dispute-class tolerance-band inversion, unsupported trust profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of trust-tier weighting constraints, proof-expiry lineage integrity, dispute-class tolerance-band constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration lineage and divergent evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-134` rejection (`INV-C143`, `INV-G169`).
- Residual risk:
Trust-calibration quality still depends on upstream attester identity binding and dispute-class labeling hygiene.

## FM-150: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration Projection Confluence Break

- Description:
Equivalent coupling-evidence-weight/proof-expiry-cutover/dispute-tolerance-band projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_evidence_weight_projection_key`/`coupling_proof_expiry_cutover_projection_key`/`coupling_dispute_tolerance_band_projection_key` or nondeterministic trust-calibration serialization.
- Consequence:
Replica-specific effective trust-calibration lineage and unstable downstream evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-135` plus confluence invariants (`INV-C144`, `INV-G170`).
- Residual risk:
Recovery requires corrected trust-calibration lineage and may temporarily block trust-governed admission for affected disputes.

## FM-151: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration Transition Violation

- Description:
Applied coupling-evidence-weight/proof-expiry-cutover/dispute-tolerance-band transitions violate deterministic trust-calibration bounds (weight laundering across attester aliases, expired-proof resurrection, dispute-band widening past class cap, trust-before-evidence coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits multi-attester normalization checks, proof-expiry cutover monotonicity, dispute-band class guardrails, evidence/trust coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration state cannot be derived from prior state + canonical trust inputs under active trust policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-136`; enforced by `INV-C143`, `INV-C145`, `INV-G171`, `INV-G172`.
- Residual risk:
Trust-calibration portfolio breadth, expiry-debt carryover semantics, and cross-dispute fairness caps remain limited.

## FM-152: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio Policy Drift Admission

- Description:
Trust-calibration-portfolio-governed trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_policy_hash` CAS checks at coupling-weight-family-portfolio/proof-expiry-debt-carryover/cross-dispute-fairness-cap, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent trust-calibration-portfolio selection and non-reproducible downstream coupling-family admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-policy CAS gate with deterministic rejection `CF-137`; convergence bounded by `INV-C146`, `INV-C147`, `INV-G173`, `INV-G174`.
- Residual risk:
Frequent trust-calibration-portfolio policy cutovers can increase replanning churn and operational latency.

## FM-153: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio Basis Apply

- Description:
Coupling-weight-family-portfolio/proof-expiry-debt-carryover/cross-dispute-fairness-cap or trust-portfolio-governed trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio lineage changed.
- Trigger:
No deterministic `coupling_weight_family_portfolio_basis_hash`/`coupling_proof_expiry_debt_carryover_basis_hash`/`coupling_cross_dispute_fairness_cap_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent trust-portfolio tuples and replay drift in downstream trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-138` (`INV-C147`, `INV-G174`, `INV-G175`).
- Residual risk:
Late admissible trust-portfolio evidence can invalidate queued plans at high cadence.

## FM-154: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio policy/record payload with weighting-family portfolio overflow, unknown family IDs, proof-expiry debt carryover inversion, fairness-cap inversion, unsupported trust-portfolio profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of portfolio bounds, family catalogs, debt carryover constraints, fairness-cap constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio lineage and divergent trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-139` rejection (`INV-C148`, `INV-G176`).
- Residual risk:
Trust-calibration-portfolio quality still depends on upstream dispute cohort canonicalization and debt-settlement labeling hygiene.

## FM-155: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio Projection Confluence Break

- Description:
Equivalent coupling-weight-family-portfolio/proof-expiry-debt-carryover/cross-dispute-fairness-cap projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_weight_family_portfolio_projection_key`/`coupling_proof_expiry_debt_carryover_projection_key`/`coupling_cross_dispute_fairness_cap_projection_key` or nondeterministic trust-calibration-portfolio serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio lineage and unstable downstream trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-140` plus confluence invariants (`INV-C149`, `INV-G177`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio lineage and may temporarily block trust-portfolio-governed admission for affected disputes.

## FM-156: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio Transition Violation

- Description:
Applied coupling-weight-family-portfolio/proof-expiry-debt-carryover/cross-dispute-fairness-cap transitions violate deterministic trust-calibration-portfolio bounds (weight-family laundering, debt reset bypass, cross-dispute fairness-cap sharding bypass, trust-portfolio-before-trust coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits portfolio boundedness checks, debt carryover monotonicity/decay guards, fairness-cap anti-sharding guards, trust/portfolio coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio state cannot be derived from prior state + canonical trust-portfolio inputs under active trust-portfolio policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-141`; enforced by `INV-C148`, `INV-C150`, `INV-G178`, `INV-G179`.
- Residual risk:
Trust-calibration-portfolio debt amortization and fairness-cap rebound profile breadth remain limited.

## FM-157: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-governed trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_policy_hash` CAS checks at coupling-portfolio-debt-amortization/fairness-rebalance/portfolio-hysteresis-freeze, trust-calibration-portfolio, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent debt amortization/rebound states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio-stability policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-policy CAS gate with deterministic rejection `CF-142`; convergence bounded by `INV-C151`, `INV-C152`, `INV-G180`, `INV-G181`.
- Residual risk:
Frequent trust-calibration-portfolio-stability policy cutovers can increase replanning churn and operational latency.

## FM-158: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability Basis Apply

- Description:
Coupling-portfolio-debt-amortization/fairness-rebalance/portfolio-hysteresis-freeze or stability-governed trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability lineage changed.
- Trigger:
No deterministic `coupling_portfolio_debt_amortization_basis_hash`/`coupling_fairness_rebalance_basis_hash`/`coupling_portfolio_hysteresis_freeze_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent stability tuples and replay drift in downstream trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-143` (`INV-C152`, `INV-G181`, `INV-G182`).
- Residual risk:
Late admissible stability evidence can invalidate queued plans at high cadence.

## FM-159: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability policy/record payload with amortization ladder inversion, fairness rebound overflow, hysteresis freeze-window inversion, unsupported trust-portfolio-stability profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of amortization ladders, rebound bands, freeze window constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability lineage and divergent trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-144` rejection (`INV-C153`, `INV-G183`).
- Residual risk:
Trust-calibration-portfolio-stability quality still depends on upstream debt-settlement and fairness-cohort labeling hygiene.

## FM-160: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability Projection Confluence Break

- Description:
Equivalent coupling-portfolio-debt-amortization/fairness-rebalance/portfolio-hysteresis-freeze projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_portfolio_debt_amortization_projection_key`/`fairness_rebalance_projection_key`/`coupling_portfolio_hysteresis_freeze_projection_key` or nondeterministic trust-calibration-portfolio-stability serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability lineage and unstable downstream trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio-stability projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-145` plus confluence invariants (`INV-C154`, `INV-G184`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio-stability lineage and may temporarily block stability-governed admission for affected disputes.

## FM-161: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability Transition Violation

- Description:
Applied coupling-portfolio-debt-amortization/fairness-rebalance/portfolio-hysteresis-freeze transitions violate deterministic trust-calibration-portfolio-stability bounds (debt anti-reset breach, rebound overshoot, freeze hysteresis bypass, stability-before-portfolio coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits amortization monotonicity checks, rebound anti-overshoot controls, freeze anti-flap guards, trust/stability coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability state cannot be derived from prior state + canonical stability inputs under active stability policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-146`; enforced by `INV-C153`, `INV-C155`, `INV-G185`, `INV-G186`.
- Residual risk:
Amortization-ladder family breadth, rebound policy diversity, and freeze-liftoff catalogs remain limited.

## FM-162: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-governed stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_policy_hash` CAS checks at coupling-amortization-ladder-portfolio/freeze-liftoff-cutover/rebound-fallback, stability, trust-calibration-portfolio, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent family-selection/liftoff/fallback states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio-stability-family policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-policy CAS gate with deterministic rejection `CF-147`; convergence bounded by `INV-C156`, `INV-C157`, `INV-G187`, `INV-G188`.
- Residual risk:
Frequent trust-calibration-portfolio-stability-family policy cutovers can increase replanning churn and operational latency.

## FM-163: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family Basis Apply

- Description:
Coupling-amortization-ladder-portfolio/freeze-liftoff-cutover/rebound-fallback or stability-family-governed stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family lineage changed.
- Trigger:
No deterministic `coupling_amortization_ladder_portfolio_basis_hash`/`coupling_freeze_liftoff_cutover_basis_hash`/`coupling_rebound_fallback_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent stability-family tuples and replay drift in downstream stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-148` (`INV-C157`, `INV-G188`, `INV-G189`).
- Residual risk:
Late admissible stability-family evidence can invalidate queued plans at high cadence.

## FM-164: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family policy/record payload with amortization-ladder portfolio overflow, unknown ladder IDs, freeze-liftoff guard inversion, rebound-fallback floor/ceiling inversion, unsupported trust-portfolio-stability-family profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of bounded ladder portfolios, liftoff guard/dwell tuples, rebound-fallback floor/ceiling bounds, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family lineage and divergent stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-149` rejection (`INV-C158`, `INV-G190`).
- Residual risk:
Trust-calibration-portfolio-stability-family quality still depends on upstream debt-epoch and fairness-cohort canonicalization hygiene.

## FM-165: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family Projection Confluence Break

- Description:
Equivalent coupling-amortization-ladder-portfolio/freeze-liftoff-cutover/rebound-fallback projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_amortization_ladder_portfolio_projection_key`/`coupling_freeze_liftoff_cutover_projection_key`/`coupling_rebound_fallback_projection_key` or nondeterministic trust-calibration-portfolio-stability-family serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family lineage and unstable downstream stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio-stability-family projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-150` plus confluence invariants (`INV-C159`, `INV-G191`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio-stability-family lineage and may temporarily block stability-family-governed admission for affected disputes.

## FM-166: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family Transition Violation

- Description:
Applied coupling-amortization-ladder-portfolio/freeze-liftoff-cutover/rebound-fallback transitions violate deterministic trust-calibration-portfolio-stability-family bounds (portfolio laundering, freeze-liftoff oscillation, rebound-fallback regression bypass, stability-family-before-stability coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits portfolio boundedness checks, freeze-liftoff anti-oscillation guards, rebound fallback non-regression checks, stability-family/stability coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family state cannot be derived from prior state + canonical stability-family inputs under active stability-family policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-151`; enforced by `INV-C158`, `INV-C160`, `INV-G192`, `INV-G193`.
- Residual risk:
Family-proof carryforward semantics, freeze-liftoff debt handoff attestations, and forgiveness-ledger catalogs remain limited.

## FM-167: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-governed stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_policy_hash` CAS checks at coupling-freeze-liftoff-debt-handoff-attestation/rebound-fallback-forgiveness-ledger/family-proof-carryforward, stability-family, stability, trust-calibration-portfolio, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent handoff attestation/forgiveness/carryforward states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio-stability-family-handoff policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-policy CAS gate with deterministic rejection `CF-152`; convergence bounded by `INV-C161`, `INV-C162`, `INV-G194`, `INV-G195`.
- Residual risk:
Frequent trust-calibration-portfolio-stability-family-handoff policy cutovers can increase replanning churn and operational latency.

## FM-168: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff Basis Apply

- Description:
Coupling-freeze-liftoff-debt-handoff-attestation/rebound-fallback-forgiveness-ledger/family-proof-carryforward or handoff-governed stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff lineage changed.
- Trigger:
No deterministic `coupling_freeze_liftoff_debt_handoff_attestation_basis_hash`/`coupling_rebound_fallback_forgiveness_ledger_basis_hash`/`coupling_family_proof_carryforward_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent handoff tuples and replay drift in downstream stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-153` (`INV-C162`, `INV-G195`, `INV-G196`).
- Residual risk:
Late admissible handoff evidence can invalidate queued plans at high cadence.

## FM-169: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff policy/record payload with orphaned freeze-liftoff debt handoff chain, forgiveness ledger inversion, family-proof carryforward bound/expiry inversion, unsupported trust-portfolio-stability-family-handoff profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of debt handoff attestation continuity, forgiveness-ledger monotonicity constraints, carryforward proof freshness/boundedness constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff lineage and divergent stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-154` rejection (`INV-C163`, `INV-G197`).
- Residual risk:
Trust-calibration-portfolio-stability-family-handoff quality still depends on upstream debt commitment and quorum labeling hygiene.

## FM-170: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff Projection Confluence Break

- Description:
Equivalent coupling-freeze-liftoff-debt-handoff-attestation/rebound-fallback-forgiveness-ledger/family-proof-carryforward projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_freeze_liftoff_debt_handoff_attestation_projection_key`/`coupling_rebound_fallback_forgiveness_ledger_projection_key`/`coupling_family_proof_carryforward_projection_key` or nondeterministic trust-calibration-portfolio-stability-family-handoff serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff lineage and unstable downstream stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio-stability-family-handoff projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-155` plus confluence invariants (`INV-C164`, `INV-G198`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio-stability-family-handoff lineage and may temporarily block handoff-governed admission for affected disputes.

## FM-171: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff Transition Violation

- Description:
Applied coupling-freeze-liftoff-debt-handoff-attestation/rebound-fallback-forgiveness-ledger/family-proof-carryforward transitions violate deterministic trust-calibration-portfolio-stability-family-handoff bounds (debt handoff attestation forgery, forgiveness-ledger reset, carryforward replay/overflow, handoff-before-stability-family coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits debt handoff continuity checks, forgiveness-ledger anti-reset guards, carryforward freshness/boundedness checks, handoff/stability-family coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff state cannot be derived from prior state + canonical handoff inputs under active handoff policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-156`; enforced by `INV-C163`, `INV-C165`, `INV-G199`, `INV-G200`.
- Residual risk:
Forgiveness-ledger replenishment profiles, carryforward expiry-cliff controls, and debt-handoff quorum-degradation catalogs remain limited.

## FM-172: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-governed handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_policy_hash` CAS checks at coupling-forgiveness-ledger-replenishment/carryforward-expiry-cliff/debt-handoff-quorum-degradation, handoff, stability-family, stability, trust-calibration-portfolio, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent replenishment/cliff/quorum states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio-stability-family-handoff-portfolio policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioPolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-policy CAS gate with deterministic rejection `CF-157`; convergence bounded by `INV-C166`, `INV-C167`, `INV-G201`, `INV-G202`.
- Residual risk:
Frequent trust-calibration-portfolio-stability-family-handoff-portfolio policy cutovers can increase replanning churn and operational latency.

## FM-173: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio Basis Apply

- Description:
Coupling-forgiveness-ledger-replenishment/carryforward-expiry-cliff/debt-handoff-quorum-degradation or handoff-portfolio-governed handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio lineage changed.
- Trigger:
No deterministic `coupling_forgiveness_ledger_replenishment_basis_hash`/`coupling_carryforward_expiry_cliff_basis_hash`/`coupling_debt_handoff_quorum_degradation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent handoff-portfolio tuples and replay drift in downstream handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-158` (`INV-C167`, `INV-G202`, `INV-G203`).
- Residual risk:
Late admissible handoff-portfolio evidence can invalidate queued plans at high cadence.

## FM-174: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio policy/record payload with replenishment-cap overflow, carryforward expiry-cliff inversion, quorum degradation tier inversion, unsupported trust-portfolio-stability-family-handoff-portfolio profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of replenishment caps/epochs, cliff grace-window ordering/decay bounds, quorum-degradation stage ladders, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio lineage and divergent handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-159` rejection (`INV-C168`, `INV-G204`).
- Residual risk:
Trust-calibration-portfolio-stability-family-handoff-portfolio quality still depends on upstream debt/quorum labeling hygiene.

## FM-175: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio Projection Confluence Break

- Description:
Equivalent coupling-forgiveness-ledger-replenishment/carryforward-expiry-cliff/debt-handoff-quorum-degradation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_forgiveness_ledger_replenishment_projection_key`/`coupling_carryforward_expiry_cliff_projection_key`/`coupling_debt_handoff_quorum_degradation_projection_key` or nondeterministic trust-calibration-portfolio-stability-family-handoff-portfolio serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio lineage and unstable downstream handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio-stability-family-handoff-portfolio projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-160` plus confluence invariants (`INV-C169`, `INV-G205`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio-stability-family-handoff-portfolio lineage and may temporarily block portfolio-governed admission for affected disputes.

## FM-176: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio Transition Violation

- Description:
Applied coupling-forgiveness-ledger-replenishment/carryforward-expiry-cliff/debt-handoff-quorum-degradation transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio bounds (replenishment reset laundering, expiry-cliff suppression, quorum degradation replay laundering, handoff-portfolio-before-handoff coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits replenishment cap monotonicity, expiry-cliff decay progression, quorum degradation anti-replay ordering, handoff-portfolio/handoff coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio state cannot be derived from prior state + canonical handoff-portfolio inputs under active handoff-portfolio policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-161`; enforced by `INV-C168`, `INV-C170`, `INV-G206`, `INV-G207`.
- Residual risk:
Replenishment debt-carryforward families, expiry-cliff smoothing policies, and quorum recovery probation catalogs remain limited.

## FM-177: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-governed handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_policy_hash` CAS checks at coupling-replenishment-debt-carryforward/expiry-cliff-smoothing-cutover/quorum-recovery-probation, handoff-portfolio, handoff, stability-family, stability, trust-calibration-portfolio, trust-calibration, evidence-integrity, coupling-profile, coupling, rehabilitation, federation, signal, objective, calibration, lifecycle, disclosure, portability, adjudication, accountability, utilization, memory/arbitration, or budget-governed apply boundaries.
- Consequence:
Replica-dependent resilience restoration states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references trust-calibration-portfolio-stability-family-handoff-portfolio-resilience policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResiliencePolicy` hash at admission boundary.
- Mitigation:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-policy CAS gate with deterministic rejection `CF-162`; convergence bounded by `INV-C171`, `INV-C172`, `INV-G208`, `INV-G209`.
- Residual risk:
Frequent trust-calibration-portfolio-stability-family-handoff-portfolio-resilience policy cutovers can increase replanning churn and operational latency.

## FM-178: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience Basis Apply

- Description:
Coupling-replenishment-debt-carryforward/expiry-cliff-smoothing-cutover/quorum-recovery-probation or resilience-governed handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience lineage changed.
- Trigger:
No deterministic `coupling_replenishment_debt_carryforward_basis_hash`/`coupling_expiry_cliff_smoothing_cutover_basis_hash`/`coupling_quorum_recovery_probation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent resilience tuples and replay drift in downstream handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-163` (`INV-C172`, `INV-G209`, `INV-G210`).
- Residual risk:
Late admissible resilience evidence can invalidate queued plans at high cadence.

## FM-179: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience policy/record payload with carryforward debt bound inversion, smoothing cutover inversion, probation stage inversion, unsupported trust-portfolio-stability-family-handoff-portfolio-resilience profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of debt carryforward bounds, smoothing cutover sequence constraints, quorum recovery probation stage ladders, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience lineage and divergent handoff-portfolio/handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-164` rejection (`INV-C173`, `INV-G211`).
- Residual risk:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience quality still depends on upstream debt/probation labeling hygiene.

## FM-180: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience Projection Confluence Break

- Description:
Equivalent coupling-replenishment-debt-carryforward/expiry-cliff-smoothing-cutover/quorum-recovery-probation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_replenishment_debt_carryforward_projection_key`/`coupling_expiry_cliff_smoothing_cutover_projection_key`/`coupling_quorum_recovery_probation_projection_key` or nondeterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience lineage and unstable downstream handoff-portfolio/handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same trust-calibration-portfolio-stability-family-handoff-portfolio-resilience projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-165` plus confluence invariants (`INV-C174`, `INV-G212`).
- Residual risk:
Recovery requires corrected trust-calibration-portfolio-stability-family-handoff-portfolio-resilience lineage and may temporarily block resilience-governed admission for affected disputes.

## FM-181: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience Transition Violation

- Description:
Applied coupling-replenishment-debt-carryforward/expiry-cliff-smoothing-cutover/quorum-recovery-probation transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience bounds (carryforward reset laundering, smoothing skip bypass, probation bypass, resilience-before-handoff-portfolio coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits carryforward monotonicity checks, smoothing cutover continuity checks, probation hold/exit checks, resilience/handoff-portfolio coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience state cannot be derived from prior state + canonical resilience inputs under active resilience policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-166`; enforced by `INV-C173`, `INV-C175`, `INV-G213`, `INV-G214`.
- Residual risk:
Debt-carryforward ladder profiles, smoothing-cutover families, and probation-exit restitution catalogs remain limited.

## FM-182: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-governed resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_policy_hash` CAS checks at coupling-debt-carryforward-ladder-portfolio/smoothing-cutover-hysteresis-class/probation-exit-restitution and downstream apply boundaries.
- Consequence:
Replica-dependent resilience-family ladder/hysteresis/restitution states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references resilience-family policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilyPolicy` hash at admission boundary.
- Mitigation:
Resilience-family policy CAS gate with deterministic rejection `CF-167`; convergence bounded by `INV-C176`, `INV-C177`, `INV-G215`, `INV-G216`.
- Residual risk:
Frequent resilience-family policy cutovers can increase replanning churn and operational latency.

## FM-183: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family Basis Apply

- Description:
Coupling-debt-carryforward-ladder-portfolio/smoothing-cutover-hysteresis-class/probation-exit-restitution or resilience-family-governed resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical resilience-family lineage changed.
- Trigger:
No deterministic `coupling_debt_carryforward_ladder_portfolio_basis_hash`/`coupling_smoothing_cutover_hysteresis_class_basis_hash`/`coupling_probation_exit_restitution_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent resilience-family tuples and replay drift in downstream resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-168` (`INV-C177`, `INV-G216`, `INV-G217`).
- Residual risk:
Late admissible resilience-family evidence can invalidate queued plans at high cadence.

## FM-184: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family policy/record payload with ladder-portfolio bound inversion, hysteresis-class guard inversion, restitution cap/release inversion, unsupported resilience-family profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of ladder portfolio bounds/catalogs, hysteresis hold-window constraints, restitution monotonicity constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family lineage and divergent resilience/handoff-portfolio/handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-169` rejection (`INV-C178`, `INV-G218`).
- Residual risk:
Resilience-family quality still depends on upstream debt ladder and probation-stage labeling hygiene.

## FM-185: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family Projection Confluence Break

- Description:
Equivalent coupling-debt-carryforward-ladder-portfolio/smoothing-cutover-hysteresis-class/probation-exit-restitution projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_debt_carryforward_ladder_portfolio_projection_key`/`coupling_smoothing_cutover_hysteresis_class_projection_key`/`coupling_probation_exit_restitution_projection_key` or nondeterministic resilience-family serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family lineage and unstable downstream resilience/handoff-portfolio/handoff/stability-family/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same resilience-family projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-170` plus confluence invariants (`INV-C179`, `INV-G219`).
- Residual risk:
Recovery requires corrected resilience-family lineage and may temporarily block resilience-family-governed admission for affected disputes.

## FM-186: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family Transition Violation

- Description:
Applied coupling-debt-carryforward-ladder-portfolio/smoothing-cutover-hysteresis-class/probation-exit-restitution transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family bounds (ladder laundering, hysteresis-class oscillation bypass, restitution regression, resilience-family-before-resilience coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits ladder-selection monotonicity checks, hysteresis anti-flap constraints, restitution non-regression/restoration checks, resilience-family/resilience coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family state cannot be derived from prior state + canonical resilience-family inputs under active resilience-family policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-171`; enforced by `INV-C178`, `INV-C180`, `INV-G220`, `INV-G221`.
- Residual risk:
Restitution clawback windows, ladder demotion quarantine modes, and hysteresis debt-cooling families remain limited.

## FM-187: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-governed resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_policy_hash` CAS checks at coupling-restitution-clawback-window/ladder-demotion-quarantine/hysteresis-debt-cooling-cutover and downstream apply boundaries.
- Consequence:
Replica-dependent settlement closure states and non-reproducible downstream admissibility.
- Detection signal:
Admitted operation references settlement policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilySettlementPolicy` hash at admission boundary.
- Mitigation:
Settlement policy CAS gate with deterministic rejection `CF-172`; convergence bounded by `INV-C181`, `INV-C182`, `INV-G222`, `INV-G223`.
- Residual risk:
Frequent settlement policy cutovers can increase replanning churn and operational latency.

## FM-188: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement Basis Apply

- Description:
Coupling-restitution-clawback-window/ladder-demotion-quarantine/hysteresis-debt-cooling-cutover or settlement-governed resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical settlement lineage changed.
- Trigger:
No deterministic `coupling_restitution_clawback_window_basis_hash`/`coupling_ladder_demotion_quarantine_basis_hash`/`coupling_hysteresis_debt_cooling_cutover_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent settlement tuples and replay drift in downstream resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-173` (`INV-C182`, `INV-G223`, `INV-G224`).
- Residual risk:
Late admissible settlement evidence can invalidate queued plans at high cadence.

## FM-189: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement policy/record payload with clawback-window inversion, demotion-quarantine release inversion, debt-cooling slope/floor inversion, unsupported settlement profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of clawback-window closure bounds, quarantine stage ordering/release guards, cooling band/slope envelopes, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement lineage and divergent resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-174` rejection (`INV-C183`, `INV-G225`).
- Residual risk:
Settlement quality still depends on upstream restitution/debt canonicalization hygiene.

## FM-190: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement Projection Confluence Break

- Description:
Equivalent coupling-restitution-clawback-window/ladder-demotion-quarantine/hysteresis-debt-cooling-cutover projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_restitution_clawback_window_projection_key`/`coupling_ladder_demotion_quarantine_projection_key`/`coupling_hysteresis_debt_cooling_cutover_projection_key` or nondeterministic settlement serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement lineage and unstable downstream resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same settlement projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-175` plus confluence invariants (`INV-C184`, `INV-G226`).
- Residual risk:
Recovery requires corrected settlement lineage and may temporarily block settlement-governed admission for affected disputes.

## FM-191: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement Transition Violation

- Description:
Applied coupling-restitution-clawback-window/ladder-demotion-quarantine/hysteresis-debt-cooling-cutover transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement bounds (clawback replay laundering, quarantine escape bypass, cooling thaw-skip, settlement-before-resilience-family coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits clawback anti-replay checks, quarantine hold/release guards, cooling-step continuity constraints, settlement/resilience-family coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement state cannot be derived from prior state + canonical settlement inputs under active settlement policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-176`; enforced by `INV-C183`, `INV-C185`, `INV-G227`, `INV-G228`.
- Residual risk:
Clawback-appeal finality profiles, quarantine-release quorum families, and cooling reentry catalogs remain limited.

## FM-192: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-governed settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_policy_hash` CAS checks at coupling-clawback-appeal-escrow-closure/ladder-demotion-quarantine-release-quorum/debt-cooling-reentry-cutover and downstream apply boundaries.
- Consequence:
Replica-dependent finality closure states and non-reproducible downstream settlement/resilience-family admissibility.
- Detection signal:
Admitted operation references finality policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilySettlementFinalityPolicy` hash at admission boundary.
- Mitigation:
Settlement-finality policy CAS gate with deterministic rejection `CF-177`; convergence bounded by `INV-C186`, `INV-C187`, `INV-G229`, `INV-G230`.
- Residual risk:
Frequent settlement-finality policy cutovers can increase replanning churn and operational latency.

## FM-193: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality Basis Apply

- Description:
Coupling-clawback-appeal-escrow-closure/ladder-demotion-quarantine-release-quorum/debt-cooling-reentry-cutover or finality-governed settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical finality lineage changed.
- Trigger:
No deterministic `coupling_clawback_appeal_escrow_closure_basis_hash`/`coupling_ladder_demotion_quarantine_release_quorum_basis_hash`/`coupling_debt_cooling_reentry_cutover_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent finality tuples and replay drift in downstream settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-178` (`INV-C187`, `INV-G230`, `INV-G231`).
- Residual risk:
Late admissible finality evidence can invalidate queued plans at high cadence.

## FM-194: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality policy/record payload with escrow close/open inversion, release-quorum threshold inversion, debt-cooling reentry hold-window inversion, unsupported finality profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of escrow closure ordering, release quorum bounds, reentry hold/cutover constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality lineage and divergent settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-179` rejection (`INV-C188`, `INV-G232`).
- Residual risk:
Finality quality still depends on upstream escrow/quorum/reentry canonicalization hygiene.

## FM-195: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality Projection Confluence Break

- Description:
Equivalent coupling-clawback-appeal-escrow-closure/ladder-demotion-quarantine-release-quorum/debt-cooling-reentry-cutover projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_clawback_appeal_escrow_closure_projection_key`/`coupling_ladder_demotion_quarantine_release_quorum_projection_key`/`coupling_debt_cooling_reentry_cutover_projection_key` or nondeterministic finality serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality lineage and unstable downstream settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same settlement-finality projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-180` plus confluence invariants (`INV-C189`, `INV-G233`).
- Residual risk:
Recovery requires corrected finality lineage and may temporarily block finality-governed admission for affected disputes.

## FM-196: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality Transition Violation

- Description:
Applied coupling-clawback-appeal-escrow-closure/ladder-demotion-quarantine-release-quorum/debt-cooling-reentry-cutover transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality bounds (escrow close replay laundering, release-quorum forgery bypass, reentry cutover skip, settlement-finality-before-settlement coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits escrow anti-replay closure checks, release-quorum verifier constraints, reentry hold/cutover continuity constraints, settlement-finality/settlement coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality state cannot be derived from prior state + canonical finality inputs under active finality policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-181`; enforced by `INV-C188`, `INV-C190`, `INV-G234`, `INV-G235`.
- Residual risk:
Appeal-reopen families, release-quorum relapse containment modes, and reentry rebaseline catalogs remain limited.

## FM-197: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-governed settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_policy_hash` CAS checks at coupling-escrow-closure-appeal-reopen-constraint/quarantine-release-quorum-relapse-containment/debt-cooling-reentry-rebaseline and downstream apply boundaries.
- Consequence:
Replica-dependent relapse closure states and non-reproducible downstream settlement-finality/settlement admissibility.
- Detection signal:
Admitted operation references relapse policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilySettlementFinalityRelapsePolicy` hash at admission boundary.
- Mitigation:
Settlement-finality-relapse policy CAS gate with deterministic rejection `CF-182`; convergence bounded by `INV-C191`, `INV-C192`, `INV-G236`, `INV-G237`.
- Residual risk:
Frequent settlement-finality-relapse policy cutovers can increase replanning churn and operational latency.

## FM-198: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse Basis Apply

- Description:
Coupling-escrow-closure-appeal-reopen-constraint/quarantine-release-quorum-relapse-containment/debt-cooling-reentry-rebaseline or relapse-governed settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical relapse lineage changed.
- Trigger:
No deterministic `coupling_escrow_closure_appeal_reopen_constraint_basis_hash`/`coupling_quarantine_release_quorum_relapse_containment_basis_hash`/`coupling_debt_cooling_reentry_rebaseline_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent relapse tuples and replay drift in downstream settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-183` (`INV-C192`, `INV-G237`, `INV-G238`).
- Residual risk:
Late admissible relapse evidence can invalidate queued plans at high cadence.

## FM-199: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse policy/record payload with reopen budget inversion, relapse-containment quorum underflow, debt-cooling reentry-rebaseline offset inversion, unsupported relapse profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of reopen-window ordering, containment quorum bounds, rebaseline hold/offset constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse lineage and divergent settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-184` rejection (`INV-C193`, `INV-G239`).
- Residual risk:
Relapse quality still depends on upstream appeal/quorum/rebaseline canonicalization hygiene.

## FM-200: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse Projection Confluence Break

- Description:
Equivalent coupling-escrow-closure-appeal-reopen-constraint/quarantine-release-quorum-relapse-containment/debt-cooling-reentry-rebaseline projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_escrow_closure_appeal_reopen_constraint_projection_key`/`coupling_quarantine_release_quorum_relapse_containment_projection_key`/`coupling_debt_cooling_reentry_rebaseline_projection_key` or nondeterministic relapse serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse lineage and unstable downstream settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same settlement-finality-relapse projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-185` plus confluence invariants (`INV-C194`, `INV-G240`).
- Residual risk:
Recovery requires corrected relapse lineage and may temporarily block relapse-governed admission for affected disputes.

## FM-201: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse Transition Violation

- Description:
Applied coupling-escrow-closure-appeal-reopen-constraint/quarantine-release-quorum-relapse-containment/debt-cooling-reentry-rebaseline transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse bounds (reopen replay laundering, relapse-containment bypass, rebaseline skip, settlement-finality-relapse-before-settlement-finality coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits reopen anti-replay budget checks, relapse-containment quorum/window constraints, rebaseline hold-offset continuity constraints, settlement-finality-relapse/settlement-finality coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse state cannot be derived from prior state + canonical relapse inputs under active relapse policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-186`; enforced by `INV-C193`, `INV-C195`, `INV-G241`, `INV-G242`.
- Residual risk:
Appeal-budget terminalization families, relapse-decay reset profiles, and rebaseline probation-reconciliation catalogs remain limited.

## FM-202: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-governed settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_policy_hash` CAS checks at coupling-appeal-reopen-budget-exhaustion/relapse-containment-decay-reset/debt-cooling-reentry-probation-reconciliation and downstream apply boundaries.
- Consequence:
Replica-dependent terminal closure states and non-reproducible downstream settlement-finality-relapse/settlement admissibility.
- Detection signal:
Admitted operation references relapse-terminal policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilySettlementFinalityRelapseTerminalPolicy` hash at admission boundary.
- Mitigation:
Settlement-finality-relapse-terminal policy CAS gate with deterministic rejection `CF-187`; convergence bounded by `INV-C196`, `INV-C197`, `INV-G243`, `INV-G244`.
- Residual risk:
Frequent settlement-finality-relapse-terminal policy cutovers can increase replanning churn and operational latency.

## FM-203: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal Basis Apply

- Description:
Coupling-appeal-reopen-budget-exhaustion/relapse-containment-decay-reset/debt-cooling-reentry-probation-reconciliation or terminal-governed settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical relapse-terminal lineage changed.
- Trigger:
No deterministic `coupling_appeal_reopen_budget_exhaustion_basis_hash`/`coupling_relapse_containment_decay_reset_basis_hash`/`coupling_debt_cooling_reentry_probation_reconciliation_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent relapse-terminal tuples and replay drift in downstream settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-188` (`INV-C197`, `INV-G244`, `INV-G245`).
- Residual risk:
Late admissible terminal evidence can invalidate queued plans at high cadence.

## FM-204: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal policy/record payload with budget-exhaustion threshold inversion, decay-reset window inversion, probation-reconciliation underflow/overflow, unsupported terminal profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of exhaustion-window ordering, decay-reset bounds, probation-reconciliation constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal lineage and divergent settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-189` rejection (`INV-C198`, `INV-G246`).
- Residual risk:
Terminal quality still depends on upstream appeal/quorum/probation canonicalization hygiene.

## FM-205: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal Projection Confluence Break

- Description:
Equivalent coupling-appeal-reopen-budget-exhaustion/relapse-containment-decay-reset/debt-cooling-reentry-probation-reconciliation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_appeal_reopen_budget_exhaustion_projection_key`/`coupling_relapse_containment_decay_reset_projection_key`/`coupling_debt_cooling_reentry_probation_reconciliation_projection_key` or nondeterministic relapse-terminal serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal lineage and unstable downstream settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same settlement-finality-relapse-terminal projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-190` plus confluence invariants (`INV-C199`, `INV-G247`).
- Residual risk:
Recovery requires corrected relapse-terminal lineage and may temporarily block terminal-governed admission for affected disputes.

## FM-206: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal Transition Violation

- Description:
Applied coupling-appeal-reopen-budget-exhaustion/relapse-containment-decay-reset/debt-cooling-reentry-probation-reconciliation transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal bounds (exhaustion replay laundering, decay-reset bypass, probation-reconciliation skip, terminal-before-relapse coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits exhaustion anti-reissue checks, decay-reset window guards, probation-reconciliation coverage constraints, settlement-finality-relapse-terminal/settlement-finality-relapse coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal state cannot be derived from prior state + canonical terminal inputs under active terminal policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-191`; enforced by `INV-C198`, `INV-C200`, `INV-G248`, `INV-G249`.
- Residual risk:
Exhaustion amnesty families, decay-reset hysteresis classes, and probation-reconciliation debt-forgiveness catalogs remain limited.

## FM-207: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure Policy Drift Admission

- Description:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure-governed settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration operations are admitted under a stale lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure policy snapshot.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_policy_hash` CAS checks at coupling-exhaustion-amnesty-window/decay-reset-hysteresis-class/probation-reconciliation-debt-forgiveness-bound and downstream apply boundaries.
- Consequence:
Replica-dependent closure stabilization states and non-reproducible downstream settlement-finality-relapse-terminal/settlement admissibility.
- Detection signal:
Admitted operation references relapse-terminal-closure policy metadata that differs from active `CapsuleAttesterDisclosureLifecycleSignalFederationRehabilitationObjectiveCouplingProfileEvidenceIntegrityTrustCalibrationPortfolioStabilityFamilyHandoffPortfolioResilienceFamilySettlementFinalityRelapseTerminalClosurePolicy` hash at admission boundary.
- Mitigation:
Settlement-finality-relapse-terminal-closure policy CAS gate with deterministic rejection `CF-192`; convergence bounded by `INV-C201`, `INV-C202`, `INV-G250`, `INV-G251`.
- Residual risk:
Frequent settlement-finality-relapse-terminal-closure policy cutovers can increase replanning churn and operational latency.

## FM-208: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure Basis Apply

- Description:
Coupling-exhaustion-amnesty-window/decay-reset-hysteresis-class/probation-reconciliation-debt-forgiveness-bound or closure-governed settlement-finality-relapse-terminal/settlement-finality-relapse/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/utilization plan is applied after canonical relapse-terminal-closure lineage changed.
- Trigger:
No deterministic `coupling_exhaustion_amnesty_window_basis_hash`/`coupling_decay_reset_hysteresis_class_basis_hash`/`coupling_probation_reconciliation_debt_forgiveness_bound_basis_hash` and sequence verification at apply boundary.
- Consequence:
Order-dependent closure tuples and replay drift in downstream settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability/utilization/memory/arbitration lineage.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure/settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/handoff/stability-family/stability/trust-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle apply tuples differ from deterministic recomputation at the same `tx_asof`.
- Mitigation:
Basis CAS gates with deterministic rejection `CF-193` (`INV-C202`, `INV-G251`, `INV-G252`).
- Residual risk:
Late admissible closure evidence can invalidate queued plans at high cadence.

## FM-209: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure Payload

- Description:
Lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure policy/record payload with amnesty-window inversion, hysteresis-class inversion, debt-forgiveness-bound underflow/overflow, unsupported closure profile IDs, or non-canonical serialization is admitted.
- Trigger:
Weak validation of amnesty-window ordering, hysteresis-class bounds, debt-forgiveness-bound constraints, profile IDs, or tuple serialization.
- Consequence:
Tamperable trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure lineage and divergent settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/lifecycle admissibility outcomes across replicas.
- Detection signal:
Trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility enforcement with explicit `CF-194` rejection (`INV-C203`, `INV-G253`).
- Residual risk:
Closure quality still depends on upstream amnesty/hysteresis/forgiveness canonicalization hygiene.

## FM-210: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure Projection Confluence Break

- Description:
Equivalent coupling-exhaustion-amnesty-window/decay-reset-hysteresis-class/probation-reconciliation-debt-forgiveness-bound projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for `coupling_exhaustion_amnesty_window_projection_key`/`coupling_decay_reset_hysteresis_class_projection_key`/`coupling_probation_reconciliation_debt_forgiveness_bound_projection_key` or nondeterministic relapse-terminal-closure serialization.
- Consequence:
Replica-specific effective trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure lineage and unstable downstream settlement-finality-relapse-terminal/settlement-finality-relapse/settlement-finality/settlement/resilience-family/resilience/handoff-portfolio/trust/evidence/coupling-profile/coupling/rehabilitation/federation/signal/objective/calibration/lifecycle/disclosure/portability/adjudication/accountability eligibility.
- Detection signal:
Same settlement-finality-relapse-terminal-closure projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison conflict `CF-195` plus confluence invariants (`INV-C204`, `INV-G254`).
- Residual risk:
Recovery requires corrected closure lineage and may temporarily block closure-governed admission for affected disputes.

## FM-211: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure Transition Violation

- Description:
Applied coupling-exhaustion-amnesty-window/decay-reset-hysteresis-class/probation-reconciliation-debt-forgiveness-bound transitions violate deterministic trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure bounds (amnesty replay laundering, hysteresis oscillation bypass, forgiveness-bound skip, closure-before-terminal coupling breach, or rollback-precedence breach).
- Trigger:
Transition validation omits amnesty anti-replay checks, hysteresis anti-oscillation constraints, debt-forgiveness continuity checks, settlement-finality-relapse-terminal-closure/settlement-finality-relapse-terminal coupling checks, or rollback restoration rules.
- Consequence:
Deterministic but incorrect trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure state and replay divergence under rollback.
- Detection signal:
Observed lifecycle-signal-federation-rehabilitation-objective-coupling-profile-evidence-integrity-trust-calibration-portfolio-stability-family-handoff-portfolio-resilience-family-settlement-finality-relapse-terminal-closure state cannot be derived from prior state + canonical closure inputs under active closure policy.
- Mitigation:
Deterministic transition guard with explicit rejection `CF-196`; enforced by `INV-C203`, `INV-C205`, `INV-G255`, `INV-G256`.
- Residual risk:
Amnesty-window ladder families, hysteresis-class portfolios, and debt-forgiveness-bound restitution catalogs remain limited.

## FM-212: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity Policy Drift Admission

- Description:
Continuity-governed transitions are admitted under stale closure-continuity policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_policy_hash` CAS checks.
- Consequence:
Replica-dependent continuity states and non-reproducible downstream settlement admissibility.
- Detection signal:
Admitted op references continuity policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-197` (`INV-C206`, `INV-C207`, `INV-G257`, `INV-G258`).
- Residual risk:
Frequent continuity policy cutovers can increase replanning churn.

## FM-213: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity Basis Apply

- Description:
Continuity records/plans apply after canonical continuity lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_debt_retirement_ledger_basis_hash`/`coupling_hysteresis_freeze_thaw_arbitration_class_basis_hash`/`coupling_debt_forgiveness_bound_restitution_basis_hash` checks.
- Consequence:
Order-dependent continuity tuples and replay drift.
- Detection signal:
Continuity tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-198` (`INV-C207`, `INV-G258`, `INV-G259`).
- Residual risk:
Late admissible continuity evidence can invalidate queued plans.

## FM-214: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity Payload

- Description:
Continuity policy/record payload with retirement/arbitration/restitution bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of continuity tuple bounds and profile integrity.
- Consequence:
Tamperable continuity lineage and divergent downstream admissibility.
- Detection signal:
Continuity tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-199` (`INV-C208`, `INV-G260`).
- Residual risk:
Continuity quality still depends on upstream canonicalization hygiene.

## FM-215: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity Projection Confluence Break

- Description:
Equivalent continuity projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for continuity projection keys.
- Consequence:
Replica-specific continuity lineage and unstable downstream eligibility.
- Detection signal:
Same continuity projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-200` (`INV-C209`, `INV-G261`).
- Residual risk:
Recovery requires corrected continuity lineage and may temporarily block admissions.

## FM-216: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity Transition Violation

- Description:
Applied continuity transitions violate deterministic closure-continuity bounds (retirement replay laundering, freeze-thaw bypass, restitution skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits continuity anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect continuity state and replay divergence under rollback.
- Detection signal:
Observed continuity state cannot be derived from prior state + canonical continuity inputs under active continuity policy.
- Mitigation:
Deterministic transition guard with `CF-201` (`INV-C208`, `INV-C210`, `INV-G262`, `INV-G263`).
- Residual risk:
Retirement ladder, arbitration-family, and restitution-revocation catalogs remain limited.

## FM-217: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization Policy Drift Admission

- Description:
Closure-finalization-governed transitions are admitted under stale closure-finalization policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_policy_hash` CAS checks.
- Consequence:
Replica-dependent closure-finalization states and non-reproducible downstream settlement admissibility.
- Detection signal:
Admitted op references closure-finalization policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-202` (`INV-C211`, `INV-C212`, `INV-G264`, `INV-G265`).
- Residual risk:
Frequent closure-finalization policy cutovers can increase replanning churn.

## FM-218: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization Basis Apply

- Description:
Closure-finalization records/plans apply after canonical closure-finalization lineage changed.
- Trigger:
Missing deterministic `coupling_retirement_ledger_clawback_window_basis_hash`/`coupling_freeze_thaw_arbitration_deadband_envelope_basis_hash`/`coupling_debt_restitution_revocation_bond_basis_hash` checks.
- Consequence:
Order-dependent closure-finalization tuples and replay drift.
- Detection signal:
Closure-finalization tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-203` (`INV-C212`, `INV-G265`, `INV-G266`).
- Residual risk:
Late admissible closure-finalization evidence can invalidate queued plans.

## FM-219: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization Payload

- Description:
Closure-finalization policy/record payload with clawback/deadband/revocation bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of closure-finalization tuple bounds and profile integrity.
- Consequence:
Tamperable closure-finalization lineage and divergent downstream admissibility.
- Detection signal:
Closure-finalization tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-204` (`INV-C213`, `INV-G267`).
- Residual risk:
Closure-finalization quality still depends on upstream canonicalization hygiene.

## FM-220: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization Projection Confluence Break

- Description:
Equivalent closure-finalization projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for closure-finalization projection keys.
- Consequence:
Replica-specific closure-finalization lineage and unstable downstream eligibility.
- Detection signal:
Same closure-finalization projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-205` (`INV-C214`, `INV-G268`).
- Residual risk:
Recovery requires corrected closure-finalization lineage and may temporarily block admissions.

## FM-221: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization Transition Violation

- Description:
Applied closure-finalization transitions violate deterministic bounds (clawback replay laundering, deadband bypass, revocation-bond skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits closure-finalization anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect closure-finalization state and replay divergence under rollback.
- Detection signal:
Observed closure-finalization state cannot be derived from prior state + canonical closure-finalization inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-206` (`INV-C213`, `INV-C215`, `INV-G269`, `INV-G270`).
- Residual risk:
Clawback ladder, deadband-family, and revocation-bond redemption catalogs remain limited.

## FM-222: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge Policy Drift Admission

- Description:
Settlement-discharge-governed transitions are admitted under stale settlement-discharge policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-207` (`INV-C216`, `INV-C217`, `INV-G271`, `INV-G272`).
- Residual risk:
Frequent settlement-discharge policy cutovers can increase replanning churn.

## FM-223: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge Basis Apply

- Description:
Settlement-discharge records/plans apply after canonical settlement-discharge lineage changed.
- Trigger:
Missing deterministic `coupling_clawback_window_exhaustion_amnesty_release_basis_hash`/`coupling_deadband_envelope_collapse_cutover_basis_hash`/`coupling_revocation_bond_redemption_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge tuples and replay drift.
- Detection signal:
Settlement-discharge tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-208` (`INV-C217`, `INV-G272`, `INV-G273`).
- Residual risk:
Late admissible settlement-discharge evidence can invalidate queued plans.

## FM-224: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge Payload

- Description:
Settlement-discharge policy/record payload with amnesty-release/collapse-cutover/redemption bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-209` (`INV-C218`, `INV-G274`).
- Residual risk:
Settlement-discharge quality still depends on upstream canonicalization hygiene.

## FM-225: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge Projection Confluence Break

- Description:
Equivalent settlement-discharge projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge projection keys.
- Consequence:
Replica-specific settlement-discharge lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-210` (`INV-C219`, `INV-G275`).
- Residual risk:
Recovery requires corrected settlement-discharge lineage and may temporarily block admissions.

## FM-226: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge Transition Violation

- Description:
Applied settlement-discharge transitions violate deterministic bounds (amnesty-release replay laundering, collapse-cutover bypass, redemption skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge state cannot be derived from prior state + canonical settlement-discharge inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-211` (`INV-C218`, `INV-C220`, `INV-G276`, `INV-G277`).
- Residual risk:
Amnesty-release ladder, collapse-cutover family, and redemption-bond decay catalogs remain limited.

## FM-227: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality Policy Drift Admission

- Description:
Settlement-discharge-finality-governed transitions are admitted under stale settlement-discharge-finality policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-212` (`INV-C221`, `INV-C222`, `INV-G278`, `INV-G279`).
- Residual risk:
Frequent settlement-discharge-finality policy cutovers can increase replanning churn.

## FM-228: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality Basis Apply

- Description:
Settlement-discharge-finality records/plans apply after canonical settlement-discharge-finality lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_release_revocation_window_basis_hash`/`coupling_collapse_cutover_restitution_clamp_basis_hash`/`coupling_redemption_bond_decay_reconciliation_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality tuples and replay drift.
- Detection signal:
Settlement-discharge-finality tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-213` (`INV-C222`, `INV-G279`, `INV-G280`).
- Residual risk:
Late admissible settlement-discharge-finality evidence can invalidate queued plans.

## FM-229: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality Payload

- Description:
Settlement-discharge-finality policy/record payload with revocation-window/restitution-clamp/decay-reconciliation bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-214` (`INV-C223`, `INV-G281`).
- Residual risk:
Settlement-discharge-finality quality still depends on upstream canonicalization hygiene.

## FM-230: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality projection keys.
- Consequence:
Replica-specific settlement-discharge-finality lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-215` (`INV-C224`, `INV-G282`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality lineage and may temporarily block admissions.

## FM-231: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality Transition Violation

- Description:
Applied settlement-discharge-finality transitions violate deterministic bounds (revocation replay laundering, restitution-clamp bypass, decay-reconciliation skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality state cannot be derived from prior state + canonical settlement-discharge-finality inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-216` (`INV-C223`, `INV-C225`, `INV-G283`, `INV-G284`).
- Residual risk:
Revocation-window ladder, restitution-clamp family, and decay-reconciliation catalogs remain limited.

## FM-232: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-governed transitions are admitted under stale settlement-discharge-finality-closure policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-217` (`INV-C226`, `INV-C227`, `INV-G285`, `INV-G286`).
- Residual risk:
Frequent settlement-discharge-finality-closure policy cutovers can increase replanning churn.

## FM-233: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure Basis Apply

- Description:
Settlement-discharge-finality-closure records/plans apply after canonical settlement-discharge-finality-closure lineage changed.
- Trigger:
Missing deterministic `coupling_revocation_window_amnesty_regrant_quota_basis_hash`/`coupling_restitution_clamp_unwind_ladder_basis_hash`/`coupling_decay_reconciliation_terminal_release_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-218` (`INV-C227`, `INV-G286`, `INV-G287`).
- Residual risk:
Late admissible settlement-discharge-finality-closure evidence can invalidate queued plans.

## FM-234: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure Payload

- Description:
Settlement-discharge-finality-closure policy/record payload with regrant-quota/unwind-ladder/terminal-release bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-219` (`INV-C228`, `INV-G288`).
- Residual risk:
Settlement-discharge-finality-closure quality still depends on upstream canonicalization hygiene.

## FM-235: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-220` (`INV-C229`, `INV-G289`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure lineage and may temporarily block admissions.

## FM-236: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure Transition Violation

- Description:
Applied settlement-discharge-finality-closure transitions violate deterministic bounds (regrant replay laundering, unwind-ladder bypass, terminal-release skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure state cannot be derived from prior state + canonical settlement-discharge-finality-closure inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-221` (`INV-C228`, `INV-C230`, `INV-G290`, `INV-G291`).
- Residual risk:
Regrant-quota ladder, restitution-unwind family, and terminal-release catalogs remain limited.

## FM-237: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-222` (`INV-C231`, `INV-C232`, `INV-G292`, `INV-G293`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation policy cutovers can increase replanning churn.

## FM-238: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation records/plans apply after canonical settlement-discharge-finality-closure-reconciliation lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_regrant_quota_debt_sunset_basis_hash`/`coupling_restitution_unwind_ladder_reconciliation_freeze_basis_hash`/`coupling_terminal_release_recertification_bond_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-223` (`INV-C232`, `INV-G293`, `INV-G294`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation evidence can invalidate queued plans.

## FM-239: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation Payload

- Description:
Settlement-discharge-finality-closure-reconciliation policy/record payload with debt-sunset/reconciliation-freeze/recertification-bond bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-224` (`INV-C233`, `INV-G295`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation quality still depends on upstream canonicalization hygiene.

## FM-240: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-225` (`INV-C234`, `INV-G296`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation lineage and may temporarily block admissions.

## FM-241: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation transitions violate deterministic bounds (debt-sunset replay laundering, reconciliation-freeze bypass, recertification-bond skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-226` (`INV-C233`, `INV-C235`, `INV-G297`, `INV-G298`).
- Residual risk:
Debt-sunset ladder, reconciliation-freeze family, and recertification-bond catalogs remain limited.

## FM-242: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation-finality policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation-finality states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation-finality policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-227` (`INV-C236`, `INV-C237`, `INV-G299`, `INV-G300`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation-finality policy cutovers can increase replanning churn.

## FM-243: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation-finality records/plans apply after canonical settlement-discharge-finality-closure-reconciliation-finality lineage changed.
- Trigger:
Missing deterministic `coupling_debt_sunset_exhaustion_amnesty_closure_basis_hash`/`coupling_restitution_freeze_thaw_reentry_envelope_basis_hash`/`coupling_recertification_bond_redemption_decay_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation-finality tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-228` (`INV-C237`, `INV-G300`, `INV-G301`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation-finality evidence can invalidate queued plans.

## FM-244: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality Payload

- Description:
Settlement-discharge-finality-closure-reconciliation-finality policy/record payload with debt-sunset-exhaustion-amnesty-closure/restitution-freeze-thaw-reentry-envelope/recertification-bond-redemption-decay bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation-finality tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation-finality lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-229` (`INV-C238`, `INV-G302`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation-finality quality still depends on upstream canonicalization hygiene.

## FM-245: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation-finality projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation-finality projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation-finality lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation-finality projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-230` (`INV-C239`, `INV-G303`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation-finality lineage and may temporarily block admissions.

## FM-246: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation-finality transitions violate deterministic bounds (amnesty-closure replay laundering, thaw-reentry envelope bypass, redemption-decay skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation-finality anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation-finality state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation-finality state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation-finality inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-231` (`INV-C238`, `INV-C240`, `INV-G304`, `INV-G305`).
- Residual risk:
Amnesty-closure ladder, thaw-reentry envelope family, and redemption-decay catalogs remain limited.

## FM-247: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation-finality-discharge policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation-finality-discharge policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-232` (`INV-C241`, `INV-C242`, `INV-G306`, `INV-G307`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation-finality-discharge policy cutovers can increase replanning churn.

## FM-248: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge records/plans apply after canonical settlement-discharge-finality-closure-reconciliation-finality-discharge lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_closure_relapse_escrow_window_basis_hash`/`coupling_thaw_reentry_ladder_rebalance_basis_hash`/`coupling_redemption_decay_probation_settlement_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-233` (`INV-C242`, `INV-G307`, `INV-G308`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation-finality-discharge evidence can invalidate queued plans.

## FM-249: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge Payload

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge policy/record payload with amnesty-closure-relapse-escrow-window/thaw-reentry-ladder-rebalance/redemption-decay-probation-settlement bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation-finality-discharge tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation-finality-discharge lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-234` (`INV-C243`, `INV-G309`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation-finality-discharge quality still depends on upstream canonicalization hygiene.

## FM-250: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation-finality-discharge projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation-finality-discharge projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation-finality-discharge lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation-finality-discharge projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-235` (`INV-C244`, `INV-G310`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation-finality-discharge lineage and may temporarily block admissions.

## FM-251: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation-finality-discharge transitions violate deterministic bounds (amnesty-closure relapse-escrow replay laundering, thaw-reentry ladder-rebalance bypass, redemption-decay probation-settlement skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation-finality-discharge anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation-finality-discharge state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation-finality-discharge state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation-finality-discharge inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-236` (`INV-C243`, `INV-C245`, `INV-G311`, `INV-G312`).
- Residual risk:
Relapse-escrow ladder, thaw-reentry rebalance family, and probation-settlement catalogs remain limited.

## FM-252: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_stabilization_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-237` (`INV-C246`, `INV-C247`, `INV-G313`, `INV-G314`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization policy cutovers can increase replanning churn.

## FM-253: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization records/plans apply after canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization lineage changed.
- Trigger:
Missing deterministic `coupling_relapse_escrow_exhaustion_release_basis_hash`/`coupling_thaw_reentry_rebalance_deadband_cutover_basis_hash`/`coupling_probation_settlement_restitution_rollforward_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-238` (`INV-C247`, `INV-G314`, `INV-G315`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization evidence can invalidate queued plans.

## FM-254: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization Payload

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization policy/record payload with relapse-escrow-exhaustion-release/thaw-reentry-rebalance-deadband-cutover/probation-settlement-restitution-rollforward bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-239` (`INV-C248`, `INV-G316`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization quality still depends on upstream canonicalization hygiene.

## FM-255: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-240` (`INV-C249`, `INV-G317`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization lineage and may temporarily block admissions.

## FM-256: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization transitions violate deterministic bounds (relapse-escrow exhaustion-release replay laundering, thaw-reentry rebalance deadband-cutover bypass, probation-settlement restitution-rollforward skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-241` (`INV-C248`, `INV-C250`, `INV-G318`, `INV-G319`).
- Residual risk:
Exhaustion-release ladder, rebalance deadband family, and restitution-rollforward catalogs remain limited.

## FM-257: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_stabilization_finality_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-242` (`INV-C251`, `INV-C252`, `INV-G320`, `INV-G321`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality policy cutovers can increase replanning churn.

## FM-258: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality records/plans apply after canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality lineage changed.
- Trigger:
Missing deterministic `coupling_exhaustion_release_amnesty_restitution_closure_basis_hash`/`coupling_rebalance_deadband_hysteresis_quarantine_exit_cutover_basis_hash`/`coupling_restitution_rollforward_debt_recertification_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-243` (`INV-C252`, `INV-G321`, `INV-G322`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality evidence can invalidate queued plans.

## FM-259: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality Payload

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality policy/record payload with exhaustion-release-amnesty-restitution-closure/rebalance-deadband-hysteresis-quarantine-exit-cutover/restitution-rollforward-debt-recertification bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-244` (`INV-C253`, `INV-G323`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality quality still depends on upstream canonicalization hygiene.

## FM-260: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-245` (`INV-C254`, `INV-G324`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality lineage and may temporarily block admissions.

## FM-261: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality transitions violate deterministic bounds (exhaustion-release amnesty-restitution-closure replay laundering, rebalance-deadband hysteresis quarantine-exit bypass, restitution-rollforward debt-recertification skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-246` (`INV-C253`, `INV-C255`, `INV-G325`, `INV-G326`).
- Residual risk:
Restitution-closure ladder, hysteresis quarantine-exit family, and debt-recertification catalogs remain limited.

## FM-262: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge Policy Drift Admission

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge-governed transitions are admitted under stale settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_stabilization_finality_discharge_policy_hash` CAS checks.
- Consequence:
Replica-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge states and non-reproducible downstream settlement/finality admissibility.
- Detection signal:
Admitted op references settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge policy metadata different from active policy hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-247` (`INV-C256`, `INV-C257`, `INV-G327`, `INV-G328`).
- Residual risk:
Frequent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge policy cutovers can increase replanning churn.

## FM-263: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge Basis Apply

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge records/plans apply after canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_restitution_closure_debt_sunset_exhaustion_basis_hash`/`coupling_hysteresis_quarantine_exit_deadband_collapse_cutover_basis_hash`/`coupling_debt_recertification_restitution_terminalization_basis_hash` checks.
- Consequence:
Order-dependent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge tuples and replay drift.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-248` (`INV-C257`, `INV-G328`, `INV-G329`).
- Residual risk:
Late admissible settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge evidence can invalidate queued plans.

## FM-264: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge Payload

- Description:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge policy/record payload with amnesty-restitution-closure-debt-sunset-exhaustion/hysteresis-quarantine-exit-deadband-collapse-cutover/debt-recertification-restitution-terminalization bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge tuple bounds and profile integrity.
- Consequence:
Tamperable settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge lineage and divergent downstream admissibility.
- Detection signal:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-249` (`INV-C258`, `INV-G330`).
- Residual risk:
Settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge quality still depends on upstream canonicalization hygiene.

## FM-265: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge Projection Confluence Break

- Description:
Equivalent settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge projection keys.
- Consequence:
Replica-specific settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge lineage and unstable downstream eligibility.
- Detection signal:
Same settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-250` (`INV-C259`, `INV-G331`).
- Residual risk:
Recovery requires corrected settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge lineage and may temporarily block admissions.

## FM-266: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge Transition Violation

- Description:
Applied settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge transitions violate deterministic bounds (amnesty-restitution-closure debt-sunset-exhaustion replay laundering, hysteresis quarantine-exit deadband-collapse bypass, debt-recertification restitution-terminalization skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge state and replay divergence under rollback.
- Detection signal:
Observed settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge state cannot be derived from prior state + canonical settlement-discharge-finality-closure-reconciliation-finality-discharge-stabilization-finality-discharge inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-251` (`INV-C258`, `INV-C260`, `INV-G332`, `INV-G333`).
- Residual risk:
Debt-sunset-exhaustion ladder, deadband-collapse family, and restitution-terminalization catalogs remain limited.

## FM-267: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation Policy Drift Admission

- Description:
Reconciliation-governed transitions are admitted under stale reconciliation policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_stabilization_finality_discharge_reconciliation_policy_hash` CAS checks.
- Consequence:
Replica-dependent reconciliation states and non-reproducible downstream admissibility.
- Detection signal:
Admitted op references reconciliation policy metadata different from active hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-252` (`INV-C261`, `INV-C262`, `INV-G334`, `INV-G335`).
- Residual risk:
Frequent reconciliation policy cutovers can increase replanning churn.

## FM-268: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation Basis Apply

- Description:
Reconciliation records/plans apply after canonical reconciliation lineage changed.
- Trigger:
Missing deterministic `coupling_debt_sunset_exhaustion_amnesty_credit_retirement_basis_hash`/`coupling_deadband_collapse_quarantine_exit_restitution_rebalance_basis_hash`/`coupling_restitution_terminalization_recertification_reopen_basis_hash` checks.
- Consequence:
Order-dependent reconciliation tuples and replay drift.
- Detection signal:
Reconciliation tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-253` (`INV-C262`, `INV-G335`, `INV-G336`).
- Residual risk:
Late admissible reconciliation evidence can invalidate queued plans.

## FM-269: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation Payload

- Description:
Reconciliation payload with retirement/rebalance/reopen bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of reconciliation tuple bounds and profile integrity.
- Consequence:
Tamperable reconciliation lineage and divergent downstream admissibility.
- Detection signal:
Reconciliation tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-254` (`INV-C263`, `INV-G337`).
- Residual risk:
Reconciliation quality still depends on upstream canonicalization hygiene.

## FM-270: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation Projection Confluence Break

- Description:
Equivalent reconciliation projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for reconciliation projection keys.
- Consequence:
Replica-specific reconciliation lineage and unstable downstream eligibility.
- Detection signal:
Same reconciliation projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-255` (`INV-C264`, `INV-G338`).
- Residual risk:
Recovery requires corrected reconciliation lineage and may temporarily block admissions.

## FM-271: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation Transition Violation

- Description:
Applied reconciliation transitions violate deterministic bounds (amnesty-credit-retirement replay laundering, restitution-rebalance bypass, recertification-reopen skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits reconciliation anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect reconciliation state and replay divergence under rollback.
- Detection signal:
Observed reconciliation state cannot be derived from prior state + canonical reconciliation inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-256` (`INV-C263`, `INV-C265`, `INV-G339`, `INV-G340`).
- Residual risk:
Retirement ladders, restitution-rebalance families, and recertification-reopen catalogs remain limited.

## FM-272: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation-Terminal Policy Drift Admission

- Description:
Terminal-governed transitions are admitted under stale terminal policy snapshots.
- Trigger:
Missing `attester_disclosure_lifecycle_signal_federation_rehabilitation_objective_coupling_profile_evidence_integrity_trust_calibration_portfolio_stability_family_handoff_portfolio_resilience_family_settlement_finality_relapse_terminal_closure_continuity_closure_finalization_settlement_discharge_finality_closure_reconciliation_finality_discharge_stabilization_finality_discharge_reconciliation_terminal_policy_hash` CAS checks.
- Consequence:
Replica-dependent terminal states and non-reproducible downstream admissibility.
- Detection signal:
Admitted op references terminal policy metadata different from active hash at admission boundary.
- Mitigation:
Deterministic policy CAS gate with `CF-257` (`INV-C266`, `INV-C267`, `INV-G341`, `INV-G342`).
- Residual risk:
Frequent terminal policy cutovers can increase replanning churn.

## FM-273: Stale Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation-Terminal Basis Apply

- Description:
Terminal records/plans apply after canonical terminal lineage changed.
- Trigger:
Missing deterministic `coupling_amnesty_credit_retirement_reopen_throttle_basis_hash`/`coupling_quarantine_exit_restitution_rebalance_appeal_bond_basis_hash`/`coupling_recertification_reopen_debt_refinalization_basis_hash` checks.
- Consequence:
Order-dependent terminal tuples and replay drift.
- Detection signal:
Terminal tuples differ from deterministic recomputation at same `tx_asof`.
- Mitigation:
Basis CAS rejection `CF-258` (`INV-C267`, `INV-G342`, `INV-G343`).
- Residual risk:
Late admissible terminal evidence can invalidate queued plans.

## FM-274: Inadmissible Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation-Terminal Payload

- Description:
Terminal payload with reopen-throttle/appeal-bond/debt-refinalization bound violations or unsupported profile IDs is admitted.
- Trigger:
Weak validation of terminal tuple bounds and profile integrity.
- Consequence:
Tamperable terminal lineage and divergent downstream admissibility.
- Detection signal:
Terminal tuple violates active profile constraints but appears admitted.
- Mitigation:
Deterministic admissibility rejection `CF-259` (`INV-C268`, `INV-G344`).
- Residual risk:
Terminal quality still depends on upstream canonicalization hygiene.

## FM-275: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation-Terminal Projection Confluence Break

- Description:
Equivalent terminal projection identity is admitted with divergent payload bytes.
- Trigger:
Missing confluence checks for terminal projection keys.
- Consequence:
Replica-specific terminal lineage and unstable downstream eligibility.
- Detection signal:
Same terminal projection key appears with multiple payload variants.
- Mitigation:
Deterministic poison `CF-260` (`INV-C269`, `INV-G345`).
- Residual risk:
Recovery requires corrected terminal lineage and may temporarily block admissions.

## FM-276: Disclosure-Lifecycle-Signal-Federation-Rehabilitation-Objective-Coupling-Profile-Evidence-Integrity-Trust-Calibration-Portfolio-Stability-Family-Handoff-Portfolio-Resilience-Family-Settlement-Finality-Relapse-Terminal-Closure-Continuity-Closure-Finalization-Settlement-Discharge-Finality-Closure-Reconciliation-Finality-Discharge-Stabilization-Finality-Discharge-Reconciliation-Terminal Transition Violation

- Description:
Applied terminal transitions violate deterministic bounds (reopen-throttle replay laundering, appeal-bond bypass, debt-refinalization skip, ordering breach, or rollback-precedence breach).
- Trigger:
Transition validation omits terminal anti-replay/anti-bypass/ordering checks.
- Consequence:
Deterministic but incorrect terminal state and replay divergence under rollback.
- Detection signal:
Observed terminal state cannot be derived from prior state + canonical terminal inputs under active policy.
- Mitigation:
Deterministic transition guard with `CF-261` (`INV-C268`, `INV-C270`, `INV-G346`, `INV-G347`).
- Residual risk:
Reopen-throttle ladders, appeal-bond families, and debt-refinalization catalogs remain limited.
