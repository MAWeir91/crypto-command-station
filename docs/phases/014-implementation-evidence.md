# Phase 014 implementation evidence

Predecessor: `61eed2fada922399c536b700c09821b567ea9de3`. The Director verified the clean isolated clone before assignment. Changes reside only in `.phase014-workspace`; no publication performed.

## Scope and decisions

- New research batch identities/views, canonical persisted-spec codec, SQLite metadata store, and bounded threaded application service.
- The sealed BacktestService constructs every financial runtime. Financial runtime, execution, accounting, risk, strategy sequencing, and analytics production files are unchanged.
- Schema v1 uses per-operation connections, foreign keys, a 10-second busy timeout, DELETE journal and FULL synchronization. Exact v1 schema structure is checked on every transaction. DB and SQLite sidecars reject symlinks, junctions and hardlinks.
- Transactional singleton lease tokens fence claims and completion. Recovery revokes old tokens, marks RUNNING jobs INTERRUPTED, preserves attempts/artifacts, and never requeues automatically. Recovery requires the caller to establish the prior coordinator is gone.
- Each executed job receives a fresh injected service/catalog. A monitored catalog additionally rejects strategy instances reused across different catalogs before the sealed service builds the financial graph. Factories remain trusted in-process code; no OS isolation claim.
- Result indexing is a transaction with completion. Verified manifest/spec/summary and bundle hashes supply the index; SQL contains summary pointers only. Cache hits compare every deterministic index field with fresh artifact evidence.
- Factory errors and ordinary simulation exceptions fail only their job. Metadata/artifact-integrity errors propagate at coordinator level. Jobs left RUNNING after an integrity exception require explicit recovery.

## Implementation validation (nine executions, including authorized extensions)

1. `uv run pytest tests/test_research_batches.py -q -p no:cacheprovider`: infrastructure abort; sandbox denied uv cache `sdists-v9/.git`.
2. Same command elevated as required: infrastructure abort; uv Python minor-version link target `cpython-3.14.6-windows-x86_64-none` missing.
3. Existing repository `.venv/Scripts/python.exe -m pytest tests/test_research_batches.py -q -p no:cacheprovider`, `PYTHONPATH=src`: infrastructure abort; pytest temporary `.lock` access denied.
4. Same direct Python command elevated: 9 passed; 1 TEST/QA DEFECT (Hypothesis default 200ms deadline on disk-backed worker-count scenario). Corrected with `deadline=None`.
5. Existing `.venv/Scripts/ruff.exe check` on new modules/tests with `--fix`: import/unused fixes applied; remaining format/long-line findings addressed.
6. Existing `.venv/Scripts/ruff.exe format` on owned changed files: 6 reformatted.
7. Authorized final formatter on all seven owned Python files: 4 reformatted, 3 unchanged.
8. Elevated direct Python focused pytest command: **17 passed in 12.51 seconds**.
9. Existing `.venv/Scripts/mypy.exe src/command_station/research/batches.py src/command_station/research/jobs.py src/command_station/research/store.py src/command_station/research/spec_codec.py tests/test_research_batches.py --cache-dir .mypy-phase014`: **Success: no issues found in 5 source files**.

Final inspection corrected import ordering only after the final checks. No further implementation validation attempted after the authorized boundary.

## Focused evidence

Tests execute the real dataset/catalog/BacktestService/runtime/artifact path. Coverage includes three-job parallel success/direct standalone equivalence, reconstruction of pending jobs, verified cache skipping factories, corrupted cache refusal, ordinary missing-factory isolation, pending cancellation/requeue, completed terminal rejection, stale lease rejection, publication-before-index failure/recovery, stale completion fencing, concurrent claim and cancellation mutual exclusion, index conflict rollback/idempotence, multi-product and SQL-like filters, schema tamper, hardlinked DB refusal, worker/catalog/strategy reuse, wrong worker engine/root, and sequential/parallel deterministic index equivalence.

Hypothesis varies member permutations, scalar parameter types (including Decimal/float/int/bool/str/None), concurrent claim contenders, cancellation races and worker counts.

## Remaining acceptance ownership

Independent QA owns full repository gates and Phase013 regression. Security/Reliability owns adversarial review. Exact candidate CI, Python3.13/3.14 coverage, Windows symlink/junction scenarios and exhaustive property coverage beyond focused examples are not claimed by this implementation report. No dependencies/lockfiles, financial production semantics, interface products, or Phase015/016 work changed.

## Independent-review repair: index row consistency

Security reproduced a CODE FAIL: a valid record from run B copied into SQL row A
was returned as B by `get_result(A)`. Changing redundant strategy/product/dataset
filter columns could also misroute result queries. Strict canonical decoding alone
did not establish SQL row consistency.

Repair adds transaction-scoped validation of every result row against its canonical
record: embedded RunId equals the SQL primary key, strategy ID equals the query
column, and the exact product/dataset relationships equal the record. Orphan
relationship rows also fail closed. Get/list and completion use the same validation.
Validation precedes filtering and pagination, so hidden corruption cannot become an
empty or misleading query result. This deliberately scans the local metadata index
on these operations; bounded response limits remain unchanged. Artifact verification
still governs cache reuse and financial authority.

Also corrected reviewed import ordering, the policy default expression, long SQL
literal formatting, redundant SQL grouping, and the specification's Python example.
Reviewer-owned tests and evidence were preserved.

Repair validation budget: four executions, all within Director authorization:

1. Root `.venv/Scripts/ruff.exe check` on research `__init__.py`, `batches.py`,
   `store.py` with `--fix`: two import findings fixed; one new 101-character error
   message manually wrapped afterward.
2. Root `.venv/Scripts/ruff.exe format` on those three files: two reformatted,
   one unchanged.
3. Elevated root `.venv/Scripts/python.exe -m pytest tests/test_phase014_security.py
   tests/test_research_batches.py -q -p no:cacheprovider`, `PYTHONPATH=src`:
   **36 passed, 1 skipped in 15.91 seconds**. Skip: Windows symlink privilege
   unavailable (`WinError 1314`). All four permanent index regressions now pass.
4. Root `.venv/Scripts/mypy.exe src/command_station/research/store.py
   src/command_station/research/batches.py src/command_station/research/__init__.py
   --cache-dir .mypy-phase014-repair`: **no issues in three source files**.

Final full lint/format checks and broader acceptance remain independent QA-owned.

## Independent-review repair: stop unstarted financial work

QA reproduced a second CODE FAIL: eager submission allowed the next uncached job's
factory to run after a corrupt cached job raised an integrity error with one worker.
The coordinator must stop unstarted financial work when integrity fails, while
letting admitted simulations finish normally.

Repair replaces eager submission with at most `max_workers` in-flight futures and
FIRST_COMPLETED handling. All observed completions are consumed before replacement
jobs are submitted. A guarded worker signals the stop fence immediately for any
exception escaping job execution, including cache/store failures outside the ordinary
worker-error handler. Ordinary worker exceptions still mark only their job FAILED
and return normally, so they do not stop other jobs.

Claims and financial admission check the stop flag under the same fence lock used
to record integrity detection. Worker construction and admission are inside that
boundary; financial execution runs outside it. A simulation admitted before stop
is allowed to finish. A job not yet claimed stays PENDING. A job already claimed
but stopped before admission remains RUNNING without fabricated result/completion
and requires explicit interrupted recovery. No simulation is interrupted or killed.

Three authorized repair validation executions:

1. Root `.venv/Scripts/ruff.exe format src/command_station/research/batches.py`:
   one file reformatted.
2. Elevated root `.venv/Scripts/python.exe -m pytest tests/test_phase014_qa.py
   tests/test_research_batches.py tests/test_phase014_security.py -q
   -p no:cacheprovider`, `PYTHONPATH=src`: **50 passed, 1 skipped in 27.23 seconds**.
   Includes the permanent corruption-first scheduling regression, ordinary failure
   isolation, parallel financial equivalence and security/recovery boundaries.
   The skip remains unavailable Windows symlink privilege.
3. Root `.venv/Scripts/mypy.exe src/command_station/research/batches.py
   --cache-dir .mypy-phase014-fence`: **no issues in one source file**.

Only `research/batches.py` and this implementation evidence changed for the second
repair. QA tests and reviewer evidence were preserved. Full acceptance remains
independent QA-owned.

## Operational timestamp contract repair

`JobView` and the initial SQLite v1 job schema now include nullable `started_at`
and `finished_at`. Submission has neither; the successful atomic claim increments
the attempt and sets its start; completion, ordinary failure, and explicit
INTERRUPTED recovery retain that start and set the finish. Pending cancellation
sets only the finish. Explicit requeue clears both current-attempt times while
preserving creation, attempts, and deterministic identities. No migration,
attempt-history table, schema-version bump, or scheduler change was introduced.

Persisted job reconstruction rejects malformed/noncanonical/non-UTC timestamps
and state/attempt/timestamp presence inconsistencies. Canonical timestamps use
`datetime.now(UTC).isoformat()` with `+00:00`. Wall-clock ordering is not imposed:
UTC clocks can move backwards and these operational values are not a monotonic
financial clock. Two real service executions with different operational times
produce identical run/job/batch identities, immutable manifests, and deterministic
index records.

Six implementation validation executions (root `.venv/Scripts` tools, isolated
Phase 014 working directory):

1. `ruff.exe format src/command_station/research/jobs.py
   src/command_station/research/store.py tests/test_phase014_timestamps.py`:
   two files reformatted, one unchanged.
2. Elevated `python.exe -m pytest tests/test_phase014_timestamps.py
   tests/test_research_batches.py -q -p no:cacheprovider`, `PYTHONPATH=src`:
   **45 passed, 4 failed in 17.79 seconds**. TEST DEFECT: the new test incorrectly
   expected pending-only scheduling to read nonpending rows; unfiltered public
   reads rejected all corrupt rows. Assertion narrowed to corrupt pending rows.
3. `ruff.exe check` on those three changed Python files: two line-length issues;
   corrected by splitting SQL strings.
4. `mypy.exe src/command_station/research/jobs.py
   src/command_station/research/store.py --cache-dir .mypy-phase014-timestamps`:
   **no issues in two source files**.
5. Repeat of execution 2 after the test/string corrections:
   **49 passed in 16.80 seconds**, no skips.
6. Repeat of execution 3: **all checks passed**.

Implementation validation is complete at the six-execution handoff boundary.
Independent QA owns broad gates, final format checking, and security/scheduler
regression acceptance. Dependencies, lockfile, financial contracts, and adjacent
phases are unchanged. No staging, commit, push, or merge was performed.

## S014-2 timestamp mutation integrity repair

Security review demonstrated that corrupt current-attempt timestamps could be
overwritten by failure/recovery, and that a separate writer could corrupt metadata
between the existing preflight read and claim/cancel/requeue's write transaction.
Every affected current job is now reconstructed and validated inside the same
`BEGIN IMMEDIATE` transaction that performs its state update. Existing preflight
reads remain, but transaction-local validation is authoritative for mutation.
Completion already validates the current row inside its write transaction and
retains that protection unchanged.

Explicit recovery validates every RUNNING row before its bulk terminal update or
lease deletion. If any row is corrupt, the transaction rolls back with all job
rows and the runner lease unchanged. Healthy recovery and lease/CAS fencing keep
their existing semantics. Ruff formatting also normalized the mixed line endings
reported by QA. Reviewer tests, financial logic, scheduler, index, dependencies,
and schema version were unchanged.

Three authorized implementation validation executions:

1. Root `.venv/Scripts/ruff.exe format src/command_station/research/store.py`:
   **one file reformatted**.
2. Elevated root `.venv/Scripts/python.exe -m pytest
   tests/test_phase014_timestamp_security.py tests/test_phase014_timestamps.py
   tests/test_research_batches.py -q -p no:cacheprovider`, `PYTHONPATH=src`:
   **55 passed in 18.53 seconds**, no skips. Includes all six permanent security
   regressions for corrupt-row preservation, lease preservation, and write-boundary
   timestamp validation, plus lifecycle and existing batch regressions.
3. Root `.venv/Scripts/mypy.exe src/command_station/research/store.py
   --cache-dir .mypy-phase014-timestamp-transactions`:
   **no issues in one source file**.

At the authorized three-execution handoff boundary, independent QA/Security own
closure and broad gates. No staging, commit, push, or merge was performed.
