# Crypto Command Station — Master Engineering Specification

**Repository:** `MAWeir91/crypto-command-station`
**Product:** Crypto Command Station (CCS)
**Document status:** Foundational architecture baseline
**Version:** 0.1
**Date:** 2026-09-28

## 1. Purpose

Crypto Command Station is an all-in-one crypto algorithmic trading platform designed around one progression:

`research -> backtest -> paper trading -> live trading`

The immediate implementation objective is a correct, deterministic Coinbase spot backtesting system.

Paper trading and live trading are intentionally deferred, but the backtesting architecture must not create a dead end. The same strategy contract, trading runtime concepts, risk model, order model, accounting model, and market-data semantics should be reusable when those environments are introduced.

This document defines the product architecture and engineering contracts that guide implementation.

The repository-level `AGENTS.md` contains the non-negotiable project laws distilled from this specification.

## 2. Product vision

The long-term product is a Crypto Trade Command Station with integrated:

- Coinbase market data;
- strategy development;
- deterministic backtesting;
- research comparisons;
- optimization;
- walk-forward analysis;
- Monte Carlo and significance analysis;
- paper bot deployment;
- live Coinbase Advanced bot deployment;
- portfolio/account visibility;
- risk controls;
- order/fill inspection;
- execution diagnostics;
- analytics;
- MCP access for ChatGPT and Codex;
- a web command center.

The platform is not three applications called backtester, paper bot, and live bot.

It is one trading platform with multiple runtime configurations.

## 3. Foundational architecture principle

The central architecture is:

```text
                         INTERFACES
             +-------------+-------------+
             |             |             |
            WEB           MCP           CLI
             |             |             |
             +-------------+-------------+
                           |
                           v
                  APPLICATION SERVICES
                           |
             +-------------+-------------+
             |             |             |
          RESEARCH      STRATEGIES      DATA
             |
             v
                    TRADING RUNTIME
                           |
        +------------------+------------------+
        |                  |                  |
     STRATEGY            RISK              BROKER
        |                  |                  |
        +------------------+------------------+
                           |
                           v
                          FILL
                           |
                +----------+----------+
                |                     |
            ACCOUNTING             POSITIONS
                |                     |
                +----------+----------+
                           |
                           v
                       PORTFOLIO
                           |
                           v
                       ANALYTICS
```

The trading runtime is the reusable center.

Backtest, paper, and live modes differ primarily in injected infrastructure.

## 4. Runtime environments

### 4.1 Backtest

```text
Clock       SimulatedClock
Market      HistoricalReplayFeed
Broker      SimulatedBroker
Execution   Historical execution model
Data        Versioned Coinbase historical dataset
```

### 4.2 Paper trading — future

```text
Clock       RealClock
Market      CoinbaseLiveFeed
Broker      SimulatedBroker
Execution   Live-market simulated fill model
Data        Live Coinbase market events
```

### 4.3 Live trading — future

```text
Clock       RealClock
Market      CoinbaseLiveFeed
Broker      CoinbaseBroker
Execution   Actual Coinbase fills
Data        Live Coinbase market/account events
```

The strategy must not contain environment-specific branches.

## 5. Architectural style

The initial application is a modular monolith.

Goals:

- one repository;
- one coherent Python codebase;
- explicit module boundaries;
- deterministic domain behavior;
- separate worker processes where useful;
- no premature distributed architecture.

Do not begin with microservices, Kafka, complex RPC, or a large distributed deployment topology.

Modules should nevertheless expose boundaries clean enough that individual infrastructure responsibilities can be separated later if justified.

## 6. Initial repository structure

The intended structure is approximately:

```text
crypto-command-station/
|
|-- AGENTS.md
|-- MASTER_ENGINEERING_SPEC.md
|-- README.md
|-- pyproject.toml
|
|-- docs/
|   |-- adr/
|   |-- phases/
|   |-- domain/
|   |-- market-data/
|   |-- backtesting/
|   +-- research/
|
|-- src/
|   +-- command_station/
|       |
|       |-- domain/
|       |-- runtime/
|       |-- market_data/
|       |-- execution/
|       |-- accounting/
|       |-- risk/
|       |-- strategy/
|       |-- research/
|       |-- analytics/
|       |-- persistence/
|       |-- jobs/
|       |-- application/
|       |-- api/
|       |-- mcp/
|       +-- cli/
|
|-- strategies/
|
|-- data/
|   |-- raw/
|   |-- canonical/
|   +-- cache/
|
|-- artifacts/
|   |-- backtests/
|   |-- optimizations/
|   +-- reports/
|
+-- tests/
    |-- unit/
    |-- integration/
    |-- golden/
    |-- property/
    |-- regression/
    +-- performance/
```

This is a target boundary map, not permission to scaffold every directory before a phase needs it.

## 7. Dependency direction

Preferred dependency flow:

`interfaces -> application services -> research/runtime -> domain`

Infrastructure adapters point inward through explicit contracts.

Examples:

```text
Coinbase REST/WS
      |
      v
Coinbase adapter
      |
      v
Domain objects
```

```text
PostgreSQL
      |
      v
Repository adapter
      |
      v
Application service
```

Hard architectural expectations:

- domain code does not import web frameworks;
- domain code does not import Coinbase SDKs;
- domain code does not import persistence frameworks;
- strategy code does not access infrastructure;
- research does not implement a second simulator;
- MCP, REST, and CLI share application services.

Automated dependency enforcement should be added once the package structure is established.

## 8. Domain vocabulary

The initial domain vocabulary includes:

- Product;
- ProductSpec;
- Candle;
- MarketTrade — future/live;
- Subscription;
- StrategyArtifact;
- StrategyInstance;
- StrategyParameters;
- StrategyState;
- Signal;
- OrderIntent;
- RiskDecision;
- Order;
- Fill;
- Fee;
- AssetBalance;
- Reservation;
- FillLot;
- Position;
- Trade;
- LedgerEntry;
- Account;
- PortfolioSnapshot;
- BacktestSpec;
- BacktestResult;
- DatasetVersion;
- ExecutionSpec;
- RiskPolicy;
- RuntimeEvent.

Domain objects should prefer immutable value semantics where practical.

Infrastructure/provider response objects must not leak throughout the core.

## 9. IDs and identity

Important entities should have stable IDs.

Suggested human-readable prefixes may include:

- `DS_` dataset;
- `ST_` strategy artifact/instance;
- `BT_` backtest;
- `RS_` research session;
- `ORD_` order;
- `FILL_` fill;
- `TRD_` logical trade;
- `OPT_` optimization;
- `JOB_` application job.

UUIDv7 or another sortable globally unique representation is a reasonable underlying implementation.

Deterministic financial fingerprints must not depend on random IDs.

## 10. Time contract

All internal timestamps are:

- timezone-aware;
- UTC;
- explicit.

No naive datetimes are allowed in runtime/domain state.

Candle intervals use half-open boundaries:

`[open_time, close_time)`

Example:

`[14:00:00, 15:00:00)`

includes 14:00 through 14:59:59... and excludes 15:00.

Backtest event ordering must be based on market/event time, not wall-clock processing time.

Future live infrastructure may additionally track:

- provider event time;
- received time;
- processed time.

## 11. Coinbase boundary

Coinbase Advanced is the canonical external venue for initial market-data semantics and eventual order execution.

The v1 implementation is Coinbase spot first.

The system should model Coinbase product characteristics faithfully where data exists, including:

- `product_id`;
- product type;
- base currency;
- quote currency;
- base increment;
- quote increment;
- price increment;
- minimum size;
- maximum size;
- relevant trading status/capability flags.

A provider adapter boundary remains useful so Coinbase payload structures do not leak into domain code.

Do not prematurely add generic exchange complexity merely to claim multi-exchange support.

## 12. Coinbase product specifications

A `ProductSpec` is a versioned snapshot of known exchange constraints.

Conceptually:

```python
ProductSpec(
    venue="coinbase",
    product_id="BTC-USD",
    product_type="SPOT",
    base_currency="BTC",
    quote_currency="USD",
    base_increment=...,
    quote_increment=...,
    price_increment=...,
    min_base_size=...,
    max_base_size=...,
    min_quote_size=...,
    max_quote_size=...,
    status=...,
)
```

Product specification snapshots must not be silently overwritten when rules change.

For historical periods where the exact historical exchange constraint is unknown, the run must preserve the source/assumption rather than pretending historical certainty.

## 13. Market-data system

### 13.1 Principle

Coinbase is the external source.

The Command Station's immutable, normalized, versioned data is the research source of truth.

Backtests must not make live Coinbase historical API calls during simulation.

### 13.2 Data layers

```text
Coinbase
   |
   v
Raw archive
   |
   v
Normalization
   |
   v
Validation
   |
   v
Canonical 1m dataset
   |
   v
Derived timeframe cache
   |
   v
Historical replay
```

### 13.3 Canonical resolution

The canonical candle resolution is one minute.

Higher timeframes are built locally from the exact canonical one-minute dataset.

Initial supported derived intervals may include:

- 5m;
- 15m;
- 30m;
- 1h;
- 2h;
- 4h;
- 6h;
- 1d.

Higher Coinbase candle endpoints may be used for validation but not as independently mixed execution inputs.

### 13.4 Raw archive

Preserve raw Coinbase provider responses separately from canonical normalized data.

Purpose:

- auditability;
- reprocessing;
- normalizer bug recovery;
- source comparison.

### 13.5 Canonical storage

Canonical candle storage should use Parquet/Arrow-compatible columnar files.

Proposed partitioning:

```text
data/canonical/
  coinbase/
    spot/
      BTC-USD/
        1m/
          year=2025/
            month=01/
            month=02/
```

Partition details may evolve based on profiling.

### 13.6 Durable numeric representation

Persist market prices/quantities in an exact decimal-compatible representation where practical.

Large numerical arrays may be converted to `float64` for indicators/research calculations.

Financial execution and accounting state must return to exact decimal arithmetic.

### 13.7 Historical importer

The historical importer must support:

- bounded Coinbase request pagination/chunking;
- retry of transient provider failures;
- resumability;
- idempotent re-execution where practical;
- boundary overlap;
- deduplication;
- conflict detection;
- raw-response preservation;
- canonical normalization;
- validation;
- manifest generation.

Adjacent request windows should preferably overlap sufficiently to detect boundary inconsistencies.

### 13.8 Data quality

Validate individual candles:

- valid timestamp alignment;
- `high >= open`;
- `high >= close`;
- `high >= low`;
- `low <= open`;
- `low <= close`;
- nonnegative volume;
- valid numeric values.

Validate series:

- strict monotonic timestamps;
- duplicate detection;
- expected interval accounting;
- overlap detection;
- gap classification.

Distinguish:

- missing source data;
- confirmed no-trade interval;
- inactive/not-yet-listed product;
- unknown gap.

Do not silently convert unknown gaps into synthetic flat candles.

### 13.9 Dataset quality states

Possible quality states may include:

- VALID;
- VALID_WITH_KNOWN_NO_TRADE_INTERVALS;
- INCOMPLETE;
- INVALID.

Exact enum naming may be refined in implementation.

The quality state must be explicit in dataset manifests and run provenance.

### 13.10 Resampling

For aggregate bars:

- open = first open;
- high = maximum high;
- low = minimum low;
- close = last close;
- volume = sum volume.

Derived bar quality inherits source quality.

A derived bar whose required source interval is unresolved must not be labeled fully valid.

### 13.11 Derived cache

Derived bars may be persisted/cacheable.

Cache identity must include at least:

- canonical dataset version/hash;
- timeframe;
- resampler version.

### 13.12 Indicators

Initial indicator results are computed in memory/per run.

Do not create a persistent combinatorial indicator cache in v1.

A future shared indicator cache must be keyed by dataset identity, timeframe, indicator identity, parameters, and implementation version.

## 14. Market-data interfaces

Separate durable/random access from chronological delivery.

### 14.1 MarketDataRepository

Responsibilities:

- retrieve canonical historical bars;
- retrieve product specs;
- inspect dataset metadata/quality;
- resolve dataset versions;
- support warmup range reads.

### 14.2 MarketDataFeed

Responsibilities:

- emit chronological runtime market events.

Implementations:

- `HistoricalReplayFeed`;
- future `CoinbaseLiveFeed`.

### 14.3 Strategy-facing MarketView

Strategies access a constrained view such as:

- latest closed bar;
- bounded historical bars;
- latest known price;
- product specification.

Every query is constrained by the runtime clock.

The strategy cannot bypass the runtime and query unrestricted historical repositories.

## 15. Future live market data

Paper/live phases will use Coinbase WebSocket data.

The intended long-term path is:

```text
Coinbase market trades
        |
        v
Normalized MarketTrade
        |
        v
Live 1m candle builder
        |
        v
BarClosed
        |
        v
Trading runtime
```

The live system should eventually preserve raw event archives and sequence/integrity information.

Live bars should be reconciled against later Coinbase REST data to detect missed events or feed defects.

This is future scope; only the interfaces should influence v1.

## 16. Trading runtime

The `TradingRuntime` owns deterministic execution sequencing.

Conceptually:

```python
TradingRuntime(
    clock=...,
    market_feed=...,
    broker=...,
    risk_engine=...,
    account=...,
    portfolio=...,
    strategy_runner=...,
    event_recorder=...,
)
```

The runtime owns lifecycle, ordering, and orchestration.

No other component owns the complete financial state machine.

## 17. Runtime object ownership

### 17.1 Runtime

Owns:

- event sequencing;
- lifecycle;
- component coordination;
- invariant enforcement points.

### 17.2 Broker

Owns:

- order lifecycle/execution state;
- active orders;
- cancellation state;
- partial fill state;
- generation of fills.

Does not own account balances or PnL.

### 17.3 Accounting

Owns:

- immutable ledger;
- account balances;
- reservations;
- fill lots;
- realized PnL accounting;
- strategy attribution.

### 17.4 Portfolio

Derives:

- current equity;
- market value;
- exposure;
- unrealized PnL;
- allocation;
- drawdown-related views.

### 17.5 Risk engine

Consumes current/projected state and returns decisions.

It does not mutate account state directly.

### 17.6 Strategy runner

Owns:

- strategy artifact binding;
- parameters;
- strategy state;
- declared subscriptions;
- callback lifecycle.

## 18. Runtime event model

Candidate internal events include:

- MarketIntervalProcessed;
- BarClosed;
- SignalGenerated;
- OrderIntentCreated;
- RiskEvaluated;
- OrderActivated;
- OrderCancelled;
- OrderPartiallyFilled;
- OrderFilled;
- PositionChanged;
- LedgerPosted;
- PortfolioUpdated;
- StrategyCallbackRequested.

Exact event types should be introduced only when needed.

The financial event pipeline must remain deterministic.

Avoid an unconstrained general asynchronous event bus in the initial core.

## 19. Canonical event ordering

At a timestamp T corresponding to completed market intervals:

1. process market activity before T;
2. evaluate existing active orders against that activity;
3. create fills;
4. apply fill-driven accounting;
5. update positions/account balances;
6. update portfolio state;
7. finalize every subscribed bar ending at T;
8. publish those completed bars atomically;
9. update indicator state;
10. deliver callbacks caused by existing fills where required;
11. run the strategy decision callback;
12. create order intents;
13. evaluate risk;
14. normalize/validate approved orders;
15. reserve resources;
16. activate orders;
17. wait for market activity after T.

The implementation may refine internal event names while preserving these semantics.

## 20. Same-timestamp atomic market state

When multiple subscribed data streams close at T, all relevant data ending at T becomes visible before any strategy decision at T.

Example:

```text
16:00
  finalize BTC 1h
  finalize BTC 4h
  finalize ETH 1h
  update indicators
  then run strategy
```

Product iteration order must not change strategy-visible state or financial results.

## 21. New-order temporal rule

A new order can never interact with market activity that occurred before activation.

For a strategy decision triggered by a bar close at 15:00, an order created by that decision cannot use the high/low of the completed 14:00-15:00 bar as fill evidence.

This is a hard anti-look-ahead invariant.

## 22. Backtest execution model

### 22.1 Reference resolution

Initial execution resolution is Coinbase one-minute candles.

### 22.2 Market orders

A market order generated after a higher-timeframe bar close fills at the first executable future market price.

For the initial one-minute candle model, the baseline is the next one-minute open after activation, adjusted by the configured slippage model.

Do not default to the signal bar close.

### 22.3 Limit orders

A newly created limit order is eligible only against future market intervals after activation.

Initial fill model may be touch-based.

The fill model must be explicit and serializable.

Future alternatives may include:

- trade-through;
- volume-aware;
- trade replay;
- order-book replay.

### 22.4 Stop-market orders

A stop triggers on future price crossing.

A gap through a stop does not receive the stop price magically.

The fill uses the next executable price under the configured model, plus applicable adverse slippage.

### 22.5 Take-profit limits

Take-profit orders use limit semantics.

Favorable gap behavior may result in execution at a better price when supported by the fill model.

### 22.6 Intrabar ambiguity

If stop and target are both reachable within a one-minute OHLC bar and finer ordering data is unavailable, the event is ambiguous.

Default resolution is conservative: resolve against the strategy.

Every ambiguous execution must preserve provenance.

### 22.7 Protective orders

Convenient strategy APIs may create parent entry intents with stop-loss/take-profit instructions.

Internally:

- entry fills first;
- position is established for filled quantity;
- protective child orders activate afterward;
- child quantity may not exceed filled parent quantity.

### 22.8 Partial fills

The domain model must support partial fills even if the first simple historical fill model usually fills the eligible quantity immediately.

## 23. Execution provenance

Every simulated fill should retain enough information to explain execution.

Candidate fields:

- reference price;
- fill price;
- slippage amount;
- fee;
- execution source;
- fill model;
- resolution classification;
- ambiguity marker;
- gap marker;
- activation timestamp;
- fill timestamp.

Example resolution classifications may include:

- EXACT_NEXT_OPEN;
- PRICE_CROSSED;
- GAP;
- AMBIGUOUS_CONSERVATIVE.

## 24. Fee model

Fees are assessed per fill.

A fee is explicit:

```text
asset
amount
rate/model identity
```

Do not bury fees invisibly inside entry price.

Analytics may derive all-in cost basis while retaining fee decomposition.

## 25. Slippage model

Slippage belongs to fills.

Retain:

- reference price;
- actual simulated fill price;
- derived slippage cost.

This is necessary for future comparison with actual Coinbase paper/live execution.

## 26. Strategy system

### 26.1 Philosophy

Strategies express trading intent.

The platform owns:

- market truth;
- order validity;
- risk authorization;
- execution;
- accounting;
- persistence.

### 26.2 Declarative strategy metadata

A strategy should declare:

- identity;
- parameters;
- state schema;
- market subscriptions;
- primary decision stream where applicable.

### 26.3 Subscriptions

Example concept:

```python
subscriptions = [
    Bars("BTC-USD", "1h", primary=True),
    Bars("BTC-USD", "4h"),
    Bars("ETH-USD", "1h"),
]
```

Subscriptions allow the runtime to determine:

- required datasets;
- resampling;
- warmup;
- decision scheduling;
- eventual live feed subscriptions.

### 26.4 Primary decision stream

Initial candle strategies should normally declare one primary bar stream.

The standard `on_bar` decision callback runs after that stream closes and after all same-timestamp supporting streams are visible.

### 26.5 Lifecycle

Initial public lifecycle:

```python
on_start(ctx)
on_bar(ctx, bar)
on_fill(ctx, fill)
on_stop(ctx)
```

Avoid an excessively large public callback surface in v1.

Internally, richer event types may exist.

### 26.6 Strategy context

Candidate context capabilities:

```text
ctx.clock
ctx.market
ctx.indicators
ctx.positions
ctx.portfolio
ctx.risk
ctx.orders
ctx.state
ctx.logger
ctx.telemetry
```

No infrastructure clients are exposed.

### 26.7 Parameters

Parameters must be typed/validated.

Candidate types:

- IntParam;
- DecimalParam;
- FloatParam where appropriate;
- BoolParam;
- ChoiceParam;
- DurationParam;
- TimeParam.

Parameters are immutable during a run unless adaptive behavior is explicitly modeled as strategy state.

### 26.8 State

Strategy state is explicit and serializable.

State may change during execution.

Do not rely on untracked arbitrary module globals or non-persistable process-local state.

### 26.9 Indicators

Strategies may use:

- platform built-in indicators;
- custom strategy functions over bounded historical bars.

Indicator calculations must not expose future bars.

Built-in indicator state may be cached in memory.

### 26.10 Warmup

The engine determines required warmup data from strategy/indicator requirements where possible.

Warmup data may calculate state but must not produce trades before the configured trading start.

### 26.11 Environment independence

Strategy code must not detect or branch on backtest/paper/live.

Prefer not exposing runtime mode at all.

## 27. Signals and intent

A strategy may optionally emit a structured signal before an order intent.

Concept:

```text
SignalGenerated
      |
      v
OrderIntent
      |
      v
Risk
      |
      v
Broker
```

Signals are useful for analytics and rejected-opportunity analysis, but v1 need not require a signal object for every order.

## 28. Order model

The order domain should support at least:

- MARKET;
- LIMIT;
- STOP_MARKET or explicit stop-trigger semantics;
- STOP_LIMIT when separately phased;
- protective bracket semantics where implemented.

Time-in-force types should be introduced according to actual supported needs, not all at once.

Potential future values include:

- GTC;
- GTD;
- IOC;
- FOK.

Orders should have explicit lifecycle states, likely including:

- NEW/CREATED;
- ACTIVE/OPEN;
- PARTIALLY_FILLED;
- FILLED;
- CANCELLED;
- REJECTED.

Exact naming may be standardized in a phase spec.

## 29. Strong sizing semantics

Avoid ambiguous numeric `size=500`.

Prefer explicit units/types conceptually such as:

- BaseSize;
- QuoteSize;
- ContractQuantity — future.

Order intent must unambiguously state economic quantity.

## 30. Accounting model

### 30.1 Spot v1 economics

Initial model:

- USD is cash;
- crypto assets are owned inventory;
- buy converts USD to crypto;
- sell converts crypto to USD;
- no leverage;
- no borrowing;
- no synthetic shorting.

### 30.2 Accounting components

Separate:

- Account;
- Portfolio;
- Position;
- Ledger.

### 30.3 Ledger

The financial ledger is append-only.

Every financial change is explainable by a financial event.

Initial transaction categories may include:

- INITIAL_DEPOSIT;
- DEPOSIT;
- WITHDRAWAL;
- ORDER_RESERVATION;
- ORDER_RESERVATION_RELEASE;
- TRADE_FILL;
- TRADING_FEE;
- ASSET_TRANSFER;
- ADJUSTMENT.

An `ADJUSTMENT` is exceptional and requires reason/source metadata.

### 30.4 Fill is the mutation source

Only fills change trading balances/positions.

Order submission does not.

Signals do not.

### 30.5 Cash reservation

`available_cash = total_cash - reserved_cash`

Active buy orders reserve the relevant cash amount plus conservative fee allowance where required.

### 30.6 Asset reservation

`available_asset = total_asset - reserved_asset`

Active sell orders reserve owned quantity.

### 30.7 Reservation lifecycle

- approval/activation creates reservation;
- partial fill consumes proportional reservation;
- cancellation releases remaining reservation;
- full fill consumes remaining reservation;
- rejection creates no lasting reservation.

### 30.8 Fill lots

Preserve immutable fill lots beneath the displayed position.

Do not rely only on weighted-average entry price.

### 30.9 Displayed position basis

The initial trading view may use weighted-average cost basis.

Lots remain available for precise reconstruction and potential future accounting/tax views.

### 30.10 Partial exits

Partial exits realize PnL only on exited quantity.

Remaining position basis remains mathematically consistent with the selected trading accounting method.

### 30.11 Fees

Track fees independently from gross price-move PnL.

Do not erase cost attribution by silently merging every fee into displayed entry price.

### 30.12 Realized vs unrealized PnL

Realized PnL derives from closed quantity.

Unrealized PnL derives from current holdings marked using the latest valid known price.

### 30.13 Portfolio equity

For spot:

`equity = cash + sum(marked asset values)`

This must reconcile independently with ledger/position views.

### 30.14 External cash flows

Deposits and withdrawals are capital flows, not trading PnL.

Performance analytics must not interpret a deposit as return.

## 31. Financial arithmetic

Use `Decimal` for:

- cash;
- quantities;
- prices in order/fill/accounting state;
- fees;
- cost basis;
- ledger values.

Use float/vectorized representations only for appropriate analytical workloads.

Define and test rounding/quantization behavior explicitly.

## 32. Dust

Do not silently set a tiny unsellable remainder to zero.

Model:

- actual quantity;
- tradable quantity;
- exchange minimum/increment state.

Dust may exist.

## 33. Logical trades

A logical trade begins when a strategy-attributed position moves from flat to non-flat and ends when it returns to flat.

A trade may contain:

- multiple entry fills;
- scale-ins;
- partial exits;
- multiple exit fills.

Trade-level analytics are derived from the underlying fills.

## 34. Portfolio snapshots

Persist/derive consistent snapshots for performance analytics.

Candidate fields:

- timestamp;
- cash;
- marked asset value;
- total equity;
- realized PnL;
- unrealized PnL;
- fees-to-date;
- exposure;
- drawdown.

Sampling policy must be explicit.

## 35. Risk architecture

### 35.1 Layers

Risk is separated into:

1. strategy sizing/risk intent;
2. bot/strategy-instance allocation;
3. portfolio/platform authorization.

### 35.2 Pipeline

```text
Strategy
   |
   v
OrderIntent
   |
   v
RiskEngine
   |
   +---- REJECT
   |
   +---- APPROVE
   |
   +---- APPROVE_WITH_MODIFICATION
   |
   +---- HALT / platform action where applicable
   |
   v
Broker
```

### 35.3 Risk sizing vs authorization

Sizing helpers answer:

"What position size corresponds to this strategy risk objective?"

Authorization answers:

"May the platform activate this requested exposure?"

Every exposure-changing intent must pass authorization regardless of how quantity was calculated.

### 35.4 Initial sizing helpers

Potential helpers:

- fixed quote amount;
- percent of account equity;
- percent of strategy allocation;
- size for stop distance.

Sizing outputs may evolve into structured proposals carrying:

- quantity;
- notional;
- estimated risk;
- stop distance;
- estimated fee/slippage cost.

### 35.5 Risk policy as data

Risk behavior must be represented by serializable configuration.

Potential v1 controls:

- strategy allocation cap;
- max product exposure;
- max portfolio exposure;
- max trade risk;
- minimum cash reserve;
- max open positions;
- max order notional;
- trading enabled/disabled.

Later:

- daily loss limits;
- drawdown limits;
- aggregate stop risk;
- group/correlation exposure;
- dynamic risk scaling.

### 35.6 Projected-state evaluation

Risk decisions must evaluate projected post-fill/post-order exposure.

Pending active orders count toward relevant exposure/capital constraints.

### 35.7 Modification rule

Automatic risk modification may reduce requested exposure only when allowed.

It must never increase requested risk to meet minimums.

If an exchange minimum cannot be met conservatively, reject.

### 35.8 Exposure direction classification

Classify intents as conceptually:

- INCREASE_EXPOSURE;
- REDUCE_EXPOSURE;
- NEUTRAL.

Most risk halts should block new exposure while allowing safe reductions/cancellations.

### 35.9 Risk reasons

Use structured/machine-readable rejection reasons.

Examples:

- INSUFFICIENT_BUYING_POWER;
- MAX_STRATEGY_ALLOCATION;
- MAX_PRODUCT_EXPOSURE;
- MAX_PORTFOLIO_EXPOSURE;
- MAX_TRADE_RISK;
- MAX_OPEN_POSITIONS;
- MIN_ORDER_SIZE;
- STALE_MARKET_DATA;
- TRADING_DISABLED.

## 36. Coinbase normalization

Before activation:

1. interpret requested unit;
2. validate product;
3. normalize price/quantity to Coinbase constraints;
4. ensure normalization does not increase requested risk;
5. risk-check projected state;
6. reserve resources;
7. activate order.

Quantity rounding should be conservative.

## 37. Research architecture

Research orchestrates experiments above the trading runtime.

It must not implement its own execution/accounting semantics.

### 37.1 Backtest

```text
BacktestSpec
    |
    v
Resolve strategy artifact
    |
    v
Resolve dataset
    |
    v
Build TradingRuntime
    |
    v
Run deterministic simulation
    |
    v
Collect results
    |
    v
Analytics
    |
    v
Persist summary/artifacts
```

### 37.2 BacktestSpec

The canonical experiment input should be serializable.

Conceptually:

```python
BacktestSpec(
    strategy=...,
    parameters=...,
    market=...,
    period=...,
    account=...,
    risk_policy=...,
    execution=...,
    random_seed=...,
)
```

Anything that materially affects results must be represented by spec data or versioned implementation identity.

### 37.3 ExecutionSpec

Should eventually capture:

- fee model;
- slippage model;
- limit fill model;
- intrabar policy;
- data-gap policy;
- simulation engine selection;
- relevant execution resolution/settings.

### 37.4 BacktestResult

A completed result is immutable.

It should reference:

- run ID;
- spec hash;
- strategy/code hash;
- dataset hash;
- product-spec identity;
- engine version/commit;
- metrics summary;
- risk summary;
- execution summary;
- artifact manifest.

### 37.5 Detailed artifacts

High-volume details may live in Parquet:

```text
artifacts/backtests/BT_x/
  orders.parquet
  fills.parquet
  trades.parquet
  equity.parquet
  events.parquet
  telemetry.parquet
  manifest.json
```

Do not require every optimization event to become a row in the main relational DB.

## 38. Analytics

Initial analytics should include at least:

### Return

- total return;
- net profit;
- CAGR where meaningful.

### Risk

- max drawdown;
- average drawdown where useful;
- longest drawdown.

### Risk-adjusted

- Sharpe;
- Sortino;
- Calmar.

### Trades

- trade count;
- win rate;
- expectancy;
- profit factor;
- average/median winner;
- average/median loser;
- streaks where useful;
- hold duration.

### Execution costs

- fees;
- slippage;
- eventually funding for derivatives.

### Exposure

- time in market;
- max/average capital deployed;
- product exposure.

All metric formulas must be documented and tested.

## 39. Optimization — later phase

After single-backtest correctness:

1. batch backtests;
2. parameter sweeps;
3. Optuna or another justified optimizer;
4. parallel isolated workers;
5. walk-forward;
6. Monte Carlo;
7. significance analysis.

Optimization must use the same deterministic backtest service.

No optimizer-specific simulator.

## 40. Walk-forward analysis — later phase

Walk-forward should become first-class.

Only out-of-sample slices should be concatenated into reported walk-forward performance.

Training/optimization periods must remain distinguishable from test periods.

The UI and reports should make in-sample versus out-of-sample status difficult to confuse.

## 41. Monte Carlo and significance — later phase

Monte Carlo tooling may operate on:

- trade sequences;
- return blocks;
- other justified resampling models.

Time-series dependence should not be ignored casually.

Exact methods require separate phase specifications and validation.

## 42. Reference and optimized simulators

### 42.1 Reference engine

Characteristics:

- simple;
- explicit;
- inspectable;
- deterministic;
- correctness-oriented.

### 42.2 Optimized engine

Potential techniques later:

- batched candle ingestion;
- NumPy/Arrow preloading;
- timeframe skip logic;
- compiled kernels;
- Rust/PyO3 for demonstrated hotspots.

### 42.3 Equivalence contract

Optimized execution must match the reference engine for supported semantics.

Create a deterministic fingerprint based on financial/domain outcomes such as:

- ordered fills;
- fill prices/quantities;
- fees;
- order lifecycle outcomes;
- positions;
- trade PnL;
- ending equity.

Optimization is rejected if it changes semantics without an accepted design change.

## 43. Event recording

Support configurable event detail levels.

Possible modes:

- summary;
- full diagnostic.

Summary may keep:

- orders;
- fills;
- trades;
- equity;
- risk decisions.

Full may additionally keep:

- bar events;
- callback events;
- indicator/strategy diagnostics;
- signal events;
- detailed execution resolution.

Optimization runs should not be forced to persist enormous traces unless requested.

## 44. Strategy telemetry

Provide a structured research telemetry mechanism separate from generic logs.

Concept:

```python
ctx.telemetry.record("atr_ratio", value)
```

Telemetry should be suitable for columnar post-run analysis.

## 45. Structured logging layers

Distinguish:

1. application logs;
2. runtime/domain event records;
3. strategy structured logs.

Do not use `print` as the primary strategy/runtime observability mechanism.

## 46. Error model

Use domain-specific failures where useful.

Candidate categories:

- InvalidDataset;
- DataGapError;
- LookaheadViolation;
- AccountingInvariantError;
- InvalidProductPrecision;
- InsufficientBuyingPower;
- RiskPolicyViolation;
- InvalidRuntimeConfiguration.

Expected trading outcomes such as a risk rejection or unfilled limit are normal domain events, not engine crashes.

## 47. Fatal invariants

Terminate/mark run failed when truth is broken, including:

- ledger reconciliation failure;
- negative spot cash caused by engine/accounting defect;
- negative spot asset quantity;
- future-data access;
- impossible event ordering;
- required corrupt market data;
- position/account mismatch;
- deterministic replay mismatch;
- reference/optimized divergence where equivalence is required.

Do not paper over an invariant defect with a warning.

## 48. Persistence architecture

### 48.1 Relational metadata

Initial development may use SQLite.

Production application state may use PostgreSQL.

Relational DB responsibilities include searchable metadata such as:

- datasets/manifests;
- product specs;
- strategy artifacts;
- strategy instances;
- backtests;
- metric summaries;
- risk policies;
- execution specs;
- jobs;
- research sessions;
- future deployments.

### 48.2 Market data

Use Parquet/columnar files.

### 48.3 Research artifacts

Use Parquet/JSON artifact files behind an `ArtifactStore` abstraction.

Initial implementation: local filesystem.

Future: S3-compatible/object store if justified.

### 48.4 Raw provider archive

Store compressed immutable files/object data.

## 49. Repository/application services

Create use-case-oriented services rather than allowing interfaces to orchestrate domain internals.

Candidate services:

- DatasetService;
- StrategyService;
- BacktestService;
- ComparisonService;
- ResearchService;
- OptimizationService;
- future DeploymentService;
- future TradingControlService.

## 50. REST, MCP, CLI

REST, MCP, and CLI are interface adapters.

All should invoke the same application services.

Wrong:

```text
REST simulator
MCP simulator
CLI simulator
```

Correct:

```text
         BacktestService
          ^     ^     ^
          |     |     |
        REST   MCP   CLI
```

## 51. MCP architecture

The MCP server is a first-class control/research interface for both ChatGPT and Codex.

Initial useful tool families may include:

### Data

- list_datasets;
- inspect_dataset;
- validate_dataset;
- find_data_gaps.

### Strategies

- list_strategies;
- inspect_strategy;
- inspect_parameters.

### Backtesting

- run_backtest;
- get_backtest;
- list_backtests;
- cancel_backtest where job semantics support it.

### Analysis

- get_metrics;
- get_trades;
- inspect_trade;
- get_equity_curve;
- get_drawdown_periods.

### Comparison

- compare_backtests.

### Research — later

- run_parameter_sweep;
- run_optimization;
- run_walk_forward;
- run_monte_carlo.

Tools should be coarse-grained and token-efficient.

Do not return giant traces by default.

Prefer summary + filtered drill-down.

MCP must call application services, not direct SQL.

## 52. Future live MCP safety

When live trading exists, classify MCP operations by authority.

Examples:

Read-only:

- portfolio status;
- fills;
- bot health.

Moderate mutation:

- run backtest;
- create paper deployment.

High consequence:

- start live bot;
- cancel live order;
- flatten position;
- halt trading.

High-consequence operations require explicit future authorization design and Security/Reliability review.

## 53. Jobs

Long-running work must use explicit job semantics.

Candidate states:

- PENDING;
- RUNNING;
- COMPLETED;
- FAILED;
- CANCELLED.

Initial implementation may use a simple database-backed or local-process job runner.

Do not introduce heavyweight distributed queues before they are needed.

## 54. Parallelism

Within one trading simulation:

- deterministic sequential financial event processing.

Across independent runs:

- parallel workers allowed.

Optimization parallelizes independent backtest runs.

No module-level mutable simulation state.

Every worker gets an isolated runtime instance.

## 55. Strategy registry

Separate:

### StrategyDefinition

Human/product identity such as "BTC Trend".

### StrategyArtifact

Immutable code/schema/version identity.

May capture:

- semantic version;
- Git commit;
- code hash;
- module/class name;
- parameter schema;
- subscription schema.

### StrategyInstance

Binds artifact to:

- concrete parameters;
- configured products/subscriptions;
- risk policy/allocation.

### Deployment — future

Binds a strategy instance/artifact to:

- paper runtime;
- live runtime.

## 56. Git as strategy code history

Initial strategy source remains Git-managed.

Do not store the only authoritative copy of Python strategy code in the database.

Database records reference immutable Git/code identities.

## 57. Research sessions

A `ResearchSession` groups experiments around a hypothesis.

Candidate contents:

- title;
- hypothesis;
- strategy versions;
- backtest IDs;
- optimization IDs;
- notes;
- conclusions;
- resulting Git commit/artifact.

This allows research history to live in the Command Station rather than depending on AI conversation memory.

## 58. Web UI — later

Likely future client: React/Next.js or another justified modern web stack.

The web client is not the product core.

Potential sections:

- Overview;
- Market Data;
- Strategy Lab;
- Backtests;
- Comparisons;
- Optimization;
- Paper Bots;
- Live Bots;
- Orders;
- Fills;
- Positions;
- Portfolio;
- Risk;
- System;
- MCP.

UI work begins only after backend contracts are stable enough to justify it.

## 59. Application progress events

Job/runtime progress displayed to UI is an application-level notification stream.

It is separate from deterministic financial runtime event processing.

Possible transport later:

- SSE;
- WebSocket.

Do not make UI notification infrastructure part of financial correctness.

## 60. Security architecture

### 60.1 Credentials

Coinbase authenticated credentials remain infrastructure-only.

Strategies never receive credentials.

Backtest and paper components must not accidentally possess live order authority.

### 60.2 Runtime construction safety

Reject invalid component combinations.

In particular:

```text
HistoricalReplayFeed + CoinbaseBroker = invalid
```

This should fail before runtime execution.

### 60.3 Future live safety

Before live trading:

- authenticated provider boundary;
- idempotent client/order IDs;
- restart recovery;
- exchange reconciliation;
- stale market-data detection;
- uncertain-order outcome handling;
- explicit kill/halt semantics;
- credential isolation;
- Security/Reliability review.

## 61. Testing strategy

### 61.1 Unit tests

Examples:

- fee calculation;
- precision normalization;
- resampling;
- risk rules;
- sizing;
- cost basis;
- ledger posting.

### 61.2 Integration tests

Examples:

`strategy -> intent -> risk -> broker -> fill -> ledger -> portfolio`

### 61.3 Golden tests

Use tiny hand-authored market sequences with exact expected outputs.

Golden tests are essential for:

- event timing;
- fill semantics;
- gap behavior;
- stop/target ambiguity;
- partial exits;
- fee accounting;
- reservations.

### 61.4 Property/invariant tests

Examples:

- spot cash never negative;
- spot asset quantity never negative;
- ledger replay reproduces balances;
- cancellation releases reservations;
- portfolio equity reconciles;
- identical inputs produce identical financial fingerprints.

### 61.5 Regression tests

Every material bug should gain a focused regression test.

### 61.6 Performance tests

Add after a meaningful correct baseline.

Performance targets must never relax financial semantics silently.

## 62. Golden execution scenarios

The initial reference engine should include compact scenarios such as:

### Signal-bar look-ahead

A limit created at an hourly close must not fill from the high/low of the just-completed signal bar.

### Next-open market execution

A market intent created at a bar close fills against the next eligible one-minute open, not the historical signal close.

### Stop gap

A stop crossed by a gap fills at the next available executable price, not at the stop level.

### Stop/target same minute

Both touched in the same one-minute candle resolves conservatively and is marked ambiguous.

### Existing stop before new decision

An existing stop executes before the strategy callback at the bar boundary, so the strategy observes the updated flat position.

### Partial fill

Only filled quantity affects balances and protected child quantity.

### Reservation cancellation

Cancelled remainder releases all unused reserved resources.

## 63. Accounting invariants

At minimum:

1. Spot cash cannot become negative.
2. Spot asset quantity cannot become negative.
3. Fill is the only trading event that changes balances.
4. Every financial change is represented in the ledger.
5. Reserved cash/asset cannot exceed owned totals.
6. Cancelled orders release remaining reservations.
7. Partial fills consume reservations correctly.
8. Position quantity reconciles to fill history.
9. Account balances can be reconstructed from ledger history.
10. Portfolio equity equals cash plus marked asset value.
11. Deposits/withdrawals do not count as trading PnL.
12. Fees reconcile to fill-level fee records.
13. Strategy-attributed holdings reconcile to account holdings.
14. Replaying identical ledger history produces identical balances.

## 64. Risk invariants

At minimum:

1. Every new exposure-changing intent is authorized.
2. Risk cannot increase requested exposure during normalization/modification.
3. Pending orders count against relevant capital/exposure.
4. Projected state is evaluated, not only current state.
5. Exposure-reducing actions remain possible under ordinary entry halts.
6. Every rejection/modification has machine-readable reasons.
7. Risk behavior is serializable as run/deployment configuration.

## 65. Market-data invariants

At minimum:

1. Canonical bars are monotonic by timestamp.
2. Duplicate timestamps are detected.
3. Unknown gaps are never silently fabricated.
4. Derived bars use only source intervals within their half-open boundary.
5. Same source dataset + resampler version yields deterministic derived bars.
6. Strategy reads cannot access data newer than runtime clock.
7. Dataset repair produces a new dataset identity.

## 66. Reproducibility contract

A completed backtest should preserve enough identity to reproduce the financial result:

- engine Git commit/version;
- strategy artifact/code hash;
- strategy params;
- dataset content hash/version;
- product-spec identity;
- risk policy;
- execution spec;
- account spec;
- random seed;
- period;
- relevant algorithm versions.

Wall-clock creation timestamps and random database IDs must not be part of financial determinism.

## 67. Performance philosophy

Optimize in this order:

1. correctness;
2. robustness;
3. architecture;
4. simplicity;
5. measured runtime hotspots.

Likely future optimization candidates:

- candle aggregation;
- order crossing scans;
- rolling indicators;
- event-loop hotspots;
- Monte Carlo kernels.

Rust/PyO3 may be introduced after profiling demonstrates a material benefit.

The Python public strategy/research API should not care whether an implementation kernel is Python, NumPy, Numba, or Rust.

## 68. Development tooling

Initial choices should favor a modern typed Python stack.

Exact dependencies belong to Phase 001, but likely categories include:

- Python 3.12+ subject to compatibility validation;
- `pytest`;
- type checking;
- lint/format tooling;
- Pydantic/dataclasses where appropriate;
- PyArrow/Parquet;
- NumPy;
- DuckDB for research inspection;
- Coinbase official SDK only inside provider infrastructure when needed;
- FastAPI later for application API;
- relational persistence tooling when application metadata begins.

Do not add dependencies before a phase needs them.

## 69. Documentation

Keep architecture decisions versioned in Git.

Use ADRs for durable decisions.

Initial ADR candidates:

1. modular monolith;
2. Coinbase as canonical external venue;
3. canonical one-minute dataset;
4. fill/ledger as financial truth;
5. instance-scoped trading runtime;
6. reference engine before optimized engine;
7. Parquet for historical market data;
8. strategy environment independence;
9. application services shared by REST/MCP/CLI.

## 70. Phase specifications

Implementation proceeds through bounded phase documents under `docs/phases/`.

Each phase must contain:

- objective;
- current architecture context;
- exact owned change surface;
- domain contracts/invariants;
- acceptance criteria;
- implementation validation expectations;
- QA validation expectations;
- Security/Reliability review requirement if justified;
- explicit out-of-scope items.

The Codex Director should route work according to the user's global engineering organization.

## 71. Proposed implementation phases

The ordering may be refined, but the baseline is:

### Phase 001 — Project foundation

- Python project;
- package skeleton;
- tooling;
- CI/static gates;
- documentation/ADR structure;
- dependency-boundary foundation.

### Phase 002 — Domain primitives

- IDs;
- Decimal money/quantity types;
- timestamps;
- product/candle primitives;
- core enums/errors.

### Phase 003 — Coinbase product catalog

- provider product metadata adapter;
- ProductSpec normalization;
- snapshots/versioning;
- validation tests.

### Phase 004 — Historical Coinbase importer

- REST chunk retrieval;
- raw archive;
- resumability;
- retries;
- overlap;
- dedupe.

### Phase 005 — Canonical datasets

- normalization;
- validation;
- dataset manifests;
- Parquet;
- content hashes;
- gap reporting.

### Phase 006 — Timeframe/resampling engine

- half-open aggregation;
- derived cache;
- quality propagation;
- warmup reads.

### Phase 007 — Reference runtime/event engine

- SimulatedClock;
- HistoricalReplayFeed;
- deterministic dispatcher;
- event sequencing;
- MarketView.

### Phase 008 — Order/execution domain

- OrderIntent;
- Order;
- activation;
- cancellation;
- reference fill model;
- market/limit/stop semantics.

### Phase 009 — Spot accounting

- ledger;
- account;
- reservations;
- fill lots;
- positions;
- portfolio valuation.

### Phase 010 — Risk engine

- RiskPolicy;
- core rules;
- sizing helpers;
- structured decisions.

### Phase 011 — Strategy runtime/API

- strategy base;
- typed params;
- state;
- subscriptions;
- indicators;
- context;
- callbacks.

### Phase 012 — First end-to-end backtest

- BacktestSpec;
- application service;
- runtime composition;
- metrics;
- immutable result/artifacts.

### Phase 013 — Regression/golden hardening

- systematic edge-case suite;
- property invariants;
- reproducibility fingerprint.

### Phase 014 — Batch backtests

- isolated workers;
- job semantics;
- result indexing.

### Phase 015 — MCP research interface

May be pulled earlier once Phase 012 is stable.

- dataset tools;
- strategy inspection;
- run/get/list backtests;
- inspect trades.

### Phase 016 — Optimization

- parameter sweeps;
- Optuna or selected engine;
- isolated parallel workers.

### Phase 017 — Walk-forward

### Phase 018 — Monte Carlo/significance

### Phase 019 — Optimized simulator

- profile;
- optimize;
- enforce reference equivalence.

### Later

- API/web command station;
- live data collector;
- paper runtime;
- authenticated Coinbase broker;
- live deployment/reconciliation.

## 72. Scope explicitly deferred from the current build

Do not implement now:

- Coinbase authenticated trading;
- API keys/secrets;
- paper trading runtime;
- live bot runtime;
- futures;
- perpetuals;
- margin;
- short selling;
- funding;
- liquidation;
- Level 2 backtesting;
- high availability;
- live reconciliation;
- kill switches;
- tax accounting;
- complex RBAC;
- multi-user product;
- Kubernetes;
- complex distributed queue infrastructure.

The architecture should leave reasonable seams without implementing these systems.

## 73. Source-of-truth philosophy

The platform should always be able to answer:

- What data did this run use?
- What strategy code did it use?
- What parameters did it use?
- What execution assumptions did it use?
- What risk policy did it use?
- Why did this order exist?
- Why was it approved/rejected?
- How was this fill determined?
- How did this fill change balances?
- How was this PnL calculated?

If the architecture makes those questions difficult to answer, reconsider the design.

## 74. Explainability goal

The eventual Command Station should be able to present a trade timeline such as:

```text
14:00:00  1h bar closed
14:00:00  EMA20=...
14:00:00  EMA50=...
14:00:00  LONG signal
14:00:00  BUY market intent
14:00:00  risk approved
14:00:00  order active
14:00:00+ next market event
14:00:00+ simulated fill
14:00:00+ fee posted
14:00:00+ position updated
14:00:00+ protective orders active
```

MCP should eventually expose the same explanation programmatically.

## 75. Review philosophy

Foundational components warrant architecture review after implementation:

- runtime event engine;
- market-data canonicalization;
- accounting;
- risk;
- strategy contract;
- simulated broker;
- first end-to-end backtest;
- optimization;
- future live boundaries.

GitHub is the shared source of truth for these reviews.

## 76. Acceptance philosophy

A phase is not accepted merely because code executes.

Acceptance means there is evidence that:

- requested behavior exists;
- domain semantics match this specification;
- critical invariants hold;
- architecture boundaries are preserved;
- relevant failure paths are explicit;
- tests establish the meaningful claims;
- environment-blocked claims remain labeled unproven rather than assumed;
- out-of-scope future capability was not accidentally introduced.

## 77. Current product baseline

At the time of this document, the agreed immediate target is:

A deterministic Coinbase spot backtesting engine that can:

- use locally stored Coinbase one-minute history;
- derive higher timeframes;
- run Python strategies on completed bars;
- submit market/limit/stop-style intents;
- apply risk authorization;
- simulate realistic temporal execution;
- assess fees/slippage;
- support partial-fill-capable domain state;
- account for cash/assets using an immutable ledger;
- generate positions/trades/equity;
- produce reproducible metrics/artifacts;
- explain its decisions;
- later serve the same strategy contract in paper/live runtimes.

## 78. Guiding sentence

**Strategies express trading intent. The Command Station owns market truth, risk, execution, financial reality, and provenance.**
