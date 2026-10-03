# Phase 014 — Batch Backtests, Local Job Runner & Result Index

**Status:** Ready for implementation  
**Date:** 2026-10-03  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Predecessor:** Phase 013 sealed on `main` at `61eed2fada922399c536b700c09821b567ea9de3`

## Objective

Implement the first multi-run application layer on top of the sealed single-run `BacktestService`.

Phase 014 adds:

- explicit immutable `BatchBacktestSpec`;
- deterministic batch/job identities;
- durable job states: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`;
- a bounded local coordinator;
- isolated per-job `BacktestService`/strategy/runtime graphs;
- parallelism only across independent runs;
- strict persisted `BacktestSpec` reconstruction;
- pending-job restartability;
- explicit interrupted-run recovery;
- pending-job cancellation and explicit requeue;
- stdlib SQLite job/result metadata;
- completed-result indexing and query APIs;
- verified cache reuse of already indexed immutable results;
- Independent QA and Security/Reliability evidence.

Phase 014 must not change the financial semantics sealed in Phases 007–013.

## Baseline gate

Before changes:

```bash
git fetch origin
git rev-parse HEAD
git status --short
```

Require exact clean baseline:

```text
61eed2fada922399c536b700c09821b567ea9de3
```

Do not disturb stale user workspaces.

## Authority

This phase implements master-spec §53 Jobs, §54 Parallelism, §66 Reproducibility, and §71 Phase 014.

Core law:

```text
within one simulation:
    deterministic sequential financial processing

across independent simulations:
    bounded parallel workers are allowed
```

## Architecture

```text
BatchBacktestSpec
      |
      v
deterministic BatchRunId
      |
      v
persist batch + PENDING jobs in LocalResearchStore (SQLite)
      |
      v
BatchBacktestService.run_pending(...)
      |
      +--> atomic PENDING -> RUNNING claim
      |
      +--> verified cached result?
      |       +--> verify immutable artifacts
      |       +--> RUNNING -> COMPLETED
      |
      +--> otherwise create fresh BacktestService
              |
              v
         existing sealed single-run service
              |
              v
         BacktestResult + immutable artifacts
              |
              v
     atomic result index + RUNNING -> COMPLETED
```

SQLite is metadata/index/job state only. It is not financial truth.

## Expected production surface

Recommended:

```text
src/command_station/research/
    batches.py
    jobs.py
    index.py
    serialization.py
```

Narrow edits may also touch:

```text
src/command_station/research/__init__.py
src/command_station/research/artifacts.py
```

No financial/runtime module should need semantic changes.

## Dependencies

Use only:

- stdlib `sqlite3`;
- stdlib `concurrent.futures`;
- existing project dependencies.

Expected unchanged:

```text
pyproject.toml
uv.lock
```

Do not add SQLAlchemy, Redis, Celery, RQ, Dramatiq, or distributed queue tooling.

## BatchBacktestSpec

Conceptually:

```python
BatchBacktestSpec(
    backtests=(BacktestSpec(...), BacktestSpec(...), ...),
)
```

Requirements:

- non-empty;
- members are exact immutable `BacktestSpec`;
- duplicate logical specs rejected;
- member order is non-semantic;
- canonical sort by `BacktestSpec.fingerprint`;
- no parameter-grid generation;
- no optimization logic.

`BatchBacktestSpec.fingerprint` is based only on schema version plus sorted member fingerprints.

## BatchRunId and BatchJobId

`BatchRunId` derives from:

```text
BatchBacktestSpec fingerprint
EngineIdentity fingerprint
```

Each member's existing `BacktestRunId` remains:

```text
BacktestSpec + EngineIdentity
```

`BatchJobId` derives from:

```text
BatchRunId + BacktestRunId + job identity schema version
```

No wall clock, path, worker count, PID, or random ID enters any deterministic experiment identity.

## JobState

Use exactly:

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

Allowed transitions:

```text
new -> PENDING

PENDING -> RUNNING
PENDING -> CANCELLED

RUNNING -> COMPLETED
RUNNING -> FAILED

FAILED -> PENDING
CANCELLED -> PENDING
```

All transitions are transactional compare-and-set operations.

`COMPLETED` is terminal.

## Cancellation

Do not interrupt a running financial simulation.

```text
cancel(PENDING) -> CANCELLED
cancel(RUNNING) -> JobNotCancellableError
```

Batch cancellation cancels only jobs still `PENDING`; already `RUNNING` jobs finish normally.

No cooperative mid-run cancellation contract is introduced in this phase.

## Requeue and attempts

Provide explicit requeue for:

```text
FAILED
CANCELLED
```

to:

```text
PENDING
```

Preserve deterministic JobId/RunId.

Persist `attempt_count`, starting at 0 and incrementing atomically on `PENDING -> RUNNING`.

No automatic retry loop.

## Operational metadata

Persist UTC operational timestamps:

```text
created_at
started_at
finished_at
```

They are metadata only and must never enter financial or reproducibility fingerprints.

Persist bounded failure metadata such as:

```text
failure_code
exception_type
message
```

No tracebacks or object reprs by default.

## LocalResearchStore

Use stdlib SQLite for:

```text
batches
jobs
results
result_products
runner_lease
```

Constructor requires an explicit absolute DB path.

Reject:

- relative path;
- `..`;
- symlink/junction DB or parent;
- hardlinked existing DB where detectable.

Use schema version:

```text
PRAGMA user_version = 1
```

Initialize v1; reopen v1; reject unknown schema. Never silently drop/recreate.

Use bound SQL parameters only.

Every connection enables at least:

```text
foreign_keys = ON
busy_timeout
```

Use a deliberate concurrency-safe journal/synchronous policy. WAL is acceptable.

Do not share one sqlite3 connection unsafely across worker threads.

## Persisted BacktestSpec

Every job stores canonical Phase 012 `BacktestSpec` JSON so pending jobs survive process/service reconstruction.

Persist no Python class/factory object.

Implement strict codec:

```python
encode_backtest_spec(spec) -> bytes
decode_backtest_spec(data) -> BacktestSpec
```

Decoder must rebuild exact:

- `StrategyArtifactRef`;
- `DatasetVersion`;
- `BacktestPeriod`;
- `ProductSpec`;
- `InitialHolding`;
- `SpotAccountSpec`;
- `RiskPolicy`;
- `ReferenceExecutionSpec`;
- typed scalar parameters;
- random seed.

Support parameter types:

```text
Decimal
float
int
bool
str
None
```

Reject unknown schemas, extra/missing fields, malformed values, nonfinite numbers, bool/int confusion, and noncanonical JSON.

After decode require:

```text
canonical_json(decoded.to_dict()) == persisted bytes
```

## Batch submission

`submit_batch(batch_spec)` stores in one transaction:

- BatchRunId;
- batch fingerprint;
- exact EngineIdentity;
- creation metadata;
- one PENDING job per member;
- canonical spec JSON;
- expected BacktestRunId;
- deterministic BatchJobId.

Idempotent resubmission of the identical batch returns existing records without resetting states.

Conflicting data for the same deterministic batch/job identity fails closed.

## Restart engine identity

A persisted batch is bound to its original EngineIdentity.

Before execution require exact equality with the current coordinator EngineIdentity.

A different engine must produce a different BatchRunId.

No old job may silently execute under new engine code.

## BatchBacktestService

Conceptually:

```python
BatchBacktestService(
    store=...,
    artifact_store=...,
    engine_identity=...,
    worker_factory=...,
)
```

Responsibilities:

- submit batch;
- run pending jobs;
- query batch/jobs/results;
- cancel pending jobs;
- requeue failed/cancelled jobs;
- explicitly recover interrupted runner state.

It must not contain fill, risk, accounting, strategy-ordering, or PnL logic.

## Worker factory and isolation

Inject:

```python
BacktestWorkerFactory() -> BacktestService
```

Every executing job gets:

- fresh `BacktestService`;
- fresh `StrategyArtifactCatalog`;
- fresh strategy instance;
- fresh StrategyRunner/state/indicators;
- fresh clock/broker/accounting/risk/runtime.

Sharing immutable/concurrency-safe dataset files, artifact root, and SQLite metadata is allowed.

Reject reuse of the same mutable `BacktestService` or `StrategyArtifactCatalog` across executing jobs.

Every worker must have the exact coordinator EngineIdentity and expected artifact root.

## Parallel implementation

A bounded local `ThreadPoolExecutor` is acceptable in Phase 014.

This phase does not claim hostile process isolation.

Threads are acceptable because strategy factories remain trusted in-process Python callables and no persistent reconstructable strategy-code registry exists yet.

No module-level mutable simulation state is allowed.

## BatchExecutionPolicy

Provide an operational policy such as:

```python
BatchExecutionPolicy(max_workers=...)
```

`max_workers` must be a bounded positive int.

It is scheduling metadata only and must not enter any experiment/result identity.

`max_workers=1` and `max_workers=N` must produce identical financial results.

## Deterministic dispatch and atomic claim

Select runnable jobs in deterministic order.

Before execution atomically perform:

```text
PENDING -> RUNNING
```

If cancellation or another claim already changed the state, do not execute that job.

This is the cancellation/claim race boundary.

## Failure isolation

A normal worker/backtest exception:

- marks only that job `FAILED`;
- records bounded failure metadata;
- does not stop unrelated jobs;
- does not rollback completed jobs.

A SQLite/schema/index integrity failure is coordinator-fatal and must fail closed.

## Completion transaction

A job becomes `COMPLETED` only after one successful DB transaction:

1. validates JobId/RunId/spec identity;
2. inserts or validates result index;
3. inserts/validates result-product rows;
4. updates `RUNNING -> COMPLETED`;
5. records result/manifest fingerprints.

If this transaction fails, the job is not reported completed.

Never delete a valid immutable artifact because metadata indexing failed.

## Artifact verification

Before completion require worker result:

- expected `BacktestRunId`;
- expected spec fingerprint;
- expected EngineIdentity;
- non-null manifest;
- coherent result/manifest IDs.

Verify the immutable artifact bundle before indexing.

## Strict manifest loader

Add a safe API such as:

```python
LocalBacktestArtifactStore.load_manifest(run_id) -> ArtifactManifest
```

It must:

- read only fixed `manifest.json`;
- require canonical JSON;
- enforce exact schema/fields/types;
- build validated records;
- verify the complete bundle;
- fail closed on any corruption.

## Result index

Introduce a typed immutable index record containing enough metadata for future list/get tools, such as:

```text
run_id
spec_fingerprint
result_fingerprint
manifest_fingerprint
engine identity fingerprint/commit
strategy artifact fingerprint
strategy_id
trading_start
replay_end
datasets/products
net_profit
total_return
max_drawdown
closed_trade_count
indexed_at
```

Financial exactness remains in artifacts. The index is a searchable summary/pointer.

## Result index idempotence

For an existing RunId:

- exact same deterministic record => idempotent success;
- any deterministic conflict => `ResultIndexConflictError`.

Never overwrite a conflicting result.

Store product mapping separately:

```text
run_id
product_id
dataset_version
```

for future filtering.

## Verified result cache

Before doing financial work for a RUNNING job, a result-index hit may skip simulation only when all of these verify:

- job/run/spec/engine identities match index;
- strict manifest load succeeds;
- full artifact bundle verifies;
- result fingerprint matches;
- manifest fingerprint matches.

Then transition to COMPLETED without financial rerun.

If index exists but artifact is missing/corrupt/conflicting, fail closed.

If artifact exists without index, executing BacktestService normally may verify/reuse it and then create the index.

## Query APIs

Provide typed application APIs:

```text
get_batch
list_batches
get_job
list_jobs
get_result
list_results
```

At minimum result filters support:

- strategy_id;
- product_id;
- optional dataset_version;
- bounded limit/offset.

Job filters support batch and state.

No raw SQL leaves the application layer.

## BatchView

Derive batch state from children:

```text
if any RUNNING:      RUNNING
elif any PENDING:    PENDING
elif any FAILED:     FAILED
elif any CANCELLED:  CANCELLED
else:                COMPLETED
```

Include exact counts for each state.

Mixed completed/failed => FAILED.

Mixed completed/cancelled => CANCELLED.

## One local coordinator lease

Persist one global runner lease per LocalResearchStore.

`run_pending` acquires it atomically and releases it in `finally`.

A second coordinator must fail explicitly rather than schedule concurrently.

The lease token/time are operational metadata only.

## Interrupted runner recovery

A process crash may leave:

- runner lease;
- RUNNING jobs;
- valid immutable artifacts.

Do not automatically assume the old process is dead.

Provide explicit:

```python
recover_interrupted_runner()
```

called only after the operator/application knows the previous coordinator is gone.

Recovery transaction:

- mark all RUNNING jobs `FAILED` with `INTERRUPTED`;
- preserve attempts;
- preserve artifacts;
- clear runner lease.

Do not auto-requeue or auto-delete anything.

After explicit requeue, a job may verify/reuse an already published immutable artifact and complete normally.

## Strategy artifacts after restart

Persist only exact `StrategyArtifactRef`.

After restart, the application must re-register the exact referenced trusted factory.

If missing or mismatched, the job fails before financial mutation.

Never substitute another strategy artifact.

## Required goldens/integrations

### Three-job successful batch

Run three distinct valid tiny specs in parallel.

Assert:

```text
3 PENDING after submit
3 COMPLETED after run
0 FAILED
0 CANCELLED
```

Every result equals direct standalone execution and is indexed/verified.

### Failure isolation

Two valid jobs plus one deliberately unavailable/misconfigured strategy artifact.

Assert two complete, one fails, no fake result for failed job, batch state FAILED.

### Cancellation and requeue

Cancel one pending job before run.

Assert no worker execution/result.

Run remaining jobs.

Then explicitly requeue cancelled job and complete it using same deterministic JobId/RunId.

### Verified cache reuse

Complete/index a run, then include that same BacktestRunId in a different batch set.

Assert verified cache hit skips financial execution.

Corrupt artifact => reuse fails closed.

### Sequential vs parallel

Run equivalent batches with:

```text
max_workers=1
max_workers=4
```

using independent metadata roots.

Require same deterministic per-run results/artifacts/index content, ignoring only operational timestamps/token.

### State isolation

Run same strategy artifact concurrently with different parameters.

Prove fresh service/catalog/strategy/state/indicator graphs and standalone equivalence.

### Persisted restart

Submit jobs, discard service/process objects, reopen same SQLite DB with a new coordinator and factories, run pending jobs successfully from persisted canonical specs.

### Interrupted runner

Simulate stale runner lease + RUNNING jobs.

Normal runner start must refuse.

Explicit recovery marks interrupted jobs FAILED, preserves artifacts, clears lease.

Requeue and complete.

### Crash after artifact publication

Simulate artifact success before DB completion.

After recovery/requeue, verify/reuse artifact and complete/index without rewriting bytes.

### Index transaction failure

Inject metadata failure after artifact publication.

No false COMPLETED state. Artifact survives. Recovery/requeue completes safely.

### Cancellation/claim race

Coordinate claim and cancel concurrently.

Only valid outcomes:

```text
CANCELLED with no execution
```

or:

```text
RUNNING then COMPLETED/FAILED
```

Never both.

### Result queries

Index multiple strategies/products and verify bounded deterministic filtering.

## Property tests

Use Hypothesis for properties equivalent to:

1. batch member permutations preserve batch fingerprint/BatchRunId;
2. unique specs produce unique deterministic JobIds;
3. illegal state transitions never succeed;
4. concurrent claim has one winner;
5. claim and cancellation are mutually exclusive;
6. worker count does not alter financial identities;
7. operational timestamps do not enter result fingerprints;
8. persisted spec codec preserves identity;
9. tampered persisted spec fails before worker execution;
10. exact result-index reinsert is idempotent;
11. result conflict cannot overwrite;
12. completed jobs always reference indexed verified artifacts;
13. failed/cancelled jobs never have fabricated results;
14. requeue preserves JobId/RunId;
15. no mutable strategy/runtime state leaks across parallel jobs.

## SQLite/security adversarial tests

Attack:

- illegal state jumps;
- double claim;
- wrong RunId completion;
- requeue completed;
- cancel running;
- reused worker service/catalog;
- worker engine mismatch;
- worker artifact-root mismatch;
- DB symlink/junction/hardlink;
- unknown `user_version`;
- altered spec JSON;
- altered fingerprint/RunId/JobId;
- SQL-like text in strategy/product filters;
- forged result index;
- index/artifact mismatch;
- corrupt cached artifact;
- second coordinator lease;
- stale lease recovery;
- cancellation-vs-claim race;
- completion-vs-recovery race;
- artifact publication followed by DB failure.

Document that interrupted recovery requires certainty that the old coordinator is dead.

Every valid finding gets permanent regression coverage.

## Independent QA

QA independently verifies:

- exact baseline;
- no financial semantic diff;
- codec;
- SQLite schema/state transitions;
- batch goldens;
- worker isolation;
- worker-count invariance;
- persisted restart;
- cancellation/requeue;
- interruption recovery;
- cache integrity;
- result indexing/filtering;
- tamper/corruption;
- concurrency races;
- entire Phase 013 hardening suite;
- all repository gates.

QA must inspect SQLite rows and immutable artifacts, not only public summaries.

## Import boundaries

Batch/job/index code remains in the research/application layer.

Lower financial layers must not import batch/job/index modules.

Future MCP calls application services, never raw SQLite.

## Explicitly out of scope

Do not implement:

- MCP;
- REST/API;
- CLI product surface;
- frontend;
- ResearchSession;
- result ranking/winner selection;
- parameter-grid generation;
- optimization/Optuna;
- walk-forward;
- Monte Carlo;
- optimized simulator;
- process/distributed worker fleet;
- Redis/message broker;
- progress percentages/event stream;
- running-job force cancellation;
- paper/live trading;
- Coinbase authenticated trading;
- fills/ledger/PnL tables in SQLite.

## Repository validation

Mandatory:

```bash
uv sync --locked
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

GitHub CI must PASS on the exact final candidate on:

```text
Python 3.13
Python 3.14
```

No dependency changes expected.

## Evidence documents

Create:

```text
docs/phases/014-implementation-evidence.md
docs/phases/014-qa-evidence.md
docs/phases/014-security-evidence.md
```

## Acceptance criteria

Phase 014 is accepted only when:

1. exact predecessor is `61eed2fada922399c536b700c09821b567ea9de3`;
2. BatchBacktestSpec is immutable/canonical;
3. duplicate specs are rejected;
4. BatchRunId and JobId are deterministic;
5. all five job states and transition laws are enforced atomically;
6. pending cancellation works and running cancellation is rejected;
7. failed/cancelled explicit requeue works;
8. completed jobs are terminal;
9. operational metadata stays outside financial identities;
10. SQLite uses stdlib only and safe path/schema rules;
11. canonical specs persist and strictly decode;
12. pending jobs survive service/process reconstruction;
13. stored EngineIdentity is enforced;
14. every executing job receives fresh BacktestService and StrategyArtifactCatalog;
15. worker engine/artifact boundary mismatches fail before financial execution;
16. bounded parallel execution exists;
17. worker count does not alter financial output;
18. atomic claim prevents double execution;
19. worker failure is isolated;
20. metadata integrity failures fail coordinator closed;
21. completion transaction atomically indexes result and marks COMPLETED;
22. immutable artifacts verify before COMPLETED;
23. strict manifest loader exists;
24. result index is idempotent and conflict-safe;
25. result-product index supports queries;
26. verified cache reuse exists;
27. corrupt cache fails closed;
28. artifact-without-index can be safely indexed through normal execution/reuse;
29. typed list/get APIs exist;
30. batch state/counts are correct;
31. one local runner lease prevents two coordinators;
32. interrupted recovery is explicit;
33. recovery preserves artifacts and marks RUNNING jobs FAILED;
34. interrupted jobs can be explicitly requeued;
35. missing strategy artifact after restart cannot be silently substituted;
36. no module-level mutable simulation state is introduced;
37. batch results equal direct standalone results;
38. successful jobs survive another job failure;
39. cancellation/claim race has one valid winner;
40. idempotent submission creates no duplicate jobs;
41. tampered persisted IDs/specs fail closed;
42. schema corruption starts no workers;
43. SQL-like input remains bound data;
44. no operational metadata changes result fingerprints;
45. no batch-level duplicate financial artifact is created;
46. no automatic retries/distributed queue/process-isolation claim;
47. unit/property/integration/golden tests PASS;
48. full Phase 013 regression suite PASS;
49. Security/Reliability PASS;
50. Independent QA PASS;
51. lock/Ruff/mypy/import/full pytest PASS;
52. Python 3.13 CI PASS;
53. Python 3.14 CI PASS;
54. production financial semantics remain unchanged;
55. Phase 015/016 work is not started.

## Stop/escalate conditions

Stop rather than silently redesign if:

- parallelism requires modifying financial runtime semantics;
- worker isolation cannot be guaranteed with fresh service/catalog graphs;
- persisted reconstruction weakens BacktestSpec identity;
- process workers require serializing arbitrary trusted Python callables;
- cache reuse cannot verify artifact integrity;
- cancellation requires interrupting the financial runtime;
- result indexing starts storing financial truth;
- interruption recovery cannot fail closed;
- a third-party dependency appears necessary;
- scope drifts into MCP/optimization/paper/live.

## Definition of done

Phase 014 is done when one local application can durably execute and index an explicit collection of deterministic independent experiments:

```text
BatchBacktestSpec
      |
      v
durable PENDING jobs
      |
      v
bounded isolated workers
      |
      +--> sealed BacktestService -> immutable result
      +--> sealed BacktestService -> immutable result
      +--> FAILED job
      |
      v
atomic durable job states
      |
      v
searchable result index
```

while preserving:

```text
one simulation = sequential deterministic financial semantics
many simulations = isolated parallel application work
```

This becomes the substrate for Phase 015 MCP research tools and Phase 016 optimization.
