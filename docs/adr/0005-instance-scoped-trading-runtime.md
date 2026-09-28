# ADR 0005 — Instance-Scoped Trading Runtime

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Backtests, optimization, paper trading, and eventual live trading all require stateful execution. Global mutable stores make parallel runs difficult, allow state leakage between experiments, complicate testing, and create fragile reset semantics.

Optimization will eventually run many independent backtests concurrently, and paper/live deployments will require isolated state ownership.

## Decision

All simulation/trading state is **instance-scoped**.

A `TradingRuntime` instance owns the lifecycle and coordinates injected components such as:

- clock;
- market feed/view;
- strategy runner;
- risk engine;
- broker;
- accounting/account;
- portfolio;
- event recorder.

No module-level mutable simulation state is permitted.

Each backtest gets a fresh runtime. Parallelism happens across isolated runtime instances.

Backtest, paper, and live are constructed by injecting different clocks/feeds/brokers rather than resetting shared global state.

## Consequences

### Positive

- independent runs cannot leak state;
- tests can create isolated runtimes;
- parallel optimization is safer;
- runtime configuration is explicit;
- future deployment state has clear ownership.

### Negative

- dependency wiring is more explicit;
- some convenient global caches require carefully scoped alternatives.

## Rejected alternatives

### Global process stores reset between runs

Rejected because correctness would depend on complete reset behavior and parallel execution would be unsafe.

### Separate runtime implementations for backtest/paper/live

Rejected because strategy/runtime semantics would drift.

## Revisit when

Instance scoping is a foundational invariant. A future optimization may add shared immutable caches, but mutable financial/runtime state must remain isolated.
