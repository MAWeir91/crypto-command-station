# ADR 0004 — Fill and Ledger as Financial Truth

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Trading systems often blur signals, orders, positions, balances, and PnL. That makes partial fills, cancellations, reconciliation, and later live trading difficult to reason about.

A strategy signal or submitted order does not itself transfer assets. Financial state changes only when execution occurs. Once execution occurs, a durable accounting history is required to explain balances and PnL.

## Decision

Adopt two related rules:

1. **A Fill is the only trading event that changes financial exposure or balances.**
2. **The append-only financial Ledger is the durable explanation of financial state.**

Signals and order submission do not directly mutate account balances or positions.

The broker produces Fill events. Accounting consumes fills and posts ledger entries. Account balances, fill lots, realized PnL, strategy attribution, positions, and portfolio views derive from those facts.

Brokers must never directly edit account cash or holdings.

Historical ledger events are not silently rewritten to force reconciliation.

## Consequences

### Positive

- partial fills are naturally supported;
- account reconstruction is possible;
- simulated and live fills can feed the same accounting system;
- reconciliation defects are diagnosable;
- PnL and fee attribution remain explainable.

### Negative

- more domain objects are required than a simple position flag;
- accounting tests and invariant checks become mandatory;
- projections/views must be kept distinct from source financial events.

## Rejected alternatives

### Broker directly updates positions and balances

Rejected because execution and accounting responsibilities become entangled.

### Position object as the primary source of truth

Rejected because position state alone cannot faithfully explain transfers, partial fills, fees, external flows, or reconciliation history.

## Revisit when

Do not revisit the principle for live trading. Future derivatives may add new financial event types—funding, borrowing, liquidation, settlement—but they should extend the ledger model rather than replace it.
