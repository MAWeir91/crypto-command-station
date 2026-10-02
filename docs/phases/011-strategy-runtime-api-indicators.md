# Phase 011 — Strategy Runtime, Environment-Independent API & Indicator Lifecycle

**Status:** Ready for implementation  
**Date:** 2026-10-01  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Depends on:** Phase 010 accepted and published at commit `98ad7baea7b32415df574697c611c20690b42793`

## 1. Objective

Implement the first public strategy runtime/API for Crypto Command Station.

Phase 011 establishes:

- one environment-independent strategy per reference runtime;
- immutable strategy metadata;
- typed immutable parameters;
- explicit schema-constrained serializable strategy state;
- declarative bar subscriptions;
- exactly one primary decision stream;
- deterministic warmup and trading-start semantics;
- in-memory per-run indicators;
- built-in SMA and EMA indicators;
- constrained strategy-facing market/product/account/position/portfolio/order views;
- `on_start`, `on_fill`, `on_bar`, and `on_stop`;
- deterministic callback ordering;
- deterministic strategy command creation;
- `OrderIntent` creation at runtime time;
- ProductSpec normalization after callbacks;
- Phase 010 risk authorization and Phase 009 reservation/activation through the existing runtime path;
- structured strategy action results;
- deterministic callback/action audit history;
- deterministic strategy-runtime fingerprint;
- strict anti-lookahead and environment-independence boundaries;
- unit, property, integration, golden, QA, and Security/Reliability evidence.

Phase 011 does **not** implement BacktestSpec, BacktestService, persistence, jobs, optimization, paper/live runtimes, or a strategy registry database.

## 2. Canonical event ordering

For a strategy-enabled runtime at timestamp `T`:

```text
CLOCK_ADVANCED
MARKET_ACTIVITY
existing orders evaluated
EXECUTION_PROCESSED
ACCOUNTING_APPLIED
PORTFOLIO_UPDATED
all bars ending T published atomically
BARS_PUBLISHED
indicators updated
existing-fill callbacks delivered
MARKET_STATE_READY
on_start if this is the configured strategy start and not yet started
on_bar if the primary stream closed at T
strategy commands collected
commands normalized / risk-authorized / reserved / activated
wait for future market activity
```

No strategy-created order may interact with the interval ending at `T`.

## 3. Strategy philosophy

Strategies express intent.

The platform owns:

- market truth;
- runtime time;
- ProductSpec normalization;
- risk authorization;
- reservations;
- order activation/execution;
- accounting;
- portfolio state;
- persistence later.

Strategy code must not own infrastructure or financial mutation.

## 4. Owned change surface

Expected production surface:

```text
src/command_station/
    strategy/
        __init__.py
        parameters.py
        state.py
        subscriptions.py
        indicators.py
        commands.py
        context.py
        base.py
        runner.py

    runtime/
        events.py
        engine.py
        __init__.py
```

A small strategy-facing wrapper around `MarketView` is expected.

Existing runtime/risk/accounting/execution tests may need composition updates.

Expected tests:

```text
tests/unit/strategy/
tests/property/strategy/
tests/integration/strategy/
tests/golden/strategy/
```

Expected unchanged:

```text
pyproject.toml
uv.lock
```

## 5. Expected Codex routing

Recommended:

- **Director — Sol / Medium:** enforce strategy/runtime boundary and callback ordering.
- **Explorer — Luna / Low:** only if useful to map Phase 007–010 seams.
- **Back-End — Sol or Terra / Medium:** implement strategy contracts/runner/runtime composition.
- **QA — Luna / Medium:** independently test ordering, lookahead, state, indicators, command flow.
- **Security/Reliability — Sol / Medium:** required review of authority leakage, future-data access, and bypasses.
- **Release — Luna / Low:** publish only after acceptance.

## 6. No new dependencies

Use the Python standard library and existing CCS contracts.

Do not add TA libraries, NumPy, pandas, Pydantic, event-bus frameworks, plugin systems, or sandbox packages for Phase 011.

No dependency changes are expected.

## 7. Strategy execution trust boundary

Phase 011 defines a constrained capability API.

It does **not** claim to sandbox hostile arbitrary Python code.

A strategy artifact is trusted application code that must obey ADR 0008.

The platform must not hand strategy callbacks:

- Coinbase/provider clients;
- credentials;
- filesystem/database handles;
- raw runtime object;
- broker object;
- accounting engine;
- risk engine;
- unrestricted historical repositories;
- runtime mode.

Do not add fake “sandbox” claims that Python cannot actually enforce.

## 8. Environment independence

Strategy code must not receive or branch on:

```text
backtest
paper
live
```

No runtime-mode property exists in StrategyContext.

No wall-clock API is exposed.

Runtime time is available only through a read-only strategy clock view.

The same strategy callback surface is intended for future backtest/paper/live composition.

## 9. One strategy per runtime in v1

Phase 011 supports exactly one StrategyRunner per ReferenceTradingRuntime.

Do not implement:

- multi-strategy capital attribution;
- strategy netting;
- cross-strategy order ownership;
- portfolio allocations by strategy.

Those require separate design.

## 10. Strategy identity

Introduce immutable metadata conceptually:

```python
StrategyDefinition(
    strategy_id="btc_trend",
    parameters=...,
    state_schema=...,
    subscriptions=...,
    indicators=...,
)
```

`strategy_id` is a stable human/code identifier, not a database ID.

Validate a conservative identifier grammar such as:

```text
[a-z][a-z0-9_-]*
```

Do not introduce Git/code artifact identity yet.

Phase 012/strategy registry will add code/artifact provenance.

## 11. Strategy-definition fingerprint

Compute deterministic SHA-256 over semantic definition data:

- definition schema version;
- strategy ID;
- parameter schema;
- state schema;
- subscriptions;
- indicator specs.

This fingerprint is metadata identity only.

It is **not** a substitute for strategy source/code hash.

## 12. Strategy base

Provide a deliberately small public lifecycle.

Conceptually:

```python
class Strategy:
    definition: StrategyDefinition

    def on_start(self, ctx: StrategyContext) -> None: ...
    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None: ...
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None: ...
    def on_stop(self, ctx: StrategyContext) -> None: ...
```

No additional required callbacks in v1.

Default no-op implementations are acceptable except `on_bar`, if an abstract decision callback is cleaner.

## 13. Strategy instance mutation

Runtime-owned strategy state is the authoritative mutable strategy state.

Strategies must not rely on arbitrary mutable module globals or hidden process-local state.

Do not attempt unsafe runtime monkey-patching to “prove” Python code has no globals.

Provide explicit state APIs and test/document them as the supported state mechanism.

## 14. Parameter schema

Implement typed parameter specs.

V1 types:

```text
IntParam
DecimalParam
FloatParam
BoolParam
ChoiceParam
```

Do not add duration/time/date parameter types unless clearly needed by tests.

Each spec has:

- name;
- optional/default semantics;
- validation bounds/choices where applicable;
- deterministic logical representation.

## 15. Parameter exactness

`DecimalParam`:

- accepts exact Decimal-compatible non-float input according to existing domain rules;
- never converts from binary float implicitly.

`FloatParam`:

- is allowed only for non-financial analytical configuration;
- requires finite float/int according to one explicit policy.

No parameter value may be NaN/infinite.

## 16. Resolved StrategyParameters

Construct an immutable fully resolved parameter object.

Requirements:

- every declared parameter resolved;
- defaults applied deterministically;
- unknown keys rejected;
- missing required keys rejected;
- values typed/validated;
- stable canonical ordering;
- deterministic fingerprint.

Parameters cannot change during a run.

## 17. Parameter immutability

Strategy callbacks receive a read-only parameter view.

Do not expose mutable dicts.

No callback may change resolved parameters.

Adaptive behavior belongs in `ctx.state`.

## 18. State schema

Introduce an explicit state schema.

A practical v1 shape:

```python
StateField(
    name=...,
    value_type=...,
    default=...,
)
```

Supported values should be deliberately bounded and canonically serializable, for example:

```text
None
bool
int
str
finite Decimal
finite float
UtcTimestamp
```

Nested arbitrary Python objects are out of scope.

## 19. StrategyState

Provide runtime-owned mutable state with schema enforcement.

Conceptually:

```python
ctx.state.get("counter")
ctx.state.set("counter", 3)
```

Requirements:

- only declared keys;
- assigned values must match declared type;
- no NaN/infinity;
- deterministic snapshots;
- deterministic fingerprint;
- no mutable container leakage.

A callback may mutate state only through this object.

## 20. Initial state

At StrategyRunner construction:

- create state from schema defaults;
- optionally accept an explicit initial-state mapping;
- validate it fully;
- resolve missing fields from defaults;
- reject unknown fields.

Do not read state from disk/database in Phase 011.

## 21. BarSubscription

Introduce immutable declaration:

```python
BarSubscription(
    product_id=ProductId(...),
    timeframe=Timeframe(...),
    primary=False,
    warmup_bars=0,
)
```

Requirements:

- unique product/timeframe stream;
- nonnegative integer warmup;
- deterministic ordering/fingerprint.

## 22. Exactly one primary stream

A strategy definition must declare exactly one primary bar subscription.

`on_bar` runs only when this stream closes.

Supporting streams never independently trigger `on_bar`.

## 23. Subscription validation against replay feed

Before execution:

- every declared subscription must exist in HistoricalReplayFeed;
- canonical 1m streams count as subscriptions;
- derived streams must come from the already-validated Phase 006/007 feed;
- no undeclared provider/dataset fetches.

Fail before runtime execution if a required stream is absent.

## 24. Strategy-visible market restriction

Strategy market access must be limited to declared subscriptions.

If the replay feed contains additional streams/products, strategy code must not gain unrestricted access to them.

`ctx.market.latest_bar(...)` and `recent_bars(...)` reject undeclared streams.

This prevents accidental hidden-data dependencies.

## 25. ProductSpec access

Strategy context should expose ProductSpec for subscribed/tradable products through a read-only strategy market/product view.

Do not expose SpotAccountSpec itself merely to obtain ProductSpec.

ProductSpec comes from the accepted financial runtime composition.

## 26. Primary callback semantics

At timestamp `T`, when the primary stream closes:

1. all subscribed bars ending at T have already been published;
2. all indicators affected by bars ending T have updated;
3. existing fills at T have already been accounted;
4. all `on_fill` callbacks for existing fills have run;
5. strategy receives the primary `Candle`;
6. supporting-stream latest values at T are visible.

Product/source iteration order must not change callback-visible state.

## 27. Strategy trading start

StrategyRunner accepts explicit:

```text
trading_start: UtcTimestamp
```

Phase 011 does not choose it from a BacktestSpec.

Require:

- within replay interval;
- exactly one replay batch timestamp;
- a primary-stream bar closes at that timestamp.

Phase 012 will supply this value from experiment composition.

## 28. Warmup semantics

Replay data before `trading_start` is warmup.

During warmup:

- market state publishes normally;
- accounting/portfolio update normally;
- indicator state updates;
- no strategy callback runs;
- no strategy order command may exist.

At `trading_start`, after publication/indicator update:

```text
on_start
then on_bar(primary bar at trading_start)
```

No trade can occur before `trading_start`.

## 29. Warmup sufficiency

Before runtime execution, prove the replay feed contains enough source bars at or before trading_start for:

- each subscription's `warmup_bars`;
- each indicator's readiness requirement.

If not:

```text
InvalidRuntimeConfigurationError
```

Do not silently start with partially warmed indicator state.

## 30. on_start

`on_start` runs exactly once.

It runs:

- at trading_start;
- after current market bars and indicators are ready;
- before the first `on_bar`.

Order commands may be submitted from `on_start`.

Those orders activate at trading_start and are eligible only for future 1m market activity.

## 31. on_fill

For fills created at timestamp T:

- accounting and portfolio update first;
- bars ending T publish;
- indicators update;
- then `on_fill` runs;
- fill callbacks ordered by ascending FillId.

`on_fill` sees:

- updated position/account/portfolio state;
- market state through T;
- indicators through T.

In Phase 011, `on_fill` may update strategy state but **may not submit/cancel orders**.

Protective-order-on-fill automation is deferred.

This restriction keeps the v1 canonical callback/intent pipeline unambiguous.

## 32. on_bar

`on_bar` is the v1 strategy decision callback.

It may:

- read context;
- update strategy state;
- submit/cancel strategy order commands.

It runs once per primary-stream close after trading_start.

It never runs for supporting-only closes.

## 33. on_stop

`on_stop` runs exactly once on normal runtime completion.

It receives final immutable views and mutable strategy state.

It may update state for final diagnostics but may not submit/cancel orders because no future market activity is guaranteed.

Do not add `on_error` in Phase 011.

## 34. Callback failure

An exception escaping a strategy callback is fatal to the runtime.

Required:

- runtime transitions to FAILED;
- no later callback executes;
- no queued command from the failed callback is activated;
- existing financial truth remains preserved;
- callback audit evidence up to failure remains inspectable.

Do not swallow strategy exceptions as warnings.

## 35. StrategyClockView

Expose only:

```python
ctx.clock.now
```

No `advance_to`.

No wall-clock access.

No timezone inference.

## 36. StrategyMarketView

Wrap the runtime MarketView.

Expose only declared-subscription data:

```python
latest_bar(product_id, timeframe)
recent_bars(product_id, timeframe, limit)
latest_price(product_id)  # only if 1m subscribed
product_spec(product_id)
visible_through
```

No backing dataset/repository access.

## 37. Account/position/portfolio views

Context may expose:

```text
ctx.account
ctx.positions
ctx.portfolio
```

using existing immutable Phase 009 views.

Do not expose SpotAccountingEngine.

`ctx.portfolio` may be `None` only before the first portfolio snapshot; after trading_start warmup validation normally provides a current snapshot.

## 38. Risk visibility

Do not expose mutable RiskEngine.

A small read-only view may expose prior RiskDecision results attributable to strategy commands.

Strategy code does not call RiskEngine directly.

## 39. Order read view

Expose immutable strategy-attributed orders and prior action results.

Do not expose SimulatedBroker.

One strategy exists in v1, so all runtime strategy-created orders are attributed to that runner.

Manual external order activation is prohibited when a StrategyRunner is attached.

## 40. Strategy order command capability

`ctx.orders` queues commands; it does not execute them immediately inside `on_bar`.

Useful methods:

```python
market(...)
limit(...)
stop_market(...)
oco_limit_stop(...)
cancel(order_id)
cancel_oco(group_id)
```

All command IDs are deterministic StrategyRunner-local monotonic values.

## 41. StrategyCommandId

Use:

```text
StrategyCommandId(1..)
```

No UUID/random/global counter.

## 42. Order command creation

Order-entry helpers create immutable `OrderIntent` values with:

```text
created_at = ctx.clock.now
```

Strategy code does not choose an earlier creation timestamp.

This structurally protects temporal eligibility.

## 43. Base quantity only

Reuse Phase 008 BaseQuantity semantics.

Strategy order helpers use explicit base quantity.

Do not add quote-sized orders in Phase 011.

## 44. MARKET BUY funding cap

Phase 009/010 require explicit quote reservation capacity for gap-capable BUYs.

Therefore strategy MARKET BUY command must include exact:

```text
max_quote_reservation
```

SELL MARKET must not include one.

## 45. STOP_MARKET BUY funding cap

BUY STOP_MARKET requires exact:

```text
max_quote_reservation
```

SELL STOP_MARKET must not include one.

## 46. LIMIT funding

BUY LIMIT does not accept strategy-supplied quote cap; Phase 009 derives it from normalized limit + fee.

SELL LIMIT uses base reservation.

## 47. OCO commands

Expose narrow LIMIT + STOP_MARKET OCO matching Phase 008 constraints.

BUY OCO requires one shared max quote reservation.

SELL OCO does not.

No automatic parent/child bracket creation.

## 48. Cancellation commands

Strategy may queue cancellation in `on_bar`.

Cancellation itself does not require new risk authorization.

Use the existing runtime cancellation APIs and reservation release behavior.

A strategy may cancel only orders attributed to its runner.

## 49. Command processing boundary

All commands successfully queued during `on_start` or `on_bar` are processed only **after that callback returns successfully**.

If callback raises:

```text
discard that callback's uncommitted commands
```

Do not partially activate commands from a failed callback.

## 50. Command order

Within one callback, process commands in StrategyCommandId order.

Across callbacks at the same timestamp:

```text
on_start commands first
then on_bar commands
```

Phase 011 on_fill emits no commands.

## 51. Command pipeline

For each entry command:

```text
Strategy OrderIntent
    |
    v
lookup exact ProductSpec
    |
    v
normalize_order_intent
    |
    v
Phase 010 runtime risk authorization
    |
    v
Phase 009 reservation
    |
    v
Phase 008 broker activation
```

Do not duplicate risk/accounting/execution logic inside strategy package.

## 52. Risk rejection is not strategy failure

If Phase 010 returns REJECT:

- runtime remains healthy;
- no order/reservation exists;
- command result records the RiskDecision;
- strategy can inspect the result on a later callback.

Do not raise merely because risk rejected an intent.

## 53. StrategyActionResult

Record immutable result per processed command.

At minimum:

```text
command_id
timestamp
command kind
status
RiskDecision | None
order IDs
cancellation result where applicable
```

Useful statuses:

```text
ACTIVATED
REJECTED
CANCELLED
```

Structural invalid command/normalization errors are strategy contract failures and may fail the runtime.

## 54. Current-callback result visibility

A command result becomes visible only after callback processing finishes.

The callback that queued the command does not synchronously receive an activated Order or risk result.

This keeps callback evaluation deterministic and side-effect ordering explicit.

## 55. Indicator philosophy

Initial indicators are per-run in-memory state only.

No persistent indicator cache.

No database/Parquet indicator artifacts.

No third-party TA library.

## 56. IndicatorSpec

Introduce immutable indicator specs with:

```text
name
source product/timeframe
kind
period
```

V1 built-ins:

```text
SMA
EMA
```

Source stream must be a declared subscription.

Names unique within a strategy.

## 57. Indicator numeric domain

Indicator values are analytical, not financial truth.

V1 built-ins may use finite Python `float`.

Requirements:

- explicit Decimal-price -> float conversion only inside indicator engine;
- nonfinite output forbidden;
- indicator values never directly mutate financial state;
- order quantities/prices still require exact Phase 008 values.

## 58. SMA semantics

For period N:

```text
ready after N source bars
value = arithmetic mean of the last N close prices
```

Use a deterministic algorithm such as `math.fsum`.

Do not read future bars.

## 59. EMA semantics

For period N:

- collect first N close prices;
- seed EMA from their SMA;
- thereafter update with:

```text
alpha = 2 / (N + 1)
ema = alpha * close + (1 - alpha) * prior_ema
```

Use one documented deterministic float algorithm.

EMA not ready before N source bars.

## 60. Indicator update timing

For timestamp T:

1. all bars ending T publish atomically;
2. update each affected indicator exactly once from its source bar;
3. expose new values to fill callbacks;
4. expose new values to primary `on_bar`.

Indicator update order must not affect final values.

Sort specs deterministically.

## 61. IndicatorView

Expose read-only:

```python
ctx.indicators.value("name") -> float | None
ctx.indicators.ready("name") -> bool
ctx.indicators.updated_at("name") -> UtcTimestamp | None
```

Unknown indicator name is an explicit error.

No mutation methods.

## 62. Custom analytical logic

A strategy may compute custom logic from bounded:

```python
ctx.market.recent_bars(...)
```

Phase 011 does not introduce arbitrary custom stateful indicator plugins.

That avoids hidden uncontrolled state.

## 63. Indicator anti-lookahead

At any callback time T:

- an indicator may contain only source bars with `close_time <= T`;
- before bar publication at T it must not contain the bar ending T;
- after indicator update at T callbacks may see it.

Property/golden tests must prove this.

## 64. Callback audit events

Maintain immutable StrategyRunner audit history.

Suggested kinds:

```text
STRATEGY_STARTED
FILL_CALLBACK
BAR_CALLBACK
COMMAND_PROCESSED
STRATEGY_STOPPED
```

Include deterministic sequence, timestamp, relevant FillId/bar reference/command ID, and state fingerprint after callback where useful.

Do not include wall-clock time.

## 65. Strategy-runtime fingerprint

Compute SHA-256 over semantic per-run strategy evidence such as:

```text
strategy runtime schema version
StrategyDefinition fingerprint
resolved parameter fingerprint
trading_start
indicator specs
callback audit history
command/action results
final strategy state fingerprint
```

Exclude:

- wall-clock;
- process ID;
- filesystem;
- random values.

This is **not** the final backtest reproducibility identity because Phase 012 still needs strategy code/artifact hash and dataset/run composition.

## 66. Runtime trace extension

Extend the closed runtime trace only where useful to prove ordering.

Recommended new kinds:

```text
INDICATORS_UPDATED
FILL_CALLBACKS_PROCESSED
STRATEGY_STARTED
STRATEGY_DECISION_PROCESSED
STRATEGY_COMMANDS_PROCESSED
STRATEGY_STOPPED
```

When strategy is attached at T, target ordering is:

```text
BARS_PUBLISHED
INDICATORS_UPDATED
FILL_CALLBACKS_PROCESSED
MARKET_STATE_READY
[STRATEGY_STARTED once at trading_start]
STRATEGY_DECISION_PROCESSED if primary closes
STRATEGY_COMMANDS_PROCESSED
```

Existing non-strategy runtimes should preserve prior observable semantics as closely as possible.

## 67. Fill callback ordering

Sort current-batch Fill facts by FillId.

Call `on_fill` once per Fill.

All fill callbacks at T occur before `on_bar(T)`.

Strategy state mutations from earlier fill callbacks are visible to later fill callbacks and `on_bar`.

## 68. Same-timestamp multi-stream atomicity

If primary and supporting streams close at T:

- publish all first;
- update all relevant indicators;
- only then call strategy.

No subscription iteration order may expose partial same-time state.

## 69. No callback on supporting-only close

If supporting bars close at T but primary does not:

- market publishes;
- indicators update;
- fill callbacks may run if fills exist;
- no `on_bar`.

This must be tested.

## 70. Product iteration determinism

Equivalent feed/source/subscription input permutations must not change:

- indicator results;
- callback sequence;
- command IDs;
- action results;
- final strategy state;
- strategy-runtime fingerprint;
- financial outcome.

## 71. Strategy-enabled runtime composition

Extend ReferenceTradingRuntime with:

```python
strategy_runner: StrategyRunner | None
```

If present, require:

- accounting exists;
- risk exists;
- runner is fresh;
- subscriptions compatible with feed/account ProductSpecs;
- trading_start/warmup valid.

Market-only and financial-without-strategy runtimes remain supported.

## 72. Strategy runner freshness

A StrategyRunner attached to a fresh runtime must have:

- no callback history;
- no command history/results;
- initial state only;
- pristine indicator state;
- not started/stopped.

No reuse across independent runs.

## 73. Manual runtime activation while strategy attached

When `strategy_runner` is present, direct external runtime order activation must be rejected.

All new strategy-runtime orders must be strategy-command-attributed.

The runner/runtime may use a private/internal activation path that still passes Phase 010 risk.

This prevents unattributed financial activity in a strategy run.

## 74. Preexisting orders

A strategy-enabled runtime must begin with:

```text
fresh broker
no orders
no fills
no reservations
fresh risk
fresh accounting
```

consistent with prior phases.

No fill may occur before the strategy starts.

## 75. StrategyContext snapshot semantics

Construct a fresh context snapshot for each callback.

It must contain state/views corresponding to the exact callback timestamp.

Do not retain a mutable live MarketView or Portfolio object across callbacks.

`ctx.state` is the deliberate mutable exception owned by StrategyRunner.

## 76. Context no-backdoor rule

StrategyContext must not expose properties such as:

```text
runtime
broker
accounting_engine
risk_engine
feed
dataset
repository
coinbase
mode
```

Tests should assert the intended public surface.

## 77. Strategy-access failures

Attempts to read undeclared stream/product should raise a strategy access/contract error.

Do not silently return data from a non-subscribed stream.

Missing subscribed history may return `None`/empty only according to the documented MarketView semantics.

## 78. Callback command permissions

V1 permissions:

```text
on_start -> entry/cancel commands allowed
on_bar   -> entry/cancel commands allowed
on_fill  -> no commands
on_stop  -> no commands
```

Attempting a forbidden command is a strategy contract failure.

## 79. Strategy callback result purity

Callbacks return normally; command effects are committed afterward.

Do not expose partially processed risk/order state to a still-running callback.

This provides transactional callback semantics for command submission.

## 80. Runtime failure atomicity for strategy commands

Before processing one callback's command batch:

- validate command shapes/products;
- normalize all entry intents where practical.

If one command has a structural strategy error, prefer failing before any command in that callback batch mutates broker/accounting.

Risk rejection is not structural failure and may produce a normal result.

If fully atomic multi-command risk/activation cannot be guaranteed without redesigning Phase 010/009, stop/escalate rather than pretending.

A documented sequential command-commit policy is acceptable only if QA/Director review explicitly validates it.

## 81. Unit tests — parameters/state

Cover:

- each parameter type;
- defaults;
- missing/unknown keys;
- immutable resolved params;
- stable fingerprints;
- Decimal exactness;
- finite float enforcement;
- state schema/defaults;
- valid state mutation;
- invalid key/type rejection;
- deterministic state fingerprint;
- no mutable container leakage.

## 82. Unit tests — subscriptions/definition

Cover:

- unique streams;
- exactly one primary;
- warmup validation;
- indicator source must be subscribed;
- unique indicator names;
- stable definition fingerprint;
- invalid strategy ID.

## 83. Unit tests — indicators

Cover:

- SMA documented examples;
- EMA seed/update examples;
- not-ready behavior;
- source-specific updates;
- no update on unrelated stream;
- deterministic input order;
- no nonfinite values;
- IndicatorView read-only behavior.

## 84. Unit tests — context/commands

Cover:

- clock read-only;
- subscribed market access;
- undeclared stream rejection;
- ProductSpec read access;
- immutable account/positions/portfolio views;
- no runtime/broker/accounting/risk engine exposure;
- command IDs deterministic;
- created_at forced to runtime now;
- BUY market/stop cap requirements;
- LIMIT cap rules;
- OCO cap rules;
- on_fill/on_stop command prohibition.

## 85. Unit tests — runner lifecycle

Cover:

- warmup no callbacks;
- on_start once;
- on_bar only primary closes;
- supporting-only no on_bar;
- fill callbacks sorted by FillId;
- fills before on_bar;
- on_stop once normal completion;
- callback exception fails runner/runtime;
- commands from failed callback discarded;
- fresh-run state isolation;
- final runner fingerprint deterministic.

## 86. Property tests

Use Hypothesis meaningfully.

At minimum properties equivalent to:

1. no callback occurs before trading_start;
2. no `on_bar` occurs without a primary close;
3. every callback market bar has `close_time <= callback timestamp`;
4. indicator source state never includes a future bar;
5. same-time subscribed bars are all visible before primary callback;
6. feed/subscription input permutation leaves callback/fingerprint outcome unchanged;
7. command created at T always has `created_at == T`;
8. strategy-created order activated at T never fills from interval ending T;
9. state schema rejects generated wrong-type assignments;
10. resolved parameters are immutable and fingerprint-stable;
11. equivalent fresh strategy runtimes produce identical callback/action/final-state fingerprints;
12. supporting-only indicator updates do not trigger strategy decisions.

## 87. Golden scenario — same-time multi-timeframe decision

Subscribe:

```text
BTC 1m
BTC 5m primary
BTC 15m supporting
```

At a timestamp where all three close:

- all bars visible;
- indicators updated;
- on_bar called once for 5m primary;
- callback can read fresh 15m supporting bar.

## 88. Golden scenario — signal-bar order anti-lookahead

Primary bar closes at T.

`on_bar` submits a limit/market order.

Assert:

- intent created_at = T;
- risk/reservation/activation occurs after callback;
- order cannot use any price from interval ending T;
- first eligible execution is future Phase 008 market activity.

Mandatory.

## 89. Golden scenario — fill callback before next decision

Existing strategy order fills during one-minute market activity ending T.

Assert exact financial sequence:

```text
Fill
accounting
portfolio
bar publication
indicator update
on_fill
MARKET_STATE_READY
on_bar if primary closes
```

In `on_fill`, strategy sees updated position/portfolio.

In `on_bar`, strategy state changes made by `on_fill` are visible.

## 90. Golden scenario — supporting-only close

Supporting stream closes at T; primary does not.

Assert:

- bar published;
- relevant indicator updates;
- no on_bar;
- no strategy decision/order command.

## 91. Golden scenario — warmup

Provide N warmup bars before trading_start.

Assert:

- indicators calculate during warmup;
- no callback/order before trading_start;
- on_start then first on_bar at trading_start;
- first decision sees ready indicators.

## 92. Golden scenario — risk rejection

Strategy submits BUY that Phase 010 rejects.

Assert:

- callback succeeds;
- command result = REJECTED with RiskDecision;
- no broker Order;
- no accounting reservation;
- runtime continues to later callbacks.

## 93. Integration tests

Use real canonical + derived datasets, HistoricalReplayFeed, SimulatedClock, SpotAccountingEngine, RiskEngine, SimulatedBroker, StrategyRunner, and ReferenceTradingRuntime.

Required:

- end-to-end strategy BUY through normalization/risk/reservation/activation/future fill/accounting;
- risk rejection then later callback continuation;
- fill-driven state visible in on_fill and later on_bar;
- multi-timeframe indicator update/decision scheduling;
- strategy cancellation releasing reservation;
- manual activation bypass blocked;
- deterministic fresh rerun across strategy + financial state.

## 94. Security/Reliability review

Adversarially verify:

- no provider/credential/runtime/broker/accounting/risk-engine leakage;
- no unrestricted dataset/repository access;
- no runtime mode exposure;
- no undeclared/future bar access;
- indicators update only after publication;
- no signal-bar fill for strategy-created order;
- no hidden arbitrary state container leakage;
- no command from forbidden callbacks;
- no manual activation bypass;
- no spoofed created_at;
- strategy cannot cancel unattributed orders;
- failed callback cannot partially activate queued commands;
- deterministic command/callback/fingerprint behavior.

Return concrete findings/counterexamples only.

## 95. Independent QA

QA independently executes:

- parameters/state;
- subscriptions/primary;
- warmup;
- SMA/EMA lifecycle;
- same-time atomic visibility;
- fill-before-decision ordering;
- signal-bar anti-lookahead;
- risk rejection continuation;
- command permission rules;
- context restrictions;
- manual activation bypass;
- state isolation;
- deterministic rerun;
- full repository gates.

## 96. Import boundaries

Strategy core may depend on:

```text
command_station.domain
immutable execution values
immutable accounting views
immutable risk decision values
runtime MarketView/clock read contracts
```

Strategy must not depend on provider clients, raw archives, Parquet stores, persistence, API/MCP/CLI, or paper/live infrastructure.

Execution/accounting/risk must not import strategy.

Runtime may orchestrate strategy.

## 97. Repository validation

Run:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

CI must pass Python 3.13 and 3.14.

No dependency changes expected.

## 98. Acceptance criteria

Phase 011 is accepted only when:

1. StrategyDefinition is immutable/fingerprinted.
2. Exactly one primary subscription required.
3. Subscription streams are validated against replay feed.
4. Strategy market access is limited to declared subscriptions.
5. ProductSpec is available without provider/accounting-engine exposure.
6. Parameters are typed/validated/immutable.
7. Decimal parameters remain exact.
8. State schema is explicit.
9. StrategyState is schema-constrained and serializable.
10. State fingerprints deterministically.
11. StrategyRunner owns strategy state/lifecycle.
12. One strategy per runtime in v1.
13. Trading start is explicit.
14. Warmup produces no callbacks/orders.
15. Warmup sufficiency is validated before run.
16. on_start runs exactly once.
17. on_start precedes first on_bar.
18. on_fill runs once per current Fill in FillId order.
19. on_fill sees accounted position/portfolio state.
20. on_fill cannot submit/cancel orders in v1.
21. on_bar only runs on primary close.
22. supporting-only close cannot trigger on_bar.
23. on_stop runs once on normal completion.
24. on_stop cannot submit/cancel orders.
25. callback exception fails runtime.
26. failed callback does not activate queued commands.
27. all same-time subscribed bars visible before decision.
28. indicators update after publication and before callbacks.
29. indicator source cannot be undeclared.
30. SMA semantics documented/tested.
31. EMA semantics documented/tested.
32. indicators are per-run memory only.
33. indicator values contain no future bars.
34. StrategyContext exposes runtime time read-only.
35. StrategyContext exposes no runtime mode.
36. StrategyContext exposes no broker/accounting/risk engine/provider.
37. strategy commands receive deterministic IDs.
38. order intent created_at forced to runtime time.
39. base-quantity semantics preserved.
40. BUY market/stop quote cap semantics preserved.
41. OCO shared-cap semantics preserved.
42. commands process only after successful callback return.
43. risk rejection is a normal command result.
44. strategy command path uses real ProductSpec normalization.
45. strategy command path uses Phase 010 RiskEngine.
46. strategy command path uses Phase 009 reservation/accounting boundary.
47. strategy command path uses Phase 008 broker.
48. strategy-created orders cannot interact with signal-bar activity.
49. strategy may cancel only attributed orders.
50. manual runtime order activation is blocked while strategy attached.
51. strategy callback/action history is deterministic.
52. strategy-runtime fingerprint is deterministic.
53. fingerprint excludes wall-clock/process/filesystem/random identity.
54. equivalent fresh strategy runs produce identical strategy evidence and financial outcomes.
55. no arbitrary custom stateful indicator plugin.
56. no persistent indicator cache.
57. no strategy artifact registry/database.
58. no BacktestSpec/BacktestService.
59. no Phase 012 analytics/result persistence.
60. no paper/live behavior.
61. unit/property/integration/golden evidence complete.
62. Security/Reliability PASS.
63. Independent QA PASS.
64. Ruff PASS.
65. strict mypy PASS.
66. import-linter PASS.
67. pytest PASS.
68. Python 3.13 CI PASS.
69. Python 3.14 CI PASS.

## 99. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- subscription validation requires a new MarketDataRepository;
- warmup cannot be proven from accepted replay inputs;
- strategy context must expose runtime/broker/accounting/risk engines;
- same-time supporting bars cannot be visible before primary callback;
- indicators require future/unpublished data;
- safe command batching requires changing Phase 008–010 financial semantics;
- callback failure cannot prevent partial command mutation;
- strategy-created orders cannot preserve Phase 008 temporal rule;
- environment independence would require pretending arbitrary Python is sandboxed;
- scope starts pulling in Phase 012 BacktestSpec/services/artifact persistence.

## 100. Explicitly out of scope

Do not implement:

- BacktestSpec/BacktestService/BacktestResult;
- strategy artifact/code hash registry;
- StrategyInstance persistence;
- multi-strategy runtime;
- strategy allocation caps;
- persistent strategy state;
- telemetry persistence;
- structured logging framework;
- arbitrary custom stateful indicator plugins;
- third-party TA library;
- persistent/shared indicator cache;
- automatic protective parent/child orchestration;
- quote-sized orders;
- batch backtests/jobs;
- database;
- API/MCP/frontend;
- paper/live trading;
- authenticated Coinbase trading.

## 101. Definition of done

Phase 011 is done when the sealed deterministic runtime can host one environment-independent strategy with a constrained API:

```text
warmup market replay
      |
      v
published subscribed bars
      |
      v
per-run indicators
      |
      v
on_start / on_fill / primary on_bar
      |
      v
explicit strategy state + typed params
      |
      v
StrategyOrderCommand
      |
      v
OrderIntent at runtime time
      |
      v
ProductSpec normalization
      |
      v
Phase 010 RiskEngine
      |
      v
Phase 009 reservation
      |
      v
Phase 008 broker activation
      |
      v
future market activity only
```

with no strategy access to provider infrastructure, unrestricted historical data, mutable financial internals, runtime mode, or future bars.
