# Phase 002 — Domain Primitives

**Status:** Ready for implementation  
**Date:** 2026-09-28  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Depends on:** Phase 001 accepted at commit `517a1ae605a7a625bfa2f2875d9e8af6506a239b`

## 1. Objective

Create the smallest stable, infrastructure-free domain foundation needed by later Coinbase product, market-data, execution, accounting, and runtime phases.

Phase 002 establishes:

- exact decimal validation/conversion rules;
- UTC timestamp value semantics;
- opaque product/asset identifiers;
- a basic internal UUID-backed entity ID primitive;
- canonical timeframe values;
- immutable candle/domain market primitives;
- foundational side/enums only where immediately useful;
- a small domain error hierarchy;
- deterministic textual encoding/round-trip behavior for foundational value objects;
- property/invariant tests for these primitives.

This phase does **not** implement Coinbase APIs, ProductSpec metadata, datasets, resampling, the trading runtime, orders, fills, accounting, risk, strategies, persistence, or MCP.

## 2. Architectural intent

Later financial code should not repeatedly re-decide:

- whether floats are acceptable financial inputs;
- whether timestamps may be naive;
- how UTC is represented;
- how product IDs are validated;
- what timeframe labels mean;
- what constitutes a structurally valid OHLCV candle;
- whether domain objects are mutable.

These rules become foundational contracts now so later phases build on one interpretation.

Keep the domain layer pure and boring.

## 3. Expected Codex routing

Follow the user's global Codex engineering organization.

The repository remains small and the authoritative paths are obvious, so broad Explorer mapping is **not required by default** for this phase.

Recommended routing:

- **Director — Sol / Medium:** orient, settle cross-boundary decisions, integrate evidence, accept/reject.
- **Back-End Engineer — Terra / Medium:** implement the bounded domain primitives and focused tests.
- **QA Engineer — Luna / Medium:** independently validate the acceptance contract and invariants.
- **Security/Reliability Engineer — Luna / Medium:** perform a bounded read-only review of the critical Decimal/time/candle invariants and source-of-truth semantics.
- **Release Engineer — Luna / Low:** publish after Director acceptance when Codex owns publication.

Security/Reliability is justified here because these primitives become financial and market-data invariants used by every later subsystem.

## 4. Owned change surface

Expected implementation is confined primarily to:

```text
src/command_station/domain/
    __init__.py
    decimal.py
    errors.py
    ids.py
    market.py
    time.py

tests/unit/domain/
tests/property/domain/

pyproject.toml          # only if needed for test/config refinement
uv.lock                 # only if dependencies actually change
README.md               # only if developer commands materially change
```

Exact file boundaries may differ slightly if the implementation is clearer, but do not create future subsystem packages in this phase.

No new runtime dependency should be necessary. Prefer Python standard library plus the already-installed test/tooling stack.

## 5. Domain purity

`command_station.domain` must remain infrastructure-free.

It must not import:

- Coinbase SDKs;
- HTTP clients;
- SQLAlchemy/database libraries;
- PyArrow/Parquet libraries;
- FastAPI;
- MCP packages;
- filesystem/application configuration;
- test libraries.

The existing import-linter setup should be extended only if a meaningful real contract can be expressed without inventing empty layers.

## 6. Exact decimal contract

### 6.1 Representation

Financial/market numeric primitives in this phase use:

```python
decimal.Decimal
```

Do not introduce float-backed money/price/quantity value objects.

### 6.2 Accepted conversion inputs

Provide one small canonical conversion/validation helper for exact decimal input.

It may accept:

- `Decimal`;
- `int`;
- decimal strings.

It must reject:

- `float`;
- booleans;
- NaN;
- positive/negative infinity;
- malformed strings.

The helper must not silently round or quantize.

Coinbase-specific precision normalization belongs to Phase 003 or later execution/product phases.

### 6.3 No global Decimal context mutation

Do not modify the process-global `decimal` context as a side effect of importing the package.

Any future calculation requiring a special context must scope it explicitly.

### 6.4 Sign validators

Provide focused validators/helpers as needed for:

- finite decimal;
- positive decimal;
- non-negative decimal.

Avoid building an elaborate arithmetic wrapper hierarchy.

### 6.5 Serialization convention

When a foundational decimal value is serialized to text, use ordinary base-10 decimal text, never binary float conversion.

Do not force a global fixed number of decimal places in Phase 002.

## 7. UTC timestamp contract

### 7.1 Value object

Create an immutable UTC timestamp primitive, preferably named:

```python
UtcTimestamp
```

or an equivalently explicit name.

It wraps a timezone-aware `datetime`.

### 7.2 Construction

Rules:

- naive datetimes are rejected;
- aware datetimes in a non-UTC offset are accepted only if normalized deterministically to UTC;
- stored/internal value is UTC;
- ordering compares actual UTC instants;
- value object is immutable/hashable.

### 7.3 Text encoding

Canonical textual representation must be deterministic RFC 3339 / ISO-8601 UTC.

Prefer a `Z` suffix for canonical formatting.

Parsing the canonical format must round-trip exactly to the same instant.

Preserve sub-second precision needed by the input; do not invent local timezone behavior.

### 7.4 Wall-clock prohibition

No primitive may call `datetime.now()` implicitly during import or validation.

A convenience "now" factory is unnecessary in this phase.

Runtime clocks are introduced later.

## 8. Internal entity ID primitive

Introduce a small opaque internal entity ID value object backed by `uuid.UUID`.

Requirements:

- immutable;
- hashable;
- comparable for equality;
- parseable from canonical UUID text;
- canonical string formatting;
- explicit factory for a new ID using standard-library UUID generation;
- invalid strings fail with a domain validation error.

Do **not** create OrderId, FillId, BacktestId, TradeId, or other future entity-specific classes yet unless they are required by code in this phase.

Do not encode financial meaning into UUID ordering.

Human-readable prefixes such as `BT_` or `ORD_` are deferred until those entity types exist.

## 9. Asset and product identity

### 9.1 Asset symbol

Create a minimal immutable asset-symbol value object.

Requirements:

- non-empty string;
- leading/trailing whitespace rejected rather than silently stripped;
- embedded whitespace rejected;
- stable string representation.

Do not over-constrain symbols to a speculative token alphabet beyond what the initial Coinbase design requires.

### 9.2 Product ID

Create a minimal immutable `ProductId` value object representing the provider product identifier such as:

```text
BTC-USD
```

Treat the ID as an opaque identifier.

Requirements:

- non-empty;
- no surrounding/embedded whitespace;
- stable string representation;
- immutable/hashable.

Do **not** parse base/quote assets from the product-ID string.

Base/quote identity belongs to the future Coinbase `ProductSpec` because provider metadata is the authority.

Do not silently uppercase/lowercase product IDs.

## 10. Timeframe contract

Create a stable `Timeframe` enum/value type for the canonical candle intervals currently specified by the master engineering spec:

- 1m;
- 5m;
- 15m;
- 30m;
- 1h;
- 2h;
- 4h;
- 6h;
- 1d.

Requirements:

- stable textual code;
- deterministic duration as a `timedelta`;
- parse from supported code;
- unsupported codes fail explicitly;
- equality/hash semantics are stable.

The duration must describe fixed UTC elapsed time. Calendar-aware monthly/weekly bars are out of scope.

## 11. Candle primitive

Create an immutable canonical OHLCV candle value object.

Candidate shape:

```python
Candle(
    product_id=ProductId(...),
    timeframe=Timeframe.ONE_MINUTE,
    open_time=UtcTimestamp(...),
    close_time=UtcTimestamp(...),
    open=Decimal(...),
    high=Decimal(...),
    low=Decimal(...),
    close=Decimal(...),
    volume=Decimal(...),
)
```

Naming may follow normal Python conventions as long as meaning remains clear.

### 11.1 Required candle invariants

A valid candle must satisfy:

- product ID is valid;
- timeframe is supported;
- `close_time > open_time`;
- `close_time - open_time == timeframe.duration`;
- open time aligns to the timeframe boundary in UTC relative to the Unix epoch;
- close time therefore aligns to the next boundary;
- OHLC values are finite and strictly positive;
- volume is finite and non-negative;
- `high >= open`;
- `high >= close`;
- `high >= low`;
- `low <= open`;
- `low <= close`.

Equivalent compact OHLC checks are acceptable if they prove the same contract.

### 11.2 Candle immutability

A Candle must be immutable/hashable or otherwise have immutable value semantics suitable for deterministic replay.

Do not embed mutable lists/dicts.

### 11.3 No source-quality claims yet

Do not introduce dataset gap classification, CandleQuality, raw-provider provenance, dataset IDs, or Parquet-specific metadata in this phase.

Those belong to market-data phases.

This Candle represents a structurally valid canonical bar, not an assertion that an entire dataset is complete.

## 12. Side enum

Introduce a minimal stable trading side enum only because it is a fundamental domain vocabulary item used by subsequent order/fill phases:

```text
BUY
SELL
```

Use stable serialization values.

Do not add order types, time-in-force, position direction, exposure direction, or risk enums yet.

## 13. Domain error hierarchy

Create a small hierarchy rooted in a project domain exception such as:

```python
DomainError
DomainValidationError
```

Specific errors may be added where they materially improve diagnostics, for example:

- InvalidDecimalError;
- InvalidTimestampError;
- InvalidIdentifierError;
- InvalidCandleError;
- UnsupportedTimeframeError.

Avoid a large speculative exception taxonomy.

Invalid user/provider data should fail deterministically with clear messages that identify the violated contract without leaking infrastructure details.

## 14. Immutability convention

Foundational value objects should use immutable semantics, preferably:

```python
@dataclass(frozen=True, slots=True)
```

or an equivalently clear standard-library pattern.

Do not introduce Pydantic merely to implement these primitives.

Pydantic may be evaluated later for application/API schemas; it is not needed in the pure domain layer now.

## 15. Serialization boundary

Phase 002 does not build a generic serialization framework.

It does establish stable textual conventions:

- UUID IDs -> canonical UUID string;
- ProductId/AssetSymbol -> exact validated string;
- Timeframe -> stable code such as `1m`;
- UTC timestamp -> canonical UTC ISO/RFC3339 string;
- Decimal -> base-10 decimal string;
- Side -> stable enum string.

Each foundational value object that has parsing/formatting behavior must have round-trip tests.

Do not add JSON/persistence adapters to the domain package.

## 16. Test requirements

### 16.1 Unit tests

Cover all explicit validation paths, including:

- valid and invalid Decimal conversion;
- float rejection;
- NaN/infinity rejection;
- timestamp naive rejection;
- offset-aware timestamp UTC normalization;
- timestamp canonical string round-trip;
- ID parse/format round-trip;
- invalid product/asset identifiers;
- all supported timeframe parse/duration values;
- unsupported timeframe rejection;
- valid candles;
- each candle OHLC invariant;
- negative volume rejection;
- zero/non-positive OHLC rejection;
- timeframe duration mismatch;
- timeframe boundary misalignment;
- immutability where practical;
- BUY/SELL stable values.

### 16.2 Property tests

Use Hypothesis for properties where it provides real value.

At minimum include properties equivalent to:

1. finite accepted decimal strings round-trip without float conversion;
2. aware datetimes normalized through `UtcTimestamp` preserve the same instant;
3. UUID string -> ID -> string round-trips;
4. generated valid OHLC tuples satisfying `low <= open/close <= high` construct successfully;
5. generated violations of candle price bounds are rejected;
6. valid aligned timestamps + timeframe produce exactly one interval duration.

Do not write property tests that merely restate a constant.

### 16.3 Determinism

Repeated construction/parsing of identical primitive inputs must produce equal values and identical canonical strings.

## 17. Import/dependency validation

The existing Phase 001 gates remain mandatory:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

If no runtime dependency is added, `uv.lock` should not change except for a justified tool/config reason.

Do not add dependencies for functionality available cleanly in the standard library.

## 18. Acceptance criteria

Phase 002 is accepted only when evidence supports all applicable claims:

1. `command_station.domain` exists as a pure infrastructure-free package.
2. Exact decimal conversion rejects floats, booleans, NaN, infinity, and malformed values.
3. Decimal conversion does not quantize or mutate global Decimal context.
4. UTC timestamp rejects naive values and normalizes aware offsets deterministically.
5. UTC timestamp canonical text round-trips.
6. Internal entity ID is immutable and UUID parse/format round-trips.
7. ProductId and AssetSymbol reject empty/whitespace-invalid values without speculative provider parsing.
8. Timeframe supports exactly the agreed initial fixed intervals with tested durations.
9. Candle enforces duration, UTC boundary alignment, finite positive OHLC, non-negative volume, and valid high/low relationships.
10. Candle is immutable.
11. Side contains only BUY/SELL with stable values.
12. Domain validation errors are explicit and bounded.
13. Unit tests cover positive/negative paths.
14. Hypothesis tests exercise meaningful numeric/time/candle invariants.
15. Ruff, strict mypy, import-linter, and pytest pass.
16. No Coinbase API/provider logic was introduced.
17. No persistence, Parquet, database, runtime, order, fill, accounting, risk, strategy, MCP, API, or frontend code was introduced.
18. No new runtime dependency was added without Director-approved necessity.

## 19. Implementation-owner validation

The Back-End Engineer should run the established finite validation gates plus any narrowly focused tests needed while implementing.

Once the changed surface is locally evidenced and ready for QA, stop and hand off.

Do not run a broad invented acceptance program beyond the phase requirements.

## 20. Independent QA assignment

QA receives:

- this phase specification;
- changed-file list;
- implementation evidence;
- relevant architecture rules.

QA should independently validate:

- public primitive behavior;
- negative/edge cases;
- immutability;
- Decimal float/special-value rejection;
- UTC normalization and naive-time rejection;
- timeframe alignment;
- Candle invariants;
- property tests;
- domain import purity;
- full required repository gates;
- absence of out-of-scope subsystem code.

QA must not report PASS solely because static checks succeed.

## 21. Security/Reliability review assignment

After implementation and QA evidence are available, perform a bounded read-only review focused on counterexamples that could corrupt later financial state.

Review specifically:

- float or bool paths that bypass exact Decimal rules;
- NaN/infinity acceptance;
- timezone/naive-datetime leakage;
- ambiguous local-time behavior;
- timestamp equality/order errors;
- candle boundary off-by-one errors;
- malformed OHLC states that still construct;
- accidental mutable state;
- parsing behavior that silently changes identifiers;
- hidden infrastructure dependencies in the domain package.

Return concrete findings only. Do not redesign the API for style.

## 22. Explicitly out of scope

Do not implement:

- Coinbase REST/WebSocket;
- Coinbase ProductSpec;
- base/quote parsing from provider metadata;
- historical importer;
- dataset manifests;
- gap records;
- candle quality/provenance;
- Parquet;
- resampling;
- MarketDataRepository;
- MarketDataFeed;
- TradingRuntime;
- event dispatcher;
- orders;
- fills;
- broker;
- ledger/accounting;
- portfolio;
- risk;
- strategy context;
- indicators;
- analytics;
- jobs;
- MCP;
- API;
- frontend;
- database models;
- paper/live trading.

## 23. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- an invariant conflicts with `AGENTS.md` or the master spec;
- standard-library primitives cannot implement the stated contract cleanly;
- a new runtime dependency appears necessary;
- product-ID rules require provider-specific assumptions not represented in the spec;
- Candle boundary semantics appear inconsistent with the half-open interval rule;
- implementing a primitive requires decisions that materially constrain accounting/execution beyond this phase.

## 24. Definition of done

Phase 002 is done when later phases can safely depend on one small, typed, immutable domain package for exact Decimal handling, UTC instants, identifiers, fixed timeframes, canonical candle structure, and BUY/SELL semantics—with meaningful unit/property evidence that invalid financial/time/market states cannot be constructed through the supported APIs.
