# Phase 012 — First End-to-End Backtest Service, Analytics & Immutable Artifacts

**Status:** Ready for implementation after Phase 011 is merged/sealed on `main`  
**Date:** 2026-10-01  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Predecessor:** Phase 011 implementation accepted at PR #1 head `647e9263788e305318ea414a5211fb2eb6fdf09d`

> **Baseline gate:** Do not implement Phase 012 from Phase 010 `main`. Phase 011 must first be merged into `main`, and the clean Phase 012 workspace must be based on the resulting `main` commit containing accepted Phase 011. If PR #1 remains open/unmerged, stop at this gate.

## 1. Objective

Implement the first complete research/backtest use case for Crypto Command Station.

Phase 012 establishes:

- immutable serializable `BacktestSpec`;
- exact dataset-version selection;
- minimal immutable strategy-artifact provenance;
- strategy artifact resolution through an injected catalog;
- canonical dataset resolution through the existing immutable dataset store;
- deterministic local derivation of required higher timeframes;
- bounded historical replay through the requested test end;
- fresh construction of clock/broker/accounting/risk/strategy/runtime for every run;
- synchronous `BacktestService.run(...)`;
- immutable `BacktestResult`;
- complete run provenance;
- deterministic backtest/run/result fingerprints;
- first documented analytics;
- FIFO-lot-based closed-trade records;
- return/drawdown/risk-adjusted/trade/cost/exposure metrics;
- execution and risk summaries;
- immutable content-hashed local artifact bundles;
- deterministic Parquet/JSON research artifacts;
- idempotent publication of an identical deterministic run;
- fatal detection when an identical run identity produces different artifacts;
- unit, property, integration, golden, QA, and Security/Reliability evidence.

Phase 012 must **compose** the accepted Phase 007–011 runtime. It must not implement another simulator.

## 2. Architecture

Canonical application flow:

```text
BacktestSpec
    |
    v
resolve StrategyArtifact
    |
    v
resolve exact Canonical DatasetVersion(s)
    |
    v
derive required higher timeframes locally
    |
    v
construct fresh:
  SimulatedClock
  SimulatedBroker
  SpotAccountingEngine
  RiskEngine
  StrategyRunner
  ReferenceTradingRuntime
    |
    v
run deterministic simulation
    |
    v
collect immutable runtime outcomes
    |
    v
analytics + summaries
    |
    v
immutable research artifact bundle
    |
    v
BacktestResult
```

Research orchestration must not duplicate fill, accounting, risk, or strategy scheduling semantics.

## 3. Phase 011 merge gate

Before Phase 012 production work:

1. verify PR #1 is merged;
2. verify clean `main` contains accepted Phase 011;
3. record the exact merged Phase 011 predecessor SHA;
4. use a clean workspace based on that `main`.

Do not build Phase 012 on the stale Phase 010 checkout, and do not disturb unrelated user workspaces.

## 4. Owned change surface

Expected production surface:

```text
src/command_station/
    research/
        __init__.py
        specs.py
        strategy_artifacts.py
        analytics.py
        trades.py
        summaries.py
        artifacts.py
        backtests.py

    market_data/
        replay.py   # narrow backwards-compatible replay-end support only if required
```

`BacktestService` is the application/use-case service even if implemented under `research/`.

Expected tests:

```text
tests/unit/research/
tests/property/research/
tests/integration/research/
tests/golden/research/
```

Expected unchanged unless a demonstrated need is accepted:

```text
pyproject.toml
uv.lock
```

PyArrow already exists and may be used.

## 5. No new dependencies

Use the standard library, existing PyArrow, and existing CCS code.

Do not add pandas, NumPy, scipy, Optuna, database tooling, job queues, or web frameworks.

## 6. BacktestSpec

Introduce an immutable canonical experiment input, conceptually:

```python
BacktestSpec(
    strategy_artifact=StrategyArtifactRef(...),
    parameters=(...),
    datasets=(BacktestDatasetRef(...), ...),
    period=BacktestPeriod(...),
    account=SpotAccountSpec(...),
    risk_policy=RiskPolicy(...),
    execution=ReferenceExecutionSpec(...),
    random_seed=0,
)
```

Anything materially affecting results must be included directly or represented by immutable versioned identity.

## 7. BacktestPeriod

Use:

```python
BacktestPeriod(
    trading_start=UtcTimestamp(...),
    replay_end=UtcTimestamp(...),
)
```

Semantics:

- source datasets may begin before `trading_start` for warmup;
- the strategy first runs at `trading_start`;
- replay includes the final one-minute market interval ending at `replay_end`;
- the runtime may therefore deliver a primary callback at `replay_end`;
- an order created at that final boundary may remain active because there is no future market activity.

Require:

```text
dataset.start < trading_start <= replay_end <= dataset.end
```

Both timestamps are UTC minute boundaries.

## 8. Dataset selection

Introduce:

```python
BacktestDatasetRef(
    product_id=ProductId(...),
    dataset_version=DatasetVersion(...),
)
```

Requirements:

- exactly one canonical 1m dataset per account product;
- unique product IDs;
- deterministic ProductId ordering;
- no provider “latest” lookup;
- no path-based identity.

DatasetVersion is the market-data identity.

## 9. Dataset resolution

Resolve dataset refs through injected immutable storage, initially the existing `LocalCanonicalDatasetStore` or a small resolver protocol around it.

Require loaded data to match:

- requested DatasetVersion;
- requested product;
- Coinbase SPOT 1m;
- `DatasetQuality.VALID`;
- enough coverage for replay_end;
- HistoricalReplayFeed period/as-of compatibility.

No network calls.

## 10. ProductSpec provenance

`SpotAccountSpec` remains the execution/accounting ProductSpec authority.

If a dataset carries `product_spec_provenance`, its fingerprint must match the corresponding account ProductSpec fingerprint.

If provenance is absent, record that absence in result provenance; never invent it.

BacktestResult always records the ProductSpec fingerprints actually used.

## 11. Higher-timeframe resolution

Inspect the Phase 011 strategy definition.

For every subscription above 1m:

```text
resample_canonical_dataset(source_dataset, timeframe)
```

locally.

Do not mix in Coinbase higher-timeframe candles.

A verified derived cache may be used only as an optimization; identity remains tied to canonical DatasetVersion + resampler version + derived result identity.

## 12. Bounded replay

The run must stop at `BacktestPeriod.replay_end`.

Prefer a backwards-compatible extension such as:

```python
HistoricalReplayFeed(
    canonical_sources,
    derived_sources,
    replay_end=...,
)
```

Rules:

- omitted replay_end preserves existing Phase 007 behavior;
- source dataset identities do not change;
- feed start remains canonical dataset start for warmup;
- batches after replay_end are omitted;
- no candle content is rewritten;
- no synthetic DatasetVersion is created just to clip a run.

Regression-test legacy replay behavior.

## 13. StrategyArtifactDescriptor

Introduce minimal immutable code provenance, conceptually:

```python
StrategyArtifactDescriptor(
    artifact_name=...,
    strategy_id=...,
    semantic_version=...,
    git_commit=...,
    code_sha256=...,
    module=...,
    qualname=...,
    definition_fingerprint=...,
)
```

Require explicit canonical fields, exact SHA-256 code hash, explicit Git identity, and deterministic descriptor fingerprint.

Do not use file timestamps or Python object repr.

## 14. No magical source hashing

Do not make reproducibility depend on fragile `inspect.getsource(...)`.

The descriptor receives explicit code identity.

A future StrategyService may produce/register descriptors. Phase 012 consumes and validates them.

## 15. Strategy artifact catalog

Provide a small injected reference catalog:

```python
catalog.register(descriptor, factory)
catalog.resolve(ref)
```

The factory is runtime infrastructure and is not serialized into BacktestSpec.

On resolution:

1. construct a fresh Strategy;
2. verify strategy ID;
3. verify exact StrategyDefinition fingerprint;
4. fail on mismatch.

No registry database.

## 16. Fresh-instance rule

Every run creates fresh:

```text
Strategy
StrategyRunner
StrategyState
IndicatorEngine
SimulatedClock
SimulatedBroker
SpotAccountingEngine
RiskEngine
ReferenceTradingRuntime
```

No mutable run object may be reused across runs.

## 17. Parameters

BacktestSpec stores concrete parameter values canonically.

Pass them through the real Phase 011 `StrategyParameters` validation.

Unknown/missing/invalid values fail before runtime execution.

Do not duplicate parameter semantics in research code.

## 18. Account/risk/execution configuration

BacktestSpec directly contains:

```text
SpotAccountSpec
RiskPolicy
ReferenceExecutionSpec
```

Canonical serialization must preserve all semantic fields, not just fingerprints.

Result provenance records the fingerprints as well.

## 19. Random seed

BacktestSpec includes exact integer `random_seed`; bool is rejected.

It participates in spec/run identity.

Current reference strategy/runtime exposes no random capability, so Phase 012 does not create stochastic behavior merely to consume it. Future stochastic components must explicitly consume the seed through a controlled capability.

## 20. BacktestSpec serialization

Implement canonical:

```text
to_dict()
fingerprint
```

Requirements:

- exact Decimal text;
- exact UTC text;
- schema/model versions;
- canonical ordering;
- no absolute paths;
- no repr/memory addresses;
- canonical JSON.

Equivalent logical specs fingerprint identically.

## 21. EngineIdentity

BacktestService requires explicit immutable engine provenance:

```python
EngineIdentity(
    git_commit=...,
    package_version=...,
    reference_engine_version=...,
)
```

Include it in run/result identity.

Do not infer or pretend the working tree is clean.

## 22. BacktestRunId

Derive deterministic run identity from:

```text
BacktestSpec fingerprint
EngineIdentity fingerprint
```

No UUIDs.

Same logical spec on the same engine identity => same run ID.

## 23. BacktestService

Provide synchronous:

```python
result = service.run(spec)
```

The service only orchestrates:

1. validate spec;
2. resolve strategy artifact;
3. resolve datasets;
4. derive supporting timeframes;
5. construct fresh runtime components;
6. run reference simulation;
7. collect immutable outcomes;
8. derive analytics/summaries;
9. publish artifact bundle;
10. return BacktestResult.

No SQL, jobs, interfaces, or alternate simulator.

## 24. Runtime composition

Construct the sealed components from spec:

```text
SimulatedClock(dataset.start)
SimulatedBroker(execution spec)
SpotAccountingEngine(account spec, execution spec)
RiskEngine(risk policy)
fresh Strategy
StrategyRunner(trading_start=period.trading_start, parameters=...)
HistoricalReplayFeed(..., replay_end=period.replay_end)
ReferenceTradingRuntime
```

Preserve all Phase 007–011 ordering.

## 25. Runtime failures

Fatal runtime/strategy/accounting errors fail the backtest.

Do not publish a completed BacktestResult for a failed runtime.

A normal risk rejection remains a successful backtest outcome.

## 26. Result collection

After successful runtime completion collect immutable:

- orders/fills/execution events;
- ledger/lots/lot consumptions/portfolio history;
- final account/positions/portfolio;
- risk decisions;
- strategy commands/action results/audit;
- runtime trace;
- all component fingerprints.

Research code must not replay or “correct” accounting.

## 27. ClosedLotTrade

Derive one analytics record per Phase 009 LotConsumption:

```python
ClosedLotTrade(
    product_id=...,
    lot_id=...,
    consumption_id=...,
    entry_fill_id=... | None,
    exit_fill_id=...,
    source=INITIAL_HOLDING | BUY_FILL,
    quantity=...,
    entry_time=...,
    exit_time=...,
    entry_price=...,
    exit_price=...,
    gross_pnl=...,
    hold_seconds=...,
)
```

This is a FIFO lot-realization segment, **not** a higher-level logical trade abstraction.

Join LotConsumption to AcquisitionLot and Fill identities; do not recompute conflicting accounting truth.

## 28. Closed-trade reconciliation

Require exact:

```text
sum ClosedLotTrade quantity per sell fill
==
sum LotConsumption quantity per sell fill
```

and exact PnL equality with LotConsumption evidence.

## 29. Analytics numeric policy

Financial amounts remain Decimal.

Analytical ratios/statistics may use finite float.

Decimal-to-float conversion is explicit and analytics-only.

No NaN/Infinity may appear in public metrics. Undefined ratios use `None`.

## 30. Analytics window

Use PortfolioSnapshots with:

```text
trading_start <= timestamp <= replay_end
```

Warmup snapshots before trading_start are excluded.

Require at least one analytics-window snapshot.

## 31. Equity metrics

Define exact:

```text
starting_equity = first analytics snapshot total_equity
ending_equity   = last analytics snapshot total_equity
net_profit      = ending_equity - starting_equity
```

If starting_equity > 0:

```text
total_return = ending / starting - 1
```

Otherwise total_return is `None`.

## 32. CAGR

For positive starting equity and positive elapsed duration:

```text
years = elapsed_seconds / (365 * 24 * 60 * 60)
CAGR = (ending / starting) ** (1 / years) - 1
```

Crypto uses 365 days, not 252 trading days.

Return `None` when undefined.

## 33. Snapshot returns

For consecutive analytics snapshots:

```text
r_t = equity_t / equity_(t-1) - 1
```

Use simple returns.

Phase 012 has no post-start external cash flows.

If prior equity <= 0, risk-adjusted metrics are undefined.

## 34. Sharpe

Use one-minute simple returns, zero risk-free rate, and:

```text
A = 365 * 24 * 60
Sharpe = mean(r) / pstdev(r) * sqrt(A)
```

Return `None` for fewer than two returns or zero standard deviation.

Use standard-library deterministic math/statistics.

## 35. Sortino

Use:

```text
downside_deviation = sqrt(mean(min(r, 0) ** 2))
Sortino = mean(r) / downside_deviation * sqrt(A)
```

Return `None` when downside deviation is zero or returns are insufficient.

## 36. Drawdowns

For each snapshot:

```text
drawdown = equity / running_peak - 1
```

A drawdown episode begins below the prior peak and ends on recovery to that peak or at test end.

For each episode retain:

- peak time;
- trough time;
- recovery/end time;
- deepest drawdown;
- duration seconds.

Report:

```text
max_drawdown
average_drawdown
longest_drawdown_seconds
```

No drawdown => 0 / 0 / 0.

## 37. Calmar

If CAGR exists and `abs(max_drawdown) > 0`:

```text
Calmar = CAGR / abs(max_drawdown)
```

Otherwise `None`.

## 38. Trade metrics

Using ClosedLotTrade segments, report at least:

```text
closed_trade_count
win_rate
gross_expectancy
profit_factor
average_winner
median_winner
average_loser
median_loser
max_win_streak
max_loss_streak
average_hold_seconds
median_hold_seconds
gross_closed_trade_pnl
```

Document explicitly that these are FIFO lot-segment metrics.

## 39. Win/loss rules

```text
WIN  gross_pnl > 0
LOSS gross_pnl < 0
FLAT gross_pnl == 0
```

Win rate = wins / all closed lot segments. Flat segments remain in the denominator.

No trades => `None`.

## 40. Profit factor

```text
gross_wins = sum(positive pnl)
gross_losses = abs(sum(negative pnl))
profit_factor = gross_wins / gross_losses
```

If gross_losses == 0, return `None`, not infinity.

## 41. Streaks and hold duration

Order trades by:

```text
exit_time, consumption_id
```

Flat breaks both streaks.

Hold seconds = exit_time - entry_time and must be nonnegative.

For INITIAL_HOLDING, the account-start lot timestamp is the entry timestamp; do not invent historical acquisition dates.

## 42. Fees

Exact:

```text
total_fees = sum(Fill.fee_amount)
```

Require equality with final PortfolioSnapshot.fees_to_date and accounting evidence.

Mismatch is fatal.

## 43. Slippage

Exact:

```text
total_slippage_cost =
    sum(Fill.slippage_per_base * Fill.base_quantity)
```

Use Phase 008 Fill provenance; do not recalculate from candles.

## 44. Exposure metrics

From analytics-window portfolio snapshots:

```text
in_market <=> marked_asset_value > 0
time_in_market = in_market_snapshot_count / snapshot_count
max_capital_deployed = max(marked_asset_value)
```

Average capital deployed may be analytical float.

For each product:

```text
product exposure = actual quantity * current mark
```

Report max and average product exposure deterministically.

## 45. BacktestMetrics

Create immutable documented metrics.

No field may expose NaN/Infinity.

All undefined behavior must be explicitly tested.

## 46. RiskSummary

Derive from recorded RiskDecision history only:

```text
decision_count
approve_count
modified_count
reject_count
reason_counts
```

Sort reason counts deterministically.

Do not re-run risk.

## 47. ExecutionSummary

Derive from broker facts only:

```text
order_count
fill_count
active_order_count
filled_order_count
cancelled_order_count
gap_fill_count
ambiguous_fill_count
total_fees
total_slippage_cost
```

Optional counts by order type/resolution are acceptable.

## 48. Result provenance

BacktestResult must preserve:

- run ID;
- spec fingerprint;
- EngineIdentity;
- StrategyArtifact descriptor/fingerprint/code hash;
- strategy definition fingerprint;
- resolved parameter fingerprint;
- DatasetVersions and candle hashes;
- dataset ProductSpec provenance where available;
- derived timeframe identities/resampler version;
- ProductSpec fingerprints;
- account fingerprint;
- risk policy fingerprint;
- execution spec fingerprint;
- random seed;
- runtime trace fingerprint;
- execution fingerprint;
- accounting fingerprint;
- risk fingerprint;
- strategy-runtime fingerprint.

## 49. BacktestResult

Immutable, conceptually:

```python
BacktestResult(
    run_id=...,
    spec_fingerprint=...,
    provenance=...,
    metrics=...,
    risk_summary=...,
    execution_summary=...,
    final_account=...,
    final_positions=...,
    final_portfolio=...,
    artifact_manifest=...,
    result_fingerprint=...,
)
```

Do not store mutable engine objects.

## 50. Result fingerprint

Compute deterministic semantic result identity from:

```text
result schema version
run ID
spec fingerprint
resolved provenance identities
runtime/execution/accounting/risk/strategy fingerprints
metrics
risk summary
execution summary
final financial views
```

Exclude absolute artifact path, publication time, PID, temp paths, and random DB IDs.

Artifact manifest has a separate fingerprint.

## 51. Reproducibility invariant

Same:

```text
BacktestSpec
EngineIdentity
StrategyArtifact
immutable datasets
```

must yield identical:

- run ID;
- result fingerprint;
- orders/fills;
- component fingerprints;
- metrics;
- logical artifact contents.

Any difference is fatal.

## 52. LocalBacktestArtifactStore

Implement safe immutable local publication using an explicit absolute root Path.

Use:

```text
staging -> verify -> atomic publish
```

similar to the canonical dataset store.

Reject symlink/path traversal hazards.

## 53. Artifact layout

Use fixed Phase 012 bundle:

```text
artifacts/backtests/<run-id>/
    spec.json
    summary.json
    orders.parquet
    fills.parquet
    trades.parquet
    equity.parquet
    risk_decisions.parquet
    strategy_actions.parquet
    manifest.json
```

No database metadata, telemetry, or optimization artifacts.

## 54. Artifact schema rules

All artifacts have explicit schema versions.

Require:

- deterministic columns;
- deterministic row ordering;
- exact financial Decimal representation;
- unambiguous UTC;
- stable enum strings;
- no pickle/repr;
- finite analytical floats only.

## 55. orders.parquet

Preserve final order facts including identities, product/side/type, requested/activated/filled/remaining quantity, prices, timestamps, status, cancellation, OCO, and ProductSpec fingerprint.

Sort by OrderId.

## 56. fills.parquet

Preserve all material Phase 008 Fill provenance.

Sort by FillId.

Do not drop reference price, fill price, slippage, fee, resolution, ambiguity, gap, activation, market interval, execution timestamp, or spec/model fingerprints.

## 57. trades.parquet

Persist ClosedLotTrade segments sorted by:

```text
exit_time, consumption_id
```

Preserve lot/fill identities.

## 58. equity.parquet

One row per analytics-window PortfolioSnapshot.

At least:

```text
timestamp
cash_total
cash_reserved
cash_available
marked_asset_value
total_equity
gross_realized_pnl
gross_unrealized_pnl
fees_to_date
```

Product exposure may use an explicitly documented deterministic long or wide schema.

## 59. risk_decisions.parquet

Persist Phase 010 decision evidence in RiskDecisionId order.

Do not reconstruct by rerunning risk.

## 60. strategy_actions.parquet

Persist Phase 011 StrategyActionResult values by StrategyCommandId.

Include command ID, timestamp, kind, status, risk decision ID if any, and order IDs.

## 61. JSON artifacts

`spec.json` is canonical BacktestSpec JSON.

`summary.json` contains run/result identity, provenance, metrics, summaries, and final financial summary.

Canonical JSON only.

## 62. ArtifactManifest

Record:

```text
artifact schema version
run ID
result fingerprint
relative path
row count where applicable
byte size
sha256
logical schema/version
```

Sort by relative path.

No absolute root.

Manifest fingerprint is SHA-256 over semantic manifest content and does not recursively include its own file hash.

## 63. Idempotent immutable publication

If run directory is absent:

```text
stage -> verify -> publish atomically
```

If already present:

- verify manifest;
- verify all file hashes/schemas;
- verify same result fingerprint;
- reuse only if identical.

Same run ID with different content => `BacktestReproducibilityError`.

Never overwrite.

## 64. Partial publication failure

Clean only the owned staging directory.

Never damage a prior published run or unrelated user files.

## 65. Success semantics

A successful backtest may legitimately contain:

- risk rejections;
- unfilled orders;
- active final orders;
- zero trades.

Fatal invariant/runtime/artifact failure means no completed BacktestResult.

## 66. No forced liquidation/cancellation

At replay end:

- do not fabricate a final sell;
- do not auto-cancel active orders;
- mark remaining holdings at final canonical 1m close;
- record active orders/reservations honestly.

## 67. Golden scenarios

### Complete round trip
Tiny BTC dataset; strategy buys after warmup, fills in future activity, later sells, ends flat. Assert exact orders/fills/ledger/trade/metrics/result/artifacts.

### No-trade baseline
Zero commands; complete equity/artifact result.

### Risk rejection
Rejected entry remains a normal completed run with risk evidence and no rejected-order financial mutation.

### Open final position
No forced liquidation; final equity includes unrealized position.

### Final unfilled order
Order created at final callback remains active with no fabricated future fill.

## 68. Unit tests

Cover:

- spec/period/dataset refs;
- canonical serialization/fingerprints;
- EngineIdentity;
- StrategyArtifact validation;
- artifact-catalog definition mismatch;
- every documented metric formula and undefined case;
- trade derivation/reconciliation;
- summaries;
- artifact schemas;
- path/symlink protections;
- canonical JSON;
- file hashes;
- staging cleanup;
- idempotent publication;
- collision failure.

## 69. Property tests

At minimum:

1. logical spec ordering does not change fingerprint;
2. metric output contains no NaN/Infinity;
3. max drawdown is never positive;
4. time in market is within [0,1];
5. ClosedLotTrade quantity/PnL reconcile to LotConsumption;
6. fee metric equals Fill fee sum;
7. slippage is exact nonnegative Decimal;
8. artifact row permutations canonicalize identically;
9. fresh identical runs produce same result fingerprint;
10. same run identity cannot silently publish different content;
11. changing a material spec input changes spec/run identity;
12. warmup snapshots never enter analytics.

## 70. Integration tests

Use real:

- LocalCanonicalDatasetStore;
- strategy artifact catalog;
- Phase 011 strategy;
- local resampling;
- HistoricalReplayFeed;
- full financial runtime;
- LocalBacktestArtifactStore;
- BacktestService.

Required:

- single-product round trip;
- multi-timeframe derived subscription;
- multi-product deterministic ordering;
- risk rejection;
- deterministic fresh rerun;
- immutable artifact reuse;
- reproducibility collision detection.

## 71. Security/Reliability review

Adversarially test:

### Dataset authority
Exact DatasetVersion, product match, corrupt store rejection, no provider fallback.

### Strategy provenance
Descriptor/factory definition mismatch, code identity mismatch, no mutable strategy reuse.

### Runtime composition
No bypass around StrategyRunner/risk/accounting; no research-created Fill/ledger/PnL semantics.

### Analytics
Warmup exclusion, no NaN/Infinity, fee/slippage reconciliation, no implicit liquidation, no accounting truth rewrite.

### Artifact filesystem
Traversal, symlink, partial publish, immutable overwrite, forged manifest, file-hash mismatch, absolute-path leakage, same-run collision.

### Determinism
No wall-clock/process/path identity, ordering invariance, repeated-run equivalence.

Return concrete findings only.

## 72. Independent QA

QA independently executes:

- spec/provenance;
- dataset mismatch;
- strategy artifact mismatch;
- timeframe derivation;
- fresh runtime composition;
- round-trip/no-trade/rejection/open-position/final-order cases;
- metric fixtures;
- artifact content inspection;
- immutable/idempotent publication;
- deterministic rerun;
- collision detection;
- full repository gates.

## 73. Import boundaries

Research may depend on:

```text
domain
market_data
execution
accounting
risk
strategy
runtime
```

Lower layers must not import `command_station.research`.

Future REST/MCP/CLI invoke BacktestService rather than internals.

## 74. No database or jobs

Phase 012 is synchronous and filesystem-artifact based.

Do not introduce:

- SQLite/Postgres;
- job tables;
- workers;
- queue/cancel semantics;
- batch backtests.

Phase 014 owns batch/job semantics.

## 75. No strategy registry persistence

The strategy artifact catalog is injected/in-memory in this phase.

No database-backed StrategyDefinition/Artifact/Instance service.

## 76. Repository validation

Run:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

GitHub CI must pass Python 3.13 and 3.14 on the exact published Phase 012 commit.

No dependency changes expected.

## 77. Acceptance criteria

Phase 012 is accepted only when:

1. Phase 011 is merged/sealed first.
2. BacktestSpec is immutable/canonical.
3. Every material experiment input is represented.
4. Dataset refs use exact DatasetVersion.
5. Dataset loading is offline and identity-verified.
6. Product/dataset mismatch fails.
7. ProductSpec provenance mismatch fails when evidence exists.
8. Strategy artifact is explicit/fingerprinted/code-hashed.
9. Factory definition mismatch fails.
10. Fresh strategy/runtime components are created per run.
11. Higher timeframes are locally resampled only.
12. Replay stops at replay_end without changing source identity.
13. Legacy replay behavior remains unchanged when unbounded.
14. Warmup is preserved.
15. Phase 011 parameter validation is reused.
16. Account/risk/execution specs are reused directly.
17. random_seed is explicit.
18. EngineIdentity is explicit.
19. run ID is deterministic.
20. BacktestService contains no second simulator.
21. Fatal runtime failure creates no completed result.
22. Risk rejection remains a normal result.
23. ClosedLotTrade derives from Phase 009 evidence.
24. Closed trade quantities/PnL reconcile exactly.
25. Warmup excluded from analytics.
26. equity/return/CAGR formulas documented/tested.
27. Sharpe/Sortino/Calmar documented/tested.
28. drawdown semantics documented/tested.
29. trade metrics are explicitly FIFO lot-segment metrics.
30. profit factor never returns infinity.
31. fees reconcile exactly.
32. slippage uses Fill provenance.
33. exposure metrics derive from portfolio snapshots.
34. no public metric emits NaN/Infinity.
35. summaries derive from recorded facts only.
36. BacktestResult is immutable.
37. result provenance includes data/code/product/account/risk/execution/engine identities.
38. result fingerprint is deterministic and path/time independent.
39. no forced end liquidation.
40. no forced end cancellation.
41. final active orders are represented honestly.
42. artifact store uses safe absolute root.
43. publication uses staging/verification/atomic publish.
44. artifact paths are canonical relative paths.
45. financial Parquet fields preserve exactness.
46. JSON is canonical.
47. manifest hashes/sizes/schemas are verified.
48. manifest fingerprint deterministic.
49. identical run bundle is reused only after verification.
50. same run ID with different content fails loudly.
51. partial publish cannot corrupt existing run.
52. no database/job/batch/optimization/MCP/API/frontend/paper/live scope.
53. unit/property/integration/golden tests PASS.
54. Security/Reliability PASS.
55. Independent QA PASS.
56. Ruff PASS.
57. strict mypy PASS.
58. import-linter PASS.
59. full pytest PASS.
60. Python 3.13 CI PASS.
61. Python 3.14 CI PASS.

## 78. Stop/escalate conditions

Stop and escalate if:

- Phase 011 is still unmerged;
- period bounding requires changing accepted execution semantics;
- research begins implementing a second simulator;
- strategy code provenance cannot be explicit;
- mutable paths would replace DatasetVersion identity;
- analytics requires rewriting Phase 009 truth;
- lot segments would be mislabeled as higher-level logical trades;
- immutable safe publication cannot be achieved;
- same run identity can produce differing output without detection;
- scope begins pulling in database/jobs/batch optimization/MCP;
- a dependency addition appears necessary without accepted justification.

## 79. Explicitly out of scope

Do not implement:

- batch backtests;
- jobs;
- optimization;
- walk-forward;
- Monte Carlo;
- optimized simulator;
- DB metadata;
- persistent StrategyService;
- ComparisonService;
- ResearchSession persistence;
- MCP/REST/CLI/frontend;
- paper/live trading;
- authenticated Coinbase trading;
- forced end liquidation;
- telemetry/full diagnostic artifact modes;
- multi-strategy backtests;
- quote-sized orders;
- futures/margin/shorts.

## 80. Definition of done

Phase 012 is done when one immutable experiment spec can produce one reproducible, auditable research result:

```text
BacktestSpec
      |
      v
exact StrategyArtifact + DatasetVersion(s)
      |
      v
fresh Phase 011/010/009/008/007 composition
      |
      v
deterministic simulation
      |
      v
orders/fills/ledger/portfolio/risk/strategy evidence
      |
      v
documented analytics
      |
      v
immutable content-hashed artifacts
      |
      v
BacktestResult
```

The platform must be able to answer what data, strategy code, parameters, account/risk/execution assumptions, engine version, orders/fills/trades, metrics, and reproducibility identity produced the result.
