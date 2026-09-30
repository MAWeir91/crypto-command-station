# Phase 007 — Reference Runtime & Deterministic Event Engine

**Status:** Ready for implementation
**Date:** 2026-09-30
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009
**Depends on:** Phase 006 accepted and published at commit `8034ac24456ffe87236011103014355c6a978cc9`

## 1. Objective

Implement the first correctness-oriented runtime/event-engine substrate for Crypto Command Station.

Phase 007 establishes:

- instance-scoped `SimulatedClock`;
- deterministic in-memory `HistoricalReplayFeed`;
- deterministic market-close batching;
- explicit market-activity-before-publication sequencing;
- atomic same-timestamp bar publication;
- constrained read-only `MarketView`;
- inspectable step-by-step reference runtime execution;
- deterministic runtime trace events and trace fingerprint;
- structural prevention of strategy-visible future bars;
- deterministic multi-product / multi-timeframe ordering;
- runtime configuration validation;
- golden, unit, property, and integration evidence.

This phase intentionally stops before order/execution semantics, accounting, risk, indicators, and the public strategy API.

---

## 2. Architecture context

The accepted runtime model is:

```text
Backtest:
Clock       SimulatedClock
Market      HistoricalReplayFeed
Broker      SimulatedBroker          # later
Execution   Historical fill model    # later
Data        Versioned canonical Coinbase data
```

Phase 007 implements only the clock, historical replay, market visibility, dispatcher, and runtime sequencing substrate.

The long-term `TradingRuntime` remains the reusable center.

---

## 3. Canonical future event order

The master engineering specification defines the eventual timestamp-T financial order:

```text
1. process market activity before T
2. evaluate existing active orders
3. create fills
4. apply accounting
5. update positions/balances
6. update portfolio
7. finalize every subscribed bar ending at T
8. publish completed bars atomically
9. update indicators
10. deliver existing-fill callbacks where required
11. run strategy decision callback
12. create intents
13. risk
14. normalize/validate
15. reserve
16. activate
17. wait for market activity after T
```

Phase 007 does **not** implement stages 2–6 or 9–16.

It must establish an event loop whose current ordering is structurally compatible with those later insertion points:

```text
clock advances to T
      |
      v
MARKET_ACTIVITY
      |
      |  Phase 008/009/010 financial processing inserts here later
      v
BARS_PUBLISHED atomically
      |
      |  indicators/fill callbacks insert here later
      v
MARKET_STATE_READY
      |
      |  Phase 011 strategy decision attaches here later
      v
next timestamp
```

Do not implement placeholder order/fill/account/risk objects merely to mimic future stages.

---

## 4. Core anti-lookahead rule

A bar ending at timestamp `T` is not strategy-visible before the publication stage at `T`.

The one-minute candle ending at `T` may be processed as market activity before publication, but `MarketView` must not expose it until the entire same-timestamp bar batch is committed.

All subscribed bars ending at `T` become visible atomically before the `MARKET_STATE_READY` boundary.

---

## 5. Owned change surface

Expected production surface:

```text
src/command_station/
    runtime/
        __init__.py
        clock.py
        events.py
        market.py
        engine.py

    market_data/
        replay.py
```

Expected tests:

```text
tests/
    unit/
        runtime/
            test_clock.py
            test_market_view.py
            test_engine.py
        market_data/
            test_replay.py

    property/
        runtime/
            test_runtime_properties.py

    integration/
        runtime/
            test_reference_runtime.py

    golden/
        runtime/
            test_event_ordering.py
```

Exact file boundaries may differ modestly if a smaller design is clearer.

Expected:

```text
pyproject.toml unchanged
uv.lock unchanged
```

---

## 6. Expected Codex routing

Follow the user's global Codex engineering organization.

Recommended routing:

- **Director — Sol / Medium:** orient, protect phase boundaries, integrate evidence, accept/reject.
- **Explorer — Luna / Low:** use when useful to map Phase 005/006 market-data contracts before implementation.
- **Back-End Engineer — Terra / Medium:** implement clock/feed/view/runtime and tests.
- **QA Engineer — Luna / Medium:** independently exercise sequencing, atomicity, replay determinism, configuration failures, and repository gates.
- **Security/Reliability Engineer — Luna / Medium:** bounded review of lookahead, authority boundaries, state isolation, invalid runtime combinations, and deterministic failure.
- **Release Engineer — Luna / Low:** publish after Director acceptance.

Security/Reliability review is required because this phase establishes the timing boundary that later controls real financial decisions.

---

## 7. No new dependencies

Use the Python standard library and existing project code.

Do not add async event frameworks, simulation frameworks, databases, queue infrastructure, or numerical libraries merely for dispatch.

No dependency changes are expected.

---

## 8. Runtime package direction

The runtime may depend on:

```text
command_station.domain
accepted market-data contracts
```

The runtime must not depend on Coinbase SDK/provider clients, historical networking, Parquet stores as execution dependencies, derived-cache filesystem stores, future strategy implementations, future broker/accounting/risk implementations, or interface layers.

`HistoricalReplayFeed` consumes already-loaded immutable datasets. It does not load them from disk itself.

---

## 9. Runtime errors

Introduce a small bounded runtime error hierarchy where useful.

Conceptually:

```text
RuntimeEngineError
InvalidRuntimeConfigurationError
RuntimeStateError
ReplayDataError
MarketPublicationError
```

Do not create a speculative large taxonomy.

---

## 10. SimulatedClock

Implement an instance-scoped mutable clock.

Conceptually:

```python
class SimulatedClock:
    @property
    def now(self) -> UtcTimestamp: ...
    def advance_to(self, timestamp: UtcTimestamp) -> None: ...
```

Requirements:

- initialized with explicit `UtcTimestamp`;
- no wall-clock calls;
- no timezone inference;
- strictly monotonic forward movement;
- backward movement rejected;
- same-time advance rejected unless an internal need is explicitly proven;
- no reset method;
- no module-level global clock;
- fresh runtime gets a fresh clock instance.

---

## 11. No RealClock yet

Do not implement `RealClock` in Phase 007.

A small read-only clock protocol may be introduced if materially useful, but only `SimulatedClock` is implemented.

---

## 12. Replay source types

`HistoricalReplayFeed` consumes immutable accepted market data:

- one or more Phase 005 `CanonicalCandleDataset` sources;
- zero or more Phase 006 `ResampledCandleDataset` sources derived from those exact canonical versions.

No Coinbase API is accessed. No filesystem is accessed. No dataset store is opened.

---

## 13. Runtime replay quality policy

For v1:

```text
canonical source quality must be VALID
```

Reject canonical source datasets with unresolved incomplete history or unsupported future quality semantics.

Likewise, any supplied derived dataset must be fully compatible with and valid for its canonical source.

The runtime must not silently step over unresolved source gaps.

---

## 14. Canonical source invariants

Each canonical replay source must be:

```text
venue = Coinbase
product_type = SPOT
timeframe = 1m
quality = VALID
```

Require one canonical dataset per product.

Reject duplicate canonical products.

Do not parse ProductId.

---

## 15. Multi-product replay interval

For Phase 007, all canonical source datasets in one `HistoricalReplayFeed` must share the same:

```text
start
end
as_of
```

Do not silently intersect or union mismatched source periods.

Backtest period selection belongs to later composition/application phases.

---

## 16. Derived-source validation

For every supplied `ResampledCandleDataset`, validate that:

- its `source_dataset_version` matches one canonical source;
- its product matches that canonical source;
- its venue/product type match;
- its `source_start`, `source_end`, and `source_as_of` match;
- its target timeframe is >1m;
- its quality is compatible with runtime replay policy;
- it contains no unresolved derived gap under the current v1 runtime policy.

Reject stale, mismatched, duplicate, one-minute, or incomplete derived streams.

---

## 17. Stream identity

Use a small immutable stream key such as:

```python
MarketStreamKey(
    product_id=ProductId(...),
    timeframe=Timeframe(...),
)
```

It must be immutable/hashable and provide stable deterministic ordering internally.

Do not derive base/quote by parsing ProductId.

---

## 18. Deterministic stream ordering

Input construction order must not affect replay results.

Use one explicit deterministic ordering for stream/bar references, for example:

```text
product_id exact text
then timeframe duration
then timeframe value as tie-break
```

Do not depend on set iteration, caller dict insertion order, object ID, or filesystem order.

---

## 19. MarketReplayBatch

`HistoricalReplayFeed` should yield immutable same-time batches.

Conceptually:

```python
MarketReplayBatch(
    timestamp=T,
    execution_intervals=(...1m candles ending T...),
    closing_bars=(...all 1m and derived bars ending T...),
)
```

Requirements:

- every execution interval is a canonical 1m candle closing at `timestamp`;
- every closing bar closes at `timestamp`;
- execution intervals also appear in closing bars as their 1m streams;
- deterministic sorting;
- no duplicate stream in one batch;
- immutable.

---

## 20. Meaning of execution_intervals

The `execution_intervals` collection is the future Phase 008 pre-publication market-activity input.

It exists so later order/fill logic can evaluate already-active orders against one-minute activity **before** newly closed bars become strategy-visible.

Phase 007 must not fill orders.

---

## 21. Feed cadence

Because v1 replay accepts complete VALID canonical one-minute datasets over a shared interval, the feed should produce one batch for every one-minute close timestamp in:

```text
(start, end]
```

For each canonical product, exactly one 1m execution interval should exist per batch.

Derived bars appear only when their full target bucket closes.

---

## 22. Feed immutability / replayability

Prefer `HistoricalReplayFeed` to be immutable and safely iterable more than once.

Iterator cursors should be local to each iteration.

Equivalent iteration over the same feed must produce equivalent batches.

---

## 23. Feed complexity

The reference implementation should remain readable but avoid obvious quadratic scans over all prior bars for every minute.

A deterministic linear merge/index progression across sorted streams is preferred.

Do not vectorize prematurely.

---

## 24. Runtime event kinds

Use a small closed trace vocabulary:

```text
RUNTIME_STARTED
CLOCK_ADVANCED
MARKET_ACTIVITY
BARS_PUBLISHED
MARKET_STATE_READY
RUNTIME_STOPPED
```

Do not create a general asynchronous event bus.

---

## 25. Event sequencing at timestamp T

For every replay batch at `T`, trace order is:

```text
CLOCK_ADVANCED(T)
MARKET_ACTIVITY(T)
BARS_PUBLISHED(T)
MARKET_STATE_READY(T)
```

Future phases insert financial/indicator/strategy work between these fixed boundaries.

---

## 26. RuntimeTraceEvent

Use an immutable event record with deterministic logical content, conceptually:

```python
RuntimeTraceEvent(
    sequence=...,
    timestamp=...,
    kind=...,
    market_refs=(...),
)
```

Do not embed mutable infrastructure objects, wall-clock creation times, or random IDs.

---

## 27. Sequence numbers

Trace sequence numbers must be strictly increasing, runtime-instance-local, deterministic, and independent of caller input ordering.

---

## 28. Trace bar references

If events refer to bars, use immutable logical references containing enough information such as:

```text
product_id
timeframe
open_time
close_time
```

Do not include filesystem paths.

---

## 29. Trace fingerprint

Compute deterministic SHA-256 over ordered logical trace content.

Include trace schema version, ordered event sequence, timestamps, kinds, and logical market/bar references.

Exclude wall-clock creation time, Python object identity, memory addresses, filesystem roots, process IDs, and random values.

Identical runtime inputs must produce identical trace fingerprints.

---

## 30. Trace is not a financial fingerprint

The Phase 007 trace fingerprint proves deterministic event/market sequencing only.

It is not the final financial backtest reproducibility fingerprint.

Later phases add orders, fills, fees, accounting, risk, strategy, and equity outcomes.

---

## 31. Market state ownership

Use an internal mutable market-state object owned by the runtime.

Expose a separate read-only `MarketView`.

Do not hand callers internal storage dictionaries/lists or mutation methods.

---

## 32. MarketView capabilities

Phase 007 may expose:

```python
latest_bar(product_id, timeframe) -> Candle | None

recent_bars(
    product_id,
    timeframe,
    limit: int,
) -> tuple[Candle, ...]

latest_price(product_id) -> Decimal | None

visible_through -> UtcTimestamp | None
```

`latest_price` should use the latest published canonical 1m close.

Do not expose unrestricted dataset access.

---

## 33. Bounded history only

`recent_bars(..., limit=N)` must require a positive integer N, return at most N already-published bars, preserve chronological order, and never query backing datasets or return unpublished/future bars.

---

## 34. Structural anti-lookahead

Do not expose methods that accept arbitrary future timestamps and directly query canonical datasets.

The simplest safe design is:

```text
MarketView contains only bars already published by the runtime.
```

Future strategy code cannot read what the view does not contain.

---

## 35. Atomic same-timestamp publication

When a batch contains multiple bars ending at `T`, publication must be all-or-nothing:

```text
validate entire closing-bar batch
      |
      v
prepare state update
      |
      v
commit all bars ending T
      |
      v
emit BARS_PUBLISHED
      |
      v
emit MARKET_STATE_READY
```

Do not expose outward state between individual same-time bar inserts.

---

## 36. Atomicity on validation failure

If any bar in a publication batch is invalid relative to runtime state:

- reject the entire batch;
- publish none of the batch;
- raise deterministic publication/runtime error;
- leave previously published state unchanged.

Tests must verify this.

---

## 37. Publication monotonicity

For each stream:

- open times strictly increase;
- close times strictly increase;
- no duplicate publication;
- no publication whose close time is before or equal to the already published close.

Equal close timestamps across different streams are expected.

---

## 38. visible_through semantics

`MarketView.visible_through` means the latest timestamp for which a complete closing-bar batch has been atomically published.

Before first publication: `None`.

After publication at T: `T`.

It must not advance merely because the clock advanced.

---

## 39. Clock vs visibility

At timestamp T during pre-publication market activity:

```text
clock.now == T
MarketView.visible_through < T
```

After atomic publication:

```text
clock.now == T
MarketView.visible_through == T
```

This is the future execution-before-strategy boundary.

---

## 40. ReferenceTradingRuntime

Implement an instance-scoped reference runtime, conceptually:

```python
ReferenceTradingRuntime(
    clock=SimulatedClock(...),
    market_feed=HistoricalReplayFeed(...),
)
```

It owns replay progression, clock advancement, MarketView state, deterministic trace, and lifecycle state.

It does not yet own broker, accounting, portfolio, risk, or strategy runner.

---

## 41. Runtime construction validation

Before execution reject invalid static configurations such as wrong clock start, missing canonical source, duplicate streams, incomplete source data, wrong derived DatasetVersion, period mismatch, product mismatch, or unsupported target streams.

Fail before midway execution where possible.

---

## 42. Clock start

Require:

```text
clock.now == replay_feed.start
```

when execution begins.

The first batch closes at `feed.start + 1 minute`.

Do not auto-rewind or overwrite caller clock state.

---

## 43. Runtime lifecycle

Use a small explicit lifecycle if useful:

```text
CREATED
RUNNING
COMPLETED
FAILED
```

Do not add pause/resume/cancel job semantics.

A runtime instance is not reset for a second independent simulation.

---

## 44. step()

Support inspectable single-step execution:

```python
step() -> RuntimeStepResult | None
```

One successful step processes exactly one replay batch.

After it:

- clock is at batch timestamp;
- batch bars are atomically published;
- trace contains the Phase 007 stages for that timestamp;
- market state is ready for later consumers.

---

## 45. run()

Provide:

```python
run() -> ReferenceRuntimeResult
```

It processes remaining batches sequentially.

If steps were already executed, run may continue from the current cursor if that contract remains deterministic.

Once completed, do not silently reset/reuse the runtime.

---

## 46. Step result

A step result may contain timestamp, execution-interval references, published-bar references, and new trace events.

Do not return future batches or mutable state handles.

---

## 47. Runtime result

At completion expose an immutable summary such as:

```text
start
end
final_clock
batch_count
published_bar_count
trace events
trace fingerprint
```

No financial metrics or fake PnL/equity.

---

## 48. Runtime failure semantics

On fatal invariant failure:

- transition to failed state;
- preserve trace emitted before failure where practical;
- do not continue replay;
- do not silently skip the bad batch.

---

## 49. No uncontrolled callbacks

Do not introduce a generic caller-supplied callback/event-bus mechanism that can mutate runtime state at arbitrary stages.

Diagnostic observation is via immutable trace/result.

Phase 011 will add the typed strategy lifecycle.

---

## 50. No strategy API yet

Do not implement Strategy, StrategyRunner, lifecycle callbacks, params/state, subscriptions, indicators, or strategy context.

`MARKET_STATE_READY` is only the deterministic insertion boundary.

---

## 51. No order/execution yet

Do not implement OrderIntent, Order, Broker, fills, activation/cancellation, or market/limit/stop execution.

Phase 008 owns these.

The only Phase 008 seam is pre-publication `MARKET_ACTIVITY` plus `execution_intervals`.

---

## 52. No accounting/risk yet

Do not implement ledger, account, reservations, positions, portfolio, RiskPolicy, or risk decisions.

---

## 53. No repository/data loading abstraction yet

Do not implement `MarketDataRepository`.

The feed receives already-loaded immutable data objects.

Runtime must not know Parquet roots, derived-cache roots, raw archives, or Coinbase clients.

---

## 54. Determinism under input permutation

Constructing a feed with source datasets in different caller order must not change replay batches, bar order, runtime trace, trace fingerprint, or final MarketView state.

---

## 55. Determinism across runtime instances

Two fresh runtime instances from logically identical inputs must produce identical batch sequences, trace sequences, trace fingerprints, and final market state.

No shared mutable state may leak between them.

---

## 56. Same-timestamp multi-timeframe example

At `01:00Z`, if BTC has closing:

```text
1m
5m
15m
30m
1h
```

all five publish in one atomic batch.

`MARKET_STATE_READY(01:00Z)` occurs only after all five are visible.

---

## 57. Same-timestamp multi-product example

At `01:00Z`, if BTC and ETH both have 1m and 1h closing bars, all relevant bars become visible before `MARKET_STATE_READY`.

Source order BTC/ETH vs ETH/BTC must not change trace/fingerprint.

---

## 58. Golden test — visibility boundary

Before first step:

```text
clock = start
MarketView has no bars
visible_through = None
```

After first batch at T:

```text
clock = T
only bars ending <= T are visible
visible_through = T
```

No later bar may appear.

---

## 59. Golden test — exact stage order

For every T assert:

```text
CLOCK_ADVANCED
MARKET_ACTIVITY
BARS_PUBLISHED
MARKET_STATE_READY
```

with strictly increasing sequence numbers.

Runtime start/stop surround replay.

---

## 60. Golden test — atomic same-time visibility

Use canonical 1m plus at least two derived timeframes that close at the same T.

Assert the single publication event includes all closing bars before `MARKET_STATE_READY`.

Prefer one multi-product scenario too.

---

## 61. Unit tests — SimulatedClock

Cover explicit initialization, forward movement, rejected backward movement, same-time policy, independent instances, and absence of reset/wall-time behavior.

---

## 62. Unit tests — HistoricalReplayFeed

Cover:

- valid single/multi-product replay;
- 1m cadence;
- derived bars only at their close;
- deterministic input-order normalization;
- duplicate canonical product rejected;
- duplicate product/timeframe stream rejected;
- incomplete canonical source rejected;
- wrong derived source version/period/product rejected;
- one-minute derived target rejected;
- repeated iteration equivalent;
- all execution intervals/bars close at batch timestamp.

---

## 63. Unit tests — MarketView

Cover:

- empty state;
- latest/recent bars;
- latest 1m price;
- missing stream;
- nonpositive limit rejected;
- chronological results;
- visible_through only after publication;
- duplicate/out-of-order publication rejection;
- atomic failure leaves prior state unchanged;
- returned tuples do not expose mutation.

---

## 64. Unit tests — Runtime

Cover:

- valid construction;
- wrong clock start rejected;
- one-batch step;
- exact event order;
- run after prefix steps;
- completed runtime cannot silently reset;
- failed runtime does not continue;
- final clock equals feed end;
- trace sequence increasing;
- deterministic trace fingerprint.

---

## 65. Property tests

Use Hypothesis meaningfully.

At minimum:

1. generated replay lengths yield strictly increasing clock timestamps and final clock=end;
2. every visible bar after a step has `close_time <= clock.now`;
3. no later-batch bar is visible early;
4. permuting source order leaves batch sequence and trace fingerprint unchanged;
5. equivalent fresh runtimes produce identical trace fingerprints;
6. generated same-time timeframe combinations appear in one publication event before `MARKET_STATE_READY`;
7. recent-bar history respects requested positive bounds and chronological order.

Keep histories small and CI-safe.

---

## 66. Integration tests

Use real canonical datasets, Phase 006 resampling, HistoricalReplayFeed, SimulatedClock, ReferenceTradingRuntime, and MarketView.

Required scenarios:

### Single product / multiple timeframes
Create 1m data, derive 5m and 15m, replay, verify atomic publication.

### Multiple products
Create two canonical products over same interval, derive supporting timeframe(s), verify source-order independence.

### Step then run
Process a prefix with `step()`, inspect view, then finish with `run()`; verify no future bars leaked.

### Deterministic rerun
Independent equivalent runtimes yield identical traces/fingerprints.

### Invalid derived source
Derived data for another canonical version is rejected before execution.

---

## 67. Golden test placement

Use:

```text
tests/golden/runtime/
```

for compact timing sequences.

Do not prematurely add fill/stop/target golden scenarios from Phase 008+.

---

## 68. Security/Reliability review

Review adversarially:

### Lookahead
- Can MarketView see a bar before publication?
- Can backing datasets leak through the view?
- Can later batches appear early?
- Does clock advancement alone expose data?

### Same-time atomicity
- Can one stream become visible before another at same T?
- Can publication failure leave partial state?
- Can caller input order alter logical publication order?

### Replay authority
- Can incomplete canonical data run?
- Can derived data from another DatasetVersion enter?
- Can provider higher-timeframe data bypass Phase 006 provenance?
- Can period/product mismatch slip through?

### Runtime isolation
- Is mutable state module-global?
- Can one runtime affect another?
- Can completed state reset/reuse accidentally?

### Determinism
- Can sets/dicts/filesystem order alter trace?
- Does trace include wall-clock/random/process-specific values?
- Are sequence numbers deterministic?

Return concrete findings/counterexamples only.

---

## 69. Import-linter considerations

Preserve existing boundaries.

A focused rule preventing direct runtime dependency on provider infrastructure may be added if it provides real enforcement without awkward package coupling.

Do not add ceremonial contracts.

---

## 70. Repository validation

Mandatory:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

GitHub Actions must pass on Python 3.13 and Python 3.14.

No dependency changes are expected.

---

## 71. Acceptance criteria

Phase 007 is accepted only when:

1. SimulatedClock is explicit and instance-scoped.
2. No wall-clock access occurs.
3. Clock moves strictly forward.
4. Replay consumes accepted in-memory datasets only.
5. No network/filesystem data access occurs in replay.
6. Canonical sources are Coinbase spot 1m.
7. Incomplete source history is rejected.
8. Derived streams match exact canonical DatasetVersion.
9. Multi-product source periods are statically compatible.
10. Duplicate streams are rejected.
11. Feed batches every canonical 1m close.
12. execution_intervals contain 1m market activity ending T.
13. closing_bars contain every accepted stream bar ending T.
14. Feed input order does not change logical output.
15. Runtime stage order is CLOCK_ADVANCED -> MARKET_ACTIVITY -> BARS_PUBLISHED -> MARKET_STATE_READY.
16. No order/fill/account/risk/strategy behavior is implemented.
17. MarketView contains only published bars.
18. Clock advancement alone does not publish bars.
19. Same-time bars publish atomically.
20. Failed publication leaves no partial mutation.
21. visible_through changes only after publication.
22. MarketView exposes bounded recent history.
23. MarketView does not expose backing datasets.
24. latest price uses latest published 1m close.
25. Runtime supports one-batch step.
26. Runtime supports deterministic run-to-completion.
27. Runtime cannot silently reset/reuse completed state.
28. Mutable runtime state is instance-scoped.
29. Trace events are immutable and sequence-numbered.
30. Trace order is deterministic.
31. Trace fingerprint is SHA-256 over deterministic logical event content.
32. Trace excludes wall-clock/random/filesystem identity.
33. Equivalent fresh runtimes have identical fingerprints.
34. Source permutations do not alter fingerprint.
35. Multi-timeframe same-T bars are all visible before MARKET_STATE_READY.
36. Multi-product same-T bars are all visible before MARKET_STATE_READY.
37. No general async event bus is introduced.
38. No arbitrary mutation callback mechanism is introduced.
39. No MarketDataRepository is introduced.
40. Runtime execution has no Parquet/raw/provider dependency.
41. No Phase 008 order/execution domain is introduced.
42. No Phase 009 accounting is introduced.
43. No Phase 010 risk is introduced.
44. No Phase 011 strategy API/indicators are introduced.
45. Unit tests cover clock/feed/view/runtime.
46. Property tests cover monotonicity/lookahead/order independence/atomicity/history bounds.
47. Integration tests cover real canonical+derived replay.
48. Golden tests cover event ordering and atomic publication.
49. Security/Reliability review PASS.
50. Independent QA PASS.
51. Ruff PASS.
52. strict mypy PASS.
53. import-linter PASS.
54. pytest PASS.
55. Python 3.13 CI PASS.
56. Python 3.14 CI PASS.

---

## 72. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- complete VALID canonical data cannot provide deterministic 1m cadence;
- Phase 006 derived bars cannot be safely tied to exact canonical DatasetVersion;
- multi-product replay requires silently intersecting mismatched periods;
- atomic publication requires exposing mutable internal state;
- safe MarketView requires full Phase 011 strategy context;
- future execution cannot insert between market activity and bar publication without redesign;
- deterministic step/run requires a general async/event-bus framework;
- trace identity requires wall-clock/random/process-specific fields;
- implementation pressure pulls order/fill/accounting/risk/strategy semantics into this phase.

---

## 73. Explicitly out of scope

Do not implement:

- OrderIntent / Order;
- SimulatedBroker;
- fill model / slippage / fees;
- order activation/cancellation;
- ledger/account/reservations;
- positions/portfolio;
- risk engine/policy;
- strategy base/runner/context;
- params/state/subscriptions;
- indicators;
- warmup trading rules;
- BacktestSpec / BacktestService;
- analytics/result persistence;
- MarketDataRepository;
- database/jobs;
- API/MCP/frontend;
- paper/live runtime;
- RealClock;
- Coinbase WebSocket;
- authenticated Coinbase trading.

---

## 74. Definition of done

Phase 007 is done when CCS has a simple, inspectable deterministic reference market-time engine:

```text
canonical 1m + exact derived bars
        |
        v
HistoricalReplayFeed
        |
        v
SimulatedClock advances to T
        |
        v
1m MARKET_ACTIVITY at T
        |
        v
all bars ending T published atomically
        |
        v
MARKET_STATE_READY
```

and a read-only MarketView can contain only data already published by the runtime.

The trace must be reproducible and source-order-independent, forming the timing oracle that Phase 008 extends with deterministic order/fill processing before bar publication.
