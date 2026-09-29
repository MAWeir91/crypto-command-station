# Phase 003 — Coinbase Product Catalog

**Status:** Ready for implementation  
**Date:** 2026-09-28  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Depends on:** Phase 002 accepted at commit `36a9851f75b7ecbc46bd419c3072d7e190f1d9a3`

## 1. Objective

Implement the first Coinbase-specific infrastructure boundary and the immutable product-specification model that later market-data, order-normalization, execution, and backtest provenance phases will depend on.

Phase 003 establishes:

- a pure-domain `ProductSpec`;
- explicit Coinbase venue and spot product-type identity;
- exact Coinbase product increments and minimum/maximum sizes;
- Coinbase trading-status and capability flags;
- deterministic ProductSpec fingerprints;
- immutable product-catalog snapshots;
- deterministic catalog content hashes;
- Coinbase public-product payload normalization;
- an unauthenticated Coinbase Advanced public product adapter;
- strict prevention of accidental credential use;
- provider/domain boundary enforcement;
- focused unit/property tests;
- an optional non-gating live public-API smoke check.

This phase does **not** implement historical candles, raw market-data archives, Parquet datasets, resampling, the trading runtime, orders, fills, accounting, risk, strategies, persistence, MCP, API, paper trading, or live trading.

## 2. Architectural intent

Coinbase is the canonical external venue.

The external Coinbase API is authoritative about current exchange product constraints.

The core domain must not depend on Coinbase SDK response classes or provider payload dictionaries.

The boundary is:

```text
Coinbase Advanced Public Product API
                |
                v
      Coinbase infrastructure adapter
                |
                v
        Payload normalization
                |
                v
             ProductSpec
                |
                v
      ProductCatalogSnapshot
```

Later systems consume `ProductSpec`, not raw Coinbase response objects.

The provider adapter may change if Coinbase changes its SDK or API. The domain contract should remain stable unless the actual trading semantics change.

## 3. Expected Codex routing

Follow the user's global Codex engineering organization.

Broad Explorer mapping is **not required by default** because the repository remains small and the relevant paths are known.

Recommended routing:

- **Director — Sol / Medium:** orient, resolve provider-contract questions, integrate evidence, accept/reject.
- **Back-End Engineer — Terra / Medium:** implement ProductSpec, normalization, Coinbase public adapter, and focused tests.
- **QA Engineer — Luna / Medium:** independently validate domain/provider contracts, negative cases, and full repository gates.
- **Security/Reliability Engineer — Luna / Medium:** review credential isolation, provider trust boundaries, malformed input handling, hashing/version semantics, and fail-safe behavior.
- **Release Engineer — Luna / Low:** publish only after Director acceptance.

Security/Reliability review is required because Coinbase metadata will later authorize precision normalization and trading behavior.

## 4. Owned change surface

Expected changes are primarily:

```text
src/command_station/
    domain/
        __init__.py
        products.py

    market_data/
        __init__.py
        coinbase/
            __init__.py
            products.py

tests/
    unit/
        domain/
            test_products.py
        market_data/
            coinbase/
                test_products.py

    property/
        domain/
            test_product_specs.py

pyproject.toml
uv.lock
```

Small changes to import-linter configuration are expected.

Do not scaffold unrelated future market-data modules.

## 5. Coinbase SDK dependency

Use the official Coinbase Advanced Python SDK:

```text
coinbase-advanced-py
```

The expected dependency range for this phase is:

```text
coinbase-advanced-py>=1.8.4,<2
```

The lockfile remains the exact resolved dependency authority.

Do not add a second HTTP client solely for Coinbase product metadata.

Do not add CCXT.

Do not add a generic multi-exchange library.

Coinbase SDK imports must remain inside the Coinbase infrastructure package.

The domain package must never import the SDK.

## 6. Public API only

Phase 003 uses **only Coinbase Advanced public product endpoints**.

The concrete adapter may use the official SDK equivalents of:

```python
RESTClient.get_public_products(...)
RESTClient.get_public_product(...)
```

Do not use:

```python
get_products(...)
get_product(...)
```

when those calls refer to authenticated/private brokerage endpoints.

No API key is required for Phase 003.

No API secret is required.

No credential file is required.

No authenticated Coinbase capability may be introduced.

## 7. Credential-isolation requirement

The Coinbase SDK can obtain credentials from environment variables when its client is constructed without explicit credential arguments.

Therefore the Phase 003 production adapter must **explicitly disable credentials** when constructing its public REST client.

Conceptually:

```python
RESTClient(
    api_key=None,
    api_secret=None,
    key_file=None,
    timeout=...,
)
```

Do not rely on environment variables being absent.

A developer who happens to have Coinbase credentials exported locally must still get an unauthenticated Phase 003 product client.

The public-product adapter must not send authenticated requests simply because credentials exist in the environment.

This is a hard Security/Reliability invariant.

## 8. Network timeout

All Coinbase public requests must use an explicit finite timeout.

A baseline such as:

```text
10 seconds
```

is appropriate unless current SDK behavior requires a small adjustment.

Do not create an unbounded network request.

Retry/backoff policy belongs to the historical-ingestion phase unless a minimal retry is required by the SDK itself.

## 9. Venue identity

Introduce a minimal stable venue enum/value:

```python
class Venue(StrEnum):
    COINBASE = "coinbase"
```

Do not add Binance, Kraken, Bybit, or speculative future venues.

The purpose is provenance, not multi-exchange abstraction.

## 10. Product type

Introduce a minimal product-type enum/value:

```python
class ProductType(StrEnum):
    SPOT = "SPOT"
```

Phase 003 supports Coinbase spot only.

Do not model:

- futures;
- perpetuals;
- options;
- margin;
- derivatives.

If a provider payload is not `SPOT`, the spot ProductSpec normalizer must reject it rather than incorrectly treating it as spot.

The catalog fetch should request/filter spot products where supported by the current Coinbase public API.

## 11. ProductSpec

Create an immutable pure-domain `ProductSpec`.

Conceptually:

```python
ProductSpec(
    venue=Venue.COINBASE,
    product_type=ProductType.SPOT,
    product_id=ProductId("BTC-USD"),
    base_currency=AssetSymbol("BTC"),
    quote_currency=AssetSymbol("USD"),
    base_increment=Decimal("0.00000001"),
    quote_increment=Decimal("0.01"),
    price_increment=Decimal("0.01"),
    base_min_size=Decimal(...),
    base_max_size=Decimal(...),
    quote_min_size=Decimal(...),
    quote_max_size=Decimal(...),
    status="online",
    is_disabled=False,
    trading_disabled=False,
    cancel_only=False,
    limit_only=False,
    post_only=False,
    auction_mode=False,
    view_only=False,
)
```

Exact field order is not important.

Semantics are.

## 12. ProductSpec numeric invariants

All numeric fields must use the Phase 002 exact Decimal helpers.

Never use float conversion.

Required rules:

```text
base_increment  > 0
quote_increment > 0
price_increment > 0

base_min_size  >= 0
quote_min_size >= 0

base_max_size  > 0
quote_max_size > 0

base_max_size  >= base_min_size
quote_max_size >= quote_min_size
```

Do not quantize these values.

Do not normalize them to a guessed number of decimal places.

Store exactly the constraint represented by Coinbase.

Provider strings such as:

```text
"0.00000001"
```

must become exact `Decimal` values.

## 13. Base and quote identity

The Coinbase payload is authoritative for:

```text
base_currency_id
quote_currency_id
```

Convert those fields into:

```python
AssetSymbol
```

Do **not** derive the currencies by splitting `ProductId`.

For example, do not assume:

```python
base, quote = product_id.split("-")
```

Provider metadata is the authority.

A product ID remains opaque.

## 14. Product identity consistency

A valid ProductSpec must require:

- valid `ProductId`;
- valid base asset;
- valid quote asset;
- base asset != quote asset;
- venue = Coinbase;
- product type = spot.

Do not require that the textual ProductId equals:

```text
BASE-QUOTE
```

That would make the opaque ProductId contract false.

## 15. Coinbase capability/status fields

Preserve relevant current Coinbase product-status information without attempting to reinterpret it prematurely.

Phase 003 ProductSpec should retain:

```text
status
is_disabled
trading_disabled
cancel_only
limit_only
post_only
auction_mode
view_only
```

Each capability field must be an actual boolean.

Do not coerce arbitrary values using Python truthiness.

For example:

```python
bool("false")
```

must never be used for provider normalization.

A malformed non-boolean field is an invalid provider payload.

## 16. Status semantics

Treat Coinbase `status` as opaque provider text.

Requirements:

- it must be a non-empty string;
- surrounding whitespace is invalid;
- preserve its exact provider value;
- do not silently lowercase/uppercase it.

Do not create speculative status enums unless Coinbase's authoritative contract gives us a closed set and a later phase needs it.

The boolean capability fields and raw status remain the source metadata.

## 17. Do not infer tradability

Phase 003 must **not** provide a misleading convenience property such as:

```python
product.can_trade
```

or:

```python
product.is_tradeable
```

Tradability may later depend on:

- provider flags;
- account jurisdiction;
- account permissions;
- trading mode;
- product state;
- system risk state.

Phase 003 records provider product facts only.

Later execution/risk logic decides whether an order is allowed.

## 18. Volatile Coinbase fields are not ProductSpec

The Coinbase product API may also return market-statistic fields such as:

```text
price
mid_market_price
24h volume
24h price change
24h percentage changes
```

These are **not** part of ProductSpec.

Do not include them in:

- ProductSpec equality semantics;
- ProductSpec hashes;
- catalog hashes;
- product-constraint version identity.

ProductSpec represents exchange/product constraints and relevant status—not a ticker snapshot.

This prevents every market-price update from creating a new product-spec version.

## 19. Provider payload normalization

The Coinbase infrastructure layer owns conversion from provider payload to ProductSpec.

Conceptually:

```python
normalize_coinbase_product(payload) -> ProductSpec
```

The normalizer must:

- read required provider fields explicitly;
- validate exact expected primitive types;
- convert decimal strings with Phase 002 helpers;
- convert base/quote IDs to `AssetSymbol`;
- convert product ID to `ProductId`;
- require spot product type;
- preserve status;
- preserve relevant boolean flags;
- reject malformed/missing required fields;
- ignore unknown extra provider fields.

Do not pass raw provider dictionaries into the domain.

Do not make ProductSpec know Coinbase JSON field names.

## 20. Required Coinbase fields

For Phase 003, normalization expects provider equivalents of:

```text
product_id
product_type

base_currency_id
quote_currency_id

base_increment
quote_increment
price_increment

base_min_size
base_max_size
quote_min_size
quote_max_size

status

is_disabled
trading_disabled
cancel_only
limit_only
post_only
auction_mode
view_only
```

If the current authoritative Coinbase API uses a materially different field contract, stop and escalate rather than silently inventing mappings.

Unknown additional fields are allowed and ignored.

Missing required fields are not.

## 21. Missing provider data

Do not substitute guessed defaults for missing Coinbase constraint fields.

Missing data is not equivalent to a default value.

Required missing values cause an explicit provider-normalization failure.

## 22. Provider-specific errors

Do not contaminate the pure domain error hierarchy with HTTP/SDK-specific errors unless the domain contract itself is invalid.

The Coinbase infrastructure package may define focused errors such as:

```text
CoinbaseProductError
CoinbaseProductPayloadError
CoinbaseProductApiError
```

Exact names may vary.

Preserve exception chaining when translating SDK/provider failures.

Do not leak Coinbase SDK exception types through the adapter's public boundary where a bounded project-specific error is appropriate.

## 23. ProductSpec canonical fingerprint

Each ProductSpec must have a deterministic cryptographic content fingerprint.

Use:

```text
SHA-256
```

over an explicit canonical representation.

The fingerprint must include a ProductSpec schema/version marker and all result-affecting ProductSpec fields:

```text
venue
product_type
product_id
base_currency
quote_currency

base_increment
quote_increment
price_increment

base_min_size
base_max_size
quote_min_size
quote_max_size

status

is_disabled
trading_disabled
cancel_only
limit_only
post_only
auction_mode
view_only
```

Use canonical Decimal text from Phase 002.

Do not hash:

- Python `repr`;
- dataclass memory layout;
- dictionary insertion order;
- SDK response serialization;
- volatile ticker fields.

The canonical encoding must be deliberately defined and tested.

## 24. ProductSpec schema version

Introduce an explicit internal product-spec schema version.

Initial value:

```text
1
```

It participates in the fingerprint.

If the meaning of the normalized ProductSpec changes later, the schema version can change deliberately.

Do not treat the Coinbase API version itself as our normalized domain schema version.

## 25. ProductCatalogSnapshot

Introduce an immutable catalog-snapshot value representing one observation of the normalized Coinbase spot catalog.

Conceptually:

```python
ProductCatalogSnapshot(
    venue=Venue.COINBASE,
    observed_at=UtcTimestamp(...),
    products=(...),
)
```

Requirements:

- products are immutable;
- every product has the same venue;
- every product is spot;
- duplicate ProductIds are rejected;
- canonical product ordering is deterministic by ProductId text;
- snapshot exposes deterministic content hash;
- observation time is explicit UTC;
- snapshot remains a pure value object.

## 26. Snapshot content hash

The catalog snapshot content hash must be deterministic and order-independent with respect to source API response ordering.

Equivalent sets of ProductSpecs produce the same catalog content hash regardless of the order Coinbase returned them.

The hash should include:

- catalog schema/version marker;
- venue;
- ordered ProductSpec fingerprints.

Do not include `observed_at` in the **content hash**.

Reason:

Two observations at different times containing identical product metadata represent the same normalized catalog content.

The observation timestamp remains separate provenance.

## 27. ProductSpec observation semantics

`observed_at` means:

> This normalized catalog was observed from Coinbase at this time.

It does **not** mean:

> These constraints were historically valid since this timestamp.

Phase 003 must not pretend we know the historical effective date of a Coinbase rule.

Later datasets/backtests may record that a current product specification was used as an assumption for a historical period.

That provenance must be explicit rather than pretending exact historical knowledge.

## 28. Snapshot immutability/version behavior

Snapshots are immutable.

If Coinbase metadata changes:

```text
old snapshot
    remains unchanged

new fetch
    creates a new snapshot
```

Never mutate an earlier ProductCatalogSnapshot in place.

Persistence of snapshots is not implemented in Phase 003.

Later storage code will persist them.

## 29. Coinbase product adapter

Create a narrow Coinbase product adapter.

A reasonable conceptual interface is:

```python
class CoinbaseProductCatalogClient:
    def list_spot_products(
        self,
        *,
        observed_at: UtcTimestamp,
    ) -> ProductCatalogSnapshot: ...

    def get_spot_product(
        self,
        product_id: ProductId,
    ) -> ProductSpec: ...
```

Exact naming may vary.

Do not expose the Coinbase SDK client through this interface.

## 30. Explicit observation timestamp

Do not hide provenance timing inside the domain model.

For deterministic testing, either:

- accept `observed_at: UtcTimestamp` explicitly when creating a catalog snapshot; or
- inject a tiny time provider into the infrastructure adapter.

Prefer the simpler explicit approach for this phase.

Do not introduce the future TradingRuntime Clock abstraction merely for product fetching.

## 31. Complete catalog semantics

`list_spot_products()` means the complete currently returned Coinbase spot catalog, not an arbitrary first page.

The implementation owner must inspect the current official Coinbase public-products pagination behavior.

If pagination exists:

- iterate until complete;
- preserve deterministic results;
- defend against duplicate ProductIds across pages;
- do not silently truncate.

If the current public endpoint/SDK call returns the complete requested catalog in one response, document/test the actual response contract.

Do not assume completeness without checking the current provider contract.

## 32. Spot filtering

Request `SPOT` products through the provider filter when the current API supports it.

Also defensively reject/filter non-SPOT payloads according to the adapter contract.

Do not normalize futures/perpetuals into spot ProductSpecs.

Do not filter the catalog to USD quote currency in this phase.

The catalog should represent Coinbase spot products generally.

Later research configuration may choose USD-quoted subsets.

## 33. Coinbase response-object isolation

The official SDK returns custom response classes.

Convert them to a plain provider mapping immediately inside the Coinbase infrastructure boundary, such as through the SDK's documented dictionary representation.

Provider SDK classes must not appear in:

```text
command_station.domain
ProductSpec
ProductCatalogSnapshot
research code
future runtime code
```

The SDK is an infrastructure implementation detail.

## 34. Test doubles and network independence

Normal repository tests must not depend on a live Coinbase network connection.

Unit tests should inject/fake the narrow SDK-facing client behavior or use representative provider payload fixtures.

CI must remain deterministic and offline-capable after dependency installation.

Do not mock the ProductSpec itself when testing normalization.

Test the real domain construction path.

## 35. Representative Coinbase fixtures

Create minimal realistic provider fixtures for cases such as:

```text
BTC-USD
ETH-USD
```

Fixtures should contain only the provider fields relevant to this phase plus selected unknown/volatile fields proving they are ignored.

Do not copy giant provider responses unnecessarily.

Do not freeze current market prices in ProductSpec expected values.

## 36. Unit-test requirements

Unit tests must cover at minimum:

### ProductSpec

- valid Coinbase spot ProductSpec;
- immutable behavior;
- positive increments;
- zero/negative increment rejection;
- minimum sizes;
- maximum sizes;
- max < min rejection;
- identical base/quote rejection;
- exact Decimal preservation;
- non-boolean capability-field rejection;
- valid status;
- invalid/empty status.

### Normalizer

- realistic BTC-USD payload;
- realistic ETH-USD payload;
- base/quote sourced from explicit provider currency fields;
- ProductId is not parsed for base/quote;
- missing required field rejection;
- malformed decimal rejection;
- float numeric rejection if a provider fixture incorrectly supplies one;
- malformed boolean rejection;
- unsupported product type rejection;
- unknown provider fields safely ignored;
- volatile ticker fields ignored.

### Fingerprints

- same ProductSpec produces same fingerprint repeatedly;
- field ordering cannot affect fingerprint;
- different increment changes fingerprint;
- different min/max constraint changes fingerprint;
- different status changes fingerprint;
- different capability flag changes fingerprint;
- volatile ticker fields do not affect fingerprint.

### Snapshot

- duplicate product IDs rejected;
- input response order does not change catalog content hash;
- observation time does not change content hash;
- product metadata change changes content hash;
- products stored in deterministic canonical order;
- immutable behavior.

### Coinbase adapter

- uses public product method;
- does not call authenticated product method;
- uses explicit credential `None` values;
- finite timeout configured;
- returns normalized ProductSpec values;
- SDK/provider exception becomes project-specific provider error;
- no raw SDK object escapes.

## 37. Property tests

Use Hypothesis where it provides meaningful invariant coverage.

At minimum include properties equivalent to:

1. positive exact Decimal increments survive ProductSpec construction unchanged;
2. valid min/max pairs where max >= min construct successfully;
3. generated max < min pairs are rejected;
4. product ordering permutations produce the same catalog content hash;
5. changing any included ProductSpec constraint changes its fingerprint;
6. repeated hashing of identical normalized content is deterministic.

Do not build elaborate generators that obscure the business invariant.

## 38. Optional live Coinbase smoke check

A non-CI live check may be used when the worker environment permits outbound network access.

The useful smoke is:

1. construct the explicitly unauthenticated Coinbase product client;
2. fetch `BTC-USD` through the public product endpoint;
3. normalize it to ProductSpec;
4. verify:
   - product ID is `BTC-USD`;
   - product type is spot;
   - base is `BTC`;
   - quote is `USD`;
   - increments are positive;
   - max sizes are not below minimums;
   - fingerprint is produced.

This is useful evidence but must **not** become a mandatory CI dependency.

If network access is unavailable, report the live check as unverified rather than retrying repeatedly.

Deterministic fixture/unit evidence remains the acceptance basis.

## 39. Dependency-direction enforcement

Extend import-linter with a real architecture rule enforcing that:

```text
command_station.domain
```

does not depend on:

```text
command_station.market_data
```

The Coinbase infrastructure layer may depend inward on the domain.

The reverse is prohibited.

Also preserve the existing production-package test dependency prohibition.

## 40. Domain purity

The pure domain product module must not import:

- `coinbase`;
- HTTP libraries;
- database code;
- PyArrow;
- filesystem adapters;
- FastAPI;
- MCP;
- environment-variable utilities.

Allowed dependencies should remain almost entirely standard library plus existing domain modules.

## 41. No persistence yet

Do not create:

- SQL tables;
- SQLite models;
- PostgreSQL models;
- JSON snapshot stores;
- Parquet product files;
- repository classes.

Phase 003 defines immutable snapshot values and provider normalization.

Persistence is introduced when its owning phase requires it.

## 42. No historical-rule invention

Current Coinbase product metadata does not automatically tell us what exchange precision/minimum rules were years ago.

Do not label a current ProductSpec as historical truth.

Future historical backtests may record provenance such as:

```text
product rule provenance:
current Coinbase product spec observed at YYYY-MM-DD
```

rather than making unsupported claims.

## 43. Current data vs product specification

Keep these concepts separate.

Product specification:

```text
increments
minimums
maximums
status
capability flags
currency identities
product identity
```

Current market state:

```text
price
bid/ask
24h volume
24h percentage changes
recent trades
```

Phase 003 implements only the first category.

## 44. Logging

Do not log full provider response bodies during normal successful operation.

Do not log environment variables.

Do not log credentials.

Focused provider failure diagnostics may include:

- endpoint/method name;
- ProductId where applicable;
- bounded error reason.

No sensitive data should exist in this phase anyway.

## 45. Error/failure behavior

Fail loudly when provider metadata cannot be trusted.

Examples:

- required field missing;
- decimal malformed;
- boolean field malformed;
- unsupported product type;
- base == quote;
- maximum below minimum;
- duplicate catalog ProductId.

Do not silently drop malformed spot products from an otherwise successful catalog fetch unless an accepted later policy explicitly says to allow partial catalogs.

A catalog that silently excludes malformed products could incorrectly appear authoritative.

## 46. Complete-catalog atomicity

Catalog normalization is all-or-nothing for one provider response set.

If one required spot product payload is malformed:

```text
catalog snapshot creation fails
```

rather than returning an apparently complete snapshot missing that product.

Later resilience/persistence phases may introduce explicit degraded catalog states if justified.

## 47. Required repository validation

The established gates remain mandatory:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

Because Phase 003 adds a runtime dependency, `pyproject.toml` and `uv.lock` are expected to change.

CI must continue to pass on Python 3.13 and Python 3.14.

## 48. Acceptance criteria

Phase 003 is accepted only when evidence supports all applicable claims:

1. `ProductSpec` is an immutable pure-domain object.
2. Coinbase is the only venue represented.
3. Spot is the only product type represented.
4. ProductSpec uses provider base/quote fields rather than parsing ProductId.
5. All increments and sizes use exact Decimal.
6. Increment/min/max invariants are enforced.
7. Relevant Coinbase status/capability fields are preserved without speculative tradability inference.
8. Provider numeric/boolean values are validated strictly.
9. Missing required provider fields fail loudly.
10. Unknown extra provider fields do not break normalization.
11. Volatile market-statistic fields do not participate in ProductSpec identity.
12. ProductSpec has a deterministic SHA-256 content fingerprint.
13. ProductSpec fingerprint includes an internal schema version.
14. `ProductCatalogSnapshot` is immutable.
15. Duplicate ProductIds are rejected.
16. Catalog ordering is deterministic.
17. Catalog hash is independent of provider response order.
18. Catalog hash excludes observation timestamp.
19. Metadata change creates a different relevant fingerprint/hash.
20. Coinbase adapter uses only public product endpoints.
21. Coinbase adapter explicitly prevents accidental environment credential use.
22. Coinbase network calls have a finite timeout.
23. Provider SDK response objects do not escape the infrastructure boundary.
24. Normal CI/tests require no Coinbase network connection.
25. Domain does not depend on market-data/Coinbase infrastructure.
26. Unit/property tests exercise meaningful positive, negative, and deterministic behavior.
27. Ruff passes.
28. Strict mypy passes.
29. Import-linter passes.
30. Pytest passes.
31. Python 3.13 CI passes.
32. Python 3.14 CI passes.
33. No historical candle ingestion was introduced.
34. No database/persistence was introduced.
35. No order/execution/accounting/risk/strategy code was introduced.
36. No Coinbase credentials or authenticated capabilities were introduced.

## 49. Implementation-owner validation

The Back-End Engineer should run:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

Add narrowly focused test runs while implementing as useful.

If network is available, one public BTC-USD smoke fetch may be included in evidence.

Do not repeatedly retry blocked network access.

After focused evidence is ready, hand off to independent QA.

## 50. Independent QA assignment

QA receives:

- this phase specification;
- changed-file list;
- implementation evidence;
- ProductSpec/public adapter contracts;
- architecture rules.

QA should independently test or inspect:

- exact Decimal semantics;
- min/max relationships;
- malformed provider fields;
- provider base/quote authority;
- ProductId opacity;
- status/capability handling;
- volatile-field exclusion;
- ProductSpec fingerprint determinism;
- snapshot hash determinism;
- duplicate handling;
- catalog order independence;
- public-vs-private Coinbase API usage;
- credential isolation;
- finite network timeout;
- provider exception translation;
- import boundaries;
- full repository gates;
- absence of out-of-scope code.

QA should construct at least a few adversarial provider payloads rather than validating only happy paths.

## 51. Security/Reliability review assignment

Perform a bounded read-only adversarial review after implementation/QA.

Focus specifically on:

### Credential authority

- Does the Coinbase SDK accidentally read existing environment credentials?
- Are `api_key`, `api_secret`, and `key_file` explicitly disabled?
- Can any code path call a private/authenticated product endpoint?
- Is any live-order capability introduced transitively or exposed through the adapter?

### Provider input trust

- Can missing fields silently become defaults?
- Can strings such as `"false"` become `True`?
- Can floats enter Decimal state?
- Can NaN/infinity enter constraints?
- Can max < min survive?
- Can a malformed spot product be silently skipped?

### Fingerprint correctness

- Is hashing based on explicit canonical encoding?
- Can field order alter the result?
- Are all relevant constraints/status flags included?
- Are volatile price fields excluded?
- Is schema version included?
- Is observation time correctly excluded from content identity?

### Snapshot integrity

- Can duplicate ProductIds survive?
- Can provider response ordering change the content hash?
- Can a snapshot mutate after creation?
- Can a non-Coinbase or non-spot ProductSpec enter a Coinbase spot snapshot?

Return concrete findings and counterexamples.

Do not redesign unrelated architecture.

## 52. Explicitly out of scope

Do not implement:

- Coinbase authenticated REST calls;
- API keys;
- secrets;
- accounts;
- fees endpoint;
- orders;
- fills;
- order books;
- WebSocket;
- market trades;
- candles;
- historical candle importer;
- raw candle archives;
- datasets;
- Parquet;
- resampling;
- MarketDataRepository;
- MarketDataFeed;
- TradingRuntime;
- broker;
- ledger;
- accounting;
- portfolio;
- risk;
- strategy runtime;
- indicators;
- optimization;
- database;
- application services;
- MCP;
- FastAPI;
- frontend;
- paper trading;
- live trading;
- derivatives.

## 53. Stop/escalate conditions

Stop and escalate to the Director rather than silently changing the design if:

- the current official Coinbase public product schema materially differs from this phase's required fields;
- the official SDK cannot make public product calls without credentials;
- `coinbase-advanced-py` is incompatible with the project's Python 3.13/3.14 range;
- complete catalog pagination semantics cannot be established confidently;
- Coinbase returns spot products that violate the proposed ProductSpec invariants;
- a required field is legitimately optional according to the current authoritative provider contract;
- another runtime dependency appears necessary;
- ProductSpec design would materially constrain future order/accounting behavior beyond what is specified here.

## 54. Definition of done

Phase 003 is done when Crypto Command Station can take current Coinbase **public spot product metadata**, validate it strictly at the provider boundary, convert it into immutable infrastructure-independent ProductSpecs, and produce a deterministic immutable catalog snapshot whose fingerprints can later anchor dataset and backtest provenance—without credentials, authenticated trading authority, persistence, or market-history functionality.
