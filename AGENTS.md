# Crypto Command Station — Project Engineering Rules

**Scope:** Repository-specific rules for `MAWeir91/crypto-command-station`.
**Product:** Crypto Command Station (CCS)
**Status:** Foundational project contract.

This file complements the user's global Codex engineering rules. The global rules govern orchestration, delegation, validation ownership, release discipline, and model routing. This file governs this repository's product architecture, domain invariants, implementation constraints, and acceptance expectations.

If a task conflicts with this file, `MASTER_ENGINEERING_SPEC.md`, or an accepted ADR, do not silently redesign the system. Escalate the conflict to the Director.

## Mission

Build a deterministic, auditable crypto trading platform that supports the progression:

`backtest -> paper trading -> live trading`

using the same strategy contract, risk model, order model, accounting model, and market-data semantics wherever possible.

Initial focus is the backtesting system. Paper and live trading are future execution environments, not separate products.

Coinbase Advanced is the canonical external venue for market data and eventual trading.

## Authoritative project sources

Use these sources in this order:

1. `AGENTS.md` — hard repository rules and invariants.
2. `MASTER_ENGINEERING_SPEC.md` — system architecture and domain contracts.
3. `docs/adr/` — accepted architectural decisions.
4. Phase specifications under `docs/phases/` — bounded implementation requirements.
5. Executable tests — acceptance and regression evidence.

When a lower-level source conflicts with a higher-level source, stop and escalate rather than guessing.

## Core architectural laws

### 1. One platform, multiple runtimes

Backtest, paper, and live trading are configurations of one trading runtime.

- Backtest: simulated clock + historical market feed + simulated broker.
- Paper: real clock + Coinbase live market feed + simulated broker.
- Live: real clock + Coinbase live market feed + Coinbase broker.

Do not create separate strategy implementations for each environment.

### 2. Strategies express intent; the platform owns reality

A strategy may:

- read approved market data through its context;
- read indicators, positions, portfolio views, parameters, and its own state;
- emit signals, telemetry, logs, and order intents.

A strategy must not:

- call Coinbase APIs directly;
- access database or filesystem infrastructure directly;
- access secrets or credentials;
- call wall-clock time directly;
- use uncontrolled randomness;
- branch on backtest/paper/live mode;
- mutate portfolio, account, position, order, or ledger state directly.

### 3. No look-ahead

A strategy may only observe information available at the runtime clock.

For a completed bar ending at timestamp T:

1. market activity before T is processed;
2. existing eligible orders are filled;
3. positions/accounting are updated;
4. all bars ending at T become visible atomically;
5. indicators are updated;
6. strategy callbacks run;
7. new intents are risk-evaluated;
8. approved orders become active;
9. those new orders may interact only with market activity after activation.

A newly created order must never fill against market activity that occurred before the order became active.

### 4. Fill changes financial reality

Signals and submitted orders do not change balances or positions.

Only fills may change:

- asset balances;
- cash balances;
- position quantity;
- realized PnL;
- fill lots;
- fee totals.

A fill must flow through accounting/ledger logic. Brokers must not mutate account balances directly.

### 5. Ledger is immutable financial truth

Financial history is append-only.

Balances, positions, PnL, and portfolio state must be reproducible from immutable financial events/fills and ledger entries.

Never silently overwrite balance history to make reconciliation pass.

### 6. Coinbase-first semantics

Coinbase Advanced is the canonical external venue.

Initial implementation targets Coinbase spot products, especially USD-quoted crypto pairs.

The system must faithfully model Coinbase product constraints where known:

- product identity;
- base/quote currencies;
- base increment;
- quote increment;
- price increment;
- minimum/maximum sizes;
- trading status and relevant capabilities.

Keep a thin provider boundary for infrastructure isolation, but do not prematurely generalize the domain around Binance, Bybit, Kraken, or other venues.

### 7. Canonical one-minute historical data

The canonical candle dataset for candle-based backtesting is Coinbase 1-minute data.

Higher timeframes must be derived locally from canonical 1-minute data.

Do not mix independently downloaded higher-timeframe candles into strategy execution. They may be used as validation sources only.

Candle intervals are UTC, timezone-aware, and half-open: `[open_time, close_time)`.

### 8. Never fabricate unknown market data silently

Missing source data, known no-trade intervals, and inactive-product periods are distinct conditions.

Do not silently synthesize zero-volume candles for unknown gaps.

If execution crosses an unresolved data gap, the run must follow an explicit configured policy and must never imply certainty that the data cannot support.

### 9. Dataset and result immutability

A dataset version used by a completed backtest is immutable.

Repairing or renormalizing data creates a new dataset version.

A completed backtest result is immutable. A rerun is a new run.

Every run must preserve provenance sufficient to reproduce it.

### 10. Determinism

Given identical:

- strategy artifact;
- strategy parameters;
- dataset version;
- account spec;
- risk policy;
- execution spec;
- engine version;
- random seed;

the reference backtest engine must produce identical domain results within explicitly documented numeric tolerances.

IDs or wall-clock metadata that are intentionally nondeterministic must not affect financial fingerprints.

### 11. Reference engine before optimized engine

Build and preserve a simple, inspectable reference simulator.

Optimized simulation paths may be added only after correctness is established.

Reference and optimized engines must produce equivalent fill/trade/accounting fingerprints for the same supported scenario.

Do not optimize away semantic clarity.

### 12. Financial arithmetic

Use `Decimal` or an equivalent exact decimal representation for financial state:

- cash;
- asset quantities;
- order prices;
- fill prices;
- fees;
- cost basis;
- ledger values;
- account balances.

Floating-point arrays are allowed for indicators, statistical analytics, and vectorized research where exact financial accounting is not being performed.

### 13. Spot accounting invariants

Until explicitly extended to margin/derivatives:

- USD cash may not become negative.
- Crypto asset balances may not become negative.
- Spot orders may not create synthetic short positions.
- Pending buy orders reserve cash.
- Pending sell orders reserve owned asset quantity.
- Cancelled orders release remaining reservations.
- Partial fills consume reservations proportionally.
- External deposits/withdrawals are not trading PnL.

### 14. Risk authorization is mandatory

Every exposure-changing order intent must pass through the risk engine before broker activation.

Risk sizing helpers and risk authorization are separate concepts.

Risk decisions must be structured and auditable.

A risk engine may reduce requested exposure only when policy allows it. It must never increase requested risk merely to make an order valid.

Exposure-reducing actions should remain possible under most trading halts.

### 15. Market events before strategy decisions

At a shared timestamp, the runtime must publish market state atomically before the strategy acts.

Processing order of products or subscriptions must not change financial outcomes.

One simulation run is single-threaded/deterministically ordered internally. Parallelism belongs across independent runs, not inside the financial event sequence unless a future accepted ADR explicitly changes this.

### 16. Explicit execution assumptions

Execution behavior must be represented by serializable configuration, including where applicable:

- fee model;
- slippage model;
- limit fill model;
- intrabar ambiguity policy;
- data-gap policy;
- execution resolution.

Ambiguous OHLC execution must not be silently resolved optimistically. Conservative resolution is the default unless a phase specification or accepted ADR states otherwise.

### 17. Product normalization before activation

Orders must be normalized and validated against Coinbase product constraints before activation.

Quantity normalization must never increase requested exposure.

Exchange minimums that cannot be satisfied conservatively cause rejection rather than risk expansion.

### 18. Runtime environment must be structurally safe

Environment behavior is determined by injected components, not scattered `if mode == ...` conditionals.

Invalid combinations must fail construction. In particular, a historical replay feed must never be paired with a live Coinbase broker.

Backtest and paper runtimes must not possess live trading credentials.

### 19. Persistence boundaries

Use storage according to workload:

- canonical market data and large research artifacts: Parquet/columnar files;
- searchable application metadata: relational database;
- raw provider payload/event archives: immutable file/object storage;
- high-volume indicator working state: memory/cache as appropriate.

Do not put bulk candle history into the application relational database without an accepted ADR changing this decision.

### 20. Application-service boundary

Web, CLI, and MCP interfaces must call shared application services.

Do not implement separate trading/research logic paths for REST, CLI, and MCP.

MCP tools must not directly query or mutate persistence when an application service owns the use case.

## Initial domain boundaries

The intended top-level modules are:

- `domain` — pure trading vocabulary and value objects;
- `runtime` — deterministic event sequencing and lifecycle;
- `market_data` — datasets, repositories, feeds, normalization, validation, resampling;
- `execution` — broker interfaces, simulated execution, fill models, fees, slippage;
- `accounting` — ledger, balances, lots, positions, valuation;
- `risk` — sizing helpers, policies, rule evaluation;
- `strategy` — strategy API, parameters, state, subscriptions, indicators, registry;
- `research` — backtests, comparisons, optimization, walk-forward, Monte Carlo;
- `analytics` — performance and risk metrics;
- `persistence` — DB and artifact adapters;
- `jobs` — bounded long-running work orchestration;
- `api`, `mcp`, `cli` — interface adapters.

The exact filenames may evolve. Cross-boundary responsibilities require Director approval.

## Dependency direction

Prefer:

`interfaces -> application services -> research/runtime -> domain`

Infrastructure adapters point inward through explicit contracts.

Hard rules:

- `domain` must not import FastAPI, Coinbase SDKs, SQLAlchemy, PyArrow, UI code, or MCP code.
- strategies must not import persistence or provider clients;
- risk must not import web/API layers;
- research must not contain a second trading simulator;
- brokers must not mutate accounting state directly.

Add automated dependency checks when the package structure exists.

## Strategy contract requirements

Strategies must use declared subscriptions and typed/validated parameters.

The first public lifecycle should remain small unless a phase specification requires more:

- `on_start`;
- `on_bar`;
- `on_fill`;
- `on_stop`.

Strategy state must be explicit and serializable so it can later survive paper/live restarts.

Strategy code should operate on completed bars by default.

Any future support for partial/current bars requires an explicit contract and accepted architecture decision.

## Backtest execution baseline

Unless superseded by a phase specification:

- source resolution: Coinbase 1-minute candles;
- strategy decision: after primary bar close;
- market order: first executable price after activation, initially modeled by next 1-minute open plus configured slippage;
- limit order: active only after order activation and evaluated on future market activity;
- stop-market gap: fill at next available executable price, not magically at stop price;
- take-profit limit: limit semantics;
- same 1-minute stop and target ambiguity: conservative default;
- fees: assessed per fill;
- slippage: assessed per fill;
- protective child orders: activate only after parent fill and only for filled quantity.

Every simulated fill should retain execution provenance sufficient to explain how it was resolved.

## Market-data requirements

Historical Coinbase ingestion must be:

- resumable;
- idempotent where practical;
- overlap/deduplicate capable at chunk boundaries;
- independently validated;
- versioned by manifest and content hash.

Preserve raw provider data separately from canonical normalized data.

Derived timeframe caches must be keyed by canonical dataset identity and resampler version.

Do not persist a global indicator cache in v1 unless profiling demonstrates a need.

## Backtest provenance

A completed run must eventually identify at minimum:

- run ID;
- strategy artifact/code hash;
- strategy parameters;
- dataset version/content hash;
- product specification snapshot/version where applicable;
- account specification;
- risk policy;
- execution specification;
- engine version/commit;
- random seed;
- start/end period;
- result/artifact manifest.

Anything capable of changing financial output must be represented in reproducible configuration or versioned implementation identity.

## Test contract

Testing must include the smallest evidence appropriate to the change, while preserving strong coverage of financial invariants.

Expected test classes:

- unit tests;
- integration tests;
- golden deterministic scenario tests;
- property/invariant tests;
- regression tests for discovered defects;
- performance tests after a meaningful baseline exists.

Hand-built synthetic market scenarios are required for execution semantics.

Real Coinbase datasets complement but do not replace synthetic edge-case tests.

## Fail loudly on broken truth

The following are fatal run/invariant failures, not warnings:

- accounting reconciliation failure;
- impossible negative spot balance;
- impossible position quantity;
- future-data access/look-ahead violation;
- invalid deterministic event ordering;
- corrupted dataset required for execution;
- inconsistent ledger replay;
- reference/optimized divergence where equivalence is required.

Normal domain outcomes such as risk rejection, insufficient buying power, an unfilled order, a stop-out, or a cancelled order are not engine failures.

## Security and future live trading

Live trading is out of scope until explicitly phased in.

When live trading is introduced:

- credentials remain infrastructure-only;
- backtest/paper workers must not possess live-order authority;
- live mutations require explicit authorization boundaries;
- restart/recovery and Coinbase reconciliation are critical acceptance requirements;
- destructive MCP/API actions require separate capability treatment;
- stale or uncertain market/account state must fail safe for new exposure.

Security/Reliability review is justified for accounting, durable state, dataset integrity, reconciliation, concurrency/idempotency, credentials, live execution, and consequential control actions.

## Scope discipline

Do not implement future features merely because interfaces anticipate them.

Current first objective: a correct, deterministic Coinbase spot backtesting engine.

Explicitly defer until separately phased:

- authenticated Coinbase order execution;
- paper deployment runtime;
- live deployment runtime;
- margin/borrowing/shorting;
- futures/perpetuals/funding/liquidation;
- high availability;
- restart reconciliation;
- live kill controls;
- Level 2 historical replay;
- tax accounting;
- multi-user authorization;
- elaborate distributed queues;
- sophisticated web UI.

## Phase execution expectations

Each implementation phase must define:

- objective;
- ownership boundary;
- relevant architecture/contracts;
- invariants;
- acceptance criteria;
- required focused validation;
- explicit out-of-scope items.

Workers must not use a phase as permission to redesign neighboring subsystems.

If a phase exposes a missing architectural decision, stop at the boundary and escalate.

## Definition of accepted foundational work

A foundational phase is not complete merely because code runs.

Acceptance requires evidence that:

- the domain contract is correct;
- the implementation preserves architectural boundaries;
- relevant invariants are executable/tested;
- deterministic behavior is demonstrated where required;
- failure paths are explicit;
- no out-of-scope live-trading capability was introduced;
- documentation/specification is updated if an accepted decision changed.

Correctness first. Speed later. Financial truth must remain explainable.
