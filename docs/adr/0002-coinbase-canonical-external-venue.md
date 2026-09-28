# ADR 0002 — Coinbase as the Canonical External Venue

**Status:** Accepted  
**Date:** 2026-09-28

## Context

The product is intended to research, paper trade, and eventually live trade crypto using Coinbase Advanced. Historical-data semantics, exchange product rules, simulated execution assumptions, and eventual live execution should therefore describe the same venue as closely as practical.

Designing the first version as a generic multi-exchange platform would force abstractions around differences that are not yet required and could weaken fidelity to the venue that will actually hold capital.

## Decision

Use **Coinbase Advanced as the canonical external venue** for the initial product.

Initial implementation focuses on Coinbase spot products and USD-quoted trading where appropriate.

Provider-specific payloads remain behind Coinbase infrastructure adapters. Core strategy and domain code do not import the Coinbase SDK or Coinbase response types directly.

The domain may retain thin venue-neutral concepts where they are genuinely intrinsic—such as Product, Order, Fill, Position, and Ledger—but implementation should not generalize prematurely for Binance, Bybit, Kraken, or other venues.

## Consequences

### Positive

- research and eventual execution use the same venue semantics;
- product precision, minimums, fees, and trading constraints can be modeled faithfully;
- less abstraction is required before product behavior is understood;
- historical-to-paper-to-live drift is easier to reason about.

### Negative

- some domain assumptions may require later extension if another venue is added;
- Coinbase API changes must be handled carefully within adapters.

## Rejected alternatives

### Binance-first research with Coinbase live execution

Rejected because venue differences would contaminate execution assumptions and market-history comparisons.

### Generic exchange interface designed around all major venues immediately

Rejected because no concrete multi-exchange requirement exists and premature generalization would increase complexity.

## Revisit when

Revisit only after Coinbase support is mature and a specific second venue has a real product requirement. The second venue should drive the abstraction changes through evidence, not speculation.
