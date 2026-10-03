# Phase 013 golden and invariant matrix

All new goldens invoke the real `BacktestService`, using canonical Parquet datasets,
trusted catalog, replay/resampling, strategy runner, risk, broker, accounting,
analytics, and published result artifacts. Synthetic sequences remain tiny.

`E` = `tests/golden/system/test_execution_accounting_strategy.py`;
`R` = `tests/golden/system/test_risk_and_reservations.py`;
`B` = `tests/golden/system/test_research_results.py`.

| Contract / scenario | Exact test | Observable golden truth |
| --- | --- | --- |
| Master §62 next-open / phase §9 | E::test_market_next_open_artifact_and_accounting | Signal at minute1; future interval [1,2) opens120; cash1000 before Fill,878.8 after; fee1.2; quantity1. |
| Master §62 signal lookahead / phase §10 | E::test_signal_bar_limit_is_future_only | Signal low80 cannot fill BUY90; untouched next interval; first Fill [2,3),90; cash909.1; action/activation timestamp1. |
| Master §62 stop gap / phase §11 | E::test_stop_gap_and_fill_accounting_before_same_time_decision | Existing SELL90 sees next open85; adverse 1% slippage yields84.15, fee0.8415; gap true; gross loss15.85; cash1083.3085. |
| Master §62 same-minute stop/target / phase §12 | E::test_oco_ambiguity_one_settlement | High120/low80 reaches SELL110 and stop90; conservative stop90 fills once; target cancels; ambiguity true; one reservation and one trade; cash1089.1. |
| Master §62 existing stop before decision / phase §13 | E::test_stop_gap_and_fill_accounting_before_same_time_decision | on_fill observes flat position and records explicit state; same-time on_bar observes that state, flat position, updated cash and portfolio. Existing trace order also remains protected by `tests/golden/accounting/test_financial_scenarios.py::test_existing_stop_and_oco_settle_golden_before_publication`. |
| Master §62 cancellation / phase §14 | R::test_cancel_restores_risk_headroom_and_cannot_fill_later | BUY90 reserves90.9, cancel restores1000 available; equivalent future proposal baseline exposure0; only second order fills later. |
| Phase §15 risk modification | R::test_modified_quantity_is_the_only_broker_and_accounting_quantity | Requested2/commitment202 -> approved0.5/50.5; actual order, Fill and reservation use0.5/50.5; cash949.5. |
| Phase §16 rejection then continuation | R::test_rejection_has_no_financial_effect_and_run_continues | Rejected2 creates no order/position/reservation; later0.5 succeeds; exact two reason counts and one approval/rejection; cash949.5. |
| Phase §17 multi-timeframe atomicity | E::test_multiframe_atomic_indicators_and_future_execution | 1m/5m primary/15m supporting; at15 both indicators and bars fresh; one entry action; future Fill [15,16). Warmup starts before trading15. |
| Phase §18 final active order | B::test_final_active_order_preserves_sealed_portfolio_distinction | Final callback creates ACTIVE order, no future Fill; final account/reservation200 versus sealed portfolio reserved0; independent root result/bundle equality. |
| Phase §19 open final holding | B::test_open_final_position_no_liquidation_and_marked_equity | One BUY, no terminal sell/trade; quantity1, final mark110, gross unrealized10, realized0, cash899, equity1009. |
| Master §62 partial Fill / phase §20 | `tests/property/system/test_financial_invariants.py::test_partial_fill_lifecycle_exact_replay_and_unused_reservation`; existing `tests/unit/accounting/test_spot_accounting.py::test_buy_partial_fill_keeps_unused_reservation_and_only_filled_lot`, `::test_fifo_partial_exit_preserves_original_lots_gross_pnl_and_fees` | Explicit immutable Fill facts; exact filled quantity/lots, actual quote+fee reservation consumption, completion or unused-remainder cancellation, ledger replay. Broker v1 executes full remaining quantity; no partial-liquidity model or protective-child feature is invented. |

## Generated and cross-layer contract coverage

| Master / phase invariants | Exact protecting evidence |
| --- | --- |
| §§63,64,73 account, risk, Fill, lot, fee, ledger and result coherence | `tests/property/system/test_financial_invariants.py::test_generated_service_financial_risk_and_trade_reconciliation`: generated requested quantity, cap and exit price; public accounting boundary observation verifies replay/open lots/account quantity/realized consumptions/fees, callback balances, risk-approved quantity/commitment limits, Fill-only cash oracle, trade PnL and finite metrics. |
| §63 partial lifecycle/replay/cancellation | `tests/property/system/test_financial_invariants.py::test_partial_fill_lifecycle_exact_replay_and_unused_reservation`; existing `tests/property/accounting/test_accounting_invariants.py::test_generated_buy_fifo_exit_cancel_replay_and_context_identity` (FIFO exits, exact replay and duplicate Fill atomicity); `tests/unit/accounting/test_spot_accounting.py::test_dust_nonterminating_average_display_and_current_mark`. |
| §64 pending BUY, SELL non-netting, unique OCO commitment | `tests/property/risk/test_risk_properties.py::test_pending_projection_non_netting_unique_oco`, `::test_all_applicable_approval_caps`, `::test_disabled_buy_and_safe_sell`, `::test_modification_caps_context_and_fresh_identity`. Existing bounded component generators directly cover these state-space contracts without duplicating fixtures. |
| §64 stale mark-dependent authorization | `tests/unit/risk/test_snapshot_consistency.py::test_stale_future_missing_marks_remain_structured_rejections`; forgery protections in regression inventory. |
| §65 canonical monotonicity, no future strategy reads, clipping | `tests/property/system/test_market_time_invariants.py::test_generated_service_visibility_and_replay_clipping`: generated replay bounds; all callback history closes <= clock; source version retained. |
| §65 explicit gaps, duplicates, repair identity | `tests/property/market_data/test_dataset_properties.py::test_generated_gap_sets_account_for_every_expected_minute`, `::test_valid_ohlcv_mutation_changes_logical_identity`; `tests/unit/market_data/test_datasets.py::test_gap_coverage_is_explicit_and_changes_identity`. |
| §65 half-open aggregation and gapped omission | `tests/property/market_data/test_resampling_properties.py::test_complete_bucket_aggregates_exactly`, `::test_any_source_gap_suppresses_eligible_bar`, `::test_emitted_buckets_are_aligned_contained_and_accounted_for`, `::test_decimal_precision_does_not_change_volume_or_ambient_context`. |
| Strategy failure/authority/state isolation | Exact protections in regression inventory; `tests/unit/strategy/test_contracts.py::test_context_only_subscribed_value_snapshots`, `::test_preflight_requires_fresh_runner_and_warmup`; `tests/unit/research/test_contracts.py::test_catalog_mismatch_and_mutable_instance_reuse`. |
| §66 identities/permutations/root independence | Exact matrix in `013-reproducibility-evidence.md`. |

Ten new golden test functions cover eleven required service scenarios; stop-gap
and existing-stop-before-decision share one scenario and explicit assertions.
No coverage claim requires production mutable internals or a second simulator.
