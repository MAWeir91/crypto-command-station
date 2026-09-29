# Phase 004 — Historical Coinbase Candle Importer

**Status:** Ready for implementation
**Date:** 2026-09-28
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009
**Depends on:** Phase 003 accepted at commit `beefeda778bf6abf0e80dfb4f50f003f01c11d00`

## 1. Objective

Implement the first historical market-data ingestion path for Crypto Command Station.

Phase 004 retrieves **Coinbase public one-minute spot candles** for an explicit UTC half-open interval, preserves every successful provider payload in a durable raw archive, resumes safely from already archived request pages, normalizes provider candles into the existing immutable `Candle` domain primitive, detects duplicate/conflicting observations, and reports unresolved missing intervals without inventing data.

This phase establishes:

- deterministic one-minute request planning;
- Coinbase's 350-bucket request cap;
- one-candle overlap between adjacent request windows;
- public unauthenticated candle access only;
- finite request timeout and explicit credential isolation;
- bounded deterministic retry for transient failures;
- durable raw provider-payload preservation;
- resumable/idempotent re-execution where practical;
- strict candle normalization;
- cross-page deduplication and conflict detection;
- explicit missing one-minute intervals;
- immutable import result/provenance values;
- unit, property, and focused integration tests.

This phase does **not** create canonical Parquet datasets, gap classifications, higher-timeframe resampling, replay/runtime behavior, or trading functionality.

## 2. Current Coinbase contract

As of 2026-09-28, Coinbase Advanced exposes:

```text
GET /api/v3/brokerage/market/products/{product_id}/candles
```

The official SDK exposes:

```python
RESTClient.get_public_candles(
    product_id,
    start,
    end,
    granularity,
    limit,
)
```

The current official API requires UNIX timestamp `start` and `end`, supports `ONE_MINUTE`, and documents **350 candle buckets maximum per request**.

A successful candle has provider string fields equivalent to:

```json
{
  "start": "1639508050",
  "low": "140.21",
  "high": "140.21",
  "open": "140.21",
  "close": "140.21",
  "volume": "56437345"
}
```

References:

- https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles
- https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/public.py
- https://github.com/coinbase/coinbase-advanced-py/blob/v1.8.4/coinbase/rest/types/product_types.py

If the implementation owner finds that the current authoritative contract materially differs, stop and escalate rather than silently changing provider semantics.

## 3. Pipeline boundary

Phase 004 owns:

```text
Coinbase public candle endpoint
            |
            v
    raw provider payload
            |
            v
       raw archive
            |
            v
 strict normalization
            |
            v
 normalized 1m Candles
            |
            v
 import result + missing-minute evidence
```

Phase 005 will own canonical dataset validation, dataset manifests/quality states, content-addressed dataset versions, and Parquet storage.

The raw archive is source evidence. The canonical dataset does not exist yet.

## 4. Expected Codex routing

Follow the user's global Codex engineering organization.

The repository is now large enough that **Explorer — Luna / Low** is appropriate when the Director benefits from a current map of the Phase 002/003 domain and Coinbase provider boundaries. Explorer remains optional when the relevant source files are already obvious.

Recommended routing:

- **Director — Sol / Medium**
- **Explorer — Luna / Low**, when useful
- **Back-End Engineer — Terra / Medium**
- **QA Engineer — Luna / Medium**
- **Security/Reliability Engineer — Luna / Medium**
- **Release Engineer — Luna / Low**

Security/Reliability review is required because this phase establishes durable market-data evidence and recovery behavior.

## 5. Expected change surface

Primarily:

```text
src/command_station/
    market_data/
        historical.py
        raw_archive.py
        coinbase/
            client.py          # optional shared public-client factory
            products.py        # small refactor permitted
            candles.py

tests/
    unit/market_data/
    unit/market_data/coinbase/
    property/market_data/
    integration/market_data/

pyproject.toml                 # only if justified
uv.lock                        # only if dependency declaration changes
```

Do not scaffold Phase 005+ packages.

## 6. Reuse accepted domain primitives

Reuse:

- `ProductId`
- `UtcTimestamp`
- `Timeframe`
- `Candle`
- Phase 002 exact Decimal rules

Every normalized historical candle must be the existing domain `Candle` with:

```python
timeframe = Timeframe.ONE_MINUTE
```

Do not introduce alternate OHLCV, timestamp, product-ID, or decimal models.

## 7. Public endpoint and credential isolation

Use only:

```python
RESTClient.get_public_candles(...)
```

Do not use the private:

```python
RESTClient.get_candles(...)
```

Preserve the Phase 003 authority boundary. The effective Coinbase public REST construction must remain equivalent to:

```python
RESTClient(
    api_key=None,
    api_secret=None,
    key_file=None,
    timeout=10,
)
```

A small refactor to a shared `create_public_rest_client()` is allowed if it keeps the product-catalog behavior unchanged.

Ambient environment credentials must never become active for historical ingestion.

## 8. Direct dependency hygiene

The Coinbase SDK currently uses `requests`.

If CCS production code directly imports `requests.exceptions` to classify timeouts, connection failures, HTTP 429, and HTTP 5xx, declare `requests` as a direct project dependency rather than relying on it transitively through the SDK.

A suitable compatible range may be:

```text
requests>=2.31,<3
```

Do not inspect exception class names as strings merely to avoid an honest dependency declaration.

## 9. Import interval

CCS imports an explicit UTC half-open interval:

```text
[start, end)
```

Rules:

- `start` and `end` are `UtcTimestamp`;
- `start < end`;
- both are exactly aligned to UTC one-minute boundaries;
- desired candle starts satisfy `start <= open_time < end`.

The number of expected one-minute starts is exactly:

```text
(end - start) / one minute
```

before accounting for missing provider data.

## 10. Completed-candle safety

Do not import the currently forming candle.

The importer must not call wall-clock time implicitly.

The import specification must carry an explicit `as_of: UtcTimestamp` or equivalent completed-through instant.

Define:

```text
completed_boundary = floor(as_of to the UTC minute)
```

Require:

```text
end <= completed_boundary
```

Example:

```text
as_of = 12:34:37Z
latest completed candle = [12:33, 12:34)
maximum end = 12:34Z
```

## 11. Import specification

Use a small immutable value such as:

```python
HistoricalCandleImportSpec(
    product_id=ProductId("BTC-USD"),
    start=UtcTimestamp(...),
    end=UtcTimestamp(...),
    as_of=UtcTimestamp(...),
)
```

Phase 004 is Coinbase spot + one-minute only. Do not add generic future venue/timeframe configuration without a present need.

## 12. UNIX time encoding

Coinbase request boundaries and candle starts use UNIX-second strings.

Requirements:

- UTC only;
- integral seconds;
- deterministic base-10 text;
- no float-rounding dependence;
- no local timezone conversion.

Provider `start` must be a strict integer string.

Reject whitespace, fractions, scientific notation, malformed text, and values that cannot form a supported UTC datetime.

## 13. Request planning

Define:

```python
COINBASE_MAX_CANDLE_BUCKETS = 350
```

Every request explicitly sets `limit <= 350`.

Build a pure deterministic planner that maps the import spec to ordered immutable request windows containing at least:

```text
product_id
request_start
request_end
granularity = ONE_MINUTE
limit
```

The planner must terminate and make strict forward progress.

## 14. Boundary overlap

Adjacent request windows intentionally overlap by **one expected one-minute candle**.

Purpose:

- detect source inconsistencies at chunk boundaries;
- avoid relying on undocumented boundary behavior;
- prevent a boundary candle from disappearing silently.

A full first request may cover at most 350 expected minutes. A subsequent full request advances by at most 349 new minutes because one minute overlaps the preceding request.

Acceptance requires:

- no request over 350;
- deterministic planning;
- one intended one-minute overlap;
- every target minute covered by at least one planned request.

## 15. Provider boundary uncertainty

CCS uses `[start, end)` internally, but do not invent stronger Coinbase inclusivity claims than the official contract supplies.

Determine final target membership from returned candle `start`.

A candle enters final output only when:

```text
spec.start <= candle.open_time < spec.end
```

If Coinbase returns a candle exactly at an internal request end, preserve it raw and let deduplication/target filtering handle it.

A candle before the request start is a provider-contract anomaly and should fail loudly.

## 16. Raw archive

Preserve every successful decoded Coinbase provider response **before normalization**.

The archive supports:

- auditability;
- reprocessing after normalizer bugs;
- source comparison;
- deterministic resume;
- conflict investigation.

The current SDK may archive its plain `to_dict()`/equivalent decoded provider mapping rather than exact HTTP wire bytes. Document that boundary. Preserve unknown provider fields.

Do not reduce the raw archive to normalized OHLCV only.

## 17. Raw archive record

A logical archived page should contain at least:

```text
archive schema version
provider = coinbase
endpoint identity
product_id
granularity
request start
request end
request limit
as_of/import provenance
decoded provider response payload
payload SHA-256
request identity SHA-256
```

No credentials.

## 18. Request identity and raw encoding

Request identity must be deterministic from request semantics:

```text
schema version
provider
endpoint
product_id exact text
granularity
request start
request end
limit
```

Do not include retry attempt, process ID, filesystem root, random UUID, or response body.

Use deliberate canonical UTF-8 JSON + SHA-256 for request/payload identities.

Do not use pickle, Python `repr`, or SDK-object serialization.

## 19. Path safety

`ProductId` is opaque.

Never place unsanitized ProductId text into a filesystem path.

Provider-controlled text such as `../../x` must not escape the archive root.

Prefer safe fixed path segments plus content hashes, for example:

```text
<archive-root>/coinbase/candles/1m/<request-id>.json
```

The archive root must be explicitly supplied, not inferred from the process working directory.

## 20. Archive integrity

On store/read:

- validate schema version;
- recompute request identity;
- recompute payload hash;
- validate request metadata;
- reject corrupt JSON;
- reject incompatible/conflicting existing evidence;
- never silently overwrite a different raw payload.

Use a safe local write pattern such as temp-file + atomic replacement after validation.

Multi-process concurrent writers are out of scope; do not claim concurrency safety that is not implemented.

## 21. Resumability

Use deterministic raw request pages as the resume mechanism.

For every planned request:

```text
if compatible archived page exists:
    validate and reuse it
    do not call Coinbase
else:
    fetch from Coinbase
    archive successful response
    continue
```

This gives crash-resumable and practically idempotent re-execution without a database checkpoint.

A corrupted archived page must fail loudly rather than being silently refetched over.

Automatic refresh/overwrite of prior evidence is deferred.

## 22. Coinbase candle adapter

Create a narrow adapter such as:

```python
class CoinbasePublicCandleClient:
    def fetch_page(self, request: CoinbaseCandleRequest) -> Mapping[str, object]: ...
```

Requirements:

- public method only;
- explicit unauthenticated client;
- finite timeout;
- explicit `ONE_MINUTE`;
- explicit limit;
- integral UNIX strings;
- SDK response converted immediately to a plain mapping;
- no SDK response object escapes infrastructure.

## 23. Response and candle normalization

A successful response must contain `candles` as a sequence/list of provider mappings.

An empty `candles` list is a valid successful response. It is **not** proof of no-trade and does not justify synthetic data.

Each provider candle must contain string fields:

```text
start
low
high
open
close
volume
```

Unknown fields are preserved raw and ignored by the normalizer.

Reject:

- missing required fields;
- non-string required fields;
- floats;
- malformed Decimal text;
- NaN/infinity;
- malformed/nonintegral timestamp text.

Normalize using the existing domain constructor:

```python
Candle(
    product_id=request.product_id,
    timeframe=Timeframe.ONE_MINUTE,
    open_time=...,
    close_time=open_time + one minute,
    open=...,
    high=...,
    low=...,
    close=...,
    volume=...,
)
```

The existing `Candle` invariants remain authoritative.

## 24. Ordering, duplicates, and conflicts

Do not rely on Coinbase response ordering.

Normalize and sort by `open_time`.

At the same `product_id + open_time`:

- identical normalized OHLCV => deduplicate;
- different normalized OHLCV => explicit conflict failure.

Use the same rule within one page and across overlapping pages.

Never choose "first", "last", or "latest" when source observations conflict.

A dedicated error such as `HistoricalCandleConflictError` is appropriate.

Both conflicting raw pages must remain available for investigation.

## 25. Missing intervals

After all pages merge, enumerate every expected one-minute start in `[start, end)`.

Any absent start is explicitly reported as missing.

Do not synthesize a flat zero-volume candle.

Do not classify the missing minute as:

- confirmed no-trade;
- inactive product;
- pre-listing;
- provider outage;
- unknown gap.

Phase 005 owns gap/quality classification.

## 26. Import result

Return an immutable value conceptually similar to:

```python
HistoricalCandleImportResult(
    spec=...,
    candles=(...sorted unique candles...),
    missing_open_times=(...sorted...),
    raw_pages=(...),
    request_count=...,
    fetched_page_count=...,
    reused_page_count=...,
)
```

Requirements:

- candles strictly ascending;
- no duplicate timestamps;
- all output candles in target interval;
- missing times sorted;
- raw page references deterministic;
- fetched vs reused counts distinguishable.

Do not call this a `DatasetVersion`.

Correctness-first in-memory collection is acceptable for the reference importer; avoid quadratic merging and unnecessary copies.

## 27. Retry policy

Use bounded deterministic retry for transient failures.

A reasonable baseline is:

```text
maximum attempts: 4 total
exponential backoff
no jitter
small finite delay cap
```

The exact delay constants may be refined.

Retry:

- connection failures;
- timeouts;
- HTTP 429;
- HTTP 5xx.

Do not automatically retry:

- normal HTTP 4xx other than 429;
- invalid import specs;
- malformed successful payloads;
- archive corruption;
- source conflicts.

Tests must inject/bypass sleeping; unit tests must not wait in real time.

## 28. Partial failure semantics

Raw progress is incremental. The normalized import result is all-or-nothing.

Example:

```text
page 1 succeeds + archives
page 2 succeeds + archives
page 3 fails permanently

=> no successful import result
=> pages 1 and 2 remain
=> next run reuses pages 1 and 2
=> next run resumes at page 3
```

Do not delete valid raw evidence because a later page fails.

Do not parallelize requests in Phase 004.

## 29. Error model

Use a small bounded hierarchy as needed, for example:

```text
HistoricalCandleImportError
HistoricalCandleRequestError
HistoricalCandlePayloadError
HistoricalCandleConflictError
RawArchiveError
RawArchiveCorruptionError
RawArchiveConflictError
```

Exact naming may vary.

Preserve useful exception chaining. Keep provider/SDK details inside the Coinbase boundary.

## 30. Testing requirements

### Request-planner unit tests

Cover:

- <350 minutes;
- exactly 350;
- 351;
- multi-page ranges;
- one-minute overlaps;
- limit never >350;
- deterministic repeated planning;
- forward progress;
- no uncovered target minute;
- invalid/misaligned boundaries;
- start >= end;
- end beyond completed boundary;
- aligned and unaligned `as_of`.

### Coinbase normalization tests

Cover:

- valid realistic candle;
- ascending/descending provider order;
- empty candles;
- missing/non-list candles;
- missing candle field;
- float/non-string numeric field;
- malformed decimal;
- NaN/infinity;
- malformed/whitespace/scientific timestamp;
- misaligned candle start;
- invalid OHLC;
- negative volume;
- unknown fields ignored normalized but retained raw;
- candle at overall end excluded;
- candle before request start rejected.

### Raw archive tests

Cover:

- deterministic request IDs;
- request change alters ID;
- safe path does not expose ProductId traversal;
- store/load round trip;
- payload/request hash verification;
- tamper rejection;
- corrupt JSON;
- schema mismatch;
- identical existing record reuse;
- conflicting record rejection;
- explicit root handling;
- unknown raw fields survive.

### Retry tests

Cover:

- first-attempt success;
- timeout/connection/429/500 then success;
- attempt cap;
- non-429 4xx no retry;
- malformed success no retry;
- injected sleeper/backoff;
- successful page archived once.

## 31. Focused integration tests

Use a fake narrow SDK-facing client plus the **real** planner, archive, normalizer, and importer.

Required scenarios:

### Resume after failure

1. page 1 archives;
2. page 2 fails permanently;
3. import fails;
4. second run uses same archive;
5. page 1 performs no network call;
6. page 2 succeeds;
7. final import completes.

### Overlap deduplication

Adjacent pages contain the same overlap candle with identical OHLCV.

Final output has one candle.

### Overlap conflict

Adjacent pages contain the same timestamp with different OHLCV.

Import fails and both raw pages remain.

### Missing minute

A target minute is absent.

Import succeeds with that minute explicitly reported missing and no synthetic candle.

## 32. Property tests

Use Hypothesis for meaningful invariants.

At minimum:

1. every valid planned request respects the 350-bucket cap;
2. planning terminates and advances for finite valid ranges;
3. every target minute is covered by at least one request;
4. adjacent multi-page plans have the intended one-minute overlap;
5. non-conflicting page-order permutations produce the same sorted merged candles;
6. identical duplicate candles are idempotently deduplicated;
7. a changed OHLCV value at the same timestamp produces a conflict.

Keep generators bounded for fast CI.

## 33. Optional live smoke

A non-CI smoke may fetch a few completed historical BTC-USD one-minute candles through the public unauthenticated endpoint.

Verify:

- raw response archived;
- normalized timestamps valid;
- no candle outside `[start, end)`;
- no credentials;
- explicit request limit.

Do not assert current price values.

Network availability is supplementary evidence, not an acceptance requirement.

## 34. Dependency boundaries

Preserve:

```text
command_station.domain
    must not depend on
command_station.market_data
```

Coinbase infrastructure may depend inward on the domain/market-data abstractions.

Do not create empty future packages merely for import-linter.

## 35. Repository validation

Mandatory:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

CI must continue on Python 3.13 and 3.14.

Update `pyproject.toml` / `uv.lock` only when justified.

## 36. Acceptance criteria

Phase 004 is accepted only when evidence supports all applicable claims:

1. Explicit UTC half-open `[start, end)` imports.
2. Start/end one-minute aligned.
3. Explicit completed-candle boundary; no hidden wall clock.
4. Public `get_public_candles` only.
5. Ambient credentials explicitly disabled.
6. Finite network timeout.
7. `ONE_MINUTE` only.
8. Explicit request limit <=350.
9. Deterministic finite planner with one-minute overlap.
10. Every successful provider response archived before normalization.
11. Raw decoded provider payload preserves unknown fields.
12. Canonical JSON/SHA-256 request and payload identities.
13. ProductId cannot cause archive path traversal.
14. Archived pages validated before reuse.
15. Corruption/conflicting evidence fails loudly.
16. Interrupted reruns reuse compatible archived pages.
17. SDK response objects do not escape infrastructure.
18. Provider candle fields strictly validated.
19. Exact Decimal path; floats/NaN/infinity rejected.
20. Strict integral UNIX candle starts.
21. Existing domain `Candle` used for normalized output.
22. Final candles sorted/unique/in range.
23. Identical overlap candles deduplicated.
24. Different OHLCV for same timestamp fails explicitly.
25. Missing expected minutes exposed.
26. Missing minutes never synthesized/classified prematurely.
27. Bounded deterministic retry for connection/timeout/429/5xx.
28. Non-transient errors do not retry indefinitely.
29. Raw progress survives later-page failure.
30. No `DatasetVersion`, canonical manifest, Parquet, gap quality classification, or resampling.
31. No replay/runtime/trading/accounting/risk/strategy/API/MCP/frontend code.
32. Unit/property/integration tests cover the required invariants.
33. Ruff, strict mypy, import-linter, pytest pass.
34. Python 3.13 and 3.14 CI pass.

## 37. Independent QA assignment

QA should independently exercise:

- 350-cap and overlap arithmetic;
- completed-candle rule;
- target end boundary;
- reverse provider ordering;
- malformed payloads;
- raw archive tamper/corruption;
- path traversal resistance;
- interrupted resume;
- retry/non-retry cases;
- identical and conflicting duplicates;
- explicit missing-minute output;
- public-only endpoint and credential isolation;
- full repository gates;
- absence of Phase 005+ scope.

QA must not PASS solely from static inspection.

## 38. Security/Reliability review

Review adversarially:

### Authority
- Can any private/authenticated endpoint run?
- Can environment credentials activate?
- Can malformed successful payloads be retried forever?

### Time
- Can naive/unaligned time enter?
- Can the forming minute enter?
- Is `[start,end)` off by one?
- Can UNIX conversion lose precision?

### Planning
- Can a request exceed 350?
- Can planning fail to advance?
- Can a target minute be uncovered?

### Archive
- Can ProductId escape archive root?
- Are hashes recomputed on read?
- Can partial/corrupt data be trusted?
- Can different evidence silently overwrite old evidence?
- Is raw payload preserved before normalization?

### Recovery
- Is retry bounded?
- Are 4xx errors retried incorrectly?
- Does resume really skip archived calls?

### Data truth
- Can conflicting candles be silently selected?
- Can missing data become fabricated candles?
- Can response ordering change final output?

Return concrete findings only.

## 39. Explicitly out of scope

Do not implement:

- authenticated Coinbase candles;
- credentials/accounts/orders/fills/fees;
- WebSocket/live trades/live candle building/order book;
- `DatasetVersion`;
- canonical dataset manifests/quality states;
- gap-reason classification;
- Parquet/PyArrow/DuckDB canonical storage;
- 5m+ resampling;
- derived caches;
- `MarketDataRepository`;
- `MarketDataFeed`;
- `HistoricalReplayFeed`;
- `TradingRuntime`;
- broker/accounting/portfolio/risk/strategies/indicators/analytics;
- optimization;
- database;
- MCP/API/frontend;
- paper/live trading.

## 40. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- Coinbase no longer documents the 350-bucket cap;
- public candles require authentication;
- one-minute semantics materially change;
- endpoint boundary behavior cannot be reconciled with overlap/filtering;
- the SDK cannot expose a faithful decoded payload for archival;
- retry classification requires brittle exception-name inspection;
- safe resumability requires a database/concurrency architecture not authorized here;
- live verification repeatedly shows conflicting Coinbase history;
- importer correctness requires Phase 005 gap-quality decisions.

## 41. Definition of done

Phase 004 is done when Crypto Command Station can deterministically request an arbitrary **completed** UTC range of Coinbase public one-minute spot candles in bounded overlapping pages, preserve each successful provider payload as durable raw evidence, resume after interruption without unnecessarily refetching completed pages, strictly normalize source candles into the accepted domain model, deduplicate identical overlaps, reject conflicting history, and expose missing source minutes without fabricating or prematurely classifying them.

The output is trustworthy historical **source evidence plus normalized import results**.

It is not yet a canonical research dataset.
