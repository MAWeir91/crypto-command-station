# Phase 014 independent QA evidence

Date: 2026-10-03. Initial review verdict: **FAIL; repair and independent closure pending**.

Current closure verdict: **PASS for local implementation acceptance**. Initial index/Ruff defects and coordinator integrity-stop defect Q014-2 are repaired and independently verified. Exact-candidate CI and native Windows symbolic-link paths remain UNPROVEN as described below.

## Authority and scope

Read the complete user attachment, Phase014 specification and implementation evidence independently. Reviewed new research jobs/batches/store/codec modules and the strict manifest-loader diff. `git rev-parse HEAD` independently returned `61eed2fada922399c536b700c09821b567ea9de3`. The Director recorded tracked cleanliness before implementation; QA began after edits and does not claim to have observed pre-edit cleanliness.

No production financial semantics, dependencies, lockfile, CLI/API/MCP, optimization or live trading changed. Financial runs continue through the sealed BacktestService. QA edited only `tests/test_phase014_qa.py` and this evidence file. No publication performed.

## Commands and results before repair

Commands ran in `.phase014-workspace`. Direct tooling below used the existing root `.venv/Scripts` executables; direct pytest was elevated because the Director's ledger already established sandbox pytest temp-lock denial. `PYTHONPATH=src` was set for direct pytest/type/dependency commands.

- `python.exe -m pytest tests/test_research_batches.py -q -p no:cacheprovider`: **17 passed in 12.67s**.
- `python.exe -m pytest -q -p no:cacheprovider`: **521 passed, 4 skipped in 52.15s**. This included the complete sealed Phase013 suite. Four skips were native Windows symlink creation `WinError 1314`; these paths remain UNPROVEN locally.
- `python.exe -m pytest tests/test_phase014_qa.py -q -p no:cacheprovider`: final independent focused coverage **8 passed in 8.97s** (earlier six-test version also passed).
- `mypy.exe src tests --cache-dir .mypy-qa014`: initial implementation **170 files passed**. With concurrent security tests present a later check reported a security-test keyword-dictionary typing error; its displayed source had already changed concurrently. This is a test issue pending final closure, not a production defect. A single-file mypy invocation without supplying source packages produced missing-stub errors; classified **QA invocation defect**, superseded by full `src tests` checks.
- `lint-imports.exe`: **4 kept, 0 broken**, 91 files/451 dependencies.
- `ruff.exe format --check .`: **FAIL**, phase spec Python example needed formatting, 204 files already formatted.
- `ruff.exe check .`: **FAIL**, unsorted imports in research `__init__.py`/`batches.py`, B008 default policy construction, E501 store line244, UP034 store line454. Handed off to implementation.
- Independent QA file `ruff.exe check tests/test_phase014_qa.py`: **PASS** after QA-owned formatting. Initial long decorator lines were QA test-format defects and corrected by formatter.
- `uv lock --check --python C:\Users\TradeStation\crypto-command-station\.venv\Scripts\python.exe`, with `UV_CACHE_DIR=.uv-qa-cache`: **PASS**, 35 packages resolved.
- `uv sync --locked --python C:\Users\TradeStation\crypto-command-station\.venv\Scripts\python.exe`, same cache: sandbox network refused with error10061; required elevated retry **PASS**, installed exact 35 locked packages into isolated workspace `.venv`. No dependency or lock edits.
- `git diff --check`: **PASS** before repair.

The ordinary global uv cache path had already been blocked by `sdists-v9/.git` access denial; an explicit interpreter alone still reproduced that denial. Workspace-local cache plus explicit root interpreter provides a working alternative. The original broken uv-managed minor-version link was not retried.

## Acceptance evidence

Implementation tests independently run real dataset/catalog/service/runtime/artifact paths: three successful parallel jobs, direct standalone equivalence, pending restart/reconstruction, cache skip without factory execution, corrupt bundle refusal, unavailable factory isolation, cancellation/requeue, completed terminal behavior, runner lease exclusion, interrupted recovery, artifact publication before index failure and unchanged manifest bytes after recovery, concurrent claim single winner, claim/cancel mutual exclusion, worker service/catalog/strategy reuse, worker engine/root mismatch, schema tamper, hardlinks, index conflict rollback/idempotence, multiple products, bound SQL-like filters, and sequential/parallel deterministic index equivalence.

QA-owned properties add synchronized simultaneous callbacks across three jobs using different validated quantity parameters and mutable schema state. Each starts with zero state; retained context observations establish distinct state/parameter identities and values1/2/3. Every job equals standalone financial output. This runs the sealed service rather than a fake worker. Factory/catalog/service isolation and unchanged sealed BacktestService construction provide evidence for fresh clocks, broker, accounting, risk, runner and runtime graphs. No hostile-process isolation is claimed.

QA inspects actual SQLite `user_version`, jobs/state/attempts/spec bytes/result hashes, results and product relationship counts, and cleared lease; verifies all completed manifests and eight-record bundles; compares `spec.json` with exact canonical job bytes. Additional Hypothesis scenarios check illegal requeue remains rejected without mutation, failed/cancelled jobs have no fabricated result, explicit requeue preserves JobId/RunId/attempt count, conflicting result insertion cannot overwrite or complete, identical deterministic reinsert retains original record despite operational timestamp changes, and completed jobs point to verified artifacts. Canonical codec rejects bool/float seed ambiguity and unknown schema. A separate multi-strategy golden checks distinct strategies, product filtering and bounded pagination.

## Defects and repair handoff

Security's permanent `tests/test_phase014_security.py` reproduced four index-integrity failures: an encoded result record can disagree with its SQLite run key; strategy/product/dataset filter metadata can disagree with the canonical encoded record. Public get/list APIs return or filter inconsistent metadata instead of failing closed. Requirement sources: fail-closed store/result integrity, conflict-safe index, corruption/tamper and searchable authoritative-provenance pointer contracts. QA reviewed the vulnerable get/list paths and incorporates Security's concrete packet without duplicating the experiment. Implementation owns repair and Security owns the regression tests.

Required Ruff gate failures are independently confirmed above. They are deterministic required-gate defects. Financial regression tests pass; that does not remove the metadata-integrity failures.

## Unproven and remaining closure

- Repaired result-index boundaries, final Ruff/mypy/full pytest require independent closure on final source.
- Exact final candidate GitHub CI on Python3.13/3.14 cannot be established before separately authorized publication. Local checks used Python3.14.6.
- Windows symlink rejection paths remain unproven because creation privilege is unavailable. Junction/hardlink evidence is owned by Security.
- No arbitrary Python sandbox or adversarial strategy isolation claim; trusted in-process factories remain the contract.

Final QA acceptance must retain the distinction between passing financial regressions, confirmed metadata defects, and environment/publication-blocked evidence.

## First repair closure

Independently inspected repaired `_verified_index`: it validates SQL run keys/strategy columns, complete exact product/dataset relationships and orphan relationships in the same transaction before public get/list filtering and completion. The original index-integrity defect is repaired and its permanent Security regressions passed in the full suite.

Repaired-state gates before the new Q014-2 regression:

- `ruff.exe format --check .`: **209 files already formatted**.
- `ruff.exe check .`: **All checks passed**.
- `mypy.exe src tests --cache-dir .mypy-qa014`: **172 files passed**, including corrected Security and independent QA tests.
- `lint-imports.exe`: **4 kept, 0 broken**.
- Elevated direct `python.exe -m pytest -q -p no:cacheprovider`, `PYTHONPATH=src`: **548 passed, 5 skipped in 59.23s**. The fifth skip is Security's Windows symbolic-link creation case. Entire Phase013 hardening/regression suite remains included.

Locked sync/lock were not repeated because dependencies and lock remain unchanged.

### Q014-2: coordinator integrity failure permits unstarted financial work

Expected behavior source: user request requires store/schema/result-integrity failures to be coordinator-level failures that fail closed. The Director explicitly resolved the boundary: stop jobs that have not begun financial execution when an integrity failure is detected; already-running simulations finish normally under the prohibition against force cancellation.

Actual: `run_pending` eagerly submits every pending job, then waits for futures in order. `ThreadPoolExecutor` context exit waits for queued jobs, which can start financial execution after an earlier job has already detected artifact corruption.

Permanent minimal regression: `tests/test_phase014_qa.py::test_integrity_failure_stops_unstarted_financial_jobs`.

1. Successfully complete/index the real sealed-service spec.
2. Submit a second batch containing that cached spec plus an uncached spec. Choose seed from deterministic IDs so the cached job sorts first.
3. Corrupt cached `summary.json` to `{}`.
4. Wrap the real fresh worker factory with a call recorder.
5. Run the second batch with `max_workers=1`.
6. The coordinator raises `BacktestReproducibilityError` as expected, but invokes the factory for the later uncached job: `calls == [1]`; required `calls == []` assertion fails.

Exact check: elevated direct `python.exe -m pytest tests/test_phase014_qa.py -q -p no:cacheprovider -k integrity_failure`: **1 failed, 8 deselected in 3.11s**, at the assertion that integrity failure fences unstarted financial work. Single-worker deterministic dispatch rules out an ambiguous scheduling race. The reproduction uses genuine canonical IDs, a real completed/indexed artifact and a normal service factory; no invalid fixture or harness behavior explains the deviation.

Handed off to Director/implementation with expectation to fence unstarted jobs and stop scheduling on coordinator-integrity errors while allowing already-running financial simulations to finish. No production repair by QA. All gates and this focused regression require independent final closure after repair.

## Final scheduler repair closure

Independently inspected bounded dispatch (at most `max_workers` in-flight futures), FIRST_COMPLETED before replacement submission, worker-origin stop signaling for escaping integrity errors, and the per-run lock that linearizes claims/financial admission against stop. Ordinary factory/financial exceptions still mark only their job FAILED and return normally. Stop never interrupts an admitted simulation.

Final broad gates:

- `ruff.exe format --check .`: **209 files already formatted**.
- `ruff.exe check .`: **All checks passed**.
- `mypy.exe src tests --cache-dir .mypy-qa014`: **172 files passed**.
- `lint-imports.exe`: **4 kept, 0 broken**.
- `git diff --check` and `git diff --exit-code -- pyproject.toml uv.lock`: **PASS**, no dependency/lock changes.
- Elevated root direct `python.exe -m pytest -q -p no:cacheprovider`, `PYTHONPATH=src`: **554 passed, 5 skipped in 100.02s**. Includes repaired Q014-2 regression, all Phase013 tests, and repaired index/security regressions. Five skips are unavailable Windows symbolic-link creation privilege.

Two focused acceptance additions were made after that full invocation collected tests, to resolve concrete missing claims without repeating the broad suite:

- `test_integrity_stop_preserves_admitted_parallel_simulation` synchronizes a genuine uncached run to begin alongside cached corruption. It waits for the repaired stop flag, completes the genuine admitted financial run, verifies its indexed immutable artifact, and proves the third job remains PENDING with attempt_count0. Uses real BacktestService execution with scoped synchronization wrappers; it does not fake financial output.
- `test_generated_persisted_spec_tamper_precedes_execution` uses Hypothesis seed/schema/extra-field mutations of persisted canonical job specs. All generated cases fail before worker invocation/claim, remain PENDING with zero attempts, and create no result rows.

Final focused check: elevated direct `python.exe -m pytest tests/test_phase014_qa.py -q -p no:cacheprovider -k 'generated_persisted or integrity'`: **3 passed, 8 deselected in 3.96s**. This includes the original single-worker corrupt-first Q014-2 regression plus both additions. Final QA test Ruff check/format and full `mypy src tests` also passed after these additions. No production changes followed this validation.

## Required scenario and property coverage assessment

Coverage is grounded in executable behaviors, not suite count:

| Required behavior | Evidence |
| --- | --- |
| Three successful parallel jobs; standalone equality; pending restart | `test_parallel_restart_cache_and_queries`, QA parallel parameter/state property |
| Worker failure isolation; cancelled job excluded; explicit failed/cancelled requeue | `test_failure_cancel_requeue_and_terminal`, QA generated requeue/index property; successful work remains complete |
| Verified cache skip; corrupt/missing/conflicting evidence fails closed | parallel cache test, cache corruption test, Security consistent-but-forged cache regression, repaired integrity-stop regressions |
| Sequential/parallel worker-count equivalence | Hypothesis `test_worker_count_invariance`, deterministic records and real artifacts/standalone comparisons |
| Fresh mutable state/catalog/service; concurrent parameters | worker reuse/boundary tests, shared-strategy rejection, QA synchronized three-job state/parameter property plus sealed fresh graph construction |
| Stale lease; explicit recovery; postpublication crash/index failure | `test_publication_failure_recovery_fences_completion`, QA completion-rejection/recovery artifact-preservation test; actual manifest bytes retained |
| Atomic cancellation/claim; concurrent claim single winner | Hypothesis contender-count and seed-generated claim/cancel properties; no fabricated result |
| Index filters, idempotence, conflict rollback, exact mappings | multiple-product golden, QA multiple-strategy golden, generated requeue/index property, actual SQLite rows and all Security index corruption/orphan regressions |
| Completion/recovery race | Security synchronized race: exactly one terminal winner, attempts preserved, indexed result iff completion won |
| Batch canonicalization, deterministic unique JobIds, duplicate rejection | Hypothesis member permutations/type values plus canonical fingerprint/identity checks |
| Illegal transitions/terminal COMPLETED | QA Hypothesis illegal requeue states plus running cancellation/double claim/wrong completion/terminal rejection cases |
| Typed persisted codec and tamper before execution | Hypothesis scalar types/roundtrip; generated persisted mutation property; malformed types/IDs/extra fields/nonfinite/duplicate keys adversarial tests |
| Completed artifact invariant; no fake failed/cancelled results; requeue identity; operational metadata excluded | QA actual SQL/bundle property and generated requeue/index property, worker-count deterministic records, no artifact rewrite after recovery |

Batch-view precedence is verified by mixed failure/cancellation/completion integration outcomes and inspected exact count derivation. Transactional completion verifies job identity and canonical index/mappings before one compare-and-set commit; corruption/conflict/recovery rejection cases leave no false completion. Strict manifest reconstruction enforces canonical schema then the sealed complete eight-record verification. Lower financial production layers remain unchanged and continue to construct the financial runtime.

## Final verdict and limits

**PASS** for independently verified local implementation behavior. Both confirmed product findings have permanent regressions and are closed. No outstanding confirmed production defect. No automatic retries, financial semantics/dependency changes, SQL financial-history storage, Phase015/016 work or publication introduced.

**UNPROVEN**: exact final candidate GitHub CI on Python3.13 and3.14; symbolic-link rejection live paths skipped because Windows creation privilege is unavailable. The full local gate ran Python3.14.6. Explicit baseline pre-edit cleanliness is Director-owned evidence because QA began after implementation. Filesystem TOCTOU hostile path replacement is not established by advisory path checks, as Security documents; this is outside the trusted local-store assumption, not a claimed guarantee.

Historical failed evidence above is retained for traceability and superseded by this closure section.

## Independent operational timestamp repair QA

QA inspected the timestamp-only changes in `research/jobs.py` and
`research/store.py`, the Phase014 operational metadata/attempt contract, and the
implementation timestamp scenarios. Timestamp reads use canonical UTC text and
state/attempt presence coherence; wall-clock ordering is deliberately not an
execution-clock invariant. No migration or schema-version increment is required
for this unreleased initial schema.

Initial independent checks, isolated `.phase014-workspace`, root `.venv/Scripts`
tools, `PYTHONPATH=src` for direct Python/import checks:

- Elevated `python.exe -m pytest tests/test_phase014_timestamps.py
  tests/test_research_batches.py tests/test_phase014_qa.py
  tests/test_phase014_security.py -q -p no:cacheprovider`: **84 passed, 1 skipped
  in 31.86s**. Windows symlink privilege skip. This verifies timestamp transitions,
  strict persisted reads, timestamp-independent financial manifests/index/IDs,
  and all prior scheduler/index/security regressions before the new Security
  timestamp tests were introduced.
- Added independent `tests/test_phase014_timestamp_qa.py` with a real successful
  second attempt after failure/requeue; attempts/creation/IDs persist, current
  attempt timestamps replace earlier times, failure metadata clears, and losing
  terminal operations preserve the completed snapshot across reopening.
  Elevated focused pytest: **1 passed in 1.70s**.
- `uv sync --locked --python C:\Users\TradeStation\crypto-command-station\.venv\Scripts\python.exe`
  with workspace `UV_CACHE_DIR`, elevated: **35 packages checked**.
- `uv lock --check`, same cache: **35 packages resolved, PASS**.
- `ruff.exe check .`: **PASS**.
- `lint-imports.exe`: **4 kept, 0 broken**.
- `git diff --check`; `git diff --exit-code -- pyproject.toml uv.lock`: **PASS**.
- Initial `ruff.exe format --check .`: **FAIL** for mixed-newline formatting in
  changed store SQL and Security's in-progress timestamp test. Initial strict
  `mypy.exe src tests --cache-dir .mypy-qa014-timestamps`: **FAIL**, Security's
  in-progress test helper lacked an annotation. These are static-gate/test-source
  issues, not evidence of a financial behavior defect; owner repair requested.

Full-suite acceptance awaits the coherent post-Security-review candidate. QA
made no production, dependency, lock, Git publication, or user-checkout changes.

### Final timestamp closure after S014-2 repair

**STATUS: PASS** for final local acceptance. The initial pending verdict and
static failures above are superseded by these results. QA independently
inspected the repair: `_current_job` reconstructs and validates the persisted
row inside the same `BEGIN IMMEDIATE` transaction as claim/cancel/requeue/fail;
recovery validates every RUNNING row before the bulk update or lease deletion.
Completion retains its existing transactional reconstruction and index checks.
The six Security regressions reject malformed/incoherent rows and preserve
job/lease snapshots, including corruption committed between preflight and the
mutation transaction and all-or-nothing recovery across multiple jobs.

Final validation uses root `.venv/Scripts` tools from the isolated workspace:

- Elevated `python.exe -m pytest tests/test_phase014_timestamps.py
  tests/test_phase014_timestamp_qa.py tests/test_phase014_timestamp_security.py
  tests/test_research_batches.py tests/test_phase014_qa.py
  tests/test_phase014_security.py -q -p no:cacheprovider`, `PYTHONPATH=src`:
  **91 passed, 1 skipped in 34.32s**. All six new integrity regressions and all
  prior index/scheduler regressions pass. Skip: Windows symlink privilege.
- `ruff.exe format --check .`: **212 files already formatted**.
- `ruff.exe check .`: **All checks passed**.
- `mypy.exe src tests --cache-dir .mypy-qa014-timestamps`:
  **no issues in 175 source files**.
- `lint-imports.exe`, `PYTHONPATH=src`: **4 kept, 0 broken**.
- `git diff --check`; `git diff --exit-code -- pyproject.toml uv.lock`: **PASS**.
- Elevated `python.exe -m pytest -q -p no:cacheprovider`, `PYTHONPATH=src`:
  **595 passed, 5 skipped in 67.99s**, **600 total tests**. All five skips are
  unavailable Windows symbolic-link creation privilege, not product failures.

Previously recorded locked sync and lock checks remain applicable: dependency
and lock files are unchanged throughout both timestamp repairs. Final functional
coverage includes every specified current-attempt timestamp transition, reopen,
strict UTC/state coherence, retry identity/attempt preservation, losing terminal
operations, and identical deterministic run/job/batch IDs, financial manifests,
and index content when operational clocks differ. Scope remains the timestamp
metadata contract and its transaction integrity; no migration/history/v2 schema,
financial-layer/dependency changes, automatic retry, future-phase work, or Git
publication was introduced. QA modified only its focused timestamp regression
and this evidence document.

**DEFECTS:** no outstanding confirmed defects within reviewed scope; S014-2 and
initial formatting/type failures are closed.

**UNPROVEN/RISKS:** exact final candidate GitHub Python3.13/3.14 CI is not local
QA evidence; the five privileged symbolic-link paths remain unproven locally.
Existing trusted-local-store filesystem TOCTOU limitation remains unchanged.
