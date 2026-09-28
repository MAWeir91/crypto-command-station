# ADR 0007 — Parquet for Historical Market Data

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Historical one-minute Coinbase data will grow to millions of rows across products and years. Backtests frequently read bounded time ranges and selected columns. Bulk candle history is a poor fit for the primary application metadata database, while research tooling benefits from Arrow-compatible columnar formats.

## Decision

Store canonical historical candle datasets and large derived market-data artifacts in **Parquet/Arrow-compatible columnar files**.

Use a relational database for searchable application metadata such as dataset manifests, backtest summaries, strategy identities, jobs, policies, and future deployments.

Use DuckDB or similar analytical tooling for ad-hoc queries over Parquet when useful.

Raw provider responses remain separately archived.

Derived timeframe caches may also use Parquet and must include canonical dataset identity plus resampler version in their cache identity.

## Consequences

### Positive

- efficient columnar scans;
- compression;
- partition pruning;
- compatibility with PyArrow, Polars/pandas, DuckDB, NumPy, and future Rust tooling;
- easier separation between immutable bulk data and mutable application metadata.

### Negative

- metadata and bulk data span different storage systems;
- atomic dataset publication/manifests require care;
- file layout and partition strategy need explicit management.

## Rejected alternatives

### PostgreSQL as the primary candle store

Rejected because bulk immutable candle history does not need transactional row-oriented behavior and would increase database size/operational burden.

### CSV

Rejected because typing, compression, metadata, and scan performance are materially weaker.

## Revisit when

Revisit only if measured workload or deployment constraints demonstrate that another storage layer materially improves correctness or operational simplicity. Any replacement must preserve immutable dataset identity and reproducibility.
