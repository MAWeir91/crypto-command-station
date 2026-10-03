# Phase 013 regression inventory

Baseline: sealed Phase012 `de09476701f609f36e14accbfa87f00ea3a51937`.
Authority: master §§61–66,73; ADRs 0001–0009. Existing regressions retain
their original homes. A historical evidence closure is distinguished from a
proven production defect; no speculative bug attribution is made here.

| Material class | Historical evidence / protecting test |
| --- | --- |
| Import timestamps, ordering, completed boundary | Phase004 implementation `5701294`; `tests/unit/market_data/test_historical.py::test_completed_boundary_and_normalization_errors`, `::test_normalization_is_order_independent_and_import_excludes_overall_end`, `::test_planner_clamps_near_datetime_max_without_overflow` |
| Resume, overlap and conflicting raw evidence | Phase004 evidence closure `3004838`; `tests/integration/market_data/test_historical_import.py::test_resume_after_failure_and_overlap_deduplication`, `::test_overlap_conflict_preserves_both_raw_pages` |
| Public-provider cursor and bounded retry | `tests/unit/market_data/coinbase/test_products.py::test_catalog_adapter_rejects_repeated_cursor_and_translates_sdk_errors`, `::test_catalog_adapter_rejects_excessive_fresh_cursor_pages`; `tests/unit/market_data/coinbase/test_candles.py::test_public_client_retries_rate_limit_and_caps_attempts`, `::test_public_candle_client_does_not_retry_malformed_response`, `::test_public_client_does_not_retry_regular_http_error_or_allow_authenticated_sdk`. These are direct existing boundary protections, not newly attributed Phase013 defects. |
| Immutable canonical dataset publication / corruption | `tests/integration/market_data/test_canonical_dataset_store.py::test_publish_load_partition_idempotence_and_corruption`, `::test_manifest_rejects_extra_fields_and_reordered_artifacts`; Phase005A property closure `63614c2`, `tests/property/market_data/test_dataset_properties.py::test_exact_decimal_values_round_trip_through_parquet` |
| Phase008 runtime integration evidence gaps | Test-only closure `25f62bf`; `tests/integration/execution/test_runtime_execution.py::test_runtime_activation_after_step_fills_only_next_open_before_publication`, `::test_runtime_limit_persists_until_a_later_interval_touches`, `::test_runtime_oco_ambiguity_fills_conservatively_before_publication`, `::test_runtime_cancellation_prevents_later_limit_fill_and_is_fingerprinted` |
| Future cancellation and partial-fill chronology | Phase009 `673cb74`; `tests/unit/accounting/test_lifecycle_repair.py::test_future_normal_or_partial_cancellation_has_no_accounting_mutation`, `::test_cancellation_cannot_precede_applied_partial_fill`; `tests/unit/accounting/test_phase009_security_boundary.py::test_future_external_cancellation_rejected_before_execution_or_release` |
| OCO dual-peer settlement | Phase009 `673cb74`; `tests/unit/accounting/test_lifecycle_repair.py::test_oco_second_peer_cannot_settle_in_successive_batch`; `tests/unit/accounting/test_phase009_security_boundary.py::test_accounting_rejects_two_oco_peer_fills_atomically` |
| Test package collection | Collection fixes `8ed6a19`, `ed37f5b`; retained `__init__.py` markers in golden/integration/property and accounting packages. All new system/regression packages also contain markers. Protection is successful normal pytest collection, not a test which duplicates pytest's loader. |
| Risk snapshot-integrity forgery | Phase010 `98ad7ba`; `tests/unit/risk/test_snapshot_consistency.py::test_forged_portfolio_value_rejects_before_history_mutation`, `::test_authorization_revalidates_snapshot_before_history_mutation`, `::test_unfilled_commitment_cannot_be_removed_with_balances` |
| Callback command atomicity / attribution | Phase011 `390dc8a`; `tests/integration/strategy/test_runtime_strategy.py::test_bad_batch_does_not_activate_earlier_valid_command`, `::test_cancel_releases_reservation_and_manual_mutation_blocked`, `::test_forbidden_callback_command_fails_and_preserves_accounted_truth`; service failure is additionally protected by `tests/regression/test_failure_atomicity.py::test_callback_exception_publishes_no_completed_result` |
| Forged / incomplete artifact manifests | Phase012 `066777a`, documented manifest repair in `012-security-evidence.md`; `tests/unit/research/test_artifacts.py::test_incomplete_or_duplicate_manifest_cannot_bypass_verification`, `::test_artifact_record_rejects_wrong_types_versions_and_values`, `::test_manifest_rejects_wrong_types_versions_and_identity` |
| All bundle members, hardlinks, publication lock | New `tests/regression/test_corruption_regressions.py::test_every_corrupted_bundle_member_rejects_reuse_without_overwrite` (all nine members), `::test_hardlinked_bundle_member_rejects_reuse`, `::test_existing_publication_lock_fails_without_touching_bundle_or_lock` |
| Service failure before completed publication | New `tests/regression/test_failure_atomicity.py::test_pre_runtime_failure_publishes_nothing` (dataset, artifact reference, parameters), `::test_insufficient_warmup_fails_before_financial_mutation`, `::test_accounting_invariant_failure_publishes_nothing`, `::test_artifact_serialization_failure_publishes_nothing_and_preserves_unrelated_stage` |

## Inventory classification

The rows below correspond in order to the protecting-test table above. Severity
was not recorded for these historical findings; it is not inferred here. Where
no repair commit is established by the retained evidence, that limitation is
explicit. Evidence closures are not relabeled as production repairs.

| Material class | Phase | Repair / evidence commit | Severity | Status |
| --- | --- | --- | --- | --- |
| Import timestamps, ordering, completed boundary | 004 | `5701294` implementation | Not recorded | COVERED |
| Resume, overlap and conflicting raw evidence | 004 | `3004838` evidence closure | Not recorded | COVERED |
| Public-provider cursor and bounded retry | 003–004 | Not attributed; direct existing boundary protections | Not recorded | COVERED |
| Immutable canonical dataset publication / corruption | 005–005A | `63614c2` property evidence closure; original repair not attributed | Not recorded | COVERED |
| Runtime integration evidence gaps | 008A | `25f62bf` test-only closure | Not recorded | COVERED |
| Future cancellation and partial-fill chronology | 009 | `673cb74` repair | Not recorded | COVERED |
| OCO dual-peer settlement | 009 | `673cb74` repair | Not recorded | COVERED |
| Test package collection | 009–010 | `8ed6a19`, `ed37f5b` collection fixes | Not recorded | COVERED |
| Risk snapshot-integrity forgery | 010 | `98ad7ba` accepted phase release | Not recorded | COVERED |
| Callback command atomicity / attribution | 011 | `390dc8a` accepted phase implementation | Not recorded | COVERED |
| Forged / incomplete artifact manifests | 012 | `066777a` manifest repair | Not recorded | COVERED |
| All bundle members, hardlinks, publication lock | 013 | No production repair; new evidence only | Not recorded | GAP CLOSED IN 013 |
| Service failure before completed publication | 013 | No production repair; new evidence only | Not recorded | GAP CLOSED IN 013 |

Independent QA executed all named protecting tests as part of the full suite:
508 collected, 504 passed, four platform-dependent symlink checks skipped.
The skipped checks are not treated as established symlink evidence.

No new production defect was demonstrated by the implementation readiness suite.
Initial failures were incorrect test construction/expectations, corrected to the
accepted contracts: explicit canonical dataset construction; scalar artifact
quantity cells; complete rejection reason counts; sufficient supporting-indicator
warmup; actual quote/fee consumption from capped BUY reservations; and preservation
of `AccountingInvariantError` as the cause of `RuntimeEngineError`.

This inventory identifies test homes. Independent QA owns execution of the
historical protecting tests and repository-wide collection/regression gates.
