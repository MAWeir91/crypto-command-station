# Phase 006 — Deterministic Timeframe Resampling & Derived Cache

**Status:** Ready for implementation  
**Date:** 2026-09-29  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Depends on:** Phase 005 fully sealed through test-evidence closure commit `63614c2fcfd762e1ac864c0e8235453bad37f5f9`

## 1. Objective

Implement deterministic higher-timeframe candle derivation from an exact immutable Phase 005 canonical one-minute `DatasetVersion`.

Phase 006 establishes:

- deterministic UTC bucket planning;
- local resampling from canonical one-minute candles only;
- exact OHLC aggregation;
- exact context-independent Decimal volume summation;
- strict prevention of partial aggregate candles;
- explicit derived-gap evidence when any required source minute is unresolved;
- conservative source-quality propagation;
- versioned resampler semantics;
- deterministic derived-cache identity;
- immutable local derived Parquet cache;
- exact Decimal-text persistence;
- artifact and manifest integrity validation;
- deterministic cache round-trip into existing domain `Candle` values;
- unit, property, integration, QA, and reliability evidence.

Phase 006 does **not** implement historical replay, runtime event ordering, strategies, indicators, execution, accounting, or application interfaces.

---

## 2. Architectural authority

The accepted architecture requires:

```text
canonical Coinbase 1m DatasetVersion
          |
          v
deterministic local resampler
          |
          v
derived higher-timeframe candles
          |
          v
optional immutable derived cache
```

ADR 0003 requires all strategy-facing higher-timeframe candles to derive locally from the exact canonical one-minute source.

Coinbase higher-timeframe candles must not be mixed into normal historical strategy/execution inputs.

ADR 0007 permits derived market-data artifacts to use Parquet.

The master engineering spec requires derived cache identity to include at least:

```text
canonical dataset version/hash
target timeframe
resampler version
```

---

## 3. Supported target timeframes

The accepted domain `Timeframe` enum currently contains:

```text
1m
5m
15m
30m
1h
2h
4h
6h
1d
```

Phase 006 derives:

```text
5m
15m
30m
1h
2h
4h
6h
1d
```

from canonical `1m`.

Reject `Timeframe.ONE_MINUTE` as a resampling target.

The canonical source is already one minute; do not create a redundant 1m derived cache.

Do not add new timeframe values.

---

## 4. Expected Codex routing

Follow the user's global Codex engineering organization.

Recommended routing:

- **Director — Sol / Medium:** orient, enforce source/derived identity boundaries, integrate evidence, accept/reject.
- **Explorer — Luna / Low:** use if useful to map the Phase 005 dataset/store contracts and domain `Timeframe` semantics.
- **Back-End Engineer — Terra / Medium:** implement planner, resampler, derived model/cache, and tests.
- **QA Engineer — Luna / Medium:** independently validate bucket boundaries, gaps, Decimal exactness, identity, cache integrity, and repository gates.
- **Security/Reliability Engineer — Luna / Medium:** review derived-source authority, path safety, immutable cache publication, corruption handling, and no-fabrication guarantees.
- **Release Engineer — Luna / Low:** publish after Director acceptance.

Security/Reliability review is required because Phase 006 introduces another durable data artifact and must never obscure incomplete canonical source history.

---

## 5. Expected change surface

Primarily:

```text
src/command_station/
    market_data/
        resampling.py
        derived_cache.py

tests/
    unit/
        market_data/
            test_resampling.py
            test_derived_cache.py

    property/
        market_data/
            test_resampling_properties.py

    integration/
        market_data/
            test_derived_cache_store.py
```

Small exports/refactors inside existing market-data modules are allowed when necessary.

Expected:

```text
pyproject.toml unchanged
uv.lock unchanged
```

PyArrow is already present from Phase 005.

Do not scaffold Phase 007 runtime/replay packages.

---

## 6. Source contract

The resampler accepts only an accepted Phase 005:

```python
CanonicalCandleDataset
```

Requirements:

- venue = Coinbase;
- product type = SPOT;
- timeframe = 1m;
- valid immutable `DatasetVersion`;
- source interval/provenance from Phase 005;
- source candle/gap accounting already valid.

Do not accept arbitrary lists of candles as the primary Phase 006 source-of-truth API.

A lower-level pure aggregation helper may operate on bounded candle sequences for testing, but public resampling must be anchored to a canonical source dataset.

---

## 7. No network access

Phase 006 performs no Coinbase HTTP request.

Do not call:

- public candle endpoints;
- private candle endpoints;
- product endpoints;
- WebSockets.

Higher-timeframe source truth is the canonical one-minute `DatasetVersion`.

---

## 8. UTC alignment rule

Every target bucket is a fixed UTC half-open interval:

```text
[bucket_open, bucket_close)
```

where:

```text
bucket_close = bucket_open + target_timeframe.duration
```

and `bucket_open` is aligned to the existing domain `Candle` alignment rule:

```text
(bucket_open - Unix epoch) % timeframe.duration == 0
```

This gives:

- 5m aligned on UTC 00,05,10,... minutes;
- hourly aligned on UTC hour boundaries;
- 2h/4h/6h aligned from Unix-epoch UTC boundaries;
- 1d aligned to UTC midnight.

Do not use local time, exchange-local time, DST, or user timezone.

---

## 9. Pure bucket planner

Implement a pure deterministic planner such as:

```python
plan_resample_buckets(
    source_start: UtcTimestamp,
    source_end: UtcTimestamp,
    target_timeframe: Timeframe,
) -> tuple[ResampleBucket, ...]
```

Each bucket should contain at least:

```text
open_time
close_time
target timeframe
required one-minute count
```

Requirements:

- target timeframe must be >1m;
- bucket must be fully contained in source `[start,end)`;
- no partial leading bucket;
- no partial trailing bucket;
- deterministic ascending order;
- no overlap between target buckets;
- no gaps between adjacent eligible target buckets;
- planner terminates.

---

## 10. Partial source edges

A canonical dataset need not begin/end on a target-timeframe boundary.

Example:

```text
source: [00:01, 00:16)
target: 5m
```

Eligible full buckets are:

```text
[00:05,00:10)
[00:10,00:15)
```

The minutes:

```text
00:01–00:05
00:15–00:16
```

are excluded edge coverage.

They are **not**:

- synthetic candles;
- derived gaps;
- errors.

They simply cannot form a complete target bucket.

The derived manifest must expose enough accounting to make this trimming visible.

---

## 11. Edge accounting

Record at least:

```text
source_expected_minute_count
eligible_bucket_count
eligible_source_minute_count
excluded_edge_minute_count
```

Validate:

```text
eligible_source_minute_count
    = eligible_bucket_count * target_duration_minutes
```

and:

```text
excluded_edge_minute_count
    = source_expected_minute_count - eligible_source_minute_count
```

This prevents silent disappearance of partial source coverage.

---

## 12. Empty eligible result

A valid source interval may contain no complete target bucket.

Example:

```text
source: [00:01,00:04)
target: 5m
```

The resampler may return a valid derived result with:

```text
eligible_bucket_count = 0
bars = ()
derived_gaps = ()
```

No fake Parquet file is required.

Source quality is still preserved in the derived manifest.

Do not manufacture a partial candle merely to avoid an empty result.

---

## 13. Complete-bucket requirement

A derived candle may be emitted only when **every one-minute source interval required by the target bucket contains a canonical source candle**.

For target timeframe `T`:

```text
required_count = T.duration / 1 minute
```

Examples:

```text
5m  -> 5 source candles
1h  -> 60 source candles
1d  -> 1440 source candles
```

No fewer source candles are acceptable.

---

## 14. Aggregate OHLCV semantics

For a complete target bucket:

```text
open   = first source candle open
high   = maximum source high
low    = minimum source low
close  = last source candle close
volume = exact sum of source volumes
```

Create the existing domain:

```python
Candle(
    product_id=...,
    timeframe=target_timeframe,
    open_time=bucket_open,
    close_time=bucket_close,
    ...
)
```

The domain `Candle` remains the final structural authority.

---

## 15. Exact Decimal aggregation

Do not convert any source OHLCV value to binary float.

Open/high/low/close remain exact `Decimal` values.

Volume summation must be mathematically exact and independent of ambient Decimal context precision.

A naïve `sum(Decimal(...))` under a low-precision global/local Decimal context may round.

The implementation must use an exact summation method whose result does not change when surrounding Decimal precision changes.

The resampler must not mutate the caller's Decimal context.

This is a hard deterministic-data invariant.

---

## 16. Exact volume-sum evidence

Tests must demonstrate that the same source bucket produces the same exact volume under materially different ambient Decimal precision settings.

Include values whose exact total would expose ordinary context rounding.

Example category:

```text
large coefficient + small exact fractional contribution
```

Do not merely test tiny integers.

---

## 17. Derived gaps

If any required one-minute source interval within an eligible target bucket is a source `GapRecord`, do **not** emit a partial aggregate `Candle`.

Instead create immutable derived-gap evidence, conceptually:

```python
DerivedGapRecord(
    open_time=bucket_open,
    close_time=bucket_close,
    reason=GapReason.MISSING_SOURCE,
    source_gap_open_times=(...),
)
```

The exact name may vary.

Requirements:

- target bucket aligned;
- target duration exact;
- at least one source gap;
- source gap timestamps sorted/unique;
- every referenced source gap lies within the target bucket;
- no derived bar and derived gap may share the same target open time.

---

## 18. Current gap authority

Under the accepted Phase 005 implementation, canonical publication currently accepts only:

```text
GapReason.MISSING_SOURCE
```

Therefore Phase 006's normal path currently propagates only unresolved missing-source gaps.

Do not invent:

- `CONFIRMED_NO_TRADE`;
- `INACTIVE_NOT_YET_LISTED`;
- `UNKNOWN`;

from missing source data.

If Phase 005 gap authority expands later, revise resampling semantics deliberately rather than guessing how mixed reasons combine.

---

## 19. No partial aggregation around gaps

For this source bucket:

```text
00:00 candle
00:01 candle
00:02 MISSING_SOURCE
00:03 candle
00:04 candle
```

targeting 5m:

```text
[00:00,00:05)
```

Phase 006 produces:

```text
no 5m Candle
one DerivedGapRecord for [00:00,00:05)
```

Do not aggregate the four available candles.

Do not use previous close.

Do not use zero volume.

Do not call it valid.

---

## 20. Derived quality

Reuse the accepted `DatasetQuality` vocabulary where semantically appropriate.

Under the current Phase 005 source model, Phase 006 normally produces:

```text
VALID
INCOMPLETE
```

Rules:

```text
if source quality is INCOMPLETE:
    derived quality = INCOMPLETE
elif any eligible derived bucket is unresolved:
    derived quality = INCOMPLETE
else:
    derived quality = VALID
```

Phase 006 must never upgrade an incomplete source dataset to `VALID`.

`VALID_WITH_KNOWN_NO_TRADE_INTERVALS` is not automatically produced in the current source model.

---

## 21. Per-bar validity vs dataset quality

A derived `Candle` is emitted only from a fully resolved source bucket.

Therefore every emitted bar is structurally complete.

The overall derived result may still be `INCOMPLETE` because:

- another target bucket contains a source gap; or
- the source canonical dataset itself is `INCOMPLETE`.

Do not encode "partial" candles.

---

## 22. Resampler version

Introduce an explicit integer constant such as:

```python
RESAMPLER_VERSION = 1
```

This version identifies the semantic aggregation algorithm.

A future change that can alter derived logical output for the same:

```text
source DatasetVersion + target timeframe
```

must increment the resampler version.

Pure performance refactors that provably preserve output need not automatically change it.

Do not use package version or PyArrow version as the resampler version.

---

## 23. DerivedCacheKey

Introduce an immutable validated SHA-256-backed cache identity such as:

```python
DerivedCacheKey
```

Compute it from explicit canonical data containing at least:

```text
derived cache-key schema version
source DatasetVersion
target timeframe
resampler version
```

The same source DatasetVersion/timeframe/resampler version must always produce the same key.

The key must not depend on:

- local filesystem root;
- source Parquet physical bytes;
- target Parquet physical bytes;
- process ID;
- publication time;
- random UUID;
- Python object identity.

---

## 24. Cache identity and source provenance

The source `DatasetVersion` already binds:

- canonical logical candle content;
- source gaps;
- source raw evidence;
- source interval;
- source `as_of`;
- accepted ProductSpec provenance;
- canonicalization schema.

Do not duplicate absolute raw paths into derived cache identity.

Do not key derived cache from a mutable "latest dataset" concept.

---

## 25. ResampledCandleDataset

Introduce an immutable derived result value, conceptually:

```python
ResampledCandleDataset(
    cache_key=...,
    source_dataset_version=...,
    source_quality=...,
    venue=Venue.COINBASE,
    product_type=ProductType.SPOT,
    product_id=...,
    target_timeframe=...,
    resampler_version=...,
    source_start=...,
    source_end=...,
    source_as_of=...,
    bars=(...),
    gaps=(...),
    quality=...,
    eligible_bucket_count=...,
    excluded_edge_minute_count=...,
    logical_bar_content_sha256=...,
    logical_gap_content_sha256=...,
    derived_result_sha256=...,
)
```

Exact naming may vary.

Do not call this a new canonical `DatasetVersion`.

Canonical one-minute source truth remains Phase 005.

Derived data is reproducible cacheable output.

---

## 26. Logical derived hashes

Compute explicit deterministic SHA-256 hashes for:

### Bar content

Ordered derived Candle content using:

- product ID;
- target timeframe;
- open/close time;
- canonical Decimal text OHLCV.

### Gap content

Ordered derived-gap records using:

- bucket open/close;
- reason;
- ordered source gap timestamps.

### Derived result

Combine at least:

```text
source DatasetVersion
target timeframe
resampler version
eligible/excluded coverage accounting
derived quality
bar content hash
gap content hash
```

These hashes support integrity verification.

They do not replace the deterministic `DerivedCacheKey`.

---

## 27. Pure resampling API

Provide one focused pure resampling boundary, conceptually:

```python
resample_canonical_dataset(
    source: CanonicalCandleDataset,
    target_timeframe: Timeframe,
) -> ResampledCandleDataset
```

It must:

1. validate source type/timeframe;
2. validate target timeframe;
3. plan full target buckets;
4. match source candles/gaps to each required minute;
5. emit complete bars or derived gaps;
6. derive quality;
7. compute hashes/cache key;
8. return an immutable result.

No filesystem or network access belongs in this function.

---

## 28. Deterministic scan

Use an ordered linear or otherwise clearly deterministic scan of the already canonical source sequence.

Avoid quadratic repeated searching across long histories.

No parallel processing is needed inside one resampling run.

Determinism and clarity are more important than premature optimization.

---

## 29. Derived Parquet persistence

Use PyArrow already accepted in Phase 005.

Persist derived bars using an explicit schema equivalent in meaning to:

```text
product_id   : string
timeframe    : string
open_time    : timestamp[us, tz=UTC]
close_time   : timestamp[us, tz=UTC]
open         : string
high         : string
low          : string
close        : string
volume       : string
```

OHLCV remains canonical Decimal text.

Do not persist gaps as fake bar rows.

---

## 30. Derived cache layout

Use a separate explicit cache root.

A reasonable layout:

```text
<derived-cache-root>/
  coinbase/
    spot/
      5m/
        <derived-cache-key>/
          manifest.json
          year=2025/
            month=01/
              part-00000.parquet
```

For other target timeframes, replace `5m` with the trusted enum value.

Do not place ProductId text in filesystem paths.

---

## 31. Derived partitioning

Partition actual derived bars by UTC `open_time` year/month.

Each artifact must:

- contain only one target timeframe;
- contain one product;
- contain rows matching its UTC partition path;
- be strictly ascending by open time;
- use exact canonical schema;
- contain no derived gaps.

No file is needed for a month containing only derived gaps.

---

## 32. Derived manifest

Create a deterministic canonical JSON manifest containing at least:

```text
derived manifest schema version
derived cache schema version
cache key
source DatasetVersion
source quality
venue
product type
product_id
target timeframe
resampler version
source start
source end
source as_of

source expected minute count
eligible bucket count
eligible source minute count
excluded edge minute count

derived quality
bar count
derived gap count

logical bar content SHA-256
logical gap content SHA-256
derived result SHA-256

derived gap records

Parquet artifact records
```

Artifact records should include:

```text
relative path
row count
first open time
last open time
byte size
SHA-256 byte hash
```

No wall-clock `created_at` is needed.

---

## 33. Deterministic manifest encoding

Use canonical UTF-8 JSON with deliberate stable rules:

- stable key ordering;
- stable enum text;
- canonical UTC timestamp text;
- canonical SHA-256 lowercase text;
- no random fields;
- no physical absolute paths.

Equivalent derived results should produce byte-for-byte equivalent manifest content under the same schema version.

---

## 34. Derived cache store

Implement a local derived cache store, conceptually:

```python
class LocalDerivedCandleCache:
    def publish(self, derived: ResampledCandleDataset) -> Mapping[str, object]: ...

    def load(self, key: DerivedCacheKey) -> ResampledCandleDataset: ...

    def load_manifest(self, key: DerivedCacheKey) -> Mapping[str, object]: ...
```

Exact API may vary.

The cache root must be explicit.

Do not infer from current working directory.

---

## 35. Cache immutability

For a given `DerivedCacheKey`:

- valid existing cache may be verified/reused;
- incompatible/corrupt existing cache must fail loudly;
- do not silently overwrite.

Derived cache is disposable/rebuildable by an explicit higher-level action, but this store should not auto-delete or auto-repair corrupted evidence.

Do not hide integrity failures behind automatic regeneration.

---

## 36. Atomic publication

Use the same class of staging discipline established in Phase 005:

```text
validate derived result
      |
      v
write staging artifacts + manifest
      |
      v
verify staging
      |
      v
atomic final publication
```

A failed publication must not leave a directory that appears valid.

Clean only owned staging artifacts.

---

## 37. Path and symlink safety

Use fixed trusted path segments plus:

- target Timeframe enum value;
- validated SHA-256 cache key;
- deterministic year/month numeric partitions.

Do not interpolate arbitrary ProductId.

Protect against:

- `..`;
- path separators in uncontrolled text;
- symlink escape from configured cache root;
- staging directory symlink redirection;
- manifest/artifact symlink escape.

Follow the accepted Phase 005 local-store safety model where appropriate.

---

## 38. Derived cache load verification

Load must verify at least:

1. canonical manifest encoding;
2. manifest schema versions;
3. requested cache key;
4. recomputed cache key from source version/timeframe/resampler version;
5. artifact existence;
6. artifact byte size/hash;
7. Parquet schema;
8. artifact row counts/ranges;
9. partition path/timeframe consistency;
10. reconstructed domain `Candle` validity;
11. every loaded Candle uses target timeframe;
12. bar ordering/uniqueness;
13. derived-gap structure/order/uniqueness;
14. bar/gap bucket disjointness;
15. eligible bucket accounting;
16. logical bar hash;
17. logical gap hash;
18. derived result hash;
19. manifest reconstructed semantics.

Do not trust only Parquet metadata.

---

## 39. Exact read-back

Read OHLCV string columns through the accepted Decimal/Candle path.

Do not convert through float.

Use the same UTC-safe PyArrow timestamp approach proven in Phase 005.

Reject:

- null required values;
- wrong physical types;
- malformed Decimal text;
- mismatched timeframe;
- wrong bucket duration;
- wrong partition membership.

---

## 40. Cache content vs cache key

`DerivedCacheKey` is the lookup identity:

```text
source DatasetVersion + target timeframe + resampler version
```

Derived output hashes are independent integrity evidence.

Do not make the cache key depend on Parquet byte hashes.

Equivalent logical source/timeframe/resampler inputs must retain the same cache key even if future compatible writer settings produce different physical bytes.

---

## 41. Resampler-version discipline

If implementation changes alter any of:

- bucket membership;
- OHLC rules;
- gap handling;
- Decimal volume result;
- source-quality propagation;

then the accepted resampler version must change.

Do not change algorithm semantics while leaving the same version merely to preserve cache hits.

---

## 42. No mutable "latest" derived cache

Do not create:

```text
latest
current
preferred
```

pointers or symlinks.

A derived cache is resolved from:

```text
source DatasetVersion
target Timeframe
resampler version
```

Later application services may choose dataset versions explicitly.

---

## 43. No Coinbase aggregate validation in Phase 006

Do not download Coinbase 5m/1h/etc. candles merely to compare outputs.

That may become a separate validation/research task later.

Phase 006 normal operation is fully offline from a canonical DatasetVersion.

---

## 44. Unit tests — bucket planning

Cover at minimum:

- 5m alignment;
- 15m alignment;
- 30m alignment;
- 1h alignment;
- 2h/4h/6h epoch alignment;
- 1d UTC-midnight alignment;
- aligned source boundaries;
- unaligned leading edge;
- unaligned trailing edge;
- both edges unaligned;
- zero complete target buckets;
- exact one complete target bucket;
- multiple complete buckets;
- 1m target rejected;
- every planned bucket fully contained in source;
- no overlap between target buckets;
- exact eligible/excluded minute accounting.

---

## 45. Unit tests — OHLCV aggregation

Cover at minimum:

- open from first minute;
- close from last minute;
- maximum high;
- minimum low;
- exact volume sum;
- source product preserved;
- target timeframe assigned;
- target open/close exact;
- source input not mutated;
- ambient Decimal context not mutated;
- exact volume unaffected by low/high ambient precision.

Use cases that would detect rounding if naïve Decimal summation were used.

---

## 46. Unit tests — gap propagation

Cover at minimum:

- one source gap in target bucket => no bar;
- multiple source gaps => one derived gap with all source timestamps;
- source gap at first minute;
- source gap at final minute;
- gaps in different target buckets => separate derived gaps;
- gap only in excluded partial edge does not create fake target gap;
- no bar/gap collision;
- derived gap reason remains `MISSING_SOURCE`.

---

## 47. Unit tests — quality

Cover:

- VALID source + no eligible gaps => VALID derived result;
- VALID source + eligible derived gap => INCOMPLETE;
- INCOMPLETE source => derived result remains INCOMPLETE even if all eligible buckets happen to be complete;
- zero eligible buckets from VALID source => no fabricated bars/gaps;
- quality cannot be caller-forced.

---

## 48. Unit tests — identity

Cover:

- same source version/timeframe/resampler => same cache key;
- source DatasetVersion change => cache key changes;
- target timeframe change => cache key changes;
- resampler version change => cache key changes;
- local filesystem root does not affect key;
- Parquet byte representation does not define key;
- logical bar hash changes when an aggregate OHLCV value changes;
- logical gap hash changes when gap evidence changes.

---

## 49. Property tests

Use Hypothesis meaningfully.

At minimum include properties equivalent to:

1. generated complete source buckets aggregate to:
   - first open;
   - max high;
   - min low;
   - last close;
   - exact volume sum;
2. every generated emitted target bar is aligned, full-duration, and fully contained in the source interval;
3. injecting any one-minute source gap into an eligible bucket prevents that bucket from emitting a bar;
4. generated gap sets produce exact bar+gap accounting across all eligible target buckets;
5. cache key is invariant to irrelevant object/filesystem construction details but changes when source DatasetVersion or target timeframe changes;
6. exact volume aggregation is invariant under bounded changes to ambient Decimal precision.

Keep examples bounded for normal CI.

---

## 50. Integration tests

Use real:

- `CanonicalCandleDataset`;
- resampler;
- PyArrow derived writer;
- local derived cache;
- derived manifest loader.

Required scenarios:

### Complete 5m derivation

A complete 1m source forms deterministic 5m bars.

Publish/load returns identical derived semantics.

### Multi-timeframe derivation

The same canonical DatasetVersion produces distinct deterministic keys/results for at least two target timeframes.

### Incomplete source bucket

A source gap suppresses the affected aggregate candle and persists explicit derived-gap evidence.

### Edge trimming

Unaligned canonical source boundaries produce only fully contained target bars.

### Month boundary

Derived bars partition according to target bar `open_time` UTC month.

### Idempotent republish

Publishing the same derived result twice verifies/reuses the existing cache.

### Corruption

Tampering with a derived Parquet artifact causes explicit integrity failure.

### Empty eligible result

A source interval too short to form the target timeframe publishes/loads without a fake Parquet bar.

---

## 51. Security/Reliability review

Perform a bounded adversarial review.

### Source authority

- Can noncanonical 1m data enter the public resampler?
- Can Coinbase higher-timeframe data bypass canonical source truth?
- Can an incomplete source be upgraded to VALID?

### Look-ahead/time boundaries

- Can a partial leading/trailing interval become a bar?
- Can a bucket include a minute outside source `[start,end)`?
- Are daily bars UTC-aligned?
- Are 2h/4h/6h boundaries deterministic?

### Data truth

- Can missing source data be silently ignored?
- Can a partial bucket aggregate around a gap?
- Can volume round under ambient Decimal precision?
- Can floats enter the resampling path?

### Cache identity

- Does key include source DatasetVersion, target timeframe, and resampler version?
- Can filesystem root or physical Parquet bytes alter the key?
- Can algorithm semantics change without version evidence?

### Filesystem/integrity

- Can ProductId escape cache root?
- Can symlinks redirect staging/final writes?
- Can a corrupt cache be silently overwritten?
- Are hashes/counts/schema/result identity revalidated?

Return concrete findings only.

---

## 52. Independent QA

QA should independently exercise:

- target timeframe coverage;
- UTC alignment;
- partial-edge trimming;
- exact OHLC;
- exact volume;
- low Decimal precision environment;
- source-gap suppression of aggregate bars;
- source-quality inheritance;
- cache key determinism;
- source/timeframe key sensitivity;
- derived manifest accounting;
- publish/load exactness;
- corruption rejection;
- path/symlink safety where platform permits;
- no Phase 007+ scope;
- full repository gates.

QA must execute behavior, not only inspect source.

---

## 53. Dependency boundaries

Preserve:

```text
command_station.domain
    must not depend on
command_station.market_data
```

PyArrow remains infrastructure-only.

Resampling may depend on accepted domain and market-data dataset contracts.

Do not push derived-cache concepts into domain primitives merely for convenience.

---

## 54. Repository validation

Mandatory:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

GitHub Actions must pass on:

```text
Python 3.13
Python 3.14
```

No dependency-file changes are expected.

---

## 55. Acceptance criteria

Phase 006 is accepted only when evidence supports all applicable claims:

1. Only accepted canonical one-minute datasets are resampled.
2. No Coinbase network call is used.
3. Target 1m is rejected as redundant.
4. Supported target timeframes are exactly existing 5m–1d values.
5. Target buckets use deterministic Unix-epoch UTC alignment.
6. Only full buckets contained in source interval are eligible.
7. Partial leading/trailing source intervals never form bars.
8. Edge exclusion accounting is explicit.
9. OHLC aggregation uses first/max/min/last semantics exactly.
10. Volume sum is exact Decimal and ambient-context independent.
11. No float conversion occurs.
12. Every emitted Candle uses the target timeframe and correct duration.
13. Any unresolved required source minute suppresses the aggregate bar.
14. A suppressed bar has explicit derived-gap evidence.
15. Missing source is never synthesized.
16. Derived result never upgrades INCOMPLETE source quality to VALID.
17. Resampler version is explicit.
18. DerivedCacheKey is validated SHA-256 text.
19. Cache key includes source DatasetVersion.
20. Cache key includes target timeframe.
21. Cache key includes resampler version.
22. Filesystem root/Parquet physical bytes do not define cache key.
23. Logical bar/gap/result hashes are deterministic.
24. Derived Parquet stores exact Decimal text.
25. UTC timestamp schema is explicit.
26. Derived gaps are not persisted as fake bar rows.
27. Cache root is explicit.
28. ProductId is not used as an unsafe path segment.
29. Cache publication is staged/atomic.
30. Existing valid cache is idempotently reused.
31. Existing corrupt/incompatible cache is not silently overwritten.
32. Artifact byte hashes are recorded and verified.
33. Loader validates schema, counts, ranges, partitions, hashes, key, and result semantics.
34. Loaded rows reconstruct valid domain Candles.
35. Empty eligible results do not create fake bars.
36. No mutable latest/current cache pointer is introduced.
37. No higher-timeframe Coinbase source is mixed into normal derived history.
38. No indicators are introduced.
39. No replay/runtime/event engine is introduced.
40. No execution/accounting/risk/strategy/API/MCP/frontend functionality is introduced.
41. Unit tests cover planner, aggregation, gaps, quality, identity.
42. Property tests cover aggregate, alignment, gaps, accounting, key, Decimal-context invariants.
43. Integration tests cover persistence, gaps, edges, month partition, corruption, empty result.
44. Security/Reliability review PASS.
45. Independent QA PASS.
46. Ruff PASS.
47. Strict mypy PASS.
48. Import-linter PASS.
49. Pytest PASS.
50. Python 3.13 CI PASS.
51. Python 3.14 CI PASS.

---

## 56. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- existing `Timeframe` alignment cannot support deterministic UTC resampling;
- exact Decimal volume summation requires changing accepted Phase 002 numeric semantics;
- Phase 005 canonical datasets cannot expose sufficient candle/gap information deterministically;
- a current canonical dataset can contain gap reasons whose combination semantics are not defined here;
- cache identity needs mutable physical file details to work;
- safe immutable cache publication would require a database;
- PyArrow behavior conflicts with the accepted Phase 005 persistence model;
- a correct design starts requiring replay/runtime interfaces;
- satisfying a target timeframe would require partial bars or fabricated minutes.

---

## 57. Explicitly out of scope

Do not implement:

- Coinbase higher-timeframe ingestion;
- Coinbase aggregate validation calls;
- 1m canonical import changes;
- gap reclassification;
- synthetic no-trade candles;
- indicator calculations;
- indicator cache;
- `MarketDataRepository`;
- `HistoricalReplayFeed`;
- runtime market events;
- `TradingRuntime`;
- execution simulation;
- orders;
- fills;
- broker;
- ledger/accounting;
- portfolio;
- risk;
- strategies;
- optimization;
- database;
- DuckDB query layer;
- MCP;
- API;
- frontend;
- paper trading;
- live trading.

---

## 58. Definition of done

Phase 006 is done when Crypto Command Station can take an immutable canonical Coinbase spot one-minute `DatasetVersion` and deterministically derive any accepted higher timeframe using exact UTC half-open buckets, exact OHLCV semantics, and explicit source-gap propagation, then safely persist/reload that reproducible output through a content-addressed immutable derived cache keyed by:

```text
source DatasetVersion
+ target Timeframe
+ resampler version
```

No partial, fabricated, or independently sourced higher-timeframe candle may enter the result.

Phase 007 can then build historical replay/runtime semantics on top of one canonical one-minute source and deterministic derived views.
