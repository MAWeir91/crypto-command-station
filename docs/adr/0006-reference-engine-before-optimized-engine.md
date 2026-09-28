# ADR 0006 — Reference Engine Before Optimized Engine

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Backtesting workloads can become computationally expensive, especially during parameter optimization. However, execution timing, order state, accounting, and intrabar semantics are difficult to validate when they are introduced first through highly vectorized or compiled logic.

Optimizing incorrect semantics only makes incorrect results faster.

## Decision

Build and preserve a **simple reference simulator** before implementing a separate optimized execution path.

The reference engine should prioritize:

- explicit event ordering;
- inspectability;
- determinism;
- correctness;
- detailed diagnostic capability.

After correctness and end-to-end behavior are established, profiling may justify an optimized simulator.

The optimized engine must match the reference engine for supported scenarios using deterministic financial fingerprints covering fills, prices, quantities, fees, lifecycle outcomes, positions, PnL, and ending equity.

Optimization must not silently change semantics.

## Consequences

### Positive

- the reference engine becomes a correctness oracle;
- debugging remains possible after optimization;
- performance work is driven by profiling;
- Rust/NumPy/compiled kernels can be introduced with an equivalence target.

### Negative

- two execution implementations may eventually require maintenance;
- the first engine will not maximize throughput.

## Rejected alternatives

### Vectorized simulator first

Rejected because hidden semantic compromises are difficult to detect.

### Replace the reference engine after optimization

Rejected because losing the oracle would make regression analysis harder.

## Revisit when

The exact equivalence fingerprint may evolve as domain behavior expands, but the existence of a readable correctness reference should remain.
