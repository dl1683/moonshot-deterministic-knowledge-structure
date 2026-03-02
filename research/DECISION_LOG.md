# Decision Log

Only decisions that changed code/test behavior are recorded.

### DEC-178 - 2026-02-17

- Decision:
Set fail-closed merge-conflict journal tx-integrity as maintained V1 behavior policy: live recording (`record_merge_conflict_journal`, `merge_and_record_conflicts`) and snapshot/preflight entrypoints (`from_canonical_payload`/`from_canonical_json`/`from_canonical_json_file` plus `validate_canonical_payload`/`validate_canonical_json`/`validate_canonical_json_file`) must reject unknown journal tx ids for `merge_conflict_journal`, and anti-drift guard ownership must remain explicit.

- Context:
Iteration 166 added fail-closed live journal tx membership validation with `tests/test_v1_merge_conflict_journal_tx_validation.py`. Iteration 167 extended fail-closed unknown journal tx rejection to payload/json/file snapshot restore and preflight validation paths with `tests/test_v1_store_snapshot_merge_conflict_journal_tx_validation.py`. Iteration 168 added `tests/test_v1_merge_conflict_journal_tx_validation_guard.py` to lock structural routing ownership across live recording and snapshot/preflight validation entrypoints. Research docs and execution gate still needed this maintained policy recorded explicitly.

- Alternatives considered:
1. Keep fail-closed journal tx validation only for live recording and allow snapshot/preflight paths to drift.
2. Expand wrapper/parity coverage as a proxy for journal tx-integrity instead of documenting behavior-level entrypoint ownership.
3. Maintain explicit fail-closed journal tx-integrity policy across live recording and snapshot/preflight entrypoints, with dedicated anti-drift guard ownership and wrapper/parity non-expansion.

- Why chosen:
Option 3 directly reduces residual journal tx-label drift risk at behavior-level entrypoints while preserving deterministic merge/query correctness guarantees.

- Risks accepted:
Explicit `journal_tx_id` overrides can still select semantically wrong but known tx ids; this policy enforces membership integrity (unknown tx rejection), not caller intent correctness.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_journal_tx_validation.py` as maintained coverage for fail-closed live recording semantics on `record_merge_conflict_journal` and `merge_and_record_conflicts`; keep `tests/test_v1_store_snapshot_merge_conflict_journal_tx_validation.py` as maintained payload/json/file snapshot restore + preflight validation coverage for fail-closed unknown journal tx rejection on `merge_conflict_journal`; keep `tests/test_v1_merge_conflict_journal_tx_validation_guard.py` as maintained anti-drift routing ownership coverage across live recording and snapshot/preflight entrypoints; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-177 - 2026-02-17

- Decision:
Set tx-derived merge-conflict journal recording and journal-backed conflict query routing as maintained V1 behavior policy: `merge_and_record_conflicts` is the primary journal recording path on `KnowledgeStore`, direct journal query entrypoints (`query_merge_conflict_projection_as_of_from_journal`, `query_merge_conflict_projection_for_tx_window_from_journal`, `query_merge_conflict_projection_transition_for_tx_window_from_journal`) and default conflict-aware fingerprint resolution (`merge_results_by_tx=None`) must resolve from recorded journal state, and replay/checkpoint/duplicate/restart invariance plus runtime-budget guard ownership remain mandatory.

- Context:
Iteration 161 added `merge_and_record_conflicts` plus `tests/test_v1_merge_conflict_journal_merge_api.py` to derive journal tx ids from merge input and fail closed on empty/ambiguous derivation, reducing dependency on caller-managed tx labels. Iteration 162 added journal-backed query default coverage in `tests/test_v1_merge_conflict_journal_query_defaults.py`, including direct `*_from_journal` entrypoints and `merge_results_by_tx=None` default resolution for conflict-aware fingerprint query surfaces. Iteration 163 added `tests/test_v1_merge_conflict_journal_query_replay_restart.py` to lock permutation/checkpoint/duplicate/restart invariance for the journal-driven query path. Iteration 164 added `tests/test_v1_merge_conflict_journal_query_runtime_guard.py` to lock bounded matrix ownership required for reliable `tools/post_iter_verify.cmd` execution. Research docs and execution gate still needed this maintained policy recorded explicitly.

- Alternatives considered:
1. Keep caller-supplied tx label bookkeeping as the primary journaling/query contract and treat `merge_and_record_conflicts` as optional convenience.
2. Expand wrapper/parity suites to infer journal-backed defaults indirectly without documenting journal-backed query entrypoints as maintained behavior.
3. Promote tx-derived merge+journal recording and journal-backed query defaults as explicit maintained behavior with dedicated invariance/runtime guard ownership.

- Why chosen:
Option 3 directly reduces the highest remaining semantic risk from caller-managed tx-label drift while keeping deterministic merge/query correctness anchored to behavior-level APIs.

- Risks accepted:
Explicit `journal_tx_id` overrides and legacy manual `record_merge_conflict_journal` calls still permit incorrect tx labeling, but that path is no longer the primary policy; fail-closed derivation in `merge_and_record_conflicts` is now the default risk-reduction mechanism.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_journal_merge_api.py` as maintained coverage for tx-derived journal recording/fail-closed semantics on `merge_and_record_conflicts`; keep `tests/test_v1_merge_conflict_journal_query_defaults.py` as maintained coverage for journal-backed direct projection entrypoints (`query_merge_conflict_projection_as_of_from_journal`, `query_merge_conflict_projection_for_tx_window_from_journal`, `query_merge_conflict_projection_transition_for_tx_window_from_journal`) and conflict-aware default resolution when `merge_results_by_tx=None`; keep `tests/test_v1_merge_conflict_journal_query_replay_restart.py` as maintained replay/checkpoint/duplicate/restart invariance coverage for journal-driven query flows; keep `tests/test_v1_merge_conflict_journal_query_runtime_guard.py` as maintained runtime-budget guard ownership for bounded query replay/restart matrix growth; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-176 - 2026-02-17

- Decision:
Set deterministic merge-conflict journal persistence on `KnowledgeStore` as maintained V1 behavior policy: `record_merge_conflict_journal` and `merge_conflict_journal` must keep recorded merge results canonical as recorded merge_results_by_tx, preserve deterministic journal ordering, and keep payload/json/file snapshot persistence + validation semantics aligned with journal-backed replay/restart invariance and explicit runtime-budget guard ownership.

- Context:
Iteration 156 added deterministic merge-conflict journal APIs with `tests/test_v1_merge_conflict_journal.py`, anchoring normalized intake and deterministic ordering parity for direct merge-conflict and conflict-aware query surfaces when replay is sourced from journal state. Iteration 157 added canonical snapshot persistence/validation coverage in `tests/test_v1_store_snapshot_merge_conflict_journal.py`, locking payload/json/file round-trip behavior plus fail-closed malformed/tampered journal snapshot handling. Iteration 158 added `tests/test_v1_store_snapshot_merge_conflict_journal_replay_restart.py` to lock permutation/checkpoint/duplicate/restart invariance for journal-backed parity histories. Iteration 159 added `tests/test_v1_store_snapshot_merge_conflict_journal_runtime_guard.py` to lock runtime-bounded matrix ownership needed to keep `tools/post_iter_verify.cmd` reliably passing. Research docs and execution gate still needed this maintained policy recorded explicitly.

- Alternatives considered:
1. Leave merge-conflict journal persistence semantics implicit behind direct merge-conflict projection and snapshot suites.
2. Expand wrapper/parity checks to infer journal persistence and replay/restart semantics indirectly.
3. Document dedicated journal behavior, snapshot persistence/validation semantics, replay/restart invariance coverage, and runtime-budget guard ownership as maintained policy while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps behavior-first deterministic merge/query guarantees explicit at the `KnowledgeStore` journal surface and makes verifier runtime-budget ownership auditable.

- Risks accepted:
Journal ingestion still depends on caller-supplied tx annotations; incorrect source tx labeling can still produce semantically incorrect recorded merge_results_by_tx histories even when canonical journal ordering and replay determinism are preserved.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_journal.py` as maintained behavior coverage for deterministic merge-conflict journal recording/retrieval semantics and direct-query parity sourced from recorded merge_results_by_tx; keep `tests/test_v1_store_snapshot_merge_conflict_journal.py` as maintained snapshot payload/json/file persistence and validation semantics coverage for merge-conflict journal state; keep `tests/test_v1_store_snapshot_merge_conflict_journal_replay_restart.py` as maintained replay/checkpoint/duplicate/restart invariance coverage for journal-backed histories; keep `tests/test_v1_store_snapshot_merge_conflict_journal_runtime_guard.py` as maintained runtime-budget guard ownership for journal-backed replay/restart matrix growth; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-175 - 2026-02-17

- Decision:
Set direct merge-conflict input-aware KnowledgeStore snapshot restore parity as maintained V1 behavior policy: `query_merge_conflict_projection_as_of`, `query_merge_conflict_projection_for_tx_window`, and `query_merge_conflict_projection_transition_for_tx_window` with canonical `merge_results_by_tx` intake semantics must preserve restore parity across payload/json/file restart paths, with replay/checkpoint/restart invariance and explicit runtime-bounded guard ownership.

- Context:
Iteration 152 added `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs.py` to lock direct merge-conflict as-of/window/transition restore parity semantics across uninterrupted progression and payload/json/file restored progression under shuffled/materialized/one-shot `merge_results_by_tx` inputs. Iteration 153 added `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py` to lock permutation/checkpoint/duplicate/restart invariance for equivalent direct merge-conflict restore parity histories. Iteration 154 added `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_runtime_guard.py` to lock runtime-bounded matrix ownership needed to keep `tools/post_iter_verify.cmd` reliably passing. Research docs and execution gate still needed this maintained policy recorded explicitly.

- Alternatives considered:
1. Leave direct merge-conflict input-aware snapshot restore parity implicit behind existing merge-conflict projection/transition and snapshot parity suites.
2. Expand wrapper/parity checks to infer direct merge-conflict restore parity behavior indirectly.
3. Document dedicated direct merge-conflict restore parity behavior/invariance suites plus runtime-guard ownership as maintained policy, while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps behavior-first deterministic merge/query semantics explicit at direct merge-conflict API surfaces and makes runtime-budget ownership auditable where verifier stability matters.

- Risks accepted:
Direct merge-conflict replay input remains caller-supplied via `merge_results_by_tx`; incorrect caller tx annotations can still produce semantically incorrect merge-conflict projections even when restore parity and replay invariance remain deterministic.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs.py` as maintained coverage for direct merge-conflict restore parity across `query_merge_conflict_projection_as_of`/`query_merge_conflict_projection_for_tx_window`/`query_merge_conflict_projection_transition_for_tx_window` with canonical `merge_results_by_tx` intake semantics; keep `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_replay_restart.py` as maintained replay/checkpoint/duplicate/restart invariance coverage for equivalent direct merge-conflict restore parity histories; keep `tests/test_v1_store_snapshot_surface_parity_merge_conflict_inputs_runtime_guard.py` as maintained runtime-bounded guard ownership for the direct merge-conflict replay/restart matrix; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-174 - 2026-02-17

- Decision:
Set conflict-aware KnowledgeStore snapshot restore parity as maintained V1 behavior policy: `query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, and `query_state_fingerprint_transition_for_tx_window` with optional `merge_results_by_tx` must preserve restore parity across payload/json/file restart paths, with replay/checkpoint/restart invariance and explicit runtime-bounded guard ownership.

- Context:
Iteration 147 added `tests/test_v1_store_snapshot_surface_parity_conflict_aware_fingerprint.py` to lock conflict-aware as-of/window/transition restore parity semantics across uninterrupted progression and payload/json/file restored progression. Iteration 148 added `tests/test_v1_store_snapshot_surface_parity_conflict_aware_replay_restart.py` to lock permutation/checkpoint/duplicate/restart invariance for conflict-aware restore parity histories. Iteration 149 added `tests/test_v1_store_snapshot_surface_parity_conflict_aware_runtime_guard.py` to lock runtime-bounded matrix ownership needed to keep `tools/post_iter_verify.cmd` reliably passing. Research docs and execution gate still needed this maintained policy recorded explicitly.

- Alternatives considered:
1. Leave conflict-aware snapshot restore parity implicit behind existing state fingerprint and snapshot full-surface parity suites.
2. Expand wrapper/parity checks to infer conflict-aware restore parity behavior indirectly.
3. Document dedicated conflict-aware restore parity behavior/invariance suites plus runtime-guard ownership as maintained policy, while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps behavior-first deterministic merge/query semantics explicit at the conflict-aware API surface and makes runtime-budget ownership auditable where verifier stability matters.

- Risks accepted:
Conflict-aware replay inputs remain caller-supplied via `merge_results_by_tx`; incorrect caller tx annotations can still produce semantically incorrect fingerprints even when restore parity and replay invariance remain deterministic.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_surface_parity_conflict_aware_fingerprint.py` as maintained coverage for conflict-aware restore parity across as-of/window/transition fingerprint APIs (`query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, `query_state_fingerprint_transition_for_tx_window`) with optional `merge_results_by_tx`; keep `tests/test_v1_store_snapshot_surface_parity_conflict_aware_replay_restart.py` as maintained replay/checkpoint/duplicate/restart invariance coverage for conflict-aware restore parity; keep `tests/test_v1_store_snapshot_surface_parity_conflict_aware_runtime_guard.py` as maintained runtime-bounded guard ownership for the conflict-aware replay/restart matrix; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-173 - 2026-02-17

- Decision:
Set canonical direct merge-conflict `merge_results_by_tx` input normalization as maintained V1 behavior policy: `query_merge_conflict_projection_as_of`, `query_merge_conflict_projection_for_tx_window`, and `query_merge_conflict_projection_transition_for_tx_window` must route replay input through a shared deterministic normalization path before projection/transition reduction.

- Context:
Iteration 144 added `KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection` and `tests/test_v1_merge_conflict_input_normalization.py` to lock behavior-level input normalization parity (shuffled order and one-shot iterable intake) while preserving deterministic projection/transition signature+code bucket semantics. Iteration 145 added `tests/test_v1_merge_conflict_input_route_guard.py` to lock structural routing through that shared normalization helper and prevent inline normalization/sort drift. Research docs and execution gate still needed this maintained input normalization policy recorded explicitly.

- Alternatives considered:
1. Leave direct merge-conflict input normalization implicit behind existing projection/transition behavior and determinism suites.
2. Expand wrapper/parity checks to infer normalization behavior indirectly.
3. Document dedicated merge-conflict input normalization behavior + route-guard suites as maintained policy and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps deterministic merge/query correctness anchored to user-visible merge-conflict projection/transition behavior while making normalization-route anti-drift ownership explicit and auditable.

- Risks accepted:
`merge_results_by_tx` remains caller-supplied replay input; incorrect caller tx annotations can still produce semantically incorrect merge-conflict projections even when normalization routing remains deterministic.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_input_normalization.py` as maintained behavior-level input normalization coverage for `merge_results_by_tx` across `query_merge_conflict_projection_as_of`/`query_merge_conflict_projection_for_tx_window`/`query_merge_conflict_projection_transition_for_tx_window`; keep `tests/test_v1_merge_conflict_input_route_guard.py` as maintained structural enforcement that those APIs route through `KnowledgeStore._normalize_merge_results_by_tx_for_merge_conflict_projection`; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-172 - 2026-02-17

- Decision:
Set canonical conflict-aware state fingerprint `merge_results_by_tx` input normalization as maintained V1 behavior policy: `query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, and `query_state_fingerprint_transition_for_tx_window` must route optional replay input through a shared deterministic normalization path before merge-conflict projection composition.

- Context:
Iteration 141 added `KnowledgeStore._normalize_merge_results_by_tx_for_state_fingerprint` and `tests/test_v1_state_fingerprint_merge_conflicts_input_normalization.py` to lock behavior-level input normalization parity (shuffled order and one-shot iterable inputs) while preserving deterministic digest/bucket semantics. Iteration 142 added `tests/test_v1_state_fingerprint_merge_conflicts_input_route_guard.py` to lock structural routing through that shared normalization helper. Research docs and execution gate still needed this maintained input normalization policy recorded explicitly.

- Alternatives considered:
1. Leave input normalization implicit behind existing conflict-aware state fingerprint behavior/invariance suites.
2. Expand wrapper/parity checks to infer normalization behavior indirectly.
3. Document dedicated input normalization behavior + route-guard suites as maintained policy and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps deterministic merge/query correctness anchored to user-visible behavior while making normalization-route anti-drift ownership explicit and auditable.

- Risks accepted:
`merge_results_by_tx` remains caller-supplied replay input; incorrect caller tx annotations still yield semantically incorrect conflict-aware fingerprints even when normalization routing stays deterministic.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_merge_conflicts_input_normalization.py` as maintained behavior-level input normalization coverage for optional `merge_results_by_tx` across `query_state_fingerprint_as_of`/`query_state_fingerprint_for_tx_window`/`query_state_fingerprint_transition_for_tx_window`; keep `tests/test_v1_state_fingerprint_merge_conflicts_input_route_guard.py` as maintained structural enforcement that those surfaces route through `KnowledgeStore._normalize_merge_results_by_tx_for_state_fingerprint`; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-171 - 2026-02-17

- Decision:
Set conflict-aware state fingerprint query semantics as maintained V1 behavior policy: `query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, and `query_state_fingerprint_transition_for_tx_window` accept optional `merge_results_by_tx` input and must remain deterministic under replay-equivalent histories with cross-surface consistency coverage.

- Context:
Iterations 137-139 extended state fingerprint query APIs with optional `merge_results_by_tx` and added dedicated behavior-level verification in `tests/test_v1_state_fingerprint_merge_conflicts.py`, `tests/test_v1_state_fingerprint_merge_conflicts_permutations.py`, and `tests/test_v1_state_fingerprint_merge_conflicts_cross_surface_consistency.py` to lock conflict-aware semantics, replay/checkpoint/duplicate invariance, and cross-surface consistency. Research docs and gate checklist still needed this conflict-aware fingerprint policy recorded as maintained.

- Alternatives considered:
1. Leave conflict-aware state fingerprint semantics implicit behind existing state fingerprint and merge-conflict projection suites.
2. Expand wrapper/parity checks to infer conflict-aware fingerprint correctness indirectly.
3. Document dedicated conflict-aware state fingerprint behavior/invariance/consistency coverage as maintained policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps user-visible deterministic merge/query guarantees explicit where they matter: optional merge-stream projection input is canonicalized in behavior-level query surfaces, replay-equivalent histories stay digest-stable, and as-of/window/transition merge-conflict components stay semantically aligned.

- Risks accepted:
`merge_results_by_tx` remains caller-supplied replay input; incorrect caller-provided tx annotations can still produce incorrect conflict-aware fingerprint projections even when deterministic ordering/replay semantics are preserved.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_merge_conflicts.py` as maintained behavior coverage for optional `merge_results_by_tx` input through `query_state_fingerprint_as_of`/`query_state_fingerprint_for_tx_window`/`query_state_fingerprint_transition_for_tx_window`; keep `tests/test_v1_state_fingerprint_merge_conflicts_permutations.py` as maintained replay/checkpoint/duplicate determinism coverage for those conflict-aware fingerprint surfaces; keep `tests/test_v1_state_fingerprint_merge_conflicts_cross_surface_consistency.py` as maintained as-of/window/transition consistency coverage for conflict-aware merge-conflict fingerprint components; and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-170 - 2026-02-17

- Decision:
Set maintained replay/restart full-surface parity policy to be explicitly runtime-bounded, with bounds anchored to `tests/test_v1_store_snapshot_surface_parity_runtime_guard.py` so `tools/post_iter_verify.cmd` remains reliably passing.

- Context:
Iteration 132 showed that replay/restart full-surface parity matrix growth can push `tools/post_iter_verify.cmd` into timeout behavior even when semantics stay correct. Iteration 133 re-bounded replay/restart coverage without losing behavior-level guarantees, and iteration 135 added `tests/test_v1_store_snapshot_surface_parity_runtime_guard.py` to lock those runtime bounds structurally. Research docs and gate checklist still needed this runtime-bounded replay/restart policy recorded as maintained.

- Alternatives considered:
1. Leave replay/restart runtime bounds implicit and rely on occasional manual trimming when verifier runtime regresses.
2. Add more wrapper/parity routing checks to proxy runtime budget control indirectly.
3. Document runtime-bounded replay/restart parity policy and keep `tests/test_v1_store_snapshot_surface_parity_runtime_guard.py` as explicit maintained guard coverage.

- Why chosen:
Option 3 preserves behavior-first deterministic semantics while making verifier runtime constraints explicit, auditable, and resistant to drift.

- Risks accepted:
Runtime-bound fixtures and guard AST expectations can require intentional updates when behavior-level replay/restart semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_surface_parity_replay_restart.py` replay/restart coverage runtime-bounded (permutation matrix, segmented replay matrix, and restart-cycle budget), keep `tests/test_v1_store_snapshot_surface_parity_runtime_guard.py` as maintained structural enforcement of those bounds, and keep `tools/post_iter_verify.cmd` passing as the execution gate signal for bounded full-surface parity coverage.

### DEC-169 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot full-surface restore parity as maintained V1 behavior policy covering as-of/window query semantics, transition query semantics, and replay/checkpoint/restart invariance across payload/json/file restore paths.

- Context:
Iterations 125-133 added and stabilized dedicated full-surface restore parity suites in `tests/test_v1_store_snapshot_surface_parity_as_of_window.py`, `tests/test_v1_store_snapshot_surface_parity_transitions.py`, and `tests/test_v1_store_snapshot_surface_parity_replay_restart.py` to compare uninterrupted progression with payload/json/file restored progression for as-of/window and transition APIs, including replay/checkpoint/duplicate/restart invariance, but research docs and gate checklist had not yet marked this snapshot full-surface restore parity policy as maintained.

- Alternatives considered:
1. Leave snapshot full-surface restore parity guarantees implicit behind existing as-of/window/transition and file-I/O restart coverage.
2. Expand wrapper/parity matrices to proxy restore parity guarantees through additional internal route checks.
3. Document dedicated snapshot full-surface restore parity behavior coverage and suite ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps user-visible restore/query parity guarantees explicit and auditable at behavior level across as-of/window, transition, and replay/restart invariance surfaces while preserving deterministic merge/query correctness focus.

- Risks accepted:
Full-surface parity fixtures and replay/restart signature baselines can require intentional updates when behavior-level snapshot semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_surface_parity_as_of_window.py` as maintained coverage for full-surface as-of/window query parity between uninterrupted progression and payload/json/file restored stores; keep `tests/test_v1_store_snapshot_surface_parity_transitions.py` as maintained coverage for full-surface transition query parity (including boundary and zero-delta expectations) across payload/json/file restored stores; and keep `tests/test_v1_store_snapshot_surface_parity_replay_restart.py` as maintained replay/checkpoint/duplicate/restart invariance coverage for full-surface restore parity across canonical payload/json snapshots and restart flows; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-168 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot referential integrity semantics as maintained V1 behavior policy with strict fail-closed dangling-reference validation, payload/json/file entrypoint parity coverage, and referential-integrity anti-drift guard ownership.

- Context:
Iterations 118-120 hardened canonical snapshot restore/preflight validation in `src/dks/core.py` by enforcing strict fail-closed referential integrity checks in `KnowledgeStore.from_canonical_payload` (revision->core references plus active relation and active relation-variant endpoint references), added dedicated payload/json/file load-vs-validate parity coverage for equivalent referential failures, and added structural anti-drift guards against referential-validation bypass/fallback drift, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave snapshot referential integrity semantics implicit behind strict deserialization and snapshot validation-error coverage.
2. Expand wrapper/parity checks to infer referential integrity semantics indirectly.
3. Document dedicated snapshot referential integrity behavior coverage, payload/json/file parity coverage, and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps fail-closed snapshot referential integrity semantics explicit and auditable at behavior level across canonical payload/json/file restore and preflight entrypoints while preserving deterministic merge/query correctness focus.

- Risks accepted:
Referential-integrity fixtures and guard expectations can require intentional updates when canonical snapshot referential integrity semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_referential_integrity.py` as maintained coverage for strict fail-closed dangling-reference rejection (revision->core, active relation endpoints, and active relation-variant endpoints) across `KnowledgeStore.from_canonical_payload`/`KnowledgeStore.from_canonical_json`/`KnowledgeStore.from_canonical_json_file` and `KnowledgeStore.validate_canonical_payload`/`KnowledgeStore.validate_canonical_json`/`KnowledgeStore.validate_canonical_json_file`; keep `tests/test_v1_store_snapshot_referential_integrity_parity.py` as maintained payload/json/file load-vs-validate parity coverage for deterministic `SnapshotValidationError` `code`/`path` semantics plus valid restore/query/report parity; and keep `tests/test_v1_store_snapshot_referential_integrity_guard.py` as snapshot referential integrity anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-167 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot preflight validation semantics as maintained V1 behavior policy with deterministic `SnapshotValidationReport` contracts, payload/json/file entrypoint parity, replay/restart invariance coverage, and preflight-validation anti-drift guard ownership.

- Context:
Iterations 114-116 introduced deterministic preflight snapshot validation APIs in `src/dks/core.py` via `KnowledgeStore.validate_canonical_payload`/`KnowledgeStore.validate_canonical_json`/`KnowledgeStore.validate_canonical_json_file` (returning `SnapshotValidationReport` with stable `schema_version`/`snapshot_checksum`/`canonical_content_digest` semantics), added replay/restart invariance coverage for preflight reports across permutation/checkpoint/duplicate-replay and repeated save/load histories, and added structural preflight-route anti-drift guards, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave snapshot preflight validation semantics implicit behind existing snapshot validation-error and snapshot integrity coverage.
2. Expand wrapper/parity checks to infer preflight report and route semantics indirectly.
3. Document dedicated snapshot preflight validation behavior coverage and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps deterministic preflight validation report and entrypoint semantics explicit and auditable at behavior level across canonical payload/json/file preflight APIs while preserving deterministic merge/query correctness focus.

- Risks accepted:
Preflight report fixtures and preflight-route guard expectations can require intentional updates when canonical snapshot preflight semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_preflight_validation.py` as maintained coverage for deterministic `SnapshotValidationReport` semantics and load-vs-validate parity across `KnowledgeStore.validate_canonical_payload`/`KnowledgeStore.validate_canonical_json`/`KnowledgeStore.validate_canonical_json_file`; keep `tests/test_v1_store_snapshot_preflight_validation_permutations.py` as maintained replay/restart invariance coverage for preflight reports across permutation/checkpoint/duplicate-replay histories plus repeated `save_canonical_json`/`load_canonical_json` flows; and keep `tests/test_v1_store_snapshot_preflight_validation_guard.py` as snapshot preflight validation anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-166 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot integrity checksum semantics as maintained V1 behavior policy with deterministic `snapshot_checksum` contracts, fail-closed checksum validation, replay/restart invariance coverage, and checksum anti-drift guard ownership.

- Context:
Iterations 113-115 introduced deterministic canonical `snapshot_checksum` emission in `KnowledgeStore.as_canonical_payload`/`KnowledgeStore.as_canonical_json`, strict fail-closed checksum mismatch/missing rejection in `KnowledgeStore.from_canonical_payload` (and payload/json/file import parity via `KnowledgeStore.from_canonical_json`/`KnowledgeStore.from_canonical_json_file`), replay/restart invariance coverage for checksum-protected canonicalization, and structural checksum-route anti-drift guards in `src/dks/core.py`, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave snapshot integrity checksum semantics implicit behind generic snapshot serialization/schema-version coverage.
2. Expand wrapper/parity checks to infer checksum semantics indirectly.
3. Document dedicated snapshot integrity behavior coverage and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps snapshot integrity semantics explicit and auditable at behavior level across canonical payload/json/file entrypoints while preserving deterministic merge/query correctness focus.

- Risks accepted:
Checksum fixtures and checksum-route guard expectations can require intentional updates when canonical snapshot integrity semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_integrity.py` as maintained coverage for deterministic `snapshot_checksum` emission plus fail-closed mismatch/missing checksum rejection across canonical payload/json/file entrypoints, keep `tests/test_v1_store_snapshot_integrity_permutations.py` as maintained replay/restart invariance coverage for checksum-protected canonicalization across permutation/checkpoint/duplicate-replay histories and repeated `save_canonical_json`/`load_canonical_json` flows, and keep `tests/test_v1_store_snapshot_integrity_guard.py` as snapshot integrity checksum anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-165 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot validation-error semantics as maintained V1 behavior policy with deterministic `SnapshotValidationError` `code`/`path` contracts, payload/json/file entrypoint parity coverage, and validation-error anti-drift guard ownership.

- Context:
Iterations 109-111 introduced deterministic snapshot validation-error routing in `src/dks/core.py` via `SnapshotValidationError` (stable `code`/`path`/`message` semantics), added behavior coverage for payload/json/file canonical deserialization entrypoint parity, and added structural anti-drift guards against fallback/coercion and route drift, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Keep snapshot validation-error semantics implicit behind strict snapshot deserialization and schema-version coverage.
2. Expand wrapper/parity checks to infer validation-error contract correctness indirectly.
3. Document dedicated snapshot validation-error behavior coverage and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps deterministic validation-error semantics explicit and auditable at behavior level across payload/json/file entrypoints while preserving deterministic merge/query correctness focus.

- Risks accepted:
Validation-error code/path fixtures and structural guard expectations can require intentional updates when canonical snapshot behavior semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_validation_errors.py` as maintained coverage for deterministic `SnapshotValidationError` `code`/`path`/`message` semantics across canonical snapshot schema-version, strict key-set, and malformed-type failures for payload/json/file entrypoints; keep `tests/test_v1_store_snapshot_validation_error_parity.py` as maintained payload/json/file entrypoint parity coverage for equivalent failures plus valid restore/query parity; and keep `tests/test_v1_store_snapshot_validation_error_guard.py` as snapshot validation-error anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-164 - 2026-02-17

- Decision:
Set strict canonical `KnowledgeStore` snapshot deserialization policy as maintained V1 behavior policy with exact key-set validation, malformed-input fail-closed semantics, and strict-deserialization anti-drift guard ownership.

- Context:
Iterations 105-107 added strict canonical snapshot key-set validation in `KnowledgeStore.from_canonical_payload` (including relation-id key-set parity), a deterministic malformed-input matrix that locks fail-closed behavior across payload/json/file deserialization entrypoints, and structural strict-deserialization route guards in `src/dks/core.py`, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave strict snapshot deserialization policy implicit behind generic canonical snapshot/schema-version suites.
2. Expand wrapper/parity checks to infer strict deserialization correctness indirectly.
3. Document dedicated strict snapshot deserialization behavior coverage and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps strict snapshot deserialization semantics explicit and auditable at behavior level, including exact key-set validation and deterministic malformed-input fail-closed behavior across canonical snapshot import entrypoints.

- Risks accepted:
Strict snapshot deserialization fixtures and guard expectations can require intentional updates when canonical snapshot import semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_schema_strictness.py` as maintained coverage for exact canonical snapshot key-set validation (including deterministic relation-id key-set parity), keep `tests/test_v1_store_snapshot_malformed_inputs.py` as maintained malformed-input matrix coverage for fail-closed payload/json/file deserialization semantics, and keep `tests/test_v1_store_snapshot_strict_deserialization_guard.py` as strict snapshot deserialization anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-163 - 2026-02-17

- Decision:
Set schema-versioned canonical `KnowledgeStore` snapshot semantics as maintained V1 behavior policy with strict fail-closed compatibility and schema-version anti-drift guard ownership.

- Context:
Iterations 101-103 added explicit `snapshot_schema_version` contract emission via `KnowledgeStore._CANONICAL_SNAPSHOT_SCHEMA_VERSION`, strict fail-closed missing/unsupported `schema_version` rejection in `KnowledgeStore.from_canonical_payload`/`KnowledgeStore.from_canonical_json`, replay/permutation plus multi-restart save/load invariance coverage for schema-versioned snapshots, and structural schema-version route guards in `src/dks/core.py`, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Keep snapshot schema version compatibility implicit behind generic canonical snapshot serialization/file-I/O suites.
2. Expand wrapper/parity checks to infer schema-version compatibility semantics indirectly.
3. Document dedicated schema-version behavior coverage and guard ownership while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 keeps schema-version compatibility policy explicit and auditable at behavior level, including fail-closed deserialization semantics and deterministic replay/restart invariance for persisted schema-versioned snapshots.

- Risks accepted:
Schema-versioned compatibility policy can require intentional test/doc updates when canonical snapshot schema semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_schema_version.py` as maintained coverage for canonical `snapshot_schema_version` emission and strict fail-closed missing/unsupported `schema_version` compatibility checks, keep `tests/test_v1_store_snapshot_schema_version_permutations.py` as maintained replay/restart invariance coverage for schema-versioned snapshots across permutation/checkpoint/duplicate-replay and multi-restart `save_canonical_json`/`load_canonical_json` flows, and keep `tests/test_v1_store_snapshot_schema_version_guard.py` as schema-version anti-drift guard ownership in `src/dks/core.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-162 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot file I/O restart equivalence (disk restart parity with uninterrupted progression) as maintained V1 behavior policy.

- Context:
Iteration 97 added `tests/test_v1_store_snapshot_file_io_restart_equivalence.py` to compare uninterrupted in-memory progression against repeated disk checkpoint restart flows through `save_canonical_json`/`load_canonical_json` across restart boundaries, but research docs and gate checklist had not yet explicitly locked this restart equivalence guarantee as maintained policy.

- Alternatives considered:
1. Leave snapshot file I/O restart equivalence implicit behind broader replay-invariance coverage and incidental file save/load checks.
2. Expand wrapper/parity checks to infer restart semantics indirectly.
3. Document dedicated restart-equivalence suite ownership and explicit disk restart parity guarantees while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps persisted-checkpoint restart semantics explicit and auditable at behavior level instead of relying on wrapper/parity proxies.

- Risks accepted:
Restart-boundary matrix fixtures can require intentional updates when behavior-level canonical checkpoint semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_file_io_restart_equivalence.py` as maintained restart equivalence coverage for canonical snapshot file I/O disk restart parity against uninterrupted progression via `save_canonical_json`/`load_canonical_json`, alongside `tests/test_v1_store_snapshot_file_io.py`, `tests/test_v1_store_snapshot_file_io_permutations.py`, `tests/test_v1_store_snapshot_file_io_lock_failures.py`, and `tests/test_v1_store_snapshot_file_io_route_guard.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-161 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot file I/O semantics, replay-invariance coverage, and fail-closed lock/route behavior as maintained V1 behavior policy.

- Context:
Iterations 91-98 added canonical snapshot file save/load APIs (`KnowledgeStore.to_canonical_json_file`, `KnowledgeStore.write_canonical_json_file`, `KnowledgeStore.from_canonical_json_file`), restart-equivalent `_save_canonical_json`/`_load_canonical_json` flows, bounded lock-contention retry around atomic replace with persistent-lock fail-closed behavior, and structural file-I/O route guards, but research docs and gate checklist had not yet marked this maintained policy.

- Alternatives considered:
1. Leave canonical snapshot file I/O semantics implicit behind in-memory snapshot canonicalization semantics and incidental smoke checks.
2. Expand wrapper/parity checks to infer canonical snapshot file save/load policy indirectly.
3. Document canonical snapshot file I/O behavior semantics and maintained deterministic coverage for save/load correctness, replay invariance, lock-contention retry + persistent-lock fail-closed behavior, and route-guard enforcement while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps persisted-checkpoint save/load semantics deterministic and auditable at behavior level, including explicit fail-closed handling for persistent lock contention and anti-drift route ownership in `src/dks/core.py`.

- Risks accepted:
Lock-retry/backoff timing details and AST-shape route-guard expectations can require explicit updates when intentional internal refactors occur without changing user-visible behavior semantics.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_file_io.py`, `tests/test_v1_store_snapshot_file_io_permutations.py`, `tests/test_v1_store_snapshot_file_io_lock_failures.py`, and `tests/test_v1_store_snapshot_file_io_route_guard.py` as maintained canonical snapshot file I/O coverage, and keep restart-equivalence `save_canonical_json`/`load_canonical_json` flow checks in `tests/test_v1_store_snapshot_file_io_restart_equivalence.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-160 - 2026-02-17

- Decision:
Set golden snapshot regression coverage as maintained verification for canonical KnowledgeStore checkpoint serialization semantics.

- Context:
Iteration 89 added `tests/test_v1_store_snapshot_golden_regression.py` with frozen canonical payload/json baselines for `KnowledgeStore.as_canonical_payload`/`KnowledgeStore.as_canonical_json` plus restore/query parity checks via `KnowledgeStore.from_canonical_json`, but research docs and gate checklist had not yet marked this golden snapshot regression policy as maintained.

- Alternatives considered:
1. Leave canonical checkpoint serialization semantics anchored only by existing behavior/permutation/route-guard suites and treat snapshot golden values as ad-hoc.
2. Expand wrapper/parity checks to infer canonical checkpoint serialization stability indirectly.
3. Document `tests/test_v1_store_snapshot_golden_regression.py` as maintained golden snapshot regression coverage for canonical checkpoint serialization semantics while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and locks user-visible canonical checkpoint serialization semantics for `KnowledgeStore.as_canonical_json`/`KnowledgeStore.from_canonical_json` with explicit frozen-golden coverage while preventing wrapper/parity drift.

- Risks accepted:
Golden checkpoint payload/json snapshots require intentional updates when behavior-level canonical snapshot serialization semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_golden_regression.py` as maintained golden snapshot regression coverage for canonical checkpoint serialization semantics across `KnowledgeStore.as_canonical_json`/`KnowledgeStore.from_canonical_json`, alongside `tests/test_v1_store_snapshot_serialization.py`, `tests/test_v1_store_snapshot_serialization_permutations.py`, and `tests/test_v1_store_snapshot_route_guard.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-159 - 2026-02-17

- Decision:
Set canonical `KnowledgeStore` snapshot serialization/deserialization semantics, replay-invariance guarantees, and snapshot route-guard ownership as maintained V1 behavior policy.

- Context:
Iterations 85-87 added canonical snapshot APIs (`KnowledgeStore.as_canonical_payload`, `KnowledgeStore.as_canonical_json`, `KnowledgeStore.from_canonical_payload`, `KnowledgeStore.from_canonical_json`) plus dedicated maintained coverage (`tests/test_v1_store_snapshot_serialization.py`, `tests/test_v1_store_snapshot_serialization_permutations.py`, `tests/test_v1_store_snapshot_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave canonical KnowledgeStore snapshot semantics implicit via `checkpoint()` copy behavior and incidental replay/fingerprint coverage.
2. Expand wrapper/parity checks to infer canonical snapshot correctness indirectly.
3. Document canonical KnowledgeStore snapshot behavior semantics, replay-invariance coverage, and snapshot route-guard ownership as maintained policy while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps user-visible `KnowledgeStore.as_canonical_json`/`KnowledgeStore.from_canonical_json` checkpoint snapshot semantics anchored to deterministic merge/query reconstruction behavior, while preserving explicit coverage for permutation/checkpoint/duplicate-replay invariance and structural anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal snapshot helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_store_snapshot_serialization.py`, `tests/test_v1_store_snapshot_serialization_permutations.py`, and `tests/test_v1_store_snapshot_route_guard.py` as maintained deterministic KnowledgeStore snapshot policy coverage for canonical payload/json serialization-deserialization semantics (`KnowledgeStore.as_canonical_json`, `KnowledgeStore.from_canonical_json`), replay-invariance guarantees across permutation/checkpoint/duplicate-replay histories, and snapshot anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-158 - 2026-02-17

- Decision:
Set canonical state fingerprint deserialization semantics, round-trip replay invariance, and deserialization anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 83-85 added canonical deserialization APIs (`from_canonical_payload`, `from_canonical_json`) for `DeterministicStateFingerprint`/`DeterministicStateFingerprintTransition` and added dedicated maintained coverage (`tests/test_v1_state_fingerprint_deserialization.py`, `tests/test_v1_state_fingerprint_deserialization_permutations.py`, `tests/test_v1_state_fingerprint_deserialization_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave canonical fingerprint deserialization semantics implicit via serialization contracts and rely on incidental replay coverage.
2. Expand wrapper/parity checks to infer canonical fingerprint deserialization correctness indirectly.
3. Document canonical fingerprint deserialization behavior semantics, maintained round-trip replay invariance coverage, and deserialization anti-drift guard ownership as maintained policy while preserving behavior-first scope and no wrapper/parity expansion unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps user-visible `from_canonical_json`/`from_canonical_payload` semantics anchored to `query_state_fingerprint_as_of`/`query_state_fingerprint_for_tx_window`/`query_state_fingerprint_transition_for_tx_window` and `DeterministicStateFingerprint`/`DeterministicStateFingerprintTransition`, while preserving explicit coverage for round-trip replay invariance and structural deserialization anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal deserialization helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_deserialization.py`, `tests/test_v1_state_fingerprint_deserialization_permutations.py`, and `tests/test_v1_state_fingerprint_deserialization_guard.py` as maintained deterministic state fingerprint deserialization policy coverage for canonical fingerprint payload/json reconstruction semantics, round-trip replay invariance via `as_canonical_json` -> `from_canonical_json`, and deserialization anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-157 - 2026-02-17

- Decision:
Set golden fingerprint regression coverage as maintained verification for canonical fingerprint serialization semantics.

- Context:
Iteration 81 added `tests/test_v1_state_fingerprint_golden_regression.py` with frozen canonical payload/json goldens for `query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, and `query_state_fingerprint_transition_for_tx_window`, but research docs and gate checklist had not yet marked this golden fingerprint regression policy as maintained.

- Alternatives considered:
1. Leave canonical fingerprint serialization semantics anchored only by existing behavior/permutation/route-guard suites and treat golden values as ad-hoc.
2. Expand wrapper/parity checks to infer canonical fingerprint serialization stability indirectly.
3. Document `tests/test_v1_state_fingerprint_golden_regression.py` as maintained verification for canonical fingerprint serialization semantics while preserving behavior-first scope and keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and locks user-visible canonical fingerprint serialization semantics with explicit frozen-golden coverage across as-of, tx-window, and transition fingerprint surfaces while preventing wrapper/parity drift.

- Risks accepted:
Golden payload/json snapshots require intentional updates when behavior-level canonical fingerprint serialization semantics intentionally change.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_golden_regression.py` as maintained golden fingerprint regression coverage for canonical fingerprint serialization semantics across `query_state_fingerprint_as_of`, `query_state_fingerprint_for_tx_window`, and `query_state_fingerprint_transition_for_tx_window`, alongside `tests/test_v1_state_fingerprint_serialization.py`, `tests/test_v1_state_fingerprint_serialization_permutations.py`, and `tests/test_v1_state_fingerprint_serialization_route_guard.py`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-156 - 2026-02-17

- Decision:
Set canonical state fingerprint serialization semantics, replay invariance, and serialization anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 77-79 added canonical serialization APIs (`as_payload`, `as_canonical_payload`, `canonical_json`, `as_canonical_json`) for `DeterministicStateFingerprint`/`DeterministicStateFingerprintTransition` and added dedicated maintained coverage (`tests/test_v1_state_fingerprint_serialization.py`, `tests/test_v1_state_fingerprint_serialization_permutations.py`, `tests/test_v1_state_fingerprint_serialization_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave canonical json state fingerprint serialization semantics implicit via digest contracts and rely on incidental replay coverage.
2. Expand wrapper/parity checks to infer canonical state fingerprint serialization correctness indirectly.
3. Document canonical state fingerprint serialization behavior semantics, permutation/checkpoint/duplicate-replay invariance, and serialization anti-drift guard ownership as maintained policy while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps user-visible canonical json state fingerprint serialization semantics anchored to `query_state_fingerprint_as_of`/`query_state_fingerprint_for_tx_window`/`query_state_fingerprint_transition_for_tx_window` and `DeterministicStateFingerprint`/`DeterministicStateFingerprintTransition`, while preserving explicit coverage for replay invariance and structural serialization anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal serialization helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_serialization.py`, `tests/test_v1_state_fingerprint_serialization_permutations.py`, and `tests/test_v1_state_fingerprint_serialization_route_guard.py` as maintained deterministic state fingerprint serialization policy coverage for canonical json payload/text semantics, permutation/checkpoint/duplicate-replay invariance, and serialization anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-155 - 2026-02-17

- Decision:
Set deterministic state fingerprint transition semantics, replay invariance, and transition anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 73-75 added `DeterministicStateFingerprintTransition` plus `query_state_fingerprint_transition_for_tx_window`, and added dedicated maintained coverage (`tests/test_v1_state_fingerprint_transition.py`, `tests/test_v1_state_fingerprint_transition_permutations.py`, `tests/test_v1_state_fingerprint_transition_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave state fingerprint transition semantics implicit via underlying as-of fingerprint snapshots and rely on incidental replay coverage.
2. Expand wrapper/parity checks to infer state fingerprint transition correctness indirectly.
3. Document deterministic state fingerprint transition behavior semantics, permutation/checkpoint/duplicate-replay invariance, and anti-drift guard ownership as maintained policy while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic state fingerprint transition semantics anchored to user-visible API behavior for `query_state_fingerprint_transition_for_tx_window`/`DeterministicStateFingerprintTransition`, while preserving explicit coverage for permutation/checkpoint/duplicate-replay invariance and structural anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal transition fingerprint routing/normalization refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_transition.py`, `tests/test_v1_state_fingerprint_transition_permutations.py`, and `tests/test_v1_state_fingerprint_transition_route_guard.py` as maintained deterministic state fingerprint transition policy coverage for `query_state_fingerprint_transition_for_tx_window`/`DeterministicStateFingerprintTransition`, including permutation/checkpoint/duplicate-replay invariance and transition fingerprint anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-154 - 2026-02-17

- Decision:
Set deterministic tx-window state fingerprint semantics, replay invariance, and fingerprint anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 69-71 added `query_state_fingerprint_for_tx_window` and dedicated maintained coverage (`tests/test_v1_state_fingerprint_windows.py`, `tests/test_v1_state_fingerprint_windows_permutations.py`, `tests/test_v1_state_fingerprint_windows_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave tx-window state fingerprint semantics implicit via underlying tx-window projection/query surfaces and rely on incidental replay coverage.
2. Expand wrapper/parity checks to infer tx-window state fingerprint correctness indirectly.
3. Document deterministic tx-window state fingerprint behavior semantics, permutation/checkpoint/duplicate-replay invariance, and anti-drift guard ownership as maintained policy while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic tx-window state snapshot semantics anchored to user-visible API behavior for `query_state_fingerprint_for_tx_window`/`DeterministicStateFingerprint`, while preserving explicit coverage for permutation/checkpoint/duplicate-replay invariance and structural anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal tx-window fingerprint routing/normalization refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint_windows.py`, `tests/test_v1_state_fingerprint_windows_permutations.py`, and `tests/test_v1_state_fingerprint_windows_route_guard.py` as maintained deterministic tx-window state fingerprint policy coverage for `query_state_fingerprint_for_tx_window`/`DeterministicStateFingerprint`, including permutation/checkpoint/duplicate-replay invariance and fingerprint anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-153 - 2026-02-17

- Decision:
Set deterministic as-of state fingerprint semantics, replay invariance, and fingerprint anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 65-67 added `DeterministicStateFingerprint` plus `query_state_fingerprint_as_of`, and added dedicated maintained coverage (`tests/test_v1_state_fingerprint.py`, `tests/test_v1_state_fingerprint_permutations.py`, `tests/test_v1_state_fingerprint_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave state fingerprint semantics implicit via underlying as-of projection/query surfaces and rely on incidental replay coverage.
2. Expand wrapper/parity checks to infer state fingerprint correctness indirectly.
3. Document deterministic state fingerprint behavior semantics, permutation/checkpoint/duplicate-replay invariance, and anti-drift guard ownership as maintained policy while keeping wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic state snapshot semantics anchored to user-visible API behavior for `query_state_fingerprint_as_of`/`DeterministicStateFingerprint`, while preserving explicit coverage for permutation/checkpoint/duplicate-replay invariance and structural anti-drift routing in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal fingerprint routing/normalization refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_state_fingerprint.py`, `tests/test_v1_state_fingerprint_permutations.py`, and `tests/test_v1_state_fingerprint_route_guard.py` as maintained deterministic state fingerprint policy coverage for `query_state_fingerprint_as_of`/`DeterministicStateFingerprint`, including permutation/checkpoint/duplicate-replay invariance and fingerprint anti-drift guard enforcement; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-152 - 2026-02-17

- Decision:
Set canonical as-of helper routing and as-of helper bypass anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 62-63 routed as-of projection logic through one shared canonical as-of helper path and added dedicated maintained coverage (`tests/test_v1_as_of_canonicalization.py`, `tests/test_v1_as_of_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave as-of helper routing implicit inside per-query implementations and rely on incidental behavior/permutation coverage.
2. Expand wrapper/parity checks to infer as-of helper correctness indirectly.
3. Document canonical as-of helper routing plus dedicated canonicalization/guard suites as maintained behavior-level policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic as-of semantics anchored to user-visible API behavior for `query_revision_lifecycle_as_of`, `query_relation_resolution_as_of`, `query_relation_lifecycle_as_of`, `query_merge_conflict_projection_as_of`, and `query_relation_lifecycle_signatures_as_of`, while structural helper-bypass drift remains explicitly guarded.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal as-of helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_as_of_canonicalization.py` and `tests/test_v1_as_of_route_guard.py` as maintained as-of helper policy coverage for `query_revision_lifecycle_as_of`, `query_relation_resolution_as_of`, `query_relation_lifecycle_as_of`, `query_merge_conflict_projection_as_of`, and `query_relation_lifecycle_signatures_as_of`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-151 - 2026-02-17

- Decision:
Set canonical tx-window helper routing and tx-window helper bypass anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 59-60 routed tx-window projection logic through one shared canonical tx-window helper path and added dedicated maintained coverage (`tests/test_v1_tx_window_canonicalization.py`, `tests/test_v1_tx_window_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave tx-window helper routing implicit inside per-query implementations and rely on incidental behavior/permutation coverage.
2. Expand wrapper/parity checks to infer tx-window helper correctness indirectly.
3. Document canonical tx-window helper routing plus dedicated canonicalization/guard suites as maintained behavior-level policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic tx-window semantics anchored to user-visible API behavior for `query_revision_lifecycle_for_tx_window`, `query_relation_resolution_for_tx_window`, `query_relation_lifecycle_for_tx_window`, `query_merge_conflict_projection_for_tx_window`, and `query_relation_lifecycle_signatures_for_tx_window`, while structural helper-bypass drift remains explicitly guarded.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal tx-window helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_tx_window_canonicalization.py` and `tests/test_v1_tx_window_route_guard.py` as maintained tx-window helper policy coverage for `query_revision_lifecycle_for_tx_window`, `query_relation_resolution_for_tx_window`, `query_relation_lifecycle_for_tx_window`, `query_merge_conflict_projection_for_tx_window`, and `query_relation_lifecycle_signatures_for_tx_window`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-150 - 2026-02-17

- Decision:
Set canonical transition helper routing and transition helper bypass anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 56-57 routed transition-diff logic through one shared canonical transition helper path and added dedicated maintained coverage (`tests/test_v1_transition_canonicalization.py`, `tests/test_v1_transition_route_guard.py`), but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave transition helper routing implicit inside per-query implementations and rely on incidental behavior/permutation coverage.
2. Expand wrapper/parity checks to infer transition helper correctness indirectly.
3. Document canonical transition helper routing plus dedicated canonicalization/guard suites as maintained behavior-level policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic transition semantics anchored to user-visible API behavior for `query_revision_lifecycle_transition_for_tx_window`, `query_merge_conflict_projection_transition_for_tx_window`, and `query_relation_lifecycle_signature_transition_for_tx_window`, while structural helper-bypass drift remains explicitly guarded.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal transition helper refactors change call structure without behavior changes.

- Follow-up verification needed:
Keep `tests/test_v1_transition_canonicalization.py` and `tests/test_v1_transition_route_guard.py` as maintained transition helper policy coverage for `query_revision_lifecycle_transition_for_tx_window`, `query_relation_resolution_transition_for_tx_window`, `query_relation_lifecycle_transition_for_tx_window`, `query_merge_conflict_projection_transition_for_tx_window`, and `query_relation_lifecycle_signature_transition_for_tx_window`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-149 - 2026-02-17

- Decision:
Set relation lifecycle signature duplicate-replay idempotence, cross-surface consistency, and signature ordering-route anti-drift guard coverage as maintained V1 behavior policy.

- Context:
Iterations 52-54 added dedicated relation lifecycle signature deterministic coverage (`tests/test_v1_relation_lifecycle_signatures_duplicate_replay.py`, `tests/test_v1_relation_lifecycle_signatures_cross_surface_consistency.py`, `tests/test_v1_relation_lifecycle_signatures_guard.py`) for `query_relation_lifecycle_signatures_as_of`, `query_relation_lifecycle_signatures_for_tx_window`, and `query_relation_lifecycle_signature_transition_for_tx_window`, but research docs and gate checklist had not yet marked this policy as maintained.

- Alternatives considered:
1. Leave relation lifecycle signature idempotence/consistency/guard checks implicit across existing behavior and permutation suites.
2. Expand wrapper/parity checks to infer lifecycle-signature determinism coverage indirectly.
3. Document dedicated relation lifecycle signature duplicate-replay/cross-surface/guard suites as maintained behavior-level policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and locks user-visible deterministic guarantees where they matter: lifecycle-signature replay is idempotent under duplicate streams, tx-window and transition surfaces remain semantically consistent with explicit as-of parity/diff expectations, and structural ordering/route drift stays guarded in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal lifecycle-signature routing refactors change call shape without changing behavior semantics.

- Follow-up verification needed:
Keep `tests/test_v1_relation_lifecycle_signatures_duplicate_replay.py`, `tests/test_v1_relation_lifecycle_signatures_cross_surface_consistency.py`, and `tests/test_v1_relation_lifecycle_signatures_guard.py` as maintained lifecycle-signature determinism coverage for `query_relation_lifecycle_signatures_as_of`/`query_relation_lifecycle_signatures_for_tx_window`/`query_relation_lifecycle_signature_transition_for_tx_window`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-148 - 2026-02-17

- Decision:
Set merge-conflict duplicate replay idempotence and cross-surface consistency (tx-window/transition) as maintained V1 behavior policy, anchored to dedicated suites and existing transition semantics coverage.

- Context:
Iterations 49-50 added dedicated merge-conflict behavior suites `tests/test_v1_merge_conflict_duplicate_replay.py` and `tests/test_v1_merge_conflict_cross_surface_consistency.py` for `query_merge_conflict_projection_as_of`, `query_merge_conflict_projection_for_tx_window`, and `query_merge_conflict_projection_transition_for_tx_window`, but research docs and gate checklist had not yet marked these guarantees as maintained policy.

- Alternatives considered:
1. Leave merge-conflict duplicate replay and cross-surface consistency checks implicit across existing projection/transition suites.
2. Expand wrapper/parity checks to infer idempotence and consistency indirectly.
3. Document dedicated merge-conflict duplicate-replay and cross-surface consistency suites as maintained behavior-level policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and locks user-visible guarantees where they matter: duplicate replay remains idempotent across merge-conflict as-of, tx-window, and transition surfaces, and tx-window/transition outputs remain consistent with explicit as-of filter/diff semantics under deterministic ordering.

- Risks accepted:
Behavior-focused guarantees intentionally do not lock every internal projection reducer route as long as behavior semantics and deterministic ordering remain unchanged.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_duplicate_replay.py` and `tests/test_v1_merge_conflict_cross_surface_consistency.py` as maintained suites for merge-conflict idempotence/consistency policy across `query_merge_conflict_projection_as_of`, `query_merge_conflict_projection_for_tx_window`, and `query_merge_conflict_projection_transition_for_tx_window`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-147 - 2026-02-17

- Decision:
Set merge-conflict transition deterministic cutoff-diff semantics as maintained V1 behavior policy, anchored to dedicated behavior/permutation suites and structural anti-drift guard coverage.

- Context:
Iterations 45-47 introduced `MergeConflictProjectionTransition` and `query_merge_conflict_projection_transition_for_tx_window`, then locked permutation/checkpoint invariance plus AST guard coverage (`tests/test_v1_merge_conflict_transition.py`, `tests/test_v1_merge_conflict_transition_permutations.py`, `tests/test_v1_merge_conflict_transition_guard.py`), but research docs and gate policy had not yet marked this transition policy as maintained.

- Alternatives considered:
1. Keep merge-conflict transition semantics implicit and rely on callers to diff `query_merge_conflict_projection_as_of` outputs.
2. Expand wrapper/parity checks to infer transition correctness indirectly.
3. Document the transition API as explicit deterministic cutoff-diff policy with dedicated behavior/permutation/guard ownership, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and keeps deterministic merge/query correctness anchored to observable API behavior: `query_merge_conflict_projection_transition_for_tx_window` deterministically diffs as-of projections at `tx_from`/`tx_to`, returns stable entered/exited signature/code count buckets in `MergeConflictProjectionTransition`, and remains protected by dedicated permutation/checkpoint and anti-drift guard coverage.

- Risks accepted:
Structural guard coverage can require explicit updates when intentional internal routing refactors change call shape without changing behavior semantics.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_transition.py`, `tests/test_v1_merge_conflict_transition_permutations.py`, and `tests/test_v1_merge_conflict_transition_guard.py` as maintained transition policy coverage for `query_merge_conflict_projection_transition_for_tx_window`/`MergeConflictProjectionTransition`; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-146 - 2026-02-17

- Decision:
Set canonical ordering-helper routing, tie-break boundary semantics coverage, and ordering-route anti-drift enforcement as maintained V1 deterministic policy for behavior-level merge/query correctness.

- Context:
Iterations 41-43 routed winner/projection ordering through canonical helper keys in `src/dks/core.py`, added tie-break boundary coverage in `tests/test_v1_tiebreak_boundaries.py`, and added structural ordering-route guard coverage in `tests/test_v1_ordering_route_guard.py`, but research docs and execution gate policy had not yet marked this ordering policy as maintained.

- Alternatives considered:
1. Leave canonical ordering-helper behavior implicit in implementation and rely on incidental coverage.
2. Expand wrapper/parity checks to detect ordering regressions indirectly.
3. Document canonical ordering helper routing, tie-break boundary semantics, and ordering-route anti-drift guard as maintained verification policy, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and preserves deterministic merge/query correctness where users observe it: `tests/test_v1_ordering_canonicalization.py` anchors canonical ordering outputs across winner/projection APIs, `tests/test_v1_tiebreak_boundaries.py` anchors tie-break boundary semantics, and `tests/test_v1_ordering_route_guard.py` locks ordering-route anti-drift in `src/dks/core.py`.

- Risks accepted:
AST-shape guard coverage can require explicit updates when intentional internal ordering-route refactors change helper call forms without changing behavior semantics.

- Follow-up verification needed:
Keep `tests/test_v1_ordering_canonicalization.py`, `tests/test_v1_tiebreak_boundaries.py`, and `tests/test_v1_ordering_route_guard.py` as maintained ordering policy coverage, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

### DEC-145 - 2026-02-17

- Decision:
Set dedicated merge-conflict projection and relation lifecycle signature suites, plus suite-routing guard enforcement, as maintained V1 deterministic verification paths for behavior-level merge/query semantics.

- Context:
Iterations 35-39 extracted merge-conflict projection and lifecycle-signature coverage into dedicated behavior/permutation suites and added `tests/test_v1_suite_routing_guard.py`, but research docs and gate checklist did not yet mark these suites/guard as maintained ownership policy.

- Alternatives considered:
1. Keep merge-conflict projection and lifecycle-signature checks partially in `tests/test_v1_core.py` and rely on incidental ownership.
2. Expand wrapper/parity coverage to compensate for suite-routing drift.
3. Document dedicated behavior/permutation suites and routing guard as maintained verification paths, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and preserves deterministic merge/query correctness at API level: `query_merge_conflict_projection_as_of`, `query_relation_lifecycle_signatures_as_of`, and `query_relation_lifecycle_signature_transition_for_tx_window` remain anchored to dedicated maintained suites with explicit anti-drift routing guard coverage.

- Risks accepted:
Suite-routing guard coverage enforces test ownership by query-surface symbols and can require explicit updates when new related query APIs are introduced.

- Follow-up verification needed:
Keep `tests/test_v1_merge_conflict_projection.py`, `tests/test_v1_merge_conflict_projection_permutations.py`, `tests/test_v1_relation_lifecycle_signatures.py`, `tests/test_v1_relation_lifecycle_signatures_permutations.py`, and `tests/test_v1_suite_routing_guard.py` as maintained verification paths; wrapper/parity expansion remains out of scope unless behavior-level semantics change first.

### DEC-144 - 2026-02-17

- Decision:
Set cross-surface consistency as a maintained deterministic merge/query guarantee for V1 behavior-level semantics, anchored to dedicated suites `tests/test_v1_cross_surface_consistency_as_of.py` and `tests/test_v1_cross_surface_consistency_windows.py`.

- Context:
Iterations 32 and 33 added dedicated cross-surface consistency suites for as-of, tx-window, and transition query APIs, but research docs and gate checklist did not yet mark this consistency guarantee as maintained policy.

- Alternatives considered:
1. Leave cross-surface consistency checks as incidental assertions spread across existing behavior/permutation suites.
2. Resume wrapper/parity expansion to chase cross-surface consistency indirectly.
3. Document dedicated cross-surface consistency suites as maintained behavior-level deterministic coverage, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and directly encodes the user-visible guarantee that query surfaces stay semantically aligned: as-of winners/projections, tx-window filtering semantics, and transition deltas remain deterministically consistent representations of the same underlying lifecycle state.

- Risks accepted:
Cross-surface suites lock observable consistency outcomes across APIs rather than every internal merge/projection helper route.

- Follow-up verification needed:
Keep `tests/test_v1_cross_surface_consistency_as_of.py` and `tests/test_v1_cross_surface_consistency_windows.py` as the maintained cross-surface consistency suites, and require behavior-level semantics changes before any wrapper/parity expansion.

### DEC-143 - 2026-02-17

- Decision:
Set duplicate replay idempotence as a maintained deterministic merge/query guarantee for V1 behavior-level query semantics, anchored to dedicated suites `tests/test_v1_duplicate_replay_semantics.py` and `tests/test_v1_duplicate_replay_windows.py`.

- Context:
Iterations 29 and 30 added dedicated duplicate replay suites covering idempotent replay equivalence for as-of, tx-window, and transition query surfaces, but research docs and gate checklist did not yet mark duplicate replay determinism as maintained policy.

- Alternatives considered:
1. Leave duplicate replay coverage as incidental behavior in other permutation/checkpoint suites.
2. Resume wrapper/parity expansion to chase idempotent replay equivalence indirectly.
3. Document duplicate replay idempotence as maintained behavior-level deterministic coverage, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and directly encodes the merge/query guarantee users depend on: replaying identical payload streams is idempotent for deterministic query outputs, deterministic ordering, and conflict signature/count summaries.

- Risks accepted:
Duplicate replay suites intentionally lock behavior-level idempotent replay outcomes rather than every internal merge path detail.

- Follow-up verification needed:
Keep `tests/test_v1_duplicate_replay_semantics.py` and `tests/test_v1_duplicate_replay_windows.py` as the maintained duplicate replay suites for deterministic idempotent replay invariance, and require behavior-level semantics changes before any wrapper/parity expansion.

### DEC-142 - 2026-02-17

- Decision:
Set checkpoint segmentation invariance as a maintained deterministic merge/query guarantee for V1 behavior-level query semantics, anchored to dedicated suites `tests/test_v1_checkpoint_segmentation_as_of.py` and `tests/test_v1_checkpoint_segmentation_windows.py`.

- Context:
Iterations 25 and 27 added dedicated checkpoint segmentation suites covering unsplit-vs-segmented replay equivalence for as-of projections and tx-window/transition query surfaces, but research docs and gate checklist did not yet mark checkpoint segmentation determinism as maintained policy.

- Alternatives considered:
1. Leave checkpoint segmentation coverage as incidental behavior in other permutation/checkpoint suites.
2. Resume wrapper/parity expansion to chase segmentation equivalence indirectly.
3. Document checkpoint segmentation invariance as maintained behavior-level deterministic coverage, and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 matches DEC-136 behavior-first policy and directly encodes the merge/query guarantee users depend on: deterministic query outputs and conflict signatures are invariant to valid checkpoint segmentation boundaries under replay.

- Risks accepted:
Checkpoint segmentation suites intentionally lock deterministic equivalence outcomes rather than every internal merge path detail.

- Follow-up verification needed:
Keep `tests/test_v1_checkpoint_segmentation_as_of.py` and `tests/test_v1_checkpoint_segmentation_windows.py` as the maintained checkpoint segmentation suites for deterministic unsplit-vs-segmented replay invariance, and require behavior-level semantics changes before any wrapper/parity expansion.

### DEC-141 - 2026-02-17

- Decision:
Set dedicated relation lifecycle projection verification suites as the maintained V1 path: `tests/test_v1_relation_lifecycle.py` for behavior semantics and `tests/test_v1_relation_lifecycle_permutations.py` for permutation/checkpoint determinism of `query_relation_lifecycle_as_of` and `query_relation_lifecycle_for_tx_window`.

- Context:
Iterations 23-24 extracted relation lifecycle projection coverage into dedicated behavior and permutation suites, but research docs/gate language had not yet made those suites the explicit maintained verification path.

- Alternatives considered:
1. Keep relation lifecycle projection verification spread across generic/core suites and rely on incidental coverage.
2. Continue expanding wrapper/parity checks without tightening behavior-suite ownership.
3. Document dedicated relation lifecycle behavior/permutation suites as the maintained verification path and keep wrapper/parity expansion out of scope unless behavior-level semantics change first.

- Why chosen:
Option 3 aligns with the behavior-first policy from DEC-136 and keeps merge/query correctness anchored to observable API semantics (`query_relation_lifecycle_as_of`, `query_relation_lifecycle_for_tx_window`) instead of wrapper/parity proliferation.

- Risks accepted:
Dedicated-suite ownership requires discipline when lifecycle semantics expand, but keeps verification drift lower than broad wrapper/parity growth.

- Follow-up verification needed:
Keep `tests/test_v1_relation_lifecycle.py` and `tests/test_v1_relation_lifecycle_permutations.py` as the maintained verification path for relation lifecycle projection behavior/determinism, and require behavior-level semantics changes before any wrapper/parity expansion.

### DEC-140 - 2026-02-17

- Decision:
Add `RelationLifecycleTransition` plus `KnowledgeStore.query_relation_lifecycle_transition_for_tx_window(tx_from, tx_to, valid_at, revision_id=None)` to expose deterministic relation lifecycle transition deltas across transaction cutoffs.

- Context:
Iterations 20-21 implemented the relation lifecycle transition API and deterministic permutation/checkpoint replay coverage (`tests/test_v1_relation_lifecycle_transition.py`, `tests/test_v1_relation_lifecycle_transition_permutations.py`), but the research docs and gate checklist did not yet encode this API's cutoff-diff semantics and validation policy.

- Alternatives considered:
1. Keep relation lifecycle cutoff-to-cutoff transition diffing in callers by manually diffing two `query_relation_lifecycle_as_of` projections.
2. Document only API name + transition bucket names and leave cutoff-diff ordering and inverted-window policy implicit.
3. Document `query_relation_lifecycle_transition_for_tx_window` as an explicit deterministic cutoff-diff query surface with stable ordering and explicit inverted-window rejection, while keeping wrapper/parity expansion out of scope.

- Why chosen:
Option 3 matches shipped behavior with the smallest policy change: `query_relation_lifecycle_transition_for_tx_window` deterministically diffs relation lifecycle as-of projections at `tx_from` and `tx_to`, returns stable `relation_id`-ordered entered/exited active/pending buckets, and rejects inverted windows (`tx_to < tx_from`) explicitly.

- Risks accepted:
Transition semantics remain endpoint-only (`tx_from` -> `tx_to`) and intentionally do not model intermediate in-window timeline transitions.

- Follow-up verification needed:
Keep relation lifecycle transition ordering/replay determinism locked via dedicated permutation/checkpoint tests, and keep wrapper/parity expansion out of scope unless future behavior-level semantics require it.

### DEC-139 - 2026-02-17

- Decision:
Add `RevisionLifecycleTransition` plus `KnowledgeStore.query_revision_lifecycle_transition_for_tx_window(tx_from, tx_to, valid_at, core_id=None)` and `RelationResolutionTransition` plus `KnowledgeStore.query_relation_resolution_transition_for_tx_window(tx_from, tx_to, valid_at, core_id=None)` to expose deterministic lifecycle transition deltas across transaction cutoffs.

- Context:
Iterations 16-18 implemented both lifecycle transition APIs and permutation/checkpoint replay coverage (`tests/test_v1_revision_lifecycle_transition.py`, `tests/test_v1_relation_resolution_transition.py`, `tests/test_v1_lifecycle_transition_permutations.py`), but the research docs and gate checklist did not yet encode behavior-level transition semantics for these query surfaces.

- Alternatives considered:
1. Keep cutoff-to-cutoff transition diffing in callers by manually diffing two as-of projections for each API.
2. Document only transition bucket names and leave cutoff-diff and inverted-window semantics implicit.
3. Document both transition APIs as explicit cutoff-diff query surfaces with deterministic ordering and explicit inverted-window rejection.

- Why chosen:
Option 3 matches shipped behavior with minimal additional policy: each transition API computes endpoint deltas by diffing deterministic as-of projections at `tx_from` and `tx_to`, returns stable ordered entered/exited buckets, and rejects inverted windows (`tx_to < tx_from`) explicitly.

- Risks accepted:
Transition semantics are intentionally endpoint-only (`tx_from` -> `tx_to`) and do not encode intermediate in-window timeline segmentation between cutoffs.

- Follow-up verification needed:
Keep transition ordering and replay determinism locked via lifecycle transition permutation/checkpoint tests; relation-level tombstones remain out of scope and must be introduced by a separate behavior-first slice.

### DEC-138 - 2026-02-17

- Decision:
Add `RelationResolutionProjection` plus `KnowledgeStore.query_relation_resolution_as_of(tx_id, valid_at, core_id=None)` and `KnowledgeStore.query_relation_resolution_for_tx_window(tx_start, tx_end, valid_at, core_id=None)` to expose deterministic relation resolution winner projections.

- Context:
Iterations 12-14 implemented relation resolution projection APIs and deterministic permutation/checkpoint replay coverage (`tests/test_v1_relation_resolution.py`, `tests/test_v1_relation_resolution_permutations.py`), but the research docs and gate checklist did not yet encode the behavior-level semantics for these query surfaces.

- Alternatives considered:
1. Keep relation resolution projection assembly in callers by repeatedly invoking `query_as_of`/`query_relation_lifecycle_as_of` and manually deriving tx-window filtering.
2. Document only the tx-cutoff relation resolution API and leave tx-window semantics implicit.
3. Document both APIs with explicit deterministic tx-window semantics and explicit scope boundary on relation-level tombstones.

- Why chosen:
Option 3 matches shipped behavior with minimal additional policy: `query_relation_resolution_as_of` returns deterministic `RelationResolutionProjection(active, pending)` relation winner buckets at a tx cutoff, while `query_relation_resolution_for_tx_window` deterministically computes relation resolution as-of `tx_end` and filters winners to inclusive `tx_start..tx_end`.

- Risks accepted:
Tx-window semantics are intentionally defined as filtered winners from the as-of `tx_end` relation resolution projection, not as full relation lifecycle timeline reconstruction across in-window intermediate states.

- Follow-up verification needed:
Keep ordering and replay determinism locked via relation resolution behavior tests; relation-level tombstones remain explicitly out of scope for this slice and must be introduced by a separate behavior-first decision/test change.

### DEC-137 - 2026-02-17

- Decision:
Add `RevisionLifecycleProjection` plus `KnowledgeStore.query_revision_lifecycle_as_of(tx_id, valid_at, core_id=None)` and `KnowledgeStore.query_revision_lifecycle_for_tx_window(tx_start, tx_end, valid_at, core_id=None)` to expose deterministic revision lifecycle winner projections.

- Context:
Iterations 8-10 implemented revision lifecycle projection APIs and deterministic permutation/checkpoint replay coverage (`tests/test_v1_revision_lifecycle.py`, `tests/test_v1_revision_lifecycle_permutations.py`), but the research docs and gate checklist did not yet encode the behavior-level semantics for these new query surfaces.

- Alternatives considered:
1. Keep lifecycle projection assembly in callers by repeatedly invoking `query_as_of` per core and manually deriving retracted winners/window filtering.
2. Document only the tx-cutoff projection API and leave tx-window semantics implicit.
3. Document both APIs with explicit deterministic tx-window semantics and explicit scope boundary on relation-level tombstones.

- Why chosen:
Option 3 matches shipped behavior with minimal additional policy: `query_revision_lifecycle_as_of` returns deterministic `RevisionLifecycleProjection(active, retracted)` winner buckets at a tx cutoff, while `query_revision_lifecycle_for_tx_window` deterministically computes lifecycle as-of `tx_end` and filters winners to inclusive `tx_start..tx_end`.

- Risks accepted:
Tx-window semantics are intentionally defined as filtered winners from the as-of `tx_end` lifecycle projection, not as full lifecycle timeline reconstruction across all in-window intermediate states.

- Follow-up verification needed:
Keep ordering and replay determinism locked via revision lifecycle tests; relation-level tombstones remain explicitly out of scope for this slice and must be introduced by a separate behavior-first decision/test change.

### DEC-136 - 2026-02-17

- Decision:
Set the deterministic V1 behavior policy: behavior-level semantics are canonical for merge/query correctness, and projection wrapper proliferation is disallowed in favor of canonical routing.

- Context:
Iterations 120-127 expanded parity shims without new user-visible semantics. Iterations 1-6 then added behavior coverage (`tests/test_v1_semantics.py`, `tests/test_v1_determinism_permutations.py`), structural guards (`tests/test_merge_result_wrapper_guard.py`), and import-time wrapper collapse (`_collapse_merge_result_projection_extension_wrappers`) in `src/dks/core.py`.

- Alternatives considered:
1. Keep parity-wrapper growth and treat deep route chains as acceptable maintenance cost.
2. Keep implementation changes but do not document a policy, leaving semantics and wrapper expectations implicit.
3. Record explicit behavior-first policy and canonical projection route constraints from the implemented tests and runtime collapse logic.

- Why chosen:
Option 3 reflects the shipped implementation. Behavior tests are source of truth for deterministic merge/query outcomes, and projection wrappers resolve directly to canonical projection route targets (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components` for summary-chunk arity and `MergeResult._extend_conflict_projection_counts_from_pre_fanned_component_chunks` for pre-fanned arity).

- Risks accepted:
Wrapper-adding refactors now require stronger justification because no-behavior-change shim proliferation is outside policy.

- Follow-up verification needed:
Keep the wrapper drift guard (`tests/test_merge_result_wrapper_guard.py`) authoritative for wrapper surface/arity/hash expectations, and require behavior-level semantics tests to lead any future merge/query semantics changes.

### DEC-135 - 2026-02-17

- Decision:
Add `RelationLifecycleSignatureTransition` and `KnowledgeStore.query_relation_lifecycle_signature_transition_for_tx_window(tx_start, tx_end, valid_from, valid_to, revision_id=None)` to expose deterministic lifecycle signature deltas across valid-time changes for a fixed inclusive transaction window.

- Context:
`query_relation_lifecycle_signatures_for_tx_window` exposed snapshot buckets at one `valid_at`, but behavior coverage needed a first-class API for endpoint lifecycle transitions (entered/exited active/pending signatures) when `valid_at` changes while tx window remains fixed.

- Alternatives considered:
1. Keep transition math in callers by diffing two lifecycle-signature projections client-side.
2. Add tests only without introducing a production transition API.
3. Add a deterministic transition query API on `KnowledgeStore` with explicit valid-range validation.

- Why chosen:
Option 3 adds externally observable V1 behavior with minimal mechanism by composing existing lifecycle-signature tx-window queries and returning stable sorted delta buckets.

- Risks accepted:
Transition semantics are point-to-point (`valid_from` -> `valid_to`) and do not yet expose intermediate timeline segmentation.

- Follow-up verification needed:
If future slices add relation-level tombstones or interval timeline queries, preserve transition-delta parity against projected signatures at both endpoints under permutation + checkpoint-resumed replay.

### DEC-134 - 2026-02-17

- Decision:
Add `KnowledgeStore.query_relation_lifecycle_signatures_for_tx_window(tx_start, tx_end, valid_at, revision_id=None)` to expose deterministic relation lifecycle signature projections over inclusive transaction windows, with explicit `ValueError` behavior for inverted windows inherited from `query_relation_lifecycle_for_tx_window`.

- Context:
`query_relation_lifecycle_signatures_as_of` provided only tx-cutoff signature buckets; behavior coverage needed a first-class tx-window signature query that stays deterministic and checkpoint-resumed replay equivalent.

- Alternatives considered:
1. Keep tx-window signature filtering in callers by manually filtering `query_relation_lifecycle_signatures_as_of` outputs.
2. Expose only tx-window edge-level lifecycle projection and leave signature materialization to callers.
3. Add a direct tx-window lifecycle signature projection API on `KnowledgeStore`.

- Why chosen:
Option 3 adds externally observable behavior with the smallest implementation by reusing existing tx-window lifecycle filtering and returning stable ordered signature buckets in one deterministic query surface.

- Risks accepted:
Signature window semantics are intentionally defined as signature materialization over the tx-window lifecycle projection at `tx_end`, rather than independent raw relation scans.

- Follow-up verification needed:
If future lifecycle slices add relation-level tombstones, preserve parity between tx-window lifecycle signature projections and filtered tx-window lifecycle edge projections under permutation + checkpoint-resumed replay.

### DEC-133 - 2026-02-17

- Decision:
Add `KnowledgeStore.query_relation_lifecycle_for_tx_window(tx_start, tx_end, valid_at, revision_id=None)` to expose deterministic relation lifecycle projections over inclusive transaction windows, with explicit `ValueError` on inverted windows (`tx_end < tx_start`).

- Context:
`query_relation_lifecycle_as_of` provides lifecycle state only at one tx cutoff; behavior coverage needed a first-class tx-window lifecycle query that remains deterministic and checkpoint-resumed replay equivalent.

- Alternatives considered:
1. Keep window filtering in tests/callers by manually filtering `query_relation_lifecycle_as_of` outputs.
2. Add a signatures-only tx-window API without edge-level lifecycle output.
3. Add a direct tx-window lifecycle projection API on `KnowledgeStore`.

- Why chosen:
Option 3 adds externally observable behavior with the smallest mechanism, keeps deterministic ordering from existing lifecycle queries, and makes tx-window semantics explicit in production code.

- Risks accepted:
Window semantics are intentionally bounded to filtering lifecycle state at `tx_end` by relation transaction-time membership in `tx_start..tx_end`.

- Follow-up verification needed:
If future lifecycle slices add relation-level tombstones, preserve parity between tx-window lifecycle projections and filtered as-of lifecycle views under permutation + checkpoint-resumed replay.

### DEC-132 - 2026-02-17

- Decision:
Add `KnowledgeStore.query_merge_conflict_projection_for_tx_window(merge_results_by_tx, tx_start, tx_end)` to expose deterministic merge-conflict projection queries over inclusive transaction windows, with explicit `ValueError` on inverted windows (`tx_end < tx_start`).

- Context:
`query_merge_conflict_projection_as_of` supports only upper-bound filtering; behavior coverage needed a first-class tx-window query API to compare unsplit vs checkpoint-resumed replay streams over bounded ranges.

- Alternatives considered:
1. Reuse `query_merge_conflict_projection_as_of` twice and subtract summaries client-side.
2. Add a wrapper utility in tests only.
3. Add a direct tx-window query API in `KnowledgeStore`.

- Why chosen:
Option 3 provides explicit externally observable behavior with the smallest deterministic mechanism and avoids non-deterministic client-side subtraction logic.

- Risks accepted:
Adds one public query entrypoint to maintain; semantics are intentionally limited to inclusive integer tx windows.

- Follow-up verification needed:
If merge-result stream schemas evolve, keep tx-window filtering parity locked to filtered `MergeResult.stream_conflict_summary` under permutation and checkpoint-resumed replay.

### DEC-001 - 2026-02-16

- Decision:
Implement a minimal Python V1 kernel in `src/dks/core.py` with immutable dataclass primitives (`ClaimCore`, `ClaimRevision`, `RelationEdge`) and deterministic hash IDs.

- Context:
Repository had no runnable `src/` or `tests/` scaffolding, so V1 execution work could not proceed.

- Alternatives considered:
1. Continue design-only docs with no executable code.
2. Build full distributed governance framework first.
3. Start with a minimal deterministic kernel and expand by failing tests.

- Why chosen:
Option 3 satisfies bootstrap + execution requirements while keeping scope inside V1 hard limits.

- Risks accepted:
Merge conflict taxonomy and relation temporal visibility are intentionally minimal in this slice.

- Follow-up verification needed:
Add tests for retractions, relation as-of visibility, and additional deterministic merge conflict classes.

### DEC-002 - 2026-02-16

- Decision:
Make `query_as_of` lifecycle-aware by selecting the highest transaction-time slot deterministically and returning `None` when the winning revision is `retracted`; add `query_relations_as_of` for relation visibility under transaction cutoffs.

- Context:
Iteration 1 stored `status` values but query behavior only considered asserted revisions, and there was no relation as-of query path.

- Alternatives considered:
1. Add a separate retraction index/subsystem.
2. Preserve current query behavior and delay lifecycle semantics.
3. Use deterministic ranking over existing revisions plus a minimal relation-as-of accessor.

- Why chosen:
Option 3 delivers required V1 behavior with minimal mechanism and keeps determinism local to current primitives.

- Risks accepted:
Retraction semantics are currently slot-level and driven by ranking, not by explicit reference chains.

- Follow-up verification needed:
Expand adversarial replay/permutation tests and conflict classes around lifecycle transitions.

### DEC-003 - 2026-02-16

- Decision:
Update merge conflict handling to compare an incoming revision against all existing same-slot revisions (same `core_id`, `valid_time`, `tx_id`) and deduplicate conflict pairs deterministically.

- Context:
Iteration 2 only compared against the first competing revision in a slot, which could miss lifecycle conflicts under multi-replica replay permutations.

- Alternatives considered:
1. Keep first-match conflict detection and rely on pairwise merge order.
2. Add a new subsystem for global merge provenance replay.
3. Enumerate all same-slot competitors inside current merge pass and dedupe by sorted revision-id pair.

- Why chosen:
Option 3 captures lifecycle-specific collisions with minimal mechanism and makes permutation replay conflict signatures deterministic.

- Risks accepted:
Conflict reporting still uses aggregate `MergeConflict` records and does not introduce a richer causal graph model.

- Follow-up verification needed:
Continue with edge-case tests for relation lifecycle semantics if relation retractions become required.

### DEC-004 - 2026-02-16

- Decision:
Extend `query_relations_as_of` with optional `active_only=True` + `valid_at` filtering so relation visibility can be deterministically constrained to currently active endpoint revisions.

- Context:
Relation querying was transaction-time only, so edges remained visible even when endpoint revisions were later retracted in lifecycle state.

- Alternatives considered:
1. Introduce a new relation lifecycle/retraction subsystem.
2. Keep relation visibility transaction-time only.
3. Reuse existing `query_as_of` lifecycle state to filter relation endpoints on demand.

- Why chosen:
Option 3 adds deterministic lifecycle-aware relation visibility with minimal mechanism and no new primitives.

- Risks accepted:
Active-only filtering depends on core-level winner selection and does not model explicit relation tombstones.

- Follow-up verification needed:
If future slices require relation-level retractions, add a dedicated relation lifecycle primitive with merge conflict coverage.

### DEC-005 - 2026-02-16

- Decision:
Classify incoming relation edges with missing endpoint revisions during merge as `orphan_relation_endpoint` conflicts and deterministically skip ingesting those relations.

- Context:
Relation ingestion was previously unconditional in merge once relation IDs were unique, allowing partial/corrupt replicas to introduce edges that reference missing revisions.

- Alternatives considered:
1. Auto-create placeholder endpoint revisions.
2. Ingest orphan relations and rely on query-time filtering.
3. Reject orphan relations at merge-time with explicit deterministic conflict classification.

- Why chosen:
Option 3 keeps V1 minimal, preserves deterministic merge outputs, and prevents invalid relation edges from entering canonical store state.

- Risks accepted:
If endpoint revisions arrive later from other replicas, skipped orphan relations are not auto-replayed in this slice.

- Follow-up verification needed:
If eventual orphan-relation recovery becomes required, add a deterministic pending-relation replay mechanism with permutation tests.

### DEC-006 - 2026-02-16

- Decision:
Add deterministic deferred orphan-relation replay in merge: keep unresolved relation edges in an internal pending buffer and promote them automatically once endpoint revisions become available in later merges.

- Context:
Iteration 5 classified orphan edges and skipped ingest, which made final relation state order-sensitive when relation edges and endpoint revisions arrived from different replicas.

- Alternatives considered:
1. Keep skip-only orphan handling and accept merge-order sensitivity.
2. Require replicas to resend relation edges after endpoints arrive.
3. Persist unresolved edges as pending and replay them deterministically at the end of each merge.

- Why chosen:
Option 3 preserves V1 minimalism while restoring deterministic final relation state under mixed-source replay permutations.

- Risks accepted:
`orphan_relation_endpoint` conflicts are now classified against incoming-replica endpoint completeness as well as merged-state completeness, which can report provenance-quality conflicts even when merged state can already resolve the relation.

- Follow-up verification needed:
If pending-buffer growth becomes a concern, add bounded retention/metrics while preserving deterministic replay behavior.

### DEC-007 - 2026-02-16

- Decision:
Treat repeated merges of an identical orphan relation edge as idempotent for conflict emission: once that relation payload is already tracked (pending or promoted), do not emit another `orphan_relation_endpoint` conflict.

- Context:
Deferred orphan replay in iteration 6 preserved deterministic final state, but replaying the same orphan edge multiple times produced duplicate orphan-conflict records even when no state changed.

- Alternatives considered:
1. Keep emitting orphan conflicts on every replay event.
2. Add a separate deduplication ledger for emitted conflicts.
3. Gate orphan-conflict emission on whether the identical relation is already known in merged state.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes merge replay idempotent while preserving collision detection and orphan classification for first-seen relations.

- Risks accepted:
Repeated sparse-source replays of an already-known relation no longer generate repeated orphan conflict telemetry.

- Follow-up verification needed:
If repeated-source quality metrics are required later, add explicit deterministic counters without changing merge-state semantics.

### DEC-008 - 2026-02-16

- Decision:
Resolve divergent `relation_id` collisions with a deterministic canonical payload winner (stable relation-field sort key) instead of implicit first-wins retention.

- Context:
With deferred orphan replay, the same `relation_id` could collide while existing state was pending in some merge orders and promoted in others, which allowed final relation payload to vary by replay order.

- Alternatives considered:
1. Keep current first-wins behavior and only assert conflict determinism.
2. Reject both colliding relations and delete the relation ID from merged state.
3. Keep emitting `relation_id_collision`, but deterministically pick one payload winner and replace existing pending/promoted state when needed.

- Why chosen:
Option 3 is the smallest mechanism that preserves collision visibility while making final merged relation state replay-order invariant for collision cases.

- Risks accepted:
Canonical winner selection is payload-lexicographic, not provenance-weighted; this favors determinism over source trust heuristics in V1.

- Follow-up verification needed:
If provenance-prioritized conflict resolution is required later, add an explicit deterministic policy layer without changing collision-signature behavior.

### DEC-009 - 2026-02-16

- Decision:
Track per-`relation_id` relation payload variants and deduplicate emitted collision pairs so `relation_id_collision` conflicts are emitted once per unique payload-pair signature under replay.

- Context:
Canonical winner selection from iteration 8 converged final state, but repeated 3+ divergent payload replays could still produce order-sensitive collision multiplicity/signature output.

- Alternatives considered:
1. Keep winner convergence only and accept replay-order differences in collision records.
2. Emit collisions only against current canonical winner.
3. Persist seen payload variants and pairwise collision signatures per relation ID.

- Why chosen:
Option 3 is the smallest deterministic extension that stabilizes both final relation payload and collision telemetry across repeated/permuted 3+ payload replays.

- Risks accepted:
Internal merge state now keeps additional deterministic bookkeeping (`_relation_variants`, `_relation_collision_pairs`) for replay idempotency.

- Follow-up verification needed:
If relation collision details need to be compacted later, keep pair-signature determinism while reducing verbosity.

### DEC-010 - 2026-02-16

- Decision:
Add an explicit `checkpoint()` snapshot clone operation and route merge snapshots through it, with tests that lock relation collision-history continuity across clone boundaries.

- Context:
Iteration 9 introduced persistent relation collision bookkeeping, but checkpoint/copy continuity under continued replay merges was not explicitly modeled or verified.

- Alternatives considered:
1. Keep implicit `copy()` usage with no dedicated checkpoint semantics.
2. Rebuild relation collision bookkeeping lazily after each clone.
3. Preserve bookkeeping directly in deterministic snapshot clones and assert behavior with post-checkpoint replay tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps merge replay state continuity explicit and verifiable without adding a new subsystem.

- Risks accepted:
`checkpoint()` adds a second snapshot entry point (with `copy()` retained for compatibility), so API surface is slightly wider.

- Follow-up verification needed:
If serialized snapshots are added later, ensure `_relation_variants` and `_relation_collision_pairs` round-trip without changing conflict signatures.

### DEC-011 - 2026-02-16

- Decision:
Add canonical conflict-signature helpers (`MergeConflict.signature`, `MergeResult.conflict_signatures`, `KnowledgeStore.conflict_signatures`) and lock checkpoint-boundary replay equivalence against unsplit streams.

- Context:
Iteration 10 validated checkpoint continuity for collision bookkeeping, but tests still computed conflict signatures ad hoc and did not directly assert unsplit-vs-resumed equivalence across checkpoint boundaries under permutation replay.

- Alternatives considered:
1. Keep ad hoc test-level tuple sorting for conflict comparisons.
2. Add a larger replay-audit subsystem for merge transcript analysis.
3. Add minimal canonical signature helpers in core and compare unsplit/resumed signatures + relation outcomes in targeted tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes replay-equivalence assertions explicit, reusable, and implementation-linked without widening V1 scope.

- Risks accepted:
The new helper API standardizes signature shape `(code, entity_id, details)`; any future conflict-field expansion will require explicit versioning if backward compatibility is needed.

- Follow-up verification needed:
If merge transcript persistence is added later, ensure stored signatures stay byte-stable with the helper outputs.

### DEC-012 - 2026-02-16

- Decision:
Add deterministic relation-state snapshot helpers (`KnowledgeStore.pending_relation_ids`, `KnowledgeStore.relation_state_signatures`) and use them in mixed orphan+collision checkpoint-boundary replay tests.

- Context:
Iteration 11 validated checkpoint-boundary conflict-signature equivalence, but replay tests did not compare active/pending relation state directly when deferred orphan promotion and `relation_id` collision history interacted in the same stream.

- Alternatives considered:
1. Keep conflict-signature-only comparisons.
2. Inspect private relation bookkeeping directly in tests.
3. Expose minimal deterministic public state-signature helpers and assert unsplit-vs-resumed equivalence for mixed orphan+collision streams.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that verifies checkpoint-resume determinism for both conflict output and relation-state output without introducing a new subsystem.

- Risks accepted:
Public API surface grows slightly to include deterministic state-inspection helpers intended for verification and debugging.

- Follow-up verification needed:
If relation-level tombstones are added later, extend `relation_state_signatures` to encode relation lifecycle state while preserving stable ordering/signature semantics.

### DEC-013 - 2026-02-16

- Decision:
Add deterministic revision-state snapshot helper (`KnowledgeStore.revision_state_signatures`) and checkpoint-boundary replay tests that combine mixed orphan+collision relation streams with same-slot lifecycle conflicts.

- Context:
Iteration 12 locked conflict-signature and relation-state equivalence for mixed orphan+collision replay, but combined replay streams that also include lifecycle same-slot conflicts did not yet assert full revision-state equivalence across unsplit vs checkpoint-resumed execution.

- Alternatives considered:
1. Keep asserting only conflict signatures and relation-state signatures.
2. Inspect `revisions` internals directly in tests.
3. Add a minimal deterministic public revision-state signature helper and reuse it in mixed replay equivalence tests.

- Why chosen:
Option 3 keeps assertions implementation-linked and deterministic while avoiding fragile direct access to internal dictionaries.

- Risks accepted:
Public API surface expands with another deterministic inspection helper intended for verification/debugging use.

- Follow-up verification needed:
If future slices add revision tombstones or provenance-priority merge policies, extend signature coverage while preserving stable ordering and checkpoint-resume invariance.

### DEC-014 - 2026-02-16

- Decision:
Add deterministic conflict-signature multiplicity helpers (`MergeResult.conflict_signature_counts`, `KnowledgeStore.conflict_signature_counts`) and use them in repeated mixed orphan+collision+lifecycle checkpoint replay tests.

- Context:
Iteration 13 compared sorted conflict signatures and state snapshots, but repeated replay scenarios needed explicit count-equivalence assertions for duplicate signatures (notably repeated orphan conflict signatures) across unsplit vs checkpoint-resumed execution.

- Alternatives considered:
1. Keep count aggregation in tests with ad hoc `Counter` logic.
2. Introduce a larger merge transcript/audit subsystem.
3. Add a minimal deterministic count-signature helper in core and reuse it in checkpoint/permutation replay tests.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that makes conflict multiplicity comparisons explicit, deterministic, and reusable without expanding V1 scope.

- Risks accepted:
Public inspection API surface grows slightly; helper output is optimized for deterministic verification rather than end-user reporting ergonomics.

- Follow-up verification needed:
If merge conflicts gain additional structured fields later, keep count-signature ordering stable or version helper outputs explicitly.

### DEC-015 - 2026-02-16

- Decision:
Add deterministic conflict-code histogram helpers (`MergeResult.conflict_code_counts`, `KnowledgeStore.conflict_code_counts`) and assert unsplit-vs-resumed code-level count equivalence in repeated checkpoint-boundary replay tests.

- Context:
Iteration 14 locked deterministic signature-level multiplicity, but aggregate per-code conflict totals were still derived ad hoc in tests and were not explicitly compared between unsplit and checkpoint-resumed replay paths.

- Alternatives considered:
1. Continue deriving code-level totals from signature counts inside each test.
2. Introduce a broader reporting subsystem for merge analytics.
3. Add a minimal deterministic histogram helper and reuse it in existing checkpoint/permutation replay tests.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that exposes deterministic per-code totals directly and keeps replay equivalence assertions concise.

- Risks accepted:
Histogram ordering is lexicographic by conflict code string; if enum names change, expected tuple ordering changes accordingly.

- Follow-up verification needed:
If conflict codes are expanded, keep histogram output ordering and count semantics stable or version helper outputs explicitly.

### DEC-016 - 2026-02-16

- Decision:
Add deterministic conflict-summary helpers (`MergeResult.conflict_summary`, `KnowledgeStore.conflict_summary`) and checkpoint-boundary continuation replay tests that assert per-step `MergeResult` signature-count/code-count parity between unsplit and resumed suffix merges.

- Context:
Iteration 15 validated unsplit-vs-resumed aggregate equivalence with store-level helpers, but continuation replay paths still lacked direct API-level assertions that `MergeResult` summary methods themselves remain checkpoint-invariant.

- Alternatives considered:
1. Keep relying on aggregated `KnowledgeStore` conflict reducers only.
2. Add a new merge transcript subsystem with structured continuation records.
3. Add a minimal summary helper and lock per-step continuation parity using existing replay fixtures.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that validates API-level merge-result determinism across checkpoint boundaries without introducing new storage or replay subsystems.

- Risks accepted:
`conflict_summary` returns a nested tuple shape optimized for deterministic comparisons rather than presentation ergonomics.

- Follow-up verification needed:
If future slices expose richer merge reporting, preserve `conflict_summary` ordering/count semantics or version the helper output explicitly.

### DEC-017 - 2026-02-16

- Decision:
Add deterministic stream-level conflict reducers over `MergeResult` sequences (`MergeResult.stream_conflict_signature_counts`, `MergeResult.stream_conflict_code_counts`, `MergeResult.stream_conflict_summary`) and extend continuation checkpoint replay tests to compare unsplit vs resumed suffix aggregates through those APIs.

- Context:
Iteration 16 validated per-step `MergeResult` parity across checkpoint boundaries, but there was no production reducer for deterministic stream-level aggregation over merge-result sequences.

- Alternatives considered:
1. Keep stream-level aggregation logic in tests via conflict-list flattening.
2. Add another store-level reducer that still consumes raw conflict iterables.
3. Add minimal stream reducers on `MergeResult` and use them directly in continuation parity checks.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that keeps aggregation deterministic while enforcing API-level parity checks without direct conflict-list flattening in checkpoint continuation assertions.

- Risks accepted:
Stream reducers aggregate from per-result summary tuples, so any future summary shape changes must preserve tuple ordering/count semantics or version these helpers.

- Follow-up verification needed:
If merge-result reporting expands beyond conflict counts, add explicit versioned stream reducers rather than mutating current tuple contracts in place.

### DEC-018 - 2026-02-16

- Decision:
Route `MergeResult` stream conflict reducers through a shared single-pass deterministic aggregation path and add explicit zero-summary edge coverage for empty streams and conflict-free continuation suffixes.

- Context:
Iteration 17 added stream-level reducers and continuation parity checks, but edge behavior for empty/single-item zero-conflict streams and checkpoint-resumed zero-conflict suffixes was not explicitly locked by tests.

- Alternatives considered:
1. Keep separate reducer loops and rely on incidental empty-tuple behavior.
2. Move zero-summary assertions into ad hoc test-local helpers.
3. Add a shared stream reducer path in production and assert zero-summary invariants directly through public `MergeResult.stream_conflict_*` APIs.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that keeps stream reduction deterministic, avoids duplicated aggregation logic, and locks zero-conflict edge semantics at the API boundary.

- Risks accepted:
The shared reducer path computes both signature and code counts even when callers request only one view, trading minor extra work for deterministic single-path behavior.

- Follow-up verification needed:
If future performance slices require selective aggregation, preserve current tuple ordering and zero-summary contracts while introducing optimized paths.

### DEC-019 - 2026-02-16

- Decision:
Add deterministic conflict-summary composition (`MergeResult.combine_conflict_summaries`) and lock mixed-stream invariance where appending conflict-free continuation suffixes does not change aggregate summaries from conflict-producing prefixes.

- Context:
Iteration 18 validated zero-summary behavior for purely conflict-free suffix streams, but there was no production API for deterministic summary composition across stream chunks and no explicit invariance test for mixed conflict/non-conflict stream concatenation under checkpoint resume.

- Alternatives considered:
1. Keep composition logic in tests by concatenating merge-result tuples only.
2. Add a broader stream accumulator object/subsystem.
3. Add a minimal summary-composition helper on `MergeResult` and assert invariance through fixed-order and permutation checkpoint replay tests.

- Why chosen:
Option 3 is the smallest implementation-linked mechanism that keeps deterministic aggregation in production while letting tests assert chunk-composition invariants without flattening raw conflict lists.

- Risks accepted:
`combine_conflict_summaries` performs map-based aggregation for both signature and code counts on each call; this favors simple deterministic semantics over incremental micro-optimizations.

- Follow-up verification needed:
If future slices need high-volume stream folding, preserve current ordering/count contracts while adding optional batched composition paths.

### DEC-020 - 2026-02-16

- Decision:
Add deterministic incremental stream-fold extension (`MergeResult.extend_conflict_summary`) and route stream reduction through it so precomputed `ConflictSummary` values can be extended with additional `MergeResult` chunks.

- Context:
Iteration 19 provided summary composition, but there was no direct production API to continue folding from an already computed summary when replay streams are processed in checkpointed chunks.

- Alternatives considered:
1. Keep incremental folding logic in tests by manually chaining `combine_conflict_summaries`.
2. Add a new stateful stream accumulator subsystem.
3. Add a minimal static extension helper on `MergeResult` and reuse it for full-stream reduction.

- Why chosen:
Option 3 is the smallest deterministic mechanism that supports checkpoint/chunk continuation folding while keeping one canonical aggregation path in production.

- Risks accepted:
`extend_conflict_summary` still recomputes per-step merge-result summaries and prioritizes deterministic behavior over specialized performance shortcuts.

- Follow-up verification needed:
If future slices optimize stream folding throughput, preserve `ConflictSummary` tuple ordering/count semantics and checkpoint chunk-equivalence guarantees.

### DEC-021 - 2026-02-16

- Decision:
Add projection-level incremental fold helpers (`MergeResult.extend_conflict_signature_counts`, `MergeResult.extend_conflict_code_counts`) and lock empty-continuation identity/no-op behavior under checkpoint-resumed permutation replay.

- Context:
Iteration 20 provided summary-level incremental extension, but callers with already-materialized signature/code projection views still had to reconstruct full `ConflictSummary` tuples before extending, and empty continuation chunk identity semantics were not explicitly asserted in checkpoint-resumed permutation paths.

- Alternatives considered:
1. Keep projection folding as test-local tuple assembly around `extend_conflict_summary`.
2. Introduce a new stateful reducer class for projection views.
3. Add minimal static projection-extension helpers on `MergeResult` backed by existing summary-fold logic.

- Why chosen:
Option 3 is the smallest deterministic mechanism that exposes direct projection-level folding without adding new subsystem state, while preserving one canonical aggregation behavior.

- Risks accepted:
Projection helpers currently route through summary-level folding and still process both projection maps per merge step; this favors deterministic API consistency over selective micro-optimizations.

- Follow-up verification needed:
If future slices add performance-specialized projection folds, preserve current tuple ordering/count semantics and empty-chunk identity behavior for checkpoint-resumed continuation flows.

### DEC-022 - 2026-02-16

- Decision:
Add projection-level composition helpers (`MergeResult.combine_conflict_signature_counts`, `MergeResult.combine_conflict_code_counts`), route `MergeResult.combine_conflict_summaries` through them, and lock projection-composition associativity/equivalence against summary composition across checkpoint-resumed chunk boundaries and permutation replay.

- Context:
Iteration 21 exposed projection-level incremental extension APIs, but callers with already-materialized projection count views still lacked direct composition helpers, and there were no explicit tests proving projection composition stays equivalent to `combine_conflict_summaries` under checkpoint chunking/permutation replay.

- Alternatives considered:
1. Keep projection composition as caller-local tuple reconstruction into `ConflictSummary`.
2. Add a new stateful projection reducer subsystem.
3. Add minimal static projection composition helpers on `MergeResult` and verify parity/associativity against existing summary composition APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-local tuple assembly while preserving one canonical composition contract through shared ordering/count semantics.

- Risks accepted:
Projection composition remains map-based and tuple-sorted per call; this prioritizes deterministic behavior and API clarity over micro-optimized batching paths.

- Follow-up verification needed:
If future slices optimize projection composition throughput, preserve current tuple ordering/count contracts and checkpoint/permutation equivalence guarantees.

### DEC-023 - 2026-02-16

- Decision:
Add projection-chunk fold helpers (`MergeResult.extend_conflict_signature_counts_from_chunks`, `MergeResult.extend_conflict_code_counts_from_chunks`) and route merge-result projection extension methods through them.

- Context:
Iteration 22 added projection-level composition and merge-result projection extension, but callers with precomputed projection chunks still had to materialize `MergeResult` streams or manually loop `combine_conflict_*` calls.

- Alternatives considered:
1. Keep projection-chunk folding as caller-local loops.
2. Add a new stateful projection accumulator subsystem.
3. Add minimal static projection-chunk fold helpers on `MergeResult` and verify parity against repeated summary composition.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-local folding logic while preserving existing projection ordering/count contracts.

- Risks accepted:
Projection-chunk folding remains map-based per chunk and favors deterministic semantics over specialized batching/performance paths.

- Follow-up verification needed:
If future slices optimize chunk-fold throughput, keep equivalence with `MergeResult.combine_conflict_summaries` and preserve tuple ordering/count determinism.

### DEC-024 - 2026-02-16

- Decision:
Add summary-chunk fold helper (`MergeResult.extend_conflict_summary_from_chunks`) and route `MergeResult.extend_conflict_summary` through it.

- Context:
Iteration 23 added projection-chunk fold APIs, but callers with precomputed `ConflictSummary` chunks still had to write local composition loops or reconstruct `MergeResult` streams.

- Alternatives considered:
1. Keep summary-chunk folding as caller-local loops over `MergeResult.combine_conflict_summaries`.
2. Add a new stateful accumulator subsystem for summary chunks.
3. Add a minimal static summary-chunk fold helper on `MergeResult` and keep existing fold/composition APIs aligned through shared composition semantics.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-local folding logic while preserving existing summary ordering/count contracts and checkpoint resume equivalence behavior.

- Risks accepted:
Summary-chunk folding remains map-based per chunk and prioritizes deterministic semantics over specialized batching/performance paths.

- Follow-up verification needed:
If future slices optimize chunk-fold throughput, preserve equivalence/associativity with repeated `MergeResult.combine_conflict_summaries` and keep deterministic tuple ordering/count semantics stable.

### DEC-025 - 2026-02-16

- Decision:
Add `MergeResult.stream_conflict_summary_from_chunks(summary_chunks)` as the explicit empty-base reducer for precomputed `ConflictSummary` chunk streams, and route `_stream_conflict_summary` through this reducer.

- Context:
Iteration 24 exposed `MergeResult.extend_conflict_summary_from_chunks`, but callers reducing only precomputed summary chunks from zero still had to provide an explicit empty base or use merge-result stream reducers indirectly.

- Alternatives considered:
1. Keep empty-base chunk reduction as caller-local `extend_conflict_summary_from_chunks(((),()), ...)` usage.
2. Add a new stateful stream accumulator subsystem for summary chunks.
3. Add a minimal static empty-base reducer helper and reuse it inside existing stream reduction paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes repeated caller boilerplate and keeps merge-result stream reduction and summary-chunk reduction aligned through one explicit empty-base chunk API.

- Risks accepted:
This adds one more public helper on `MergeResult`; API surface grows slightly while preserving existing summary tuple contracts.

- Follow-up verification needed:
If future slices add projection-level empty-base chunk reducers, keep equivalence with `extend_conflict_summary_from_chunks` and preserve empty-chunk identity/no-op semantics under checkpoint-resumed permutation replay.

### DEC-026 - 2026-02-16

- Decision:
Add projection-level empty-base chunk stream reducers (`MergeResult.stream_conflict_signature_counts_from_chunks`, `MergeResult.stream_conflict_code_counts_from_chunks`) and route projection stream views through them.

- Context:
Iteration 25 added summary-chunk empty-base reduction, but projection reducers still lacked direct empty-base chunk APIs and required callers to use explicit empty-base extension calls or full `MergeResult` streams.

- Alternatives considered:
1. Keep projection empty-base reduction as caller-local `extend_conflict_*_from_chunks(tuple(), ...)` usage.
2. Add a new stateful projection stream accumulator subsystem.
3. Add minimal static projection empty-base reducer helpers and reuse them inside existing projection stream reducers.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes repeated caller boilerplate and aligns projection stream reducers with existing summary-chunk empty-base reduction semantics.

- Risks accepted:
Projection stream helpers now compute through separate projection chunk paths instead of the shared summary reducer path; behavior remains deterministic but adds small API surface.

- Follow-up verification needed:
If future slices optimize projection stream throughput, preserve equivalence with `extend_conflict_signature_counts_from_chunks`/`extend_conflict_code_counts_from_chunks` and keep empty-chunk identity/no-op semantics under checkpoint-resumed permutation replay.

### DEC-027 - 2026-02-16

- Decision:
Add projection reducers over precomputed `ConflictSummary` chunk streams (`MergeResult.extend_conflict_signature_counts_from_summary_chunks`, `MergeResult.stream_conflict_signature_counts_from_summary_chunks`, `MergeResult.extend_conflict_code_counts_from_summary_chunks`, `MergeResult.stream_conflict_code_counts_from_summary_chunks`).

- Context:
Iteration 26 added projection chunk stream reducers, but callers holding only summary chunks still had to unpack projection chunks externally before using projection reducers.

- Alternatives considered:
1. Keep summary-chunk projection unpacking as caller-local tuple slicing.
2. Add a new stateful projection reducer subsystem over summary chunks.
3. Add minimal static summary-chunk projection reducer helpers on `MergeResult` and lock parity against existing projection chunk reducers.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-side unpacking while preserving established projection reducer ordering/count semantics.

- Risks accepted:
The API surface grows by four helper methods; behavior remains deterministic but increases the number of reducer entry points that must remain semantically aligned.

- Follow-up verification needed:
If future slices optimize reducer throughput, preserve equivalence between summary-chunk projection reducers and projection chunk reducers under split and checkpoint-resumed permutation replay.

### DEC-028 - 2026-02-16

- Decision:
Route merge-result projection reducers (`MergeResult.extend_conflict_signature_counts`, `MergeResult.stream_conflict_signature_counts`, `MergeResult.extend_conflict_code_counts`, `MergeResult.stream_conflict_code_counts`) through summary-chunk projection reducer helpers.

- Context:
Iteration 27 added projection reducers that consume `ConflictSummary` chunks directly, but merge-result projection reducers still used separate projection-chunk reducers, leaving two production reduction paths for equivalent projection semantics.

- Alternatives considered:
1. Keep merge-result projection reducers on projection-chunk paths and rely on tests for semantic parity.
2. Remove projection-chunk reducers and force all callers onto summary-chunk reducers.
3. Reuse summary-chunk projection reducers inside merge-result projection reducers while retaining projection-chunk APIs for callers that already have projection chunks.

- Why chosen:
Option 3 is the smallest deterministic mechanism that converges merge-result projection reduction onto one reducer path without removing existing APIs used by precomputed projection-chunk callers.

- Risks accepted:
Merge-result projection reducers now compute projection views from `conflict_summary()` chunks per result; this keeps semantics aligned but may do minor extra tuple materialization compared to direct projection extraction.

- Follow-up verification needed:
If future optimization slices specialize projection reduction throughput, preserve parity between merge-result projection reducers and summary-chunk projection reducers across split and checkpoint-resumed permutation replay.

### DEC-029 - 2026-02-16

- Decision:
Route `MergeResult.stream_conflict_summary_from_chunks` through projection-from-summary-chunk stream reducers using a shared deterministic chunk source (`itertools.tee`), and add replay/split parity tests that lock `MergeResult.stream_conflict_summary(...)` to exactly `(MergeResult.stream_conflict_signature_counts(...), MergeResult.stream_conflict_code_counts(...))`.

- Context:
Iteration 28 aligned merge-result projection reducers with summary-chunk projection reducers, but `stream_conflict_summary_from_chunks` still used a separate summary fold path. Semantics matched, yet parity with projection stream reducers was validated indirectly rather than by direct split/permutation invariants.

- Alternatives considered:
1. Keep separate summary-fold implementation and rely only on existing end-state equivalence tests.
2. Recompute stream summaries by materializing all merge results and calling projection reducers independently.
3. Reuse projection-from-summary-chunk reducers in `stream_conflict_summary_from_chunks` with shared chunk replay and lock parity via split/permutation tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that converges stream-summary reduction and projection reduction onto one production path while preserving iterable compatibility for chunk streams.

- Risks accepted:
`itertools.tee` may buffer chunk elements when projection reducers consume at different rates; this is acceptable for current V1 test-scale streams and preserves deterministic semantics.

- Follow-up verification needed:
If future slices introduce large unbounded chunk streams, reassess memory behavior while preserving the locked parity invariant and deterministic ordering/count semantics.

### DEC-030 - 2026-02-16

- Decision:
Add shared empty-summary chunk normalization (`MergeResult._iter_nonempty_conflict_summary_chunks`) and route summary-chunk reducers through it (`extend_conflict_summary_from_chunks`, `stream_conflict_summary_from_chunks`, `extend_conflict_signature_counts_from_summary_chunks`, `extend_conflict_code_counts_from_summary_chunks`).

- Context:
Iteration 29 converged stream-summary and projection-summary reducers onto shared chunk-stream paths, but no production-level normalization explicitly removed no-op `((), ())` summary chunks before fold/reduction. One-shot iterable parity was covered indirectly, not with dedicated one-shot stream assertions.

- Alternatives considered:
1. Keep no-op chunk handling implicit and only validate tuple-materialized chunk streams.
2. Materialize every summary chunk stream to tuples before reduction.
3. Add a minimal shared iterator normalization that elides empty summary chunks and keep streaming reducers iterable-first.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes empty-chunk identity explicit in production and preserves one-shot iterable compatibility without introducing materialization-only behavior.

- Risks accepted:
Extra generator wrapping is introduced in reducer paths; behavior remains deterministic but may add minor iterator overhead.

- Follow-up verification needed:
If future slices introduce large or externally throttled chunk streams, keep one-shot iterable compatibility and parity invariants while profiling reducer throughput.

### DEC-031 - 2026-02-16

- Decision:
Add shared empty-projection chunk normalization (`MergeResult._iter_nonempty_projection_chunks`) and route projection-chunk extension reducers (`MergeResult.extend_conflict_signature_counts_from_chunks`, `MergeResult.extend_conflict_code_counts_from_chunks`) through it.

- Context:
Iteration 30 locked one-shot parity for summary-chunk streams and established shared empty-summary normalization, but projection-chunk reducers still consumed raw chunk iterables directly without explicit production-level empty-chunk normalization, and one-shot iterable parity for projection chunk streams was not yet locked.

- Alternatives considered:
1. Keep projection-chunk normalization implicit and rely on existing tuple-materialized parity checks.
2. Materialize projection chunk streams before reduction to simplify no-op filtering.
3. Add minimal shared iterator normalization for projection chunks and keep reducers iterable-first.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes no-op projection chunk handling explicit in production while preserving streaming/one-shot iterable compatibility and existing reducer semantics.

- Risks accepted:
Projection reducers add a small iterator wrapper layer; this is acceptable because deterministic behavior and parity guarantees are prioritized over micro-optimization.

- Follow-up verification needed:
If future slices optimize projection reducer throughput, preserve empty-chunk identity, one-shot iterable compatibility, and split/checkpoint permutation parity contracts.

### DEC-032 - 2026-02-16

- Decision:
Add a shared summary-to-projection chunk iterator (`MergeResult._iter_projection_chunks_from_summary_chunks`) and route summary-chunk projection extension reducers (`MergeResult.extend_conflict_signature_counts_from_summary_chunks`, `MergeResult.extend_conflict_code_counts_from_summary_chunks`) through it.

- Context:
Iteration 31 locked one-shot parity for projection-chunk stream reducers, but summary-chunk projection extension reducers still projected chunks with duplicated inline generator expressions and had no dedicated one-shot non-empty-base parity coverage.

- Alternatives considered:
1. Keep inline projection generators in each summary-chunk extension reducer and rely on existing tuple-materialized tests.
2. Materialize summary chunks before projection to simplify reducer internals.
3. Add one shared iterator helper for summary-to-projection chunk normalization/projection and lock one-shot non-empty-base extension parity in split and checkpoint-resumed permutation replay tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated projection plumbing in production and gives one explicit reducer path that aligns signature/code summary-chunk extension behavior.

- Risks accepted:
This adds one internal iterator layer before projection-chunk reducers; behavior remains deterministic but introduces minor generator indirection.

- Follow-up verification needed:
If future slices optimize summary-chunk projection extension throughput, preserve one-shot iterable compatibility, empty-chunk identity, and non-empty-base extension parity against projection-chunk reducers.

### DEC-033 - 2026-02-16

- Decision:
Add a shared merge-result summary-chunk iterator (`MergeResult._iter_conflict_summary_chunks`) and route merge-result stream/projection reducers through it, with one-shot parity tests for `MergeResult.extend_conflict_signature_counts` and `MergeResult.extend_conflict_code_counts` using non-empty base projections.

- Context:
Iteration 32 locked one-shot non-empty-base parity for summary-chunk projection extension reducers, but direct merge-result projection extension APIs still used duplicated inline summary extraction and lacked dedicated one-shot parity coverage against the summary-chunk extension path.

- Alternatives considered:
1. Keep inline merge-result summary generator expressions and rely on existing tuple-materialized parity tests.
2. Materialize full merge-result summary tuples before every projection extension reduction.
3. Add one shared merge-result summary-chunk iterator helper and lock direct extension API one-shot parity to summary-chunk extension reducers in split and checkpoint-resumed permutation replay tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated merge-result summary extraction paths and makes direct projection extension one-shot behavior explicitly equivalent to summary-chunk projection reducers.

- Risks accepted:
An additional internal iterator helper introduces minor generator indirection in reducer call paths.

- Follow-up verification needed:
If future slices optimize merge-result projection extension throughput, preserve one-shot iterable compatibility and parity with summary-chunk projection extension reducers across split and checkpoint-resumed permutation replay.

### DEC-034 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_summary_from_chunks` through `MergeResult.stream_conflict_summary_from_chunks` using a shared base-plus-chunk iterator (`MergeResult._iter_conflict_summary_extension_chunks`) that prepends `base_summary` and applies shared empty-summary normalization.

- Context:
Iteration 33 locked one-shot parity for merge-result projection extension APIs, but direct summary extension (`MergeResult.extend_conflict_summary`) with non-empty base summaries did not yet have explicit one-shot parity coverage against summary-chunk extension reduction.

- Alternatives considered:
1. Keep the existing local fold loop inside `extend_conflict_summary_from_chunks` and add tests only.
2. Materialize base/suffix summary chunks to tuples before reduction.
3. Route summary extension through one stream reducer path with a shared base+chunk iterator and lock one-shot non-empty-base parity against `extend_conflict_summary_from_chunks`.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes a duplicate summary-fold code path and makes direct summary extension API behavior explicitly equivalent to summary-chunk extension reducers under one-shot iterable inputs.

- Risks accepted:
This adds one internal `itertools.chain` iterator layer in summary extension reduction paths, which is acceptable for V1 because deterministic parity and one-shot compatibility are prioritized over micro-optimization.

- Follow-up verification needed:
If future slices optimize summary extension throughput, preserve one-shot iterable compatibility and non-empty-base parity between direct summary extension and summary-chunk extension reducers across split and checkpoint-resumed permutation replay.

### DEC-035 - 2026-02-16

- Decision:
Add shared merge-result summary-stream iterator routing (`MergeResult._iter_conflict_summary_stream_chunks`) and route direct stream reducers (`MergeResult.stream_conflict_summary`, `MergeResult.stream_conflict_signature_counts`, `MergeResult.stream_conflict_code_counts`) through it, then lock one-shot parity for direct summary stream reduction against summary-chunk stream reduction with injected empty chunks.

- Context:
Iteration 34 locked one-shot non-empty-base parity for direct summary extension, but direct summary stream APIs still lacked dedicated one-shot parity coverage against `MergeResult.stream_conflict_summary_from_chunks` under split recomposition and checkpoint-resumed permutation replay when empty chunks are injected on the chunk path.

- Alternatives considered:
1. Add tests only and keep direct stream reducers on their existing per-method chunk iterator calls.
2. Materialize merge-result summaries before direct stream reduction to simplify one-shot behavior.
3. Add one shared direct-stream chunk iterator helper and validate one-shot merge-result stream parity against chunk-stream reduction with empty-chunk injection.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps reducers iterable-first, removes duplicated direct-stream iterator wiring, and aligns direct stream APIs to one reusable merge-result chunk route before asserting one-shot parity invariants.

- Risks accepted:
Direct stream reducers now pass through one extra iterator helper, adding minor generator indirection while preserving deterministic ordering and count semantics.

- Follow-up verification needed:
If future slices optimize direct stream reducer throughput, preserve one-shot iterable compatibility and chunk-path parity invariants (including empty-chunk identity) across split and checkpoint-resumed permutation replay.

### DEC-036 - 2026-02-16

- Decision:
Add shared merge-result projection-stream chunk routing (`MergeResult._iter_conflict_projection_stream_chunks`) and route direct projection stream reducers (`MergeResult.stream_conflict_signature_counts`, `MergeResult.stream_conflict_code_counts`) through projection-chunk stream reducers, then lock one-shot parity against summary-chunk projection stream reducers with injected empty summary chunks.

- Context:
Iteration 35 locked one-shot parity for direct summary stream reduction, but direct projection stream APIs still lacked dedicated one-shot parity coverage against `MergeResult.stream_conflict_signature_counts_from_summary_chunks` and `MergeResult.stream_conflict_code_counts_from_summary_chunks` under split recomposition and checkpoint-resumed permutation replay with empty summary-chunk injection.

- Alternatives considered:
1. Add tests only and keep direct projection stream reducers on per-method summary-chunk reducer calls.
2. Materialize merge-result summaries before direct projection stream reduction to simplify one-shot parity checks.
3. Add one shared projection-stream chunk iterator helper and reduce direct projection stream APIs through projection-chunk stream reducers while asserting parity against summary-chunk projection stream reducers.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated direct projection-stream iterator wiring, keeps reducers iterable-first, and gives one reusable projection-chunk stream path before parity assertions.

- Risks accepted:
Direct projection stream reducers now add one internal iterator helper layer, introducing minor generator indirection while preserving deterministic ordering/count semantics.

- Follow-up verification needed:
If future slices optimize projection stream throughput, preserve one-shot iterable compatibility and parity invariants between direct projection stream reducers and summary-chunk projection stream reducers (including empty-summary-chunk identity) across split and checkpoint-resumed permutation replay.

### DEC-037 - 2026-02-16

- Decision:
Route `MergeResult.combine_conflict_summaries` through `MergeResult.extend_conflict_summary_from_chunks` and add one-shot continuation-composition parity tests for direct projection stream APIs (`MergeResult.stream_conflict_signature_counts`, `MergeResult.stream_conflict_code_counts`) across split and checkpoint-resumed permutation replay with injected empty summary chunks.

- Context:
Iteration 36 locked one-shot parity for direct projection stream reducers against summary-chunk stream reducers, but continuation-composition invariants were still validated primarily as plain split recomposition and resumed suffix composition rather than explicit one-shot continuation recomposition coverage against full direct stream projections.

- Alternatives considered:
1. Add tests only and keep `MergeResult.combine_conflict_summaries` on its separate local projection-combine path.
2. Materialize continuation summaries/projections before recomposition checks to simplify assertions.
3. Reuse the summary extension reducer path for summary composition and add one-shot continuation-composition parity tests for direct projection stream APIs with injected empty summary chunks.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes one duplicate summary-composition path while extending one-shot direct projection stream coverage to explicit continuation recomposition invariants.

- Risks accepted:
`MergeResult.combine_conflict_summaries` now incurs a minimal iterator chain through extension reducers; this adds negligible overhead relative to deterministic path unification.

- Follow-up verification needed:
If future slices optimize summary/projection reducer throughput, preserve continuation-composition invariants where combined prefix/suffix projection counts equal full direct-stream projection counts under split and checkpoint-resumed permutation replay.

### DEC-038 - 2026-02-16

- Decision:
Route `MergeResult.combine_conflict_summaries` through direct summary-chunk stream reduction (`MergeResult.stream_conflict_summary_from_chunks`) using shared composition chunk routing (`MergeResult._iter_conflict_summary_composition_chunks`), and add one-shot continuation-composition parity tests for direct summary composition against full direct summary streams.

- Context:
Iteration 37 locked one-shot continuation-composition parity for direct projection stream composition, but direct summary composition (`MergeResult.combine_conflict_summaries`) did not yet have dedicated one-shot continuation recomposition coverage against full `MergeResult.stream_conflict_summary` outputs under split and checkpoint-resumed permutation replay with empty summary-chunk injection.

- Alternatives considered:
1. Add tests only and keep summary composition routed through the summary-extension reducer entry point.
2. Materialize prefix/suffix summary composition chunks in callers and avoid a dedicated composition iterator path.
3. Add a minimal shared summary-composition chunk iterator and route `combine_conflict_summaries` through the direct summary-chunk stream reducer, then lock one-shot continuation recomposition parity in split and checkpoint-resumed permutation replay tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes summary composition reduce through the same normalized stream-summary reducer path used for chunk streams while adding explicit continuation-composition one-shot parity guarantees for direct summary recomposition.

- Risks accepted:
Summary composition now introduces one additional internal iterator helper layer before reduction; overhead is negligible relative to deterministic path unification.

- Follow-up verification needed:
If future slices optimize summary reducer throughput, preserve one-shot continuation-composition parity where `MergeResult.combine_conflict_summaries(prefix, continuation)` remains equivalent to full direct `MergeResult.stream_conflict_summary` across split and checkpoint-resumed permutation replay.

### DEC-039 - 2026-02-16

- Decision:
Add iterable summary-composition entrypoint `MergeResult.combine_conflict_summaries_from_chunks(...)`, route pairwise `MergeResult.combine_conflict_summaries(...)` through it, and lock one-shot three-way continuation-composition associativity parity for direct summary composition across split and checkpoint-resumed permutation replay.

- Context:
Iteration 38 locked one-shot continuation-composition parity for pairwise direct summary recomposition, but three-segment continuation associativity (prefix/middle/suffix) under one-shot replay with injected empty summary chunks was not yet explicitly locked against full direct `MergeResult.stream_conflict_summary` outputs.

- Alternatives considered:
1. Add three-way tests only and keep pairwise composition as the sole composition entrypoint.
2. Materialize three-way summary chunks in tests and skip one-shot iterable composition coverage.
3. Add a minimal iterable composition entrypoint and assert one-shot three-way associativity via both repeated pairwise `combine_conflict_summaries` and iterable composition reduction.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps multi-segment summary recomposition on one normalized reduction path while making three-way one-shot associativity invariants explicit and implementation-linked.

- Risks accepted:
This introduces one additional public composition helper that is semantically close to `stream_conflict_summary_from_chunks`; API surface grows slightly to gain explicit multi-segment composition intent.

- Follow-up verification needed:
If future slices optimize summary composition throughput, preserve one-shot three-way associativity invariants where left-associated and right-associated recomposition remain equivalent to iterable chunk composition and full direct stream summaries across split and checkpoint-resumed permutation replay.

### DEC-040 - 2026-02-16

- Decision:
Add iterable direct projection composition entrypoints (`MergeResult.combine_conflict_signature_counts_from_chunks`, `MergeResult.combine_conflict_code_counts_from_chunks`), route pairwise projection composition through them, and lock one-shot three-way continuation-composition associativity for direct projection composition across split and checkpoint-resumed permutation replay.

- Context:
Iteration 39 locked one-shot three-way associativity for direct summary composition, but direct projection composition still relied on pairwise-only combiners and did not yet have dedicated one-shot three-segment continuation associativity coverage (prefix/middle/suffix) against full direct projection stream outputs with injected empty summary chunks.

- Alternatives considered:
1. Add projection associativity tests only and keep pairwise projection composition as the sole composition path.
2. Materialize projection chunks in tests and skip iterable composition entrypoints.
3. Add minimal iterable projection composition reducers, route pairwise combiners through them, and assert one-shot three-way associativity via both repeated pairwise composition and iterable chunk composition.

- Why chosen:
Option 3 is the smallest deterministic mechanism that unifies projection composition paths while making one-shot three-way continuation associativity explicit and implementation-linked for direct projection stream APIs.

- Risks accepted:
This adds two new projection-composition helpers to the API surface and one internal iterator helper layer for projection composition normalization.

- Follow-up verification needed:
If future slices optimize projection composition throughput, preserve one-shot three-way associativity invariants where left-associated and right-associated direct projection recomposition remain equivalent to iterable projection composition and full direct projection stream outputs across split and checkpoint-resumed permutation replay.

### DEC-041 - 2026-02-16

- Decision:
Route projection extension reducers (`MergeResult.extend_conflict_signature_counts_from_chunks`, `MergeResult.extend_conflict_code_counts_from_chunks`) through iterable projection composition reducers using a shared base-plus-continuation iterator (`MergeResult._iter_conflict_projection_extension_chunks`), and lock one-shot three-way continuation-extension associativity for direct projection extension APIs with non-empty base prefixes.

- Context:
Iteration 40 locked one-shot three-way continuation-composition associativity for direct projection composition, but non-empty-base three-way continuation extension associativity for direct extension APIs (`extend_conflict_signature_counts`, `extend_conflict_code_counts`) was not yet explicitly locked against full direct projection streams across split and checkpoint-resumed permutation replay with injected empty summary chunks.

- Alternatives considered:
1. Add non-empty-base three-way extension tests only and keep projection extension reducers on the existing chunk-fold loops.
2. Materialize continuation projection chunks before extension to simplify associativity checks.
3. Route projection extension through one shared base-plus-continuation iterator and iterable composition reducers, then assert one-shot non-empty-base three-way continuation extension parity for direct and summary-chunk extension paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that unifies projection extension/composition reduction paths while making non-empty-base three-way continuation extension associativity explicit and implementation-linked under one-shot iterable replay.

- Risks accepted:
Projection extension now adds one internal iterator helper layer before projection composition reduction; this introduces minor generator indirection while preserving deterministic ordering/count semantics.

- Follow-up verification needed:
If future slices optimize projection extension throughput, preserve one-shot non-empty-base three-way continuation associativity invariants where left-associated and one-shot continuation extension remain equivalent to full direct projection stream outputs and injected-empty summary-chunk extension paths across split and checkpoint-resumed permutation replay.

### DEC-042 - 2026-02-16

- Decision:
Route summary extension chunk reduction (`MergeResult.extend_conflict_summary_from_chunks`) through iterable summary composition (`MergeResult.combine_conflict_summaries_from_chunks`) using shared base-plus-continuation summary-chunk normalization (`MergeResult._iter_conflict_summary_extension_chunks`), and lock one-shot three-way continuation-extension associativity for direct summary extension APIs with non-empty base summaries.

- Context:
Iteration 41 locked one-shot three-way continuation-extension associativity for direct projection extension APIs with non-empty base prefixes, but direct summary extension APIs (`MergeResult.extend_conflict_summary`, `MergeResult.extend_conflict_summary_from_chunks`) still lacked explicit three-way non-empty-base continuation-extension associativity coverage against full direct summary streams across split and checkpoint-resumed permutation replay with injected empty summary chunks.

- Alternatives considered:
1. Add non-empty-base three-way summary-extension tests only and keep summary extension chunk reduction on its existing direct stream reducer call.
2. Materialize continuation summary chunks before extension to simplify associativity checks.
3. Route summary extension chunk reduction through iterable summary composition and assert one-shot non-empty-base three-way continuation extension parity for direct and summary-chunk extension paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that unifies summary extension/composition reduction paths while making non-empty-base three-way continuation-extension associativity explicit and implementation-linked under one-shot iterable replay.

- Risks accepted:
Summary extension now incurs one additional internal helper call into iterable composition reduction; this adds minor iterator indirection while preserving deterministic ordering/count semantics.

- Follow-up verification needed:
If future slices optimize summary extension throughput, preserve one-shot non-empty-base three-way continuation-extension associativity invariants where left-associated and one-shot continuation extension remain equivalent to full direct summary stream outputs and injected-empty summary-chunk extension paths across split and checkpoint-resumed permutation replay.

### DEC-043 - 2026-02-16

- Decision:
Add explicit pre-composed continuation summary extension (`MergeResult.extend_conflict_summary_with_precomposed_continuation`) and route `MergeResult.extend_conflict_summary_from_chunks` to first compose continuation chunks via `MergeResult.combine_conflict_summaries_from_chunks` before applying base-summary extension.

- Context:
Iteration 42 locked one-shot three-way continuation-extension associativity for direct summary extension, but the continuation pre-composition step itself was not an explicit implementation surface and was not directly locked to direct `extend_conflict_summary` and full `stream_conflict_summary` outputs under split and checkpoint-resumed permutation replay with injected empty summary chunks.

- Alternatives considered:
1. Keep `extend_conflict_summary_from_chunks` as base-plus-chunk reduction only and add assertions in tests without a dedicated pre-composed continuation extension entrypoint.
2. Materialize continuation summaries in tests only and leave production routing unchanged.
3. Add a minimal explicit pre-composed continuation extension helper and route chunk extension through continuation composition, then lock parity in existing split/permutation continuation-extension coverage.

- Why chosen:
Option 3 is the smallest deterministic mechanism that exposes pre-composed continuation extension behavior directly while preserving the shared normalized summary-extension reduction path and enabling explicit one-shot parity assertions for continuation composition plus extension.

- Risks accepted:
`extend_conflict_summary_from_chunks` now performs continuation composition and base extension as two reduction calls instead of one combined reduction call, adding minor helper indirection while preserving deterministic output semantics.

- Follow-up verification needed:
If future slices optimize summary extension performance, preserve parity invariants where pre-composed continuation extension remains equivalent to direct `MergeResult.extend_conflict_summary`, `MergeResult.extend_conflict_summary_from_chunks`, and full `MergeResult.stream_conflict_summary` across split and checkpoint-resumed permutation replay with injected empty summary chunks.

### DEC-044 - 2026-02-16

- Decision:
Add explicit pre-composed continuation projection extension entrypoints (`MergeResult.extend_conflict_signature_counts_with_precomposed_continuation`, `MergeResult.extend_conflict_code_counts_with_precomposed_continuation`) and route projection chunk-extension reducers to pre-compose continuation projection chunks before applying base extension.

- Context:
Iteration 43 locked pre-composed continuation summary extension parity, but direct projection extension APIs still only exposed base-plus-chunk extension entrypoints and did not explicitly expose nor lock a pre-composed continuation projection extension surface against full direct projection streams under split and checkpoint-resumed permutation replay with injected empty summary chunks.

- Alternatives considered:
1. Keep projection chunk extension on direct base-plus-chunk reduction and add parity assertions only in tests.
2. Pre-compose continuation projection chunks in tests only while leaving production projection extension routing unchanged.
3. Add minimal explicit pre-composed continuation projection extension helpers and route projection chunk extension through continuation projection composition, then lock parity in existing three-way continuation-extension coverage.

- Why chosen:
Option 3 is the smallest deterministic mechanism that mirrors the summary pre-composed continuation extension pattern for projections, unifies projection extension routing around one explicit continuation-composition-plus-extension path, and enables direct one-shot parity assertions for pre-composed continuation projection extension behavior.

- Risks accepted:
Projection chunk extension now performs continuation projection composition and base extension as two reducer calls instead of one combined reduction path, adding minor helper indirection while preserving deterministic tuple ordering/count semantics.

- Follow-up verification needed:
If future slices optimize projection extension performance, preserve parity invariants where pre-composed continuation projection extension remains equivalent to direct `MergeResult.extend_conflict_signature_counts`/`MergeResult.extend_conflict_code_counts`, summary-chunk projection extension reducers with injected empty summary chunks, and full direct projection stream outputs across split and checkpoint-resumed permutation replay.

### DEC-045 - 2026-02-16

- Decision:
Add shared projection pre-composed continuation extension routing (`MergeResult._extend_projection_counts_with_precomposed_continuation`) and explicitly normalize empty continuation projections to identity/no-op behavior before extension-chain reduction.

- Context:
Iteration 44 introduced explicit pre-composed continuation projection extension entrypoints, but empty continuation projection identity invariants were only covered through broader extension paths and were not independently locked for direct pre-composed APIs under checkpoint-resumed split recomposition.

- Alternatives considered:
1. Keep pre-composed extension logic duplicated in signature/code methods and add tests only.
2. Add a separate empty-continuation API surface for projection extension.
3. Factor a shared projection pre-composed extension helper and lock explicit empty-continuation identity plus split/checkpoint recomposition parity for direct projection pre-composed APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated projection pre-composed extension routing while making empty-continuation identity behavior explicit and test-locked without adding new public subsystem surface.

- Risks accepted:
Shared helper routing adds one extra internal call frame for projection pre-composed extension paths; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize projection reducer throughput, preserve explicit empty-continuation identity invariants for direct pre-composed projection extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-046 - 2026-02-16

- Decision:
Add shared summary pre-composed continuation extension routing (`MergeResult._extend_conflict_summary_with_precomposed_continuation`) and explicitly normalize empty continuation summaries to identity/no-op behavior before extension-chain reduction.

- Context:
Iteration 45 locked explicit empty-continuation identity for direct projection pre-composed APIs, but the corresponding direct summary pre-composed API (`MergeResult.extend_conflict_summary_with_precomposed_continuation`) still relied on inline extension-chunk routing without dedicated empty-continuation normalization or focused split/permutation identity stress coverage.

- Alternatives considered:
1. Add tests only and keep summary pre-composed extension routing inlined.
2. Introduce a new dedicated summary identity API surface.
3. Factor a shared summary pre-composed extension helper and lock explicit empty-continuation-summary identity plus split/checkpoint recomposition parity for direct summary pre-composed APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that mirrors projection helper routing, removes summary pre-composed extension duplication, and makes empty-continuation summary identity behavior explicit and test-locked without adding new subsystem surface.

- Risks accepted:
Shared helper routing adds one extra internal call frame for summary pre-composed extension paths; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize summary reducer throughput, preserve explicit empty-continuation-summary identity invariants for direct pre-composed summary extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-047 - 2026-02-16

- Decision:
Route direct pre-composed summary extension through explicit base+continuation pair composition (`MergeResult._iter_conflict_summary_pair_chunks`) and lock parity where `MergeResult.extend_conflict_summary_with_precomposed_continuation(base, continuation)` equals `MergeResult.combine_conflict_summaries(base, continuation)` across split recomposition and checkpoint-resumed permutation replay, including explicit empty-base and empty-continuation one-shot chunk paths.

- Context:
Iteration 46 locked empty-continuation identity for direct pre-composed summary extension, but parity with direct pairwise composition (`combine_conflict_summaries`) was not yet explicitly locked across split recomposition and checkpoint-resumed permutation replay with one-shot empty endpoint paths.

- Alternatives considered:
1. Add tests only and keep the existing summary extension helper routing shape.
2. Add a separate public API for pairwise pre-composed summary composition parity checks.
3. Route the helper through an explicit base+continuation pair chunk iterator and add focused split/permutation parity tests (including empty endpoints).

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps pre-composed summary extension behavior definitionally aligned with pairwise summary composition while making the parity invariant explicit and implementation-linked.

- Risks accepted:
This changes only internal helper routing and removes an explicit empty-continuation branch, relying on shared empty-chunk normalization for identity behavior.

- Follow-up verification needed:
If future slices optimize summary reducer internals, preserve invariants where pre-composed summary extension remains equivalent to pairwise summary composition and summary-chunk extension paths under one-shot split/permutation replay.

### DEC-048 - 2026-02-16

- Decision:
Route direct pre-composed projection extension through explicit base+continuation pair composition (`MergeResult._iter_conflict_projection_pair_chunks`) and lock parity where `MergeResult.extend_conflict_signature_counts_with_precomposed_continuation(base, continuation)`/`MergeResult.extend_conflict_code_counts_with_precomposed_continuation(base, continuation)` equal pairwise projection composition (`MergeResult.combine_conflict_signature_counts`, `MergeResult.combine_conflict_code_counts`) across split recomposition and checkpoint-resumed permutation replay, including explicit empty-base and empty-continuation one-shot chunk paths.

- Context:
Iteration 47 locked direct summary pre-composed extension parity against pairwise summary composition, but symmetric parity coverage for direct projection pre-composed extension vs pairwise projection composition was not yet explicitly locked across split recomposition and checkpoint-resumed permutation replay with one-shot empty-endpoint chunk paths.

- Alternatives considered:
1. Add tests only and keep projection pre-composed extension helper routing shape unchanged.
2. Add dedicated projection parity APIs for pairwise-composition checks.
3. Route projection pre-composed extension through explicit base+continuation pair chunk normalization and add focused split/permutation parity tests with one-shot empty-endpoint paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps pre-composed projection extension definitionally aligned with pairwise projection composition while making the parity invariant explicit and implementation-linked for both signature and code projections.

- Risks accepted:
Internal helper routing removes an explicit continuation-empty branch and relies on shared non-empty projection chunk normalization for identity/no-op behavior.

- Follow-up verification needed:
If future slices optimize projection reducer internals, preserve invariants where pre-composed projection extension remains equivalent to pairwise projection composition and projection-chunk extension paths under one-shot split/permutation replay.

### DEC-049 - 2026-02-16

- Decision:
Route projection reducers from summary chunks through explicit continuation precomposition (`MergeResult._compose_projection_counts_from_summary_chunks`) and then shared pre-composed projection extension, and lock parity where summary-derived continuation projections remain equivalent to direct projection-chunk precomposition + pairwise projection composition under split and checkpoint-resumed permutation replay.

- Context:
Iteration 48 locked direct pre-composed projection extension parity against pairwise projection composition, but summary-derived continuation projection paths (`*_from_summary_chunks`) still reduced through separate stream/extend entrypoints without an explicit shared continuation-precompose helper, and parity was not directly locked for summary-derived continuation precomposition with injected empty summary/projection chunks.

- Alternatives considered:
1. Add tests only while leaving summary-derived projection stream/extend routing split across separate reduction shapes.
2. Add new public APIs for summary-derived precomposed continuation projections.
3. Add one shared internal continuation-precompose helper for summary-derived projection reducers and lock parity in split/permutation replay tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that unifies summary-derived projection reduction routing without expanding public surface area, while making summary-derived precomposed continuation parity explicit and implementation-linked.

- Risks accepted:
Summary-derived projection reducers now perform explicit continuation precomposition before non-empty-base extension, adding minor internal helper indirection while preserving deterministic output semantics.

- Follow-up verification needed:
If future slices optimize summary-to-projection reduction throughput, preserve invariants where summary-derived continuation precomposition remains equivalent to direct projection precomposition and pairwise projection composition across split recomposition and checkpoint-resumed permutation replay with injected empty summary/projection chunks.

### DEC-050 - 2026-02-16

- Decision:
Add shared summary-chunk projection extension precompose+extend routing (`MergeResult._extend_projection_counts_from_summary_chunks_with_precomposed_continuation`), route both `MergeResult.extend_conflict_signature_counts_from_summary_chunks` and `MergeResult.extend_conflict_code_counts_from_summary_chunks` through it, and lock non-empty-base parity where those summary-chunk extension APIs equal direct pre-composed continuation extension when continuation projections are precomposed from summary chunks.

- Context:
Iteration 49 unified summary-derived projection continuation precomposition through `MergeResult._compose_projection_counts_from_summary_chunks`, but signature/code summary-chunk extension entrypoints still duplicated this compose-then-extend sequence and did not explicitly lock parity against direct `*_with_precomposed_continuation` extension on non-empty bases under split/checkpoint replay paths.

- Alternatives considered:
1. Keep duplicated summary-chunk extension routing and add tests only.
2. Add a new public API that accepts summary chunks and precomposed projection continuation together.
3. Add one internal helper for summary-chunk extension precompose+extend routing and lock parity in split/permutation replay tests with one-shot summary iterables.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated routing logic without expanding public surface area, while making the non-empty-base summary-chunk-extension-vs-precomposed-extension parity invariant explicit and implementation-linked.

- Risks accepted:
This adds one internal helper call layer for summary-chunk extension APIs; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize summary-to-projection extension throughput, preserve invariants where summary-chunk extension with one-shot iterables remains equivalent to direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-051 - 2026-02-16

- Decision:
Add shared summary-chunk summary extension precompose+extend routing (`MergeResult._extend_conflict_summary_from_chunks_with_precomposed_continuation`), route `MergeResult.extend_conflict_summary_from_chunks` through it, and lock non-empty-base parity where summary-chunk extension equals direct pre-composed continuation extension when continuation summaries are precomposed from summary chunks.

- Context:
Iteration 50 unified summary-chunk projection extension routing with a shared precompose+extend helper and locked non-empty-base parity for projection reducers, but summary-chunk summary extension still inlined compose-then-extend routing and lacked focused non-empty-base split/permutation parity coverage against `MergeResult.extend_conflict_summary_with_precomposed_continuation`.

- Alternatives considered:
1. Keep inline summary-chunk extension routing and add tests only.
2. Add a new public API that accepts summary chunks plus a precomposed continuation summary.
3. Add one internal helper for summary-chunk summary extension precompose+extend routing and lock parity in split/permutation replay tests with one-shot summary iterables.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes duplicated compose-then-extend routing shape and makes the non-empty-base summary-chunk-extension-vs-precomposed-extension invariant explicit and implementation-linked without expanding public API surface.

- Risks accepted:
This adds one internal helper call layer for summary-chunk summary extension paths; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize summary extension throughput, preserve invariants where summary-chunk summary extension with one-shot iterables remains equivalent to direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-052 - 2026-02-16

- Decision:
Add shared summary-chunk composition helper routing (`MergeResult._compose_conflict_summary_chunks`), route `MergeResult.combine_conflict_summaries_from_chunks` through it, and use the same helper when precomposing continuation summaries in `MergeResult._extend_conflict_summary_from_chunks_with_precomposed_continuation`; then lock explicit empty-base and empty-continuation one-shot endpoint parity for summary-chunk extension vs direct pre-composed continuation extension.

- Context:
Iteration 51 locked non-empty-base parity between `MergeResult.extend_conflict_summary_from_chunks` and `MergeResult.extend_conflict_summary_with_precomposed_continuation`, but empty-endpoint paths for summary-chunk extension precomposition were not explicitly locked under split recomposition and checkpoint-resumed permutation replay.

- Alternatives considered:
1. Add empty-endpoint tests only and keep summary-chunk composition/precomposition routing duplicated.
2. Add dedicated public APIs for empty-base and empty-continuation summary-chunk extension.
3. Factor one shared internal summary-chunk composition helper and add focused split/permutation empty-endpoint parity tests using one-shot summary iterables.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes composition/precomposition routing drift and makes empty-endpoint parity explicit without expanding public API surface.

- Risks accepted:
Internal summary composition now adds one shared helper indirection; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize summary composition/extension internals, preserve invariants where summary-chunk extension with empty-base and empty-continuation one-shot paths remains equivalent to direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-053 - 2026-02-16

- Decision:
Route summary-derived projection chunk extraction through shared projection composition chunk normalization (`MergeResult._iter_conflict_projection_composition_chunks`) and lock explicit empty-base and empty-continuation one-shot endpoint parity for summary-chunk projection extension vs direct pre-composed continuation extension.

- Context:
Iteration 52 locked empty-endpoint parity for summary-chunk summary extension paths, but projection-side summary-chunk extension still lacked explicit empty-endpoint parity coverage against `MergeResult.extend_conflict_signature_counts_with_precomposed_continuation`/`MergeResult.extend_conflict_code_counts_with_precomposed_continuation` under split recomposition and checkpoint-resumed permutation replay.

- Alternatives considered:
1. Add empty-endpoint projection tests only and keep summary-derived projection extraction directly on `_iter_nonempty_projection_chunks`.
2. Introduce dedicated public projection extension APIs for empty-base and empty-continuation summary-chunk endpoints.
3. Route summary-derived projection extraction through the existing shared projection composition chunk normalizer and add focused split/permutation empty-endpoint parity tests using one-shot summary iterables.

- Why chosen:
Option 3 is the smallest deterministic mechanism that aligns summary-derived projection chunk normalization with direct projection composition paths while adding explicit empty-endpoint parity coverage without expanding the public API.

- Risks accepted:
Summary-derived projection extraction adds one internal helper indirection; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize projection-from-summary reduction internals, preserve invariants where summary-chunk projection extension with empty-base and empty-continuation one-shot paths remains equivalent to direct pre-composed continuation projection extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-054 - 2026-02-16

- Decision:
Route direct merge-result projection extension entrypoints through shared merge-result precompose+extend routing (`MergeResult._extend_projection_counts_from_merge_results_with_precomposed_continuation`) and lock explicit empty-base and empty-continuation parity where direct merge-result extension equals summary-chunk projection extension under split recomposition and checkpoint-resumed permutation replay with one-shot merge-result iterables.

- Context:
Iteration 53 locked empty-endpoint parity for summary-chunk projection extension against direct pre-composed continuation extension, but direct merge-result projection extension entrypoints (`MergeResult.extend_conflict_signature_counts`, `MergeResult.extend_conflict_code_counts`) still used duplicated inline summary-chunk routing and lacked focused empty-endpoint parity coverage against summary-chunk extension reducers across split/permutation replay paths.

- Alternatives considered:
1. Keep direct merge-result extension routing inline and add empty-endpoint tests only.
2. Add a new public API for merge-result continuation precomposition before projection extension.
3. Add one internal merge-result precompose+extend helper and lock focused empty-endpoint parity tests that exercise one-shot merge-result iterables.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes direct merge-result projection extension routing duplication while making empty-endpoint parity invariants explicit and implementation-linked without expanding public API surface.

- Risks accepted:
Direct merge-result projection extension paths add one internal helper call layer; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize merge-result projection extension internals, preserve invariants where one-shot merge-result extension with empty-base and empty-continuation paths remains equivalent to summary-chunk projection extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-055 - 2026-02-16

- Decision:
Add shared merge-result projection continuation composition routing (`MergeResult._compose_projection_counts_from_merge_results`), route `MergeResult._extend_projection_counts_from_merge_results_with_precomposed_continuation` through it, and lock explicit empty-base and empty-continuation parity where direct merge-result projection extension equals direct pre-composed continuation extension under split recomposition and checkpoint-resumed permutation replay with one-shot merge-result iterables.

- Context:
Iteration 54 locked direct merge-result projection extension parity against summary-chunk projection extension, but direct merge-result projection extension was still validated indirectly relative to direct pre-composed continuation extension APIs, without focused empty-endpoint parity tests for `MergeResult.extend_conflict_signature_counts`/`MergeResult.extend_conflict_code_counts` vs `*_with_precomposed_continuation`.

- Alternatives considered:
1. Keep merge-result continuation precomposition inlined inside the existing merge-result extension helper and add tests only.
2. Add a new public API for merge-result continuation precomposition output.
3. Factor one internal merge-result continuation composition helper and lock focused empty-endpoint parity tests against direct pre-composed continuation extension.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes remaining internal routing duplication while making direct-extension-vs-precomposed-extension empty-endpoint invariants explicit and implementation-linked without expanding the public API.

- Risks accepted:
Adds one internal helper call in merge-result projection extension routing; behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize merge-result projection reducer internals, preserve invariants where one-shot merge-result extension with empty-base and empty-continuation paths remains equivalent to direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-056 - 2026-02-16

- Decision:
Remove callback indirection from merge-result projection precompose+extend routing by making `MergeResult._extend_projection_counts_from_merge_results_with_precomposed_continuation` extend through shared pair-extension normalization (`MergeResult._extend_projection_counts_with_precomposed_continuation`), and lock non-empty-base plus non-empty-continuation parity for direct merge-result projection extension vs direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay with one-shot merge-result iterables.

- Context:
Iteration 55 locked direct merge-result projection extension parity against direct pre-composed continuation extension for explicit empty-base and empty-continuation endpoints, but the corresponding non-empty-base + non-empty-continuation paths were not explicitly locked under split/permutation replay, and merge-result precompose+extend still used an extra extension-callback hop.

- Alternatives considered:
1. Add non-empty-base tests only and keep callback-based helper routing unchanged.
2. Introduce a new public API to expose merge-result precomposed projection continuations.
3. Remove internal callback indirection in merge-result precompose+extend routing and add focused non-empty-base split/permutation parity tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that tightens internal routing to one explicit pair-extension reducer and makes the non-empty-base/non-empty-continuation direct-extension-vs-precomposed invariant explicit without expanding public surface area.

- Risks accepted:
Direct merge-result projection extension helper signatures change internally; public behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize merge-result projection extension throughput, preserve invariants where direct merge-result extension with non-empty bases and non-empty continuations remains equivalent to direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-057 - 2026-02-16

- Decision:
Remove callback indirection from summary-chunk projection precompose+extend routing by making `MergeResult._extend_projection_counts_from_summary_chunks_with_precomposed_continuation` extend through shared pair-extension normalization (`MergeResult._extend_projection_counts_with_precomposed_continuation`), and lock non-empty-base plus non-empty-continuation parity for direct merge-result projection extension vs summary-chunk projection extension across split recomposition and checkpoint-resumed permutation replay with one-shot merge-result and summary-chunk iterables.

- Context:
Iteration 56 locked direct merge-result projection extension parity against direct pre-composed continuation extension for non-empty-base + non-empty-continuation paths, but direct-vs-summary-chunk parity for the same non-empty paths was not explicitly locked under split/permutation replay, and summary-chunk precompose+extend still used an extra extension-callback hop.

- Alternatives considered:
1. Add non-empty-base direct-vs-summary tests only and keep callback-based summary-chunk helper routing unchanged.
2. Introduce a new public API to expose summary-chunk continuation projection precomposition.
3. Remove internal callback indirection in summary-chunk precompose+extend routing and add focused non-empty-base split/permutation parity tests for direct-vs-summary extension APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps summary-chunk extension internals aligned to the same pair-extension reducer used by direct extension paths while making the non-empty-base/non-empty-continuation direct-vs-summary invariant explicit without expanding public surface area.

- Risks accepted:
Summary-chunk projection extension helper signature changed internally; public behavior remains deterministic and output-equivalent.

- Follow-up verification needed:
If future slices optimize summary-chunk projection extension throughput, preserve invariants where direct merge-result extension with non-empty bases and non-empty continuations remains equivalent to summary-chunk projection extension across split recomposition and checkpoint-resumed permutation replay.

### DEC-058 - 2026-02-16

- Decision:
Route pairwise summary composition through shared projection-count pair composition (`MergeResult._compose_conflict_projection_count_pairs`) and lock focused non-empty-base plus non-empty-continuation parity where summary-chunk projection extension APIs equal direct pre-composed continuation extension across split recomposition and checkpoint-resumed permutation replay with one-shot summary iterables and middle/suffix continuation recomposition checks.

- Context:
Iteration 57 locked non-empty-base plus non-empty-continuation parity for direct merge-result projection extension vs summary-chunk projection extension, but focused API-level parity coverage for summary-chunk projection extension vs direct pre-composed continuation extension under recomposed middle/suffix continuation paths was not explicitly isolated in the latest projection-extension suite.

- Alternatives considered:
1. Add focused tests only and keep pairwise summary composition routed through iterable summary-chunk reduction.
2. Add a new public projection-pair composition API for recomposed continuation assertions.
3. Add one shared internal projection-pair composition helper for pairwise summary composition and lock focused split/permutation parity tests using existing public extension APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that aligns pairwise summary composition with projection pair-composition semantics while making focused summary-chunk-extension-vs-precomposed-extension invariants explicit and implementation-linked without expanding public surface area.

- Risks accepted:
Pairwise summary composition no longer delegates to iterable summary-chunk reduction routing; correctness now depends directly on projection pair-composition helper equivalence.

- Follow-up verification needed:
If future slices optimize summary/projection composition internals, preserve invariants where summary-chunk projection extension with non-empty bases and continuations remains equivalent to direct pre-composed continuation extension under split recomposition, middle/suffix recomposition, and checkpoint-resumed permutation replay with one-shot summary iterables.

### DEC-059 - 2026-02-16

- Decision:
Reroute pairwise summary composition through shared summary-chunk composition (`MergeResult._compose_conflict_summary_pair_with_chunks`) and lock focused parity where `MergeResult.combine_conflict_summaries` equals `MergeResult.combine_conflict_summaries_from_chunks` under split recomposition and checkpoint-resumed permutation replay with injected empty summary chunks and one-shot chunk iterables.

- Context:
Iteration 58 aligned pairwise summary composition through projection-pair composition, but focused API-level parity coverage directly comparing pairwise summary composition against iterable summary composition (with injected empty chunks and one-shot iterables) was not isolated in dedicated split/permutation tests.

- Alternatives considered:
1. Keep pairwise routing on projection-pair composition and add parity tests only.
2. Introduce a new public summary-pair composition API.
3. Route pairwise summary composition through existing summary-chunk composition routing and add focused split/permutation parity tests for pair-vs-iterable summary composition APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes pair-vs-iterable routing drift risk while making the composition API parity invariant explicit and implementation-linked without expanding public surface area.

- Risks accepted:
Pairwise summary composition now depends on summary-chunk composition routing (`MergeResult.stream_conflict_summary_from_chunks`) and its normalization behavior; output remains deterministic and equivalent under current tests.

- Follow-up verification needed:
If future slices optimize summary-composition internals, preserve invariants where `MergeResult.combine_conflict_summaries` remains equivalent to `MergeResult.combine_conflict_summaries_from_chunks` across split recomposition, injected-empty summary-chunk paths, and checkpoint-resumed permutation replay with one-shot chunk iterables.

### DEC-060 - 2026-02-16

- Decision:
Route pairwise projection composition through shared projection pair-via-chunks routing (`MergeResult._compose_conflict_projection_pair_with_chunks`) and lock focused parity where `MergeResult.combine_conflict_signature_counts`/`MergeResult.combine_conflict_code_counts` equal iterable projection composition reducers (`MergeResult.combine_conflict_signature_counts_from_chunks`/`MergeResult.combine_conflict_code_counts_from_chunks`) under split recomposition and checkpoint-resumed permutation replay with injected empty projection chunks and one-shot chunk iterables.

- Context:
Iteration 59 locked pairwise-vs-iterable summary composition parity with injected empty summary chunks, but projection-side pairwise composition APIs still lacked focused split/permutation parity coverage directly against their iterable `*_from_chunks` counterparts with injected empty projection chunks and one-shot iterables.

- Alternatives considered:
1. Add projection pair-vs-iterable parity tests only and keep pairwise projection composition directly routed to `*_from_chunks((left, right))`.
2. Add a new public projection pair-composition API variant for chunk normalization.
3. Add one internal projection pair-via-chunks helper and lock focused projection pair-vs-iterable parity tests across split and permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes pair-vs-iterable projection routing drift risk while making the projection composition API parity invariant explicit and implementation-linked without expanding public API surface.

- Risks accepted:
Pairwise projection composition now depends on an additional internal helper layer; behavior remains deterministic and output-equivalent under current coverage.

- Follow-up verification needed:
If future slices optimize projection-composition internals, preserve invariants where `MergeResult.combine_conflict_signature_counts`/`MergeResult.combine_conflict_code_counts` remain equivalent to `*_from_chunks` across split recomposition, injected-empty projection-chunk paths, and checkpoint-resumed permutation replay with one-shot chunk iterables.

### DEC-061 - 2026-02-16

- Decision:
Add explicit summary-derived projection-pair composition helper (`MergeResult.combine_conflict_projection_counts_via_summary_pair`) and lock focused parity where pairwise projection composition outputs match summary-pair composition projections derived from `MergeResult.combine_conflict_summaries` under split recomposition and checkpoint-resumed permutation replay with injected empty summary chunks and one-shot chunk iterables.

- Context:
Iteration 60 locked pairwise-vs-iterable projection composition parity for injected empty projection chunks, but projection pair outputs were not yet explicitly locked against summary-pair composition projections (`MergeResult.combine_conflict_summaries`) under the same split/permutation replay conditions.

- Alternatives considered:
1. Add parity tests only using direct `MergeResult.combine_conflict_summaries` calls inline in test helpers.
2. Reroute `MergeResult.combine_conflict_signature_counts` and `MergeResult.combine_conflict_code_counts` through summary composition internally.
3. Add one explicit projection-pair-via-summary helper and use focused split/permutation parity tests to lock pairwise projection outputs to summary-derived projections.

- Why chosen:
Option 3 is the smallest deterministic mechanism that exposes summary-derived projection composition as an explicit implementation entrypoint while keeping existing pairwise projection APIs stable and making the new parity invariant implementation-linked.

- Risks accepted:
Adds one public helper layer for projection composition via summary pair routing; behavior remains deterministic and output-equivalent under current coverage.

- Follow-up verification needed:
If future slices optimize projection/summary composition internals, preserve invariants where pairwise projection composition outputs remain equal to summary-derived projection outputs across split recomposition, injected-empty summary-chunk paths, and checkpoint-resumed permutation replay with one-shot chunk iterables.

### DEC-062 - 2026-02-16

- Decision:
Add explicit projection-pair pre-composed continuation extension helper (`MergeResult.extend_conflict_projection_counts_with_precomposed_continuation`) and lock focused parity where pre-composed projection extension outputs remain equal when continuation projections are recomposed via `MergeResult.combine_conflict_projection_counts_via_summary_pair` under split recomposition and checkpoint-resumed permutation replay with injected empty summary chunks and one-shot chunk iterables.

- Context:
Iteration 61 locked pairwise projection composition outputs to summary-pair-derived projection composition outputs, but the projection pre-composed continuation extension path still required caller-local signature/code fan-out and had no focused split/permutation parity coverage tying extension outputs directly to summary-pair-derived continuation recomposition.

- Alternatives considered:
1. Add tests only using caller-local signature/code extension fan-out.
2. Internally reroute all projection pre-composed extension APIs through summary-pair composition.
3. Add one explicit projection-pair pre-composed extension helper and lock focused split/permutation parity tests against summary-pair-derived continuation recomposition.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-local extension fan-out drift risk while making the projection-extension-vs-summary-pair-continuation invariant explicit and implementation-linked without forcing broader routing changes.

- Risks accepted:
Adds one public helper layer for projection extension with pre-composed continuation tuples; behavior remains deterministic and output-equivalent under current coverage.

- Follow-up verification needed:
If future slices optimize projection extension/composition internals, preserve invariants where `MergeResult.extend_conflict_projection_counts_with_precomposed_continuation` remains equivalent for direct and summary-pair-recomposed continuation projections across split recomposition, injected-empty summary-chunk paths, and checkpoint-resumed permutation replay with one-shot chunk iterables.

### DEC-063 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_with_precomposed_continuation` through shared explicit fan-out helper (`MergeResult._extend_conflict_projection_counts_with_precomposed_continuation_via_fan_out`) and lock focused endpoint parity where the projection API equals explicit signature/code fan-out extension APIs across empty-base and empty-continuation replay endpoints under split recomposition and checkpoint-resumed permutation replay with one-shot iterables.

- Context:
Iteration 62 added the projection pre-composed extension API and locked continuation-recomposition parity against summary-pair-derived continuations, but explicit endpoint parity for that API versus direct signature/code fan-out extension calls was not yet isolated under empty-base and empty-continuation replay endpoints.

- Alternatives considered:
1. Add endpoint parity tests only and keep projection API fan-out inlined.
2. Replace projection API routing with summary-pair composition routing before extension.
3. Add one shared internal explicit fan-out helper for projection pre-composed extension routing and lock focused endpoint parity tests against explicit signature/code fan-out APIs.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes inline fan-out drift risk while making empty-endpoint projection-API-vs-explicit-fan-out invariants implementation-linked without expanding public API surface.

- Risks accepted:
Adds one internal helper layer in projection pre-composed extension routing; behavior remains deterministic and output-equivalent under current coverage.

- Follow-up verification needed:
If future slices optimize projection extension internals, preserve invariants where `MergeResult.extend_conflict_projection_counts_with_precomposed_continuation` remains equivalent to explicit signature/code fan-out extension across empty-base and empty-continuation replay endpoints under split recomposition and checkpoint-resumed permutation replay with one-shot iterables.

### DEC-064 - 2026-02-16

- Decision:
Add projection-level summary-chunk extension API (`MergeResult.extend_conflict_projection_counts_from_summary_chunks`) routed through one-shot-safe fan-out helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out`), and lock focused endpoint parity where `MergeResult.extend_conflict_projection_counts_with_precomposed_continuation` equals summary-chunk projection extension reducers across empty-base and empty-continuation replay endpoints under split recomposition and checkpoint-resumed permutation replay with one-shot summary-chunk iterables.

- Context:
Iteration 63 locked projection pre-composed continuation extension outputs against explicit signature/code pre-composed fan-out endpoints, but did not yet expose a projection-level summary-chunk extension API or isolate endpoint parity against summary-chunk projection extension reducers in split/permutation replay paths.

- Alternatives considered:
1. Add parity tests only using inline tuple fan-out to existing projection summary-chunk reducers.
2. Route `MergeResult.extend_conflict_projection_counts_with_precomposed_continuation` internally through summary-chunk extension reducers.
3. Add a projection-level summary-chunk extension API with one-shot-safe fan-out routing and lock focused endpoint parity tests against summary-chunk projection extension reducers.

- Why chosen:
Option 3 is the smallest deterministic mechanism that removes caller-local summary-chunk fan-out drift risk while adding explicit projection-level API coverage and preserving existing pre-composed projection extension routing.

- Risks accepted:
Adds one public helper layer and one internal fan-out helper for projection summary-chunk extension; behavior remains deterministic and output-equivalent under current coverage.

- Follow-up verification needed:
If future slices optimize projection summary-chunk extension routing, preserve invariants where projection pre-composed continuation extension remains equivalent to projection summary-chunk extension reducers across empty-base and empty-continuation replay endpoints under split recomposition and checkpoint-resumed permutation replay with one-shot summary-chunk iterables.

### DEC-065 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks` through summary-extension-derived projection routing (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) and lock focused parity where projection summary-chunk extension outputs equal projection outputs derived from `MergeResult.extend_conflict_summary_from_chunks` under split recomposition and checkpoint-resumed permutation replay with one-shot summary-chunk iterables.

- Context:
Iteration 64 introduced projection-level summary-chunk extension with focused endpoint parity against pre-composed projection extension and explicit signature/code summary-chunk reducers, but did not yet isolate parity directly against summary-derived projection outputs from `MergeResult.extend_conflict_summary_from_chunks` across split/permutation replay paths.

- Alternatives considered:
1. Add parity tests only and leave `MergeResult.extend_conflict_projection_counts_from_summary_chunks` routed exclusively through explicit signature/code fan-out.
2. Reroute projection summary-chunk extension directly through explicit signature/code reducers and remove summary extension routing paths.
3. Add explicit summary-extension-derived projection routing and lock focused split/permutation parity against `MergeResult.extend_conflict_summary_from_chunks`, while retaining explicit fan-out entrypoint for parity diagnostics.

- Why chosen:
Option 3 is the smallest deterministic mechanism that aligns projection summary-chunk extension with existing summary extension semantics and makes the parity invariant implementation-linked without removing explicit fan-out comparison paths.

- Risks accepted:
Default projection summary-chunk extension routing now depends on summary extension reducer behavior; explicit fan-out routing remains available for targeted parity verification and debugging.

- Follow-up verification needed:
If future slices optimize summary or projection extension internals, preserve invariants where `MergeResult.extend_conflict_projection_counts_from_summary_chunks` stays equivalent to summary-derived projection extension outputs across split recomposition, recomposed continuation paths, and checkpoint-resumed permutation replay with one-shot summary-chunk iterables.

### DEC-066 - 2026-02-16

- Decision:
Add explicit default-route projection summary-chunk extension entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route`), route `MergeResult.extend_conflict_projection_counts_from_summary_chunks` through that shim, and lock focused endpoint parity where explicit fan-out routing (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`) remains equal to default summary-derived routing across split recomposition and checkpoint-resumed permutation replay with injected empty summary chunks and one-shot iterables.

- Context:
Iteration 65 locked default projection summary-chunk extension outputs to summary-derived projection outputs, but explicit fan-out projection routing still lacked focused split/permutation endpoint parity coverage against the default route under empty-base and empty-continuation replay endpoints.

- Alternatives considered:
1. Add fan-out parity tests only and keep default projection summary-chunk routing inlined to summary-extension routing.
2. Remove explicit fan-out projection routing and keep only default summary-derived routing.
3. Add a dedicated default-route shim and lock focused endpoint parity between explicit fan-out and default routing paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes default-vs-fan-out routing invariants implementation-linked while preserving both routes for focused parity diagnostics.

- Risks accepted:
Adds one public and one internal routing shim with no intended behavior change; parity tests guard against drift between route implementations.

- Follow-up verification needed:
If future slices optimize projection summary-chunk routing internals, preserve invariants where explicit fan-out routing remains equal to default summary-derived routing across empty-base and empty-continuation replay endpoints, split recomposition, and checkpoint-resumed permutation replay with one-shot summary-chunk iterables.

### DEC-067 - 2026-02-16

- Decision:
Align `_extend_conflict_projection_counts_from_summary_chunks_via_default_route` to call the explicit summary-extension entrypoint (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) and lock focused raw-stream parity where `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route` equals `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension` across split recomposition and checkpoint-resumed permutation replay using `conflict_summary_chunks_with_empty_path(...)`, recomposed continuation summaries, injected empty chunks, and one-shot iterables.

- Context:
Iteration 66 locked explicit fan-out parity against default routing at empty endpoints, but did not yet isolate default-route-vs-summary-extension parity directly over raw continuation summary-chunk streams emitted from replay results.

- Alternatives considered:
1. Add raw-stream parity tests only and keep default-route internal routing pointed at the private summary-extension helper.
2. Remove default-route entrypoints and route all callers through summary-extension directly.
3. Keep both public routes, align default-route internals to the explicit summary-extension entrypoint, and add focused split/permutation raw-stream parity tests.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps both public entrypoints available for diagnostics while making the raw-stream parity invariant explicit and implementation-linked without expanding API surface.

- Risks accepted:
Adds no new behavior surface but increases parity coverage footprint; test runtime and maintenance overhead rise slightly with two additional split/permutation suites.

- Follow-up verification needed:
If future slices optimize projection summary-chunk routing or summary-chunk normalization, preserve invariants where default-route and summary-extension projection routing remain equivalent for raw replay-derived continuation summary streams (including injected-empty and one-shot iterable paths) across split recomposition and checkpoint-resumed permutation replay.

### DEC-068 - 2026-02-16

- Decision:
Route the public projection summary-chunk extension entrypoint through an explicit internal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_public_entrypoint`) and lock focused raw-stream parity where `MergeResult.extend_conflict_projection_counts_from_summary_chunks` equals both explicit route entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route`, `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary-chunk streams, injected empty chunks, and one-shot iterables.

- Context:
Iteration 67 locked parity between default-route and summary-extension projection routing over raw replay-derived summary streams, but the public default entrypoint still lacked dedicated split/permutation raw-stream parity coverage against both explicit route entrypoints.

- Alternatives considered:
1. Add parity tests only and keep public entrypoint routing inline.
2. Remove explicit route entrypoints and keep only the public entrypoint.
3. Add an explicit internal public-entrypoint shim and lock focused public-vs-explicit route parity tests over raw replay-derived summary streams.

- Why chosen:
Option 3 is the smallest deterministic mechanism that makes public-entrypoint routing intent implementation-linked while preserving existing route entrypoints for diagnostics and parity isolation.

- Risks accepted:
Adds one internal no-behavior-change shim and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices alter projection summary-chunk routing internals, preserve invariants where the public projection extension entrypoint remains equivalent to explicit default-route and summary-extension entrypoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-069 - 2026-02-16

- Decision:
Extract deterministic fan-out summary-chunk splitting into `MergeResult._fan_out_conflict_summary_chunks` and lock focused raw-stream parity where the public projection summary-chunk extension entrypoint (`MergeResult.extend_conflict_projection_counts_from_summary_chunks`) equals explicit fan-out routing (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 68 locked public projection summary-chunk extension parity against default-route and summary-extension entrypoints over raw replay-derived summary streams, but did not yet isolate dedicated raw-stream parity coverage against the explicit fan-out route under the same split/permutation replay conditions.

- Alternatives considered:
1. Add public-vs-fan-out parity tests only and leave fan-out chunk splitting inlined in `_extend_conflict_projection_counts_from_summary_chunks_via_fan_out`.
2. Remove explicit fan-out routing and rely only on default-route and summary-extension entrypoints.
3. Add a shared fan-out chunk splitter helper and lock focused public-vs-fan-out raw-stream parity tests across split and checkpoint-resumed permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps explicit fan-out routing available for diagnostics while reducing fan-out chunk-splitting drift risk and making public-vs-fan-out raw-stream parity implementation-linked.

- Risks accepted:
Adds one internal helper and two parity suites with no intended behavior change; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices change projection summary-chunk routing internals, preserve invariants where public projection extension remains equivalent to explicit fan-out routing across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-070 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out` through explicit internal fan-out route shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route`) before component fan-out execution (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`), and lock focused raw-stream parity where explicit fan-out routing equals explicit summary-extension routing across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 69 locked public-entrypoint raw-stream parity against explicit fan-out routing and extracted shared fan-out chunk splitting, but explicit-route parity coverage between `...via_fan_out` and `...via_summary_extension` was not isolated yet over the same replay-derived continuation summary streams.

- Alternatives considered:
1. Add explicit-route parity tests only and leave fan-out route dispatch inlined in `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`.
2. Remove explicit fan-out routing and rely on summary-extension/default-route entrypoints only.
3. Add a dedicated fan-out route shim and lock focused split/permutation explicit-route parity between fan-out and summary-extension entrypoints.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps explicit fan-out routing available for diagnostics while making fan-out-vs-summary-extension parity implementation-linked and resilient to internal fan-out refactors.

- Risks accepted:
Adds one internal routing layer and two additional parity suites with no intended behavior change; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices optimize projection summary-chunk routing internals, preserve invariants where explicit fan-out and explicit summary-extension routing remain equivalent across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-071 - 2026-02-16

- Decision:
Route the internal fan-out route shim through explicit route-to-component handoff helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route_components`) before component execution (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`), and lock focused raw-stream parity where internal fan-out route shims (`...via_fan_out_route`, `...via_fan_out_route_components`) equal component execution across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 70 introduced explicit fan-out route shimming and locked explicit fan-out API parity against explicit summary-extension routing, but it did not yet isolate dedicated split/permutation raw-stream parity between the internal fan-out route shim itself and its component implementation path.

- Alternatives considered:
1. Add internal route-vs-component parity tests only and keep route-to-component dispatch inlined inside `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route`.
2. Remove internal fan-out route shim and call components directly from public fan-out routing.
3. Add explicit internal route-to-component handoff helper and lock focused raw-stream parity across internal route, route-handoff, and component execution paths.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps internal route boundaries explicit for diagnostics while making route-to-component parity implementation-linked and resilient to future internal fan-out refactors.

- Risks accepted:
Adds one internal no-behavior-change helper and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices optimize fan-out internals, preserve invariants where internal route shims and component execution remain equivalent across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-072 - 2026-02-16

- Decision:
Route public fan-out projection summary-chunk extension through an explicit internal public-entrypoint shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint`) and lock focused raw-stream parity where public fan-out entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint`) equal internal fan-out route shims (`...via_fan_out_route`, `...via_fan_out_route_components`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 71 locked parity between internal fan-out route shims and component execution, but it did not yet isolate dedicated split/permutation raw-stream parity between the public fan-out entrypoint and those internal route shims.

- Alternatives considered:
1. Add public-vs-internal parity tests only and keep public fan-out dispatch inlined.
2. Remove explicit internal route shims and keep only a public fan-out entrypoint.
3. Add an explicit public-entrypoint shim and lock focused public-vs-internal route-shim parity tests across split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps public fan-out route boundaries explicit for diagnostics while making public-to-internal route parity implementation-linked and refactor-safe.

- Risks accepted:
Adds one internal no-behavior-change shim and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out routing internals, preserve invariants where public fan-out entrypoints remain equivalent to internal fan-out route shims across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-073 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint` through an explicit public-to-component handoff shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components`) and lock focused raw-stream parity where public fan-out entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint`) equal direct component execution (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 72 locked parity between public fan-out entrypoints and internal fan-out route shims, but direct split/permutation parity between those public entrypoints and component execution was not isolated yet.

- Alternatives considered:
1. Add public-entrypoint-vs-components parity tests only and keep public-entrypoint dispatch inlined.
2. Remove internal fan-out route shims and route all fan-out callers directly to components.
3. Add an explicit public-to-component handoff shim and lock focused public-entrypoint-vs-components parity tests across split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps the public-entrypoint-to-components boundary explicit for diagnostics while making direct component parity implementation-linked and refactor-safe.

- Risks accepted:
Adds one internal no-behavior-change shim and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out internals, preserve invariants where public fan-out entrypoints remain equivalent to direct component execution (including explicit public-to-component handoff) across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-074 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components` through an explicit public-components-route helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`) that delegates to internal fan-out route shims, and lock focused raw-stream parity where public-components shims (`...via_fan_out_public_components`, `...via_fan_out_public_components_route`) equal internal fan-out route shims (`...via_fan_out_route`, `...via_fan_out_route_components`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 73 locked public fan-out entrypoints against direct component execution (including the public-to-component handoff), but direct split/permutation parity between the public-components handoff path and internal fan-out route shims was not isolated yet.

- Alternatives considered:
1. Add public-components-vs-internal-route parity tests only and keep dispatch inlined in `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components`.
2. Remove the public-components handoff shim and route public fan-out entrypoints directly to internal route shims.
3. Add an explicit public-components-route helper and lock focused public-components-vs-internal-route parity tests across split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps the public-components-to-internal-route boundary explicit for diagnostics while making that route parity implementation-linked and refactor-safe.

- Risks accepted:
Adds one internal no-behavior-change helper and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out internals, preserve invariants where public-components fan-out shims remain equivalent to internal fan-out route shims across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-075 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route` through an explicit route-to-components handoff helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route_components`) and lock focused raw-stream parity where both public-components-route helpers equal direct component execution (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 74 locked parity between public-components shims and internal fan-out route shims, but direct split/permutation parity between the public-components-route helper and direct component execution was not isolated yet.

- Alternatives considered:
1. Add public-components-route-vs-components parity tests only and keep direct component dispatch inlined inside `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`.
2. Remove the public-components-route helper and dispatch public-components fan-out calls directly to components.
3. Add an explicit public-components-route-to-components handoff helper and lock focused parity tests across split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps the public-components-route-to-components boundary explicit for diagnostics while making direct component parity implementation-linked and refactor-safe.

- Risks accepted:
Adds one internal no-behavior-change helper and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out internals, preserve invariants where public-components-route fan-out helpers remain equivalent to direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-076 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components` through an explicit public-components-to-route-components handoff helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_components`) and lock focused raw-stream parity where both public-components helpers equal route-components dispatch (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route_components`) and direct component execution (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`) across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 75 locked parity between public-components-route helpers and direct component execution, but direct split/permutation parity between the public-components helper itself and route-components dispatch was not isolated yet.

- Alternatives considered:
1. Add public-components-vs-route-components parity tests only and keep route-components dispatch inlined inside `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components`.
2. Route the public-components helper back through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route` and skip direct route-components parity coverage.
3. Add an explicit public-components-to-route-components handoff helper and lock focused parity tests across split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic mechanism that keeps the public-components-to-route-components boundary explicit for diagnostics while making route-components/component parity implementation-linked and refactor-safe.

- Risks accepted:
Adds one internal no-behavior-change helper and two additional split/permutation parity suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out internals, preserve invariants where public-components fan-out helpers remain equivalent to route-components dispatch and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-077 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_components` through the explicit public-components-route helper (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`) instead of directly to route-components dispatch, and extend split/permutation raw-stream parity coverage so the handoff output is locked to route dispatch (`...via_fan_out_public_components_route`), route-components dispatch (`...via_fan_out_public_components_route_components`), and direct component execution (`...via_fan_out_components`) across replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 76 locked parity between public-components helpers and route-components/component execution, but it did not isolate direct parity between the explicit public-components-to-route-components handoff helper and the explicit public-components-route helper.

- Alternatives considered:
1. Keep dispatch from `...via_fan_out_public_components_components` directly to route-components and add assertions only in tests.
2. Route `...via_fan_out_public_components_components` straight to direct component execution and skip explicit route parity.
3. Route `...via_fan_out_public_components_components` through `...via_fan_out_public_components_route` and expand raw-stream parity assertions across route, route-components, and components.

- Why chosen:
Option 3 is the smallest no-behavior-change mechanism that keeps the public-components-components to public-components-route boundary explicit and implementation-linked under refactors.

- Risks accepted:
Adds one extra internal call layer and additional parity assertions in existing split/permutation suites; maintenance surface and test runtime increase slightly.

- Follow-up verification needed:
If future slices refactor fan-out route internals, preserve invariants where `...via_fan_out_public_components_components` remains equivalent to `...via_fan_out_public_components_route`, `...via_fan_out_public_components_route_components`, and `...via_fan_out_components` across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-078 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route` and extend raw-stream parity assertions so direct public-components dispatch is explicitly locked to direct public-components-route dispatch across split recomposition and checkpoint-resumed permutation replay with replay-derived summary chunks, injected empty chunks, and one-shot iterables.

- Context:
Iteration 77 locked public-components-components handoff parity against route dispatch, route-components dispatch, and component execution, but direct parity between public-components dispatch and public-components-route dispatch was only covered transitively.

- Alternatives considered:
1. Keep `...via_fan_out_public_components` routed through `...via_fan_out_public_components_components` and add direct route parity assertions only in tests.
2. Route `...via_fan_out_public_components` directly to components and reduce internal route boundary usage.
3. Route `...via_fan_out_public_components` directly through `...via_fan_out_public_components_route` and add explicit direct-route parity assertions.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns the production routing boundary with the intended explicit parity invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Public-components-components remains as an extra internal indirection path used for diagnostics/parity coverage; internal call graph remains slightly wider.

- Follow-up verification needed:
If fan-out internals are refactored again, preserve explicit invariants where direct public-components dispatch stays equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths).

### DEC-079 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock direct public-entrypoint dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 78 locked direct public-components dispatch to direct public-components-route dispatch, but direct public-entrypoint-vs-public-components-route parity was only indirectly covered through broader public/internal fan-out parity suites.

- Alternatives considered:
1. Keep public-entrypoint dispatch routed through `...via_fan_out_public_components` and rely on transitive parity coverage.
2. Route public-entrypoint dispatch directly to components and bypass explicit public-components-route boundary.
3. Route public-entrypoint dispatch directly to explicit public-components-route helper and add focused parity suites for split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns production routing with the explicit public-entrypoint-to-route boundary and keeps route diagnostics implementation-linked.

- Risks accepted:
Adds one more focused parity helper/suite pair and preserves internal diagnostic indirection helpers, increasing internal surface and test runtime slightly.

- Follow-up verification needed:
If fan-out internals are refactored again, preserve explicit invariants where direct public-entrypoint dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-080 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock direct public fan-out API dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 79 locked direct public-entrypoint dispatch to direct public-components-route dispatch, but direct public fan-out API dispatch (`...via_fan_out`) to public-components-route dispatch was not isolated in dedicated raw-stream split/permutation parity suites.

- Alternatives considered:
1. Keep public fan-out API dispatch routed through `...via_fan_out_public_entrypoint` and rely on transitive parity coverage.
2. Route public fan-out API dispatch directly to component execution and bypass explicit public-components-route boundary.
3. Route public fan-out API dispatch directly to explicit public-components-route helper and add focused parity suites for split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns production routing with the explicit public-api-to-route boundary and keeps route diagnostics implementation-linked.

- Risks accepted:
Adds one more focused parity helper/suite pair and keeps internal diagnostic shims in place, increasing internal call-graph/test surface slightly.

- Follow-up verification needed:
If fan-out internals are refactored again, preserve explicit invariants where direct public fan-out API dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-081 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock top-level public projection summary-chunk extension dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 80 locked direct public fan-out API dispatch to direct public-components-route dispatch, but top-level public projection summary-chunk extension dispatch (`MergeResult.extend_conflict_projection_counts_from_summary_chunks`) to direct public-components-route dispatch was still covered transitively through fan-out/default-route parity paths.

- Alternatives considered:
1. Keep top-level public API dispatch routed through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_public_entrypoint` and rely on transitive parity coverage.
2. Route top-level public API dispatch directly to summary-extension/default-route shims and skip explicit public-components-route parity coverage.
3. Route top-level public API dispatch directly to explicit public-components-route helper and add focused parity suites for split/permutation replay.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns top-level public API production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains multiple explicit routing shims (`...via_public_entrypoint`, `...via_default_route`, `...via_summary_extension`) for diagnostics, which keeps internal call-graph/test surface wider.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where top-level public projection summary-chunk extension dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-082 - 2026-02-16

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_public_entrypoint` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock internal public-entrypoint projection summary-chunk dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 81 locked top-level public projection summary-chunk extension dispatch to direct public-components-route dispatch, but the retained internal public-entrypoint shim still routed through default-route/summary-extension paths and lacked focused split/permutation raw-stream parity coverage against explicit public-components-route dispatch.

- Alternatives considered:
1. Keep the internal public-entrypoint shim routed through default-route/summary-extension shims and rely on transitive parity coverage from top-level API tests.
2. Keep current internal routing and add only focused assertions in tests without changing production dispatch.
3. Route the internal public-entrypoint shim directly to explicit public-components-route helper and add focused split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns internal public-entrypoint production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains default-route/summary-extension shims for diagnostics while reducing one internal path�s runtime usage, keeping routing surface broader than minimally necessary.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where internal public-entrypoint dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-083 - 2026-02-16

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock public default-route projection summary-chunk dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 82 locked internal public-entrypoint projection summary-chunk dispatch to direct public-components-route dispatch, but public default-route API dispatch (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route`) still routed through the internal summary-derived default-route shim and lacked focused split/permutation raw-stream parity coverage against explicit public-components-route dispatch.

- Alternatives considered:
1. Keep public default-route API dispatch routed through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route` and rely on transitive parity coverage from existing public/internal entrypoint tests.
2. Keep current public default-route routing and add only focused assertions in tests without changing production dispatch.
3. Route public default-route API dispatch directly to explicit public-components-route helper and add focused split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns public default-route production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains the internal summary-derived default-route shim for diagnostics while bypassing it in the public default-route API path, which keeps routing surface broader than minimally necessary.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where public default-route dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-084 - 2026-02-17

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock internal default-route projection summary-chunk dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 83 locked public default-route API projection summary-chunk dispatch to direct public-components-route dispatch, but the retained internal default-route shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route`) still routed through summary-extension and lacked focused split/permutation raw-stream parity coverage against explicit public-components-route dispatch.

- Alternatives considered:
1. Keep internal default-route shim routed through summary-extension and rely on transitive parity coverage from public default-route and entrypoint tests.
2. Keep current internal routing and add focused assertions only in tests without changing production dispatch.
3. Route internal default-route shim directly to explicit public-components-route helper and add focused split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns internal default-route production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains summary-extension routing helpers for diagnostics while bypassing them in the internal default-route shim path, which keeps routing surface broader than minimally necessary.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where internal default-route dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-085 - 2026-02-17

- Decision:
Route `MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock public summary-extension projection summary-chunk dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 84 locked internal default-route projection summary-chunk dispatch to direct public-components-route dispatch, but public summary-extension API dispatch (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) still routed through the internal summary-extension shim and lacked focused split/permutation raw-stream parity coverage against explicit public-components-route dispatch.

- Alternatives considered:
1. Keep public summary-extension API dispatch routed through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_summary_extension` and rely on transitive parity coverage from public/default-route/internal entrypoint tests.
2. Keep current public summary-extension routing and add focused assertions only in tests without changing production dispatch.
3. Route public summary-extension API dispatch directly to explicit public-components-route helper and add focused split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns public summary-extension production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains the internal summary-extension shim for diagnostics while bypassing it in the public summary-extension API path, which keeps routing surface broader than minimally necessary.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where public summary-extension dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-086 - 2026-02-17

- Decision:
Route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_summary_extension` directly through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, and add focused split/permutation raw-stream one-shot parity tests that lock internal summary-extension projection summary-chunk dispatch to direct public-components-route dispatch (plus route-components/components parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 85 locked public summary-extension projection summary-chunk dispatch to direct public-components-route dispatch, but the retained internal summary-extension shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) still routed through `MergeResult.extend_conflict_summary_from_chunks` and lacked focused split/permutation raw-stream parity coverage against explicit public-components-route dispatch.

- Alternatives considered:
1. Keep internal summary-extension shim routed through `MergeResult.extend_conflict_summary_from_chunks` and rely on transitive parity coverage from public summary-extension/default-route/entrypoint tests.
2. Keep current internal summary-extension routing and add focused assertions only in tests without changing production dispatch.
3. Route internal summary-extension shim directly to explicit public-components-route helper and add focused split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that aligns internal summary-extension production routing with the explicit public-components-route invariant and keeps route diagnostics implementation-linked.

- Risks accepted:
Retains summary-derived extension helpers for diagnostics while bypassing them in the internal summary-extension shim path, which keeps routing surface broader than minimally necessary.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where internal summary-extension dispatch remains equivalent to direct public-components-route dispatch, route-components dispatch, and direct component execution across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-087 - 2026-02-17

- Decision:
Add shared summary-extension projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_summary_extension_dispatch`) and route both summary-extension entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_summary_extension`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock public summary-extension API dispatch directly to the internal summary-extension shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 86 locked internal summary-extension dispatch to direct public-components-route dispatch, but direct public-summary-extension-API vs internal-summary-extension-shim parity was still covered transitively through components-route parity tests and not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both entrypoints routed directly to public-components-route helper and rely on transitive parity coverage only.
2. Route public summary-extension API through internal summary-extension shim and drop explicit shared dispatch helper.
3. Add explicit shared summary-extension dispatch shim and focused API-vs-internal parity suites while keeping both entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps API-to-internal-shim routing parity implementation-linked under refactors without collapsing public API dispatch onto private shim indirection.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where public summary-extension dispatch remains equivalent to internal summary-extension shim dispatch and shared summary-extension dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-088 - 2026-02-17

- Decision:
Add shared default-route projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route_dispatch`) and route both default-route entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_default_route`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_default_route`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock public default-route API dispatch directly to the internal default-route shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 87 locked public summary-extension API dispatch to the internal summary-extension shim via a shared dispatch shim, but the default-route public API vs internal default-route shim parity remained transitive through components-route parity tests and was not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both default-route entrypoints routed directly to the public-components-route helper and rely on transitive parity coverage only.
2. Route public default-route API directly through internal default-route shim and avoid adding an explicit shared dispatch helper.
3. Add explicit shared default-route dispatch shim and focused API-vs-internal parity suites while keeping both default-route entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps default-route API-to-internal-shim routing parity implementation-linked under refactors without collapsing public API dispatch onto private shim-only indirection.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where public default-route dispatch remains equivalent to internal default-route shim dispatch and shared default-route dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-089 - 2026-02-17

- Decision:
Add shared public-entrypoint projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_public_entrypoint_dispatch`) and route both top-level public projection summary-chunk entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_public_entrypoint`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock public API dispatch directly to the internal public-entrypoint shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 88 locked public default-route API dispatch to the internal default-route shim via a shared dispatch shim, but top-level public projection API vs internal public-entrypoint shim parity remained transitive through components-route parity tests and was not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both top-level public entrypoints routed directly to the public-components-route helper and rely on transitive parity coverage only.
2. Route top-level public API directly through internal public-entrypoint shim and avoid adding an explicit shared dispatch helper.
3. Add explicit shared public-entrypoint dispatch shim and focused API-vs-internal parity suites while keeping both top-level public entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps top-level public API-to-internal-public-entrypoint routing parity implementation-linked under refactors without collapsing public API dispatch onto private shim-only indirection.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where top-level public projection dispatch remains equivalent to internal public-entrypoint shim dispatch and shared public-entrypoint dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-090 - 2026-02-17

- Decision:
Add shared fan-out public-entrypoint projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint_dispatch`) and route both fan-out public projection summary-chunk entrypoints (`MergeResult.extend_conflict_projection_counts_from_summary_chunks_via_fan_out`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_entrypoint`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock fan-out public API dispatch directly to the internal fan-out public-entrypoint shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 89 locked top-level public projection API dispatch to the internal public-entrypoint shim via a shared dispatch shim, but fan-out public projection API vs internal fan-out public-entrypoint shim parity remained transitive through components-route parity tests and was not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both fan-out public entrypoints routed directly to the public-components-route helper and rely on transitive parity coverage only.
2. Route fan-out public API directly through the internal fan-out public-entrypoint shim and avoid adding an explicit shared dispatch helper.
3. Add explicit shared fan-out public-entrypoint dispatch shim and focused API-vs-internal parity suites while keeping both fan-out public entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps fan-out public API-to-internal-public-entrypoint routing parity implementation-linked under refactors without collapsing public fan-out API dispatch onto private shim-only indirection.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where fan-out public projection dispatch remains equivalent to internal fan-out public-entrypoint shim dispatch and shared fan-out public-entrypoint dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-091 - 2026-02-17

- Decision:
Add shared fan-out public-components projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_dispatch`) and route both fan-out public-components projection summary-chunk entrypoints (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_components`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock direct public-components dispatch to the internal public-components-components shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 90 locked fan-out public API dispatch to the internal fan-out public-entrypoint shim via a shared dispatch shim, but direct fan-out public-components dispatch vs internal public-components-components shim parity remained transitive through route/components parity tests and was not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both public-components entrypoints routed directly to public-components-route helper and rely on transitive parity coverage only.
2. Route only `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components` through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_components` and avoid adding an explicit shared dispatch helper.
3. Add explicit shared public-components dispatch shim and focused public-components-vs-public-components-components parity suites while keeping both entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps public-components-to-components-components routing parity implementation-linked under refactors without collapsing dispatch onto one private shim call path.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where fan-out public-components dispatch remains equivalent to internal public-components-components shim dispatch and shared public-components dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-092 - 2026-02-17

- Decision:
Add shared fan-out public-components-route projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route_dispatch`) and route both fan-out public-components-route projection summary-chunk entrypoints (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route_components`) through it, then add focused split/permutation raw-stream one-shot parity tests that lock direct public-components-route dispatch to the internal public-components-route-components shim (including dispatch-shim parity) across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 91 locked fan-out public-components dispatch to internal public-components-components shim via shared dispatch, but direct fan-out public-components-route dispatch vs internal public-components-route-components shim parity remained transitive through route/components parity tests and was not isolated as its own split/permutation invariant.

- Alternatives considered:
1. Keep both public-components-route entrypoints routed directly to `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components` and rely on transitive parity coverage only.
2. Route only `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route` through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_public_components_route_components` and avoid adding an explicit shared dispatch helper.
3. Add explicit shared public-components-route dispatch shim and focused public-components-route-vs-route-components parity suites while keeping both entrypoints routed through the shared shim.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps public-components-route-to-route-components routing parity implementation-linked under refactors without collapsing dispatch onto one private shim call path.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where fan-out public-components-route dispatch remains equivalent to internal public-components-route-components shim dispatch and shared public-components-route dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-093 - 2026-02-17

- Decision:
Add shared internal fan-out-route projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route_dispatch`) and route both internal fan-out-route projection summary-chunk entrypoints (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route_components`) through it, then extend focused split/permutation raw-stream one-shot parity tests to lock direct internal route dispatch to the internal route-components shim and shared dispatch shim across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 92 locked fan-out public-components-route dispatch to internal route-components shim via shared dispatch, but direct internal fan-out-route dispatch parity (`...via_fan_out_route` vs `...via_fan_out_route_components`) still depended on a direct call chain and was not isolated through an explicit shared internal dispatch helper.

- Alternatives considered:
1. Keep both internal fan-out-route entrypoints directly routed and rely on existing transitive parity coverage only.
2. Route only `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route` through `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route_components` without adding a shared dispatch helper.
3. Add explicit shared internal fan-out-route dispatch shim and extend the focused split/permutation parity suites to assert route-vs-route-components-vs-dispatch equivalence.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps internal route-to-route-components parity implementation-linked under refactors without collapsing diagnostics onto one private shim-only call edge.

- Risks accepted:
Adds one extra internal no-behavior-change helper and broadens existing parity assertions; internal call graph/test assertions increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where internal fan-out-route dispatch remains equivalent to internal route-components shim dispatch and shared internal route dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-094 - 2026-02-17

- Decision:
Add shared internal fan-out-components projection dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_dispatch`) and route internal component execution entrypoint (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`) through it, then extend focused split/permutation raw-stream one-shot parity tests to lock direct internal components execution to shared components dispatch shim outputs across replay-derived summary chunks with injected-empty wrappers.

- Context:
Iteration 93 locked internal fan-out-route dispatch to route-components and route-dispatch shim parity, but the terminal internal component execution path (`...via_fan_out_components`) still embedded fan-out logic directly and lacked an explicit dispatch-shim parity lock for one-shot/injected-empty raw summary streams.

- Alternatives considered:
1. Keep internal component execution logic inline and rely on transitive parity coverage from route-dispatch tests.
2. Route only `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_route_dispatch` through a new helper while leaving `...via_fan_out_components` inline.
3. Add explicit shared internal components dispatch shim and extend focused split/permutation parity assertions to assert components-vs-components-dispatch equivalence.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps internal terminal component dispatch parity implementation-linked under refactors while preserving existing route diagnostic shims.

- Risks accepted:
Adds one extra internal no-behavior-change helper and broadens existing parity assertions; internal call graph/test assertions increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where internal fan-out-components execution remains equivalent to shared internal components dispatch shim outputs across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-095 - 2026-02-17

- Decision:
Extract explicit terminal fan-out reducer composition helper (`MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks`) and route shared internal components dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_dispatch`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock dispatch-shim outputs directly to explicit signature/code reducer composition (`MergeResult.extend_conflict_signature_counts_from_summary_chunks` + `MergeResult.extend_conflict_code_counts_from_summary_chunks`) across injected-empty wrapper paths.

- Context:
Iteration 94 locked internal fan-out-components execution (`...via_fan_out_components`) to shared components dispatch shim parity, but terminal dispatch internals still composed signature/code reducers inline and explicit reducer-composition invariants were not isolated as dedicated split/permutation raw-stream coverage.

- Alternatives considered:
1. Keep terminal reducer composition inline in dispatch shim and rely on transitive route/components parity coverage only.
2. Add dedicated tests that duplicate inline composition logic in test helpers without extracting an implementation helper.
3. Extract an explicit terminal reducer-composition helper and add dedicated dispatch-vs-explicit-composition parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal dispatch-to-signature/code reducer composition implementation-linked under refactors while making the invariant explicit and directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk routing internals are refactored again, preserve explicit invariants where shared internal components dispatch shim outputs remain equivalent to explicit signature/code reducer composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-096 - 2026-02-17

- Decision:
Add shared internal fan-out-components terminal dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_dispatch`) and route both internal fan-out-components entrypoints (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components`, `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_dispatch`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock direct internal fan-out-components execution outputs to explicit terminal reducer-helper composition via `MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks`.

- Context:
Iteration 95 locked shared components-dispatch outputs to explicit terminal signature/code composition, but direct internal fan-out-components execution parity (`...via_fan_out_components`) versus explicit terminal helper composition remained transitive through dispatch-shim equality rather than isolated as its own split/permutation raw-stream invariant.

- Alternatives considered:
1. Keep current routing and rely on transitive parity (`...via_fan_out_components` equals `...via_fan_out_components_dispatch`, and dispatch equals explicit terminal helper composition).
2. Add direct components-vs-terminal-helper tests only, without introducing an explicit shared terminal dispatch shim.
3. Add shared terminal dispatch shim and dedicated components-vs-terminal-helper parity suites while preserving existing components-vs-dispatch and dispatch-vs-helper invariants.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps direct internal fan-out-components execution parity with terminal helper composition implementation-linked under refactors without collapsing existing diagnostic shim coverage.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk fan-out internals are refactored again, preserve explicit invariants where direct internal fan-out-components execution outputs remain equivalent to explicit terminal helper composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-097 - 2026-02-17

- Decision:
Add shared internal terminal-components shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components`) and route terminal dispatch (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_dispatch`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock terminal-dispatch outputs directly to explicit terminal helper composition via `MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks`.

- Context:
Iteration 96 locked direct internal fan-out-components execution to explicit terminal helper composition, but terminal dispatch still performed fan-out-to-helper composition inline and terminal-dispatch-vs-explicit-helper parity remained transitive rather than isolated as its own split/permutation raw-stream invariant.

- Alternatives considered:
1. Keep terminal dispatch inline and rely on transitive coverage through existing fan-out-components parity tests.
2. Add terminal-dispatch parity tests only, without introducing a dedicated terminal-components shim.
3. Add an explicit terminal-components shim and dedicated terminal-dispatch-vs-terminal-helper parity suites while preserving existing components-vs-terminal-dispatch coverage.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-dispatch-to-terminal-helper composition parity implementation-linked under refactors while making terminal dispatch invariants directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk fan-out internals are refactored again, preserve explicit invariants where terminal dispatch outputs remain equivalent to explicit terminal helper composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-098 - 2026-02-17

- Decision:
Add shared internal terminal-components dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch`) and route terminal-components shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock terminal-components-shim outputs directly to explicit terminal helper composition via `MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks`.

- Context:
Iteration 97 locked terminal-dispatch outputs to explicit terminal helper composition, but terminal-components shim still performed fan-out-to-helper composition inline and terminal-components-shim-vs-explicit-helper parity remained transitive rather than isolated as its own split/permutation raw-stream invariant.

- Alternatives considered:
1. Keep terminal-components shim inline and rely on transitive coverage through existing terminal-dispatch parity tests.
2. Add terminal-components-shim parity tests only, without introducing a dedicated terminal-components dispatch shim.
3. Add an explicit terminal-components dispatch shim and dedicated terminal-components-shim-vs-terminal-helper parity suites while preserving existing terminal-dispatch coverage.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-components-shim-to-terminal-helper composition parity implementation-linked under refactors while making the terminal-components invariant directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk fan-out internals are refactored again, preserve explicit invariants where terminal-components shim outputs remain equivalent to explicit terminal helper composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-099 - 2026-02-17

- Decision:
Add shared internal terminal-components-dispatch terminal-helper shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_terminal_helper`) and route terminal-components dispatch (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock terminal-components-dispatch outputs directly to explicit terminal helper composition via `MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks` and the new dispatch terminal-helper shim.

- Context:
Iteration 98 locked terminal-components-shim outputs to explicit terminal helper composition, but terminal-components dispatch still performed fan-out-to-helper composition inline and terminal-components-dispatch-vs-explicit-helper parity remained transitive through the terminal-components shim instead of isolated as its own split/permutation raw-stream invariant.

- Alternatives considered:
1. Keep terminal-components dispatch inline and rely on transitive coverage through terminal-components parity tests.
2. Add terminal-components-dispatch parity tests only, without introducing a dispatch terminal-helper shim.
3. Add an explicit terminal-components-dispatch terminal-helper shim and dedicated terminal-components-dispatch-vs-terminal-helper parity suites while preserving existing terminal-components and terminal-dispatch coverage.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-components-dispatch-to-terminal-helper composition parity implementation-linked under refactors while making dispatch-level invariants directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk fan-out internals are refactored again, preserve explicit invariants where terminal-components dispatch outputs remain equivalent to explicit terminal helper composition and the dispatch terminal-helper shim across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-100 - 2026-02-17

- Decision:
Add explicit pre-fanned terminal reducer shim (`MergeResult._extend_conflict_projection_counts_from_pre_fanned_component_chunks`) and route terminal-components-dispatch terminal-helper shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_terminal_helper`) through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock terminal-helper dispatch directly to both pre-fanned composition and explicit fan-out component reducer composition (`MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks`) across materialized, one-shot, and injected-empty component-stream paths.

- Context:
Iteration 99 locked terminal-components dispatch outputs to explicit terminal helper composition and the terminal-helper shim, but terminal-helper dispatch still called explicit fan-out component reducer composition directly and pre-fanned component-stream parity invariants were not isolated as dedicated split/permutation coverage.

- Alternatives considered:
1. Keep terminal-helper shim routed directly to `MergeResult._extend_conflict_projection_counts_from_fan_out_component_chunks` and rely on existing transitive parity coverage.
2. Add direct terminal-helper-vs-explicit-composition tests only, without introducing a pre-fanned composition shim.
3. Add an explicit pre-fanned terminal reducer shim and dedicated terminal-helper parity suites covering materialized, one-shot, and injected-empty pre-fanned component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-helper-to-pre-fanned composition parity implementation-linked under refactors while making pre-fanned component-stream invariants explicit and directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change helper and two focused split/permutation parity suites; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If projection summary-chunk fan-out internals are refactored again, preserve explicit invariants where terminal-helper dispatch outputs remain equivalent to both pre-fanned component composition and explicit fan-out component reducer composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-101 - 2026-02-17

- Decision:
Add explicit independent pre-fanned component-stream dispatch shim (`MergeResult._extend_conflict_projection_counts_from_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_pre_fanned_component_chunks` through it, then add dedicated split/permutation raw-stream one-shot parity tests that lock independently rechunked/permuted signature/code pre-fanned streams to explicit fan-out component reducer composition.

- Context:
Iteration 100 locked terminal-helper pre-fanned parity to explicit fan-out component composition, but pre-fanned parity coverage still used mirrored signature/code summary chunk streams and did not isolate independently chunked component boundaries.

- Alternatives considered:
1. Keep mirrored component-stream parity coverage only and rely on transitive helper equivalence.
2. Add independent-stream tests only, without introducing a dedicated independent dispatch shim.
3. Add explicit independent pre-fanned dispatch shim and focused independent-stream split/permutation parity suites.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps independent pre-fanned component-stream parity implementation-linked under refactors while making independent boundary invariants explicit and directly testable.

- Risks accepted:
Adds one internal no-behavior-change shim and two focused parity suites; internal call graph/test runtime increase slightly.

- Follow-up verification needed:
If pre-fanned projection routing internals are refactored again, preserve explicit invariants where independently chunked signature/code pre-fanned streams remain equivalent to explicit fan-out component reducer composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-102 - 2026-02-17

- Decision:
Add explicit terminal-helper independent component-stream dispatch shim (MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_terminal_helper_independent_component_dispatch) and route MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_terminal_helper through it, then add dedicated split/permutation raw-stream parity tests that lock terminal-helper pre-fanned routing to the new shim, pre-fanned independent dispatch, and explicit fan-out component reducer composition under independently rechunked/permuted component streams.

- Context:
Iteration 101 locked independent pre-fanned component-stream dispatch to explicit fan-out composition, but terminal-helper parity remained transitive through pre-fanned routing and was not directly isolated against the independent dispatch shim across independently chunked signature/code stream boundaries.

- Alternatives considered:
1. Keep terminal-helper routing unchanged and rely on transitive parity through existing pre-fanned independent tests.
2. Add terminal-helper parity tests only, without introducing a terminal-helper-specific independent dispatch shim.
3. Add explicit terminal-helper independent dispatch shim and focused split/permutation parity suites covering materialized, one-shot, and injected-empty independently chunked component-stream paths.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-helper-to-independent-dispatch parity implementation-linked under refactors while making this route-level invariant directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change shim and two focused parity suites; internal call graph/test runtime increase slightly.

- Follow-up verification needed:
If terminal-helper pre-fanned routing internals are refactored again, preserve explicit invariants where terminal-helper dispatch remains equivalent to terminal-helper independent dispatch, pre-fanned independent dispatch, and explicit fan-out component reducer composition across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-103 - 2026-02-17

- Decision:
Add explicit terminal-components dispatch independent-component shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch` through it, then add dedicated split/permutation raw-stream parity tests that lock terminal-components dispatch and its new shim to terminal-helper independent dispatch under independently rechunked/permuted signature/code component streams.

- Context:
Iteration 102 locked terminal-helper dispatch to terminal-helper independent dispatch for independently chunked component streams, but terminal-components dispatch parity still depended on a transitive route through terminal-helper and was not isolated as a direct dispatch-level invariant.

- Alternatives considered:
1. Keep terminal-components dispatch inline and rely on transitive parity through terminal-helper tests.
2. Add dispatch-vs-helper parity tests only, without introducing a terminal-components dispatch shim.
3. Add explicit terminal-components dispatch independent shim and focused split/permutation parity suites covering materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-components-dispatch-to-terminal-helper-independent parity implementation-linked under refactors while making this dispatch-level invariant directly testable.

- Risks accepted:
Adds one extra internal no-behavior-change shim and two focused parity suites; internal call graph/test runtime increase slightly.

- Follow-up verification needed:
If terminal-components dispatch internals are refactored again, preserve explicit invariants where terminal-components dispatch remains equivalent to the terminal-components dispatch independent shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-104 - 2026-02-17

- Decision:
Add explicit terminal-components independent-dispatch pre-fanned route shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between terminal-components independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 103 locked terminal-components dispatch and its independent shim to terminal-helper independent dispatch, but direct parity between terminal-components independent dispatch and pre-fanned independent dispatch remained transitive through terminal-helper routing and was not isolated as an explicit dispatch-level invariant.

- Alternatives considered:
1. Keep terminal-components independent dispatch routed through terminal-helper independent dispatch and rely on transitive parity coverage.
2. Add direct terminal-components-independent-vs-pre-fanned assertions only, without introducing a dedicated pre-fanned route shim.
3. Add explicit terminal-components independent pre-fanned route shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps terminal-components-independent-to-pre-fanned parity implementation-linked under refactors while making that direct invariant explicit in both routing and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph/test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent routing internals are refactored again, preserve explicit invariants where terminal-components independent dispatch remains equivalent to both the independent pre-fanned route shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-105 - 2026-02-17

- Decision:
Add explicit pre-fanned-route terminal-helper independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the pre-fanned route shim and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 104 locked terminal-components independent dispatch to both the pre-fanned route shim and pre-fanned independent dispatch, but direct parity between the pre-fanned route shim and terminal-helper independent dispatch remained asserted only transitively through other route links.

- Alternatives considered:
1. Keep pre-fanned route shim pointed at pre-fanned independent dispatch and rely on existing transitive parity assertions.
2. Add direct pre-fanned-route-vs-terminal-helper assertions only, without adding an explicit shim in production routing.
3. Add explicit pre-fanned-route terminal-helper shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps pre-fanned-route-to-terminal-helper parity implementation-linked under refactors while making that direct route invariant explicit in both code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph/test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the pre-fanned route shim remains equivalent to both the new pre-fanned-route terminal-helper shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-106 - 2026-02-17

- Decision:
Add explicit pre-fanned-route terminal-helper-to-pre-fanned-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between pre-fanned-route terminal-helper dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 105 locked direct parity between the pre-fanned route shim and terminal-helper independent dispatch, but the pre-fanned-route terminal-helper shim to pre-fanned independent dispatch link remained asserted transitively through intermediate route invariants.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct pre-fanned-route-terminal-helper-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit pre-fanned-route terminal-helper-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps pre-fanned-route-terminal-helper-to-pre-fanned-independent parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where pre-fanned-route terminal-helper dispatch remains equivalent to the new direct pre-fanned-component-dispatch shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-107 - 2026-02-17

- Decision:
Add explicit direct-shim-to-terminal-helper bridge (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the direct pre-fanned-component-dispatch shim and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 106 locked direct parity between pre-fanned-route terminal-helper dispatch and pre-fanned independent dispatch, but direct parity between the new direct pre-fanned-component-dispatch shim and terminal-helper independent dispatch remained asserted only transitively through intermediate pre-fanned equivalences.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct assertions between the direct pre-fanned-component-dispatch shim and terminal-helper independent dispatch without adding a production routing bridge.
3. Add an explicit direct-shim-to-terminal-helper bridge and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps direct-shim-to-terminal-helper parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the direct pre-fanned-component-dispatch shim remains equivalent to the direct-shim-to-terminal-helper bridge and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-108 - 2026-02-17

- Decision:
Add explicit direct-shim-to-terminal-helper-bridge pre-fanned-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the direct-shim-to-terminal-helper bridge and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 107 locked direct parity between the direct pre-fanned-component-dispatch shim and terminal-helper independent dispatch through the new direct-shim-to-terminal-helper bridge, but direct parity between that bridge and pre-fanned independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct bridge-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps direct-shim-to-terminal-helper-bridge-to-pre-fanned-independent parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the direct-shim-to-terminal-helper bridge remains equivalent to the new bridge-to-pre-fanned-independent shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-109 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent terminal-helper dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the bridge-to-pre-fanned-independent shim and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 108 locked direct parity between the direct-shim-to-terminal-helper bridge and pre-fanned independent dispatch via a bridge-to-pre-fanned-independent shim, but direct parity between that bridge-to-pre-fanned-independent shim and terminal-helper independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct bridge-to-pre-fanned-independent-vs-terminal-helper assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-pre-fanned-independent terminal-helper shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-to-terminal-helper parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent shim remains equivalent to the new bridge-to-terminal-helper shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-110 - 2026-02-17

- Decision:
Add explicit bridge-to-terminal-helper-to-pre-fanned-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the bridge-to-terminal-helper shim and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 109 locked direct parity between the bridge-to-pre-fanned-independent shim, the bridge-to-terminal-helper shim, and terminal-helper independent dispatch, but the bridge-to-terminal-helper route still jumped straight to terminal-helper dispatch in production and did not carry an explicit implementation-linked hop to pre-fanned independent dispatch.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct bridge-to-terminal-helper-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-terminal-helper-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-terminal-helper-to-pre-fanned parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-terminal-helper shim remains equivalent to the new bridge-to-pre-fanned-independent dispatch shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-111 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this bridge chain and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 110 locked direct parity between bridge-to-terminal-helper shim and pre-fanned independent dispatch through an explicit bridge-to-pre-fanned-independent hop, but direct parity between that bridge-to-terminal-helper-to-pre-fanned-independent hop and terminal-helper independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct bridge-to-terminal-helper-to-pre-fanned-independent-vs-terminal-helper assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-terminal-helper-to-pre-fanned-independent-to-terminal-helper parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-terminal-helper-to-pre-fanned-independent dispatch shim remains equivalent to both the new bridge-to-pre-fanned-independent-via-terminal-helper-independent shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-112 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this bridge chain and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 111 locked direct parity between bridge-to-terminal-helper-to-pre-fanned-independent dispatch shim, bridge-to-pre-fanned-independent-via-terminal-helper-independent shim, and terminal-helper independent dispatch, but direct parity between the bridge-to-pre-fanned-independent-via-terminal-helper-independent shim and pre-fanned independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct bridge-to-pre-fanned-independent-via-terminal-helper-independent-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent shim remains equivalent to both the new bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-113 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent dispatch shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this bridge chain and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 112 locked direct parity between bridge-to-pre-fanned-independent-via-terminal-helper-independent shim, bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent shim, and pre-fanned independent dispatch, but direct parity between the terminal pre-fanned shim and terminal-helper independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct terminal-pre-fanned-vs-terminal-helper assertions only, without adding an explicit routing shim.
3. Add explicit bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent shim remains equivalent to both the new bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-114 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this bridge chain and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 113 locked direct parity between the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent shim, the new bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim, and terminal-helper independent dispatch, but direct parity between that newest terminal-helper bridge and pre-fanned independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct terminal-helper-bridge-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit terminal-helper-bridge-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim remains equivalent to both the new bridge-to-pre-fanned-independent terminal shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-115 - 2026-02-17

- Decision:
Add explicit bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this bridge chain and terminal-helper independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 114 locked direct parity between the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim, the new bridge-to-pre-fanned-independent terminal shim, and pre-fanned independent dispatch, but direct parity between that newest pre-fanned terminal shim and terminal-helper independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct pre-fanned-terminal-shim-vs-terminal-helper assertions only, without adding an explicit routing shim.
3. Add explicit pre-fanned-terminal-shim-to-terminal-helper shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-to-terminal-helper parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned shim remains equivalent to both the new bridge-to-terminal-helper-independent terminal shim and terminal-helper independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-116 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 115 locked direct parity between the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent shim, the new bridge-to-terminal-helper-independent terminal shim, and terminal-helper independent dispatch, but direct parity between that newest terminal-helper shim and pre-fanned independent dispatch remained asserted only transitively.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct terminal-helper-shim-vs-pre-fanned assertions only, without adding an explicit routing shim.
3. Add explicit terminal-helper-shim-to-pre-fanned-independent shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-to-pre-fanned parity implementation-linked under refactors while making this direct route invariant explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper shim remains equivalent to both the new bridge-to-pre-fanned-independent terminal shim and pre-fanned independent dispatch across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-117 - 2026-02-17

- Decision:
Add explicit bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest terminal-helper bridge and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 116 locked direct parity between the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent shim and pre-fanned independent dispatch, but the newly introduced deepest terminal-helper route hop was still exercised only indirectly through the routed pre-fanned shim.

- Alternatives considered:
1. Keep current routing and rely on transitive parity through existing assertions.
2. Add direct assertions only, without adding an explicit routing shim for the new hop.
3. Add explicit deepest bridge-to-terminal-helper shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the newest route hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the bridge-to-pre-fanned-independent-via-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent-to-terminal-helper-independent-to-pre-fanned-independent shim remains equivalent to both the new deepest bridge-to-terminal-helper-independent shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-118 - 2026-02-17

- Decision:
Add explicit bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest pre-fanned bridge shim and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 117 locked direct parity for the deepest terminal-helper bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next terminal-helper-to-pre-fanned alternation hop remained implicit because that deepest terminal-helper bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit deepest terminal-helper-to-pre-fanned bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the deepest terminal-helper bridge remains equivalent to both the new deepest pre-fanned bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-131 - 2026-02-17

- Decision:
Add `MergeConflictProjection` and `KnowledgeStore.query_merge_conflict_projection_as_of(merge_results_by_tx, tx_id)` so replay streams can be queried directly for tx-cutoff conflict signature/code count projections without caller-local reduction logic.

- Context:
Iteration 130 exposed deterministic relation lifecycle signatures, but merge conflict projections still required ad hoc filtering/reduction in callers whenever replay streams needed an as-of conflict view.

- Alternatives considered:
1. Keep using `MergeResult.stream_conflict_summary` directly with caller-local filtering.
2. Add another `MergeResult` reducer overload and keep tx-cutoff logic external.
3. Add a small typed `KnowledgeStore` query API that consumes `(tx_id, MergeResult)` replay tuples and returns first-class signature/code projection outputs.

- Why chosen:
Option 3 is the smallest behavior-level addition that introduces a deterministic tx-cutoff conflict query surface while reusing existing stream reducers and preserving one-shot iterable compatibility.

- Risks accepted:
Replay callers must provide deterministic tx annotations (`merge_results_by_tx`) for each merge result; incorrect caller-provided tx tags can yield incorrect cutoff projections.

- Follow-up verification needed:
If replay metadata expands beyond tx cutoffs, keep projection ordering/count determinism and preserve checkpoint-resumed permutation equivalence for any added filters.

### DEC-130 - 2026-02-17

- Decision:
Add `RelationLifecycleSignatureProjection` and `KnowledgeStore.query_relation_lifecycle_signatures_as_of(tx_id, valid_at, revision_id=None)` so lifecycle as-of results are available as stable ordered relation state signatures split by active/pending buckets.

- Context:
Iteration 129 exposed active/pending relation lifecycle objects in one query, but deterministic replay assertions still required callers/tests to derive relation signatures manually when comparing lifecycle state snapshots across checkpoint-resumed permutation streams.

- Alternatives considered:
1. Keep `query_relation_lifecycle_as_of` only and build signatures in callers.
2. Add a flattened signature list without lifecycle bucket separation.
3. Add a dedicated lifecycle-signature projection API that keeps active/pending buckets explicit and deterministic.

- Why chosen:
Option 3 is the smallest behavior-level extension that provides a first-class deterministic signature view while preserving existing lifecycle query semantics and revision-filter behavior.

- Risks accepted:
Adds one more query/projection type to the public API surface; future lifecycle dimensions (for example relation tombstones) must be added explicitly to this projection shape.

- Follow-up verification needed:
If lifecycle semantics expand, keep signature ordering and bucket boundaries deterministic across transaction cutoffs, revision filters, and checkpoint-resumed permutation replay.

### DEC-129 - 2026-02-17

- Decision:
Add a deterministic combined lifecycle query surface (`KnowledgeStore.query_relation_lifecycle_as_of`) backed by a small immutable projection type (`RelationLifecycleProjection`) so active relations and pending orphan relations are returned together for a single tx cutoff.

- Context:
Iteration 128 exposed pending relation visibility, but callers still had to issue separate queries to compose active-endpoint and pending relation lifecycle state. That split made checkpoint-resumed replay lifecycle assertions more verbose and easier to drift.

- Alternatives considered:
1. Keep separate APIs only (`query_relations_as_of` + `query_pending_relations_as_of`) and compose in callers.
2. Add another helper that only concatenates outputs without lifecycle naming.
3. Add a dedicated lifecycle projection API with explicit `active` and `pending` buckets and behavior tests for retraction transitions and checkpoint-resumed replay equivalence.

- Why chosen:
Option 3 is the smallest behavior-level addition that makes lifecycle state queryable through one deterministic API while reusing existing relation visibility semantics (`active_only=True` + pending buffer visibility).

- Risks accepted:
Introduces one more query entrypoint and projection type in the public API surface; future lifecycle modes (for example tombstones) will require explicit extension of this projection rather than implicit tuple growth.

- Follow-up verification needed:
If lifecycle semantics expand, keep `query_relation_lifecycle_as_of` deterministic across tx cutoffs and checkpoint-resumed replay, including revision-id filtering behavior.

### DEC-128 - 2026-02-17

- Decision:
Add `KnowledgeStore.query_pending_relations_as_of(tx_id, revision_id=None)` and behavior tests for pending relation visibility/promotion, and pivot runtime control away from no-op dispatch parity work.

- Context:
Iterations 125-127 repeatedly expanded deep dispatch parity shims without adding user-visible behavior. Pending orphan relations were tracked internally (`_pending_relations`) but had no deterministic query API.

- Alternatives considered:
1. Continue parity-only shim additions.
2. Add another merge-summary wrapper without changing query behavior.
3. Expose deterministic pending relation visibility with tx-cutoff + revision filtering and validate pending-to-active promotion behavior.

- Why chosen:
Option 3 adds externally observable V1 lifecycle behavior with minimal mechanism, aligns with the runtime directive pivot, and exercises real merge/relation functions in tests.

- Risks accepted:
Introduces one additional query surface on `KnowledgeStore`; callers must distinguish active relation query (`query_relations_as_of`) from pending relation query (`query_pending_relations_as_of`).

- Follow-up verification needed:
If relation-level tombstones are added later, keep pending/active query semantics deterministic across checkpoint-resumed replay and transaction cutoffs.

### DEC-127 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new next-hop deepest terminal-helper bridge hop, the immediate deepest pre-fanned bridge hop, and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 126 locked direct parity for the next-hop deepest pre-fanned bridge after the latest terminal-helper hop against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next pre-fanned-to-terminal-helper alternation hop remained implicit because that newest pre-fanned bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit next-hop deepest pre-fanned-to-terminal-helper bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the newest next-hop deepest pre-fanned bridge after the latest terminal-helper hop remains equivalent to both this new next-hop deepest terminal-helper bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-126 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new next-hop deepest pre-fanned bridge hop, the immediate deepest terminal-helper bridge hop, and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 125 locked direct parity for the next-hop deepest terminal-helper bridge after the latest pre-fanned hop against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next terminal-helper-to-pre-fanned alternation hop remained implicit because that newest terminal-helper bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit next-hop deepest terminal-helper-to-pre-fanned bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the next-hop deepest terminal-helper bridge after the latest pre-fanned hop remains equivalent to both the new next-hop deepest pre-fanned bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-125 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new next-hop deepest terminal-helper bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 124 locked direct parity for the next-hop deepest pre-fanned bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next pre-fanned-to-terminal-helper alternation hop remained implicit because that next-hop deepest pre-fanned bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit next-hop deepest pre-fanned-to-terminal-helper bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the next-hop deepest pre-fanned bridge remains equivalent to both the new next-hop deepest terminal-helper bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-124 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new next-hop deepest pre-fanned bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 123 locked direct parity for the next-hop deepest terminal-helper bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next terminal-helper-to-pre-fanned alternation hop remained implicit because that next-hop deepest terminal-helper bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit next-hop deepest terminal-helper-to-pre-fanned bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the next-hop deepest terminal-helper bridge remains equivalent to both the new next-hop deepest pre-fanned bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-123 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new next-hop deepest terminal-helper bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 122 locked direct parity for the next-hop deepest pre-fanned bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next pre-fanned-to-terminal-helper alternation hop remained implicit because that next-hop deepest pre-fanned bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit next-hop deepest pre-fanned-to-terminal-helper bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the next-hop deepest pre-fanned bridge remains equivalent to both the new next-hop deepest terminal-helper bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-122 - 2026-02-17

- Decision:
Add explicit next-hop deepest bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest pre-fanned bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 121 locked direct parity for the deepest terminal-helper bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next terminal-helper-to-pre-fanned alternation hop remained implicit because that deepest terminal-helper bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit deepest terminal-helper-to-pre-fanned bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the deepest terminal-helper bridge remains equivalent to both the new deepest pre-fanned bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-121 - 2026-02-17

- Decision:
Add explicit deepest bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest terminal-helper bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 120 locked direct parity for the deepest pre-fanned bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next pre-fanned-to-terminal-helper alternation hop remained implicit because that deepest pre-fanned bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit deepest pre-fanned-to-terminal-helper bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the deepest pre-fanned bridge remains equivalent to both the new deepest terminal-helper bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-119 - 2026-02-17

- Decision:
Add explicit deepest bridge-to-terminal-helper-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest terminal-helper bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 118 locked direct parity for the deepest pre-fanned bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next pre-fanned-to-terminal-helper alternation hop remained implicit because that deepest pre-fanned bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit deepest pre-fanned-to-terminal-helper bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the deepest pre-fanned bridge remains equivalent to both the new deepest terminal-helper bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.

### DEC-120 - 2026-02-17

- Decision:
Add explicit deepest bridge-to-pre-fanned-independent terminal shim (`MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch`) and route `MergeResult._extend_conflict_projection_counts_from_summary_chunks_via_fan_out_components_terminal_components_dispatch_independent_component_dispatch_pre_fanned_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch_pre_fanned_component_chunks_independent_component_dispatch_terminal_helper_independent_component_dispatch` through it, then extend split/permutation raw-stream parity assertions to lock direct equality between this new deepest pre-fanned bridge hop and both terminal-helper independent dispatch and pre-fanned independent dispatch under independently rechunked/permuted component streams.

- Context:
Iteration 119 locked direct parity for the deepest terminal-helper bridge against terminal-helper independent and pre-fanned independent endpoint dispatches, but the next terminal-helper-to-pre-fanned alternation hop remained implicit because that deepest terminal-helper bridge still called pre-fanned independent dispatch directly.

- Alternatives considered:
1. Keep current routing and rely on direct endpoint equality assertions without a new shim.
2. Add direct assertions only for a conceptual next hop, without adding an explicit routing shim.
3. Add explicit deepest terminal-helper-to-pre-fanned bridge shim and extend existing split/permutation parity helper assertions across materialized, one-shot, and injected-empty independently chunked component streams.

- Why chosen:
Option 3 is the smallest deterministic no-behavior-change mechanism that keeps the next deep-route alternation hop implementation-linked under refactors while making direct raw-stream parity invariants explicit in code and tests.

- Risks accepted:
Adds one extra internal no-behavior-change shim and expands focused parity assertions; internal call graph and test runtime increase slightly.

- Follow-up verification needed:
If terminal-components independent pre-fanned routing internals are refactored again, preserve explicit invariants where the deepest terminal-helper bridge remains equivalent to both the new deepest pre-fanned bridge shim and the terminal-helper/pre-fanned independent dispatch endpoints across replay-derived raw summary streams (including injected-empty and one-shot iterable paths) under split recomposition and checkpoint-resumed permutation replay.
