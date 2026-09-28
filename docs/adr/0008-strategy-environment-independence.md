# ADR 0008 — Strategy Environment Independence

**Status:** Accepted  
**Date:** 2026-09-28

## Context

The desired lifecycle is backtest -> paper -> live. If a strategy branches on runtime mode or directly calls Coinbase, the platform is not testing the same behavior that later trades real capital.

Strategies need market data, indicators, state, risk sizing, and order capabilities without owning infrastructure.

## Decision

A strategy must remain **environment-independent**.

Strategy code receives a constrained context/capability surface and must not:

- call Coinbase directly;
- query databases or filesystems directly;
- access credentials;
- use wall-clock time directly;
- branch on backtest/paper/live mode;
- mutate account/portfolio/order/ledger internals;
- use uncontrolled randomness.

The runtime injects the environment through MarketDataFeed, Clock, Broker, persistence, and other infrastructure implementations.

Prefer not exposing runtime mode to strategy code at all.

Strategy state is explicit and serializable.

## Consequences

### Positive

- the same strategy artifact can progress through research, paper, and live;
- backtest/live drift is reduced;
- deterministic testing becomes practical;
- restart persistence can be designed around explicit state.

### Negative

- some convenient Python operations are intentionally unavailable to strategies;
- strategy context APIs must be designed carefully;
- nonstandard strategies may require new platform capabilities instead of ad-hoc I/O.

## Rejected alternatives

### `if mode == "backtest"` branches

Rejected because they permit different behavior in research and production.

### Direct provider client in strategies

Rejected because provider authority, credentials, and execution semantics would leak into strategy logic.

## Revisit when

New strategy capabilities should be added as explicit context contracts rather than by weakening environment independence.
