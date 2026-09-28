# ADR 0003 — Canonical One-Minute Market Data

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Strategies may consume higher timeframes such as 15m, 1h, and 4h while execution needs finer temporal information to avoid same-bar look-ahead and unrealistic fills.

Loading independently sourced higher-timeframe candles alongside lower-timeframe execution candles can create inconsistent OHLC boundaries and hidden look-ahead. A single canonical source also makes dataset versioning and reproducibility easier.

## Decision

Use **Coinbase one-minute candles as the canonical candle dataset** for candle-based historical research.

All higher timeframes used by the trading runtime are derived locally from the exact canonical one-minute dataset using deterministic half-open UTC intervals:

`[open_time, close_time)`

Coinbase-provided higher-timeframe candles may be used for validation, but not mixed independently into strategy execution.

Derived bars must preserve source-quality information. Unknown missing one-minute data must not be silently replaced with fabricated flat candles.

## Consequences

### Positive

- all strategy timeframes share one source of truth;
- higher-timeframe close timing is deterministic;
- one-minute execution can resolve many ambiguities hidden in large candles;
- derived data can be hashed and reproduced;
- future trade-level data can improve execution without changing strategy contracts.

### Negative

- historical downloads and storage are larger than higher-timeframe-only data;
- one-minute OHLC still cannot resolve every intraminute path ambiguity;
- substantial history requires efficient columnar storage.

## Rejected alternatives

### Store only each strategy's native timeframe

Rejected because execution would lack sufficient temporal resolution.

### Download every required Coinbase timeframe independently

Rejected because independently sourced bars can disagree or create boundary inconsistencies.

## Revisit when

A future accepted ADR may add trade-level or order-book replay as a higher-fidelity execution source. The one-minute canonical bar dataset may remain the standard candle research layer even then.
