# Phase 014 Security / Reliability evidence

STATUS: PASS for the bounded Security/Reliability review, including independent index-integrity closure and final scheduler fencing inspection. Final phase acceptance remains subject to independent QA repository gates and execution evidence.

## Finding S014-1: medium, durable index identity and filter divergence

Contract: Phase014 spec lines474 and937 require metadata/index integrity failures to fail the coordinator closed; lines519-576 define an immutable searchable provenance index, conflict-safe indexing and verified cache identity. The requested review explicitly includes forged result indexes and index/artifact mismatch.

`LocalResearchStore.get_result` and `list_results` in `research/store.py` select only the record BLOB and reconstruct it with `_result`. They do not compare the embedded RunId with the results primary key, or the canonical strategy/products/dataset fields with the SQL filter columns. A canonical genuine record for run B can replace run A's record and `get_result(A)` returns B without error. Likewise, tampering `results.strategy_id` or `result_products.product_id/dataset_version` silently misroutes public result filtering. This is metadata integrity failure, not a malformed fixture: each reproduction first runs the real sealed service successfully and then alters one independent persisted index representation with SQLite.

Permanent regressions: `tests/test_phase014_security.py::test_result_record_cannot_disagree_with_sql_identity` and three cases of `test_result_filter_metadata_corruption_fails_closed`. They initially failed and now pass after the implementation owner's repair. `LocalResearchStore._verified_index` verifies every canonical record's SQL RunId/strategy plus all product/dataset mappings transactionally before get/list filtering or completion; orphan mappings are rejected. Independent closure added hidden filter/offset/empty-page corruption, unrelated get, orphan query/completion rollback, and coherently encoded forged metric cache scenarios. All passed.

## Executed independent evidence

Existing Python: `C:\Users\TradeStation\crypto-command-station\.venv\Scripts\python.exe`; working directory `.phase014-workspace`; `PYTHONPATH=src`. All pytest checks ran elevated directly due to the supplied blocked-capability ledger. No equivalent uv or sandbox-temp retries were made.

- `python -m pytest tests/test_phase014_security.py -q -p no:cacheprovider`: initial packet 4 failed, 2 passed; expanded packet **4 failed, 14 passed, 1 skipped**, 4.04s. Failures are the finding above. Symlink skip is WinError1314, unavailable privilege.
- `python -m pytest tests/test_phase014_security.py -q -p no:cacheprovider -k junction`: **1 passed, 19 deselected**, 1.57s. Windows directory junction creation succeeded; store refused its parent boundary before creating the target DB.
- `ruff check tests/test_phase014_security.py`: **passed** after formatting/import correction.
- Initial standalone mypy invocation omitted source path and incorrectly resolved installed imports as untyped; this is a validation-harness defect, not product failure. Corrected invocation with source identified an overly broad `**dict` keyword type in the regression harness. Changed to explicit typed filter calls; final gate belongs to independent closure/QA.

## Independent repair closure

- Same direct elevated pytest packet: **24 passed, 1 skipped in5.72s**. The only skip remains Windows symlink privilege unavailable.
- Added forged-cache test initially allowed an unrelated new experiment to execute its own factory, causing a harness assertion. Corrected the fixture by cancelling that unrelated PENDING job before invoking cache reuse; this was a TEST/QA DEFECT, not a product finding.
- `PYTHONPATH=src; mypy src/command_station/research/store.py tests/test_phase014_security.py --cache-dir .mypy-security014`: **Success, no issues in2 source files**.
- `ruff check tests/test_phase014_security.py`: **All checks passed**. Format check found two layout-only differences in new tests; `ruff format tests/test_phase014_security.py` corrected them afterward.

Passing independent attacks cover forged persisted JobId/RunId/spec fingerprint before any worker executes; strict codec bool/int ambiguity, parameter type mismatch, unknown fields, nonfinite Decimal and duplicate JSON keys; traversal; hardlinked SQLite journal/wal/shm refusal without changing external bytes; wrong completion identity with zero index effects; and actual concurrent completion/recovery with exactly one terminal winner and preserved artifacts/attempt count.

Implementation evidence additionally supplies ordinary worker exception isolation, reused service/catalog/strategy checks, worker engine/root mismatch, duplicate claims, cancelling RUNNING, requeueing COMPLETED, second lease refusal, interrupted artifact-before-index recovery, corrupted cached bundles, and postpublication metadata failure. These were inspected as bounded evidence; broad gates and Phase013 regression belong to independent QA.

## Unproven and scope

- Symbolic-link creation is environment-blocked; rejection logic is present but live Windows symlink behavior was skipped. Junction and hardlink behavior are independently established.
- Filesystem TOCTOU resistance to an adversary replacing validated paths during a SQLite operation is not established; path validation is advisory checking rather than an OS-level no-follow handle protocol. Trusted in-process factories and explicit operator-known-dead recovery remain required assumptions.
- The Director clarified that coordinator-fatal integrity errors must fence yet-unstarted financial work while already-running simulations finish. QA owns the deterministic queued-continuation execution regression; final Security reviewed the subsequent scheduler implementation without duplicating QA's test commands.
- No financial runtime changes or publication performed by Security. Changes owned here are the separate security regression file and this evidence document.

## Final bounded scheduler review

Reviewed final `research/batches.py` after Q014-2 repair and the permanent QA corruption-first scheduling regression. No additional concrete defect found.

- `run_pending` keeps at most `max_workers` futures active, waits for FIRST_COMPLETED, and consumes observed outcomes before replenishing. A fatal future escapes before replacements are submitted. Any replenishment race with a newly failing worker is additionally fenced inside the worker.
- `_execute_guarded` sets the shared stop Event under the same lock used by claims and financial admission. Escaping cache/store/result-integrity errors participate, including checks outside the ordinary worker exception handler. A claim or admission that loses to that stop returns before new financial execution. A claimed but nonadmitted job remains RUNNING with no invented completion, allowing explicit recovery to mark INTERRUPTED and preserve its attempt count.
- Ordinary worker errors are recorded FAILED and return normally; they do not set the stop flag. The financial `worker.run` call is outside the fence lock. Once admitted, it is allowed to finish and is neither interrupted nor killed by another job's integrity error.
- On fatal propagation, the executor context waits for admitted work to settle before `finally` releases the lease. No early lease release opens a second coordinator while those simulations still run. Explicit recovery remains operator-known-dead only; store lease/claim tokens continue to fence stale completion and cannot authorize force cancellation.
- Cached-result completion can continue after another worker stops admission, but performs no new financial simulation and still requires verified artifacts plus a lease-fenced atomic index transaction. This does not violate the Director's financial-admission stop boundary.

This final review was targeted inspection only. Implementer reported50 focused passes/1 symlink skip after scheduler repair; QA independently owns confirming Q014-2, parallel execution and broad gates. The earlier independent Security24-pass index packet is unchanged by the scheduler-only production repair. Adversarial filesystem replacement races remain unproven as described above.

RECOMMENDATION: no further bounded security repair. Incorporate independent QA's final fatal-dispatch and repository-gate evidence before final phase acceptance.

## Operational timestamp review: S014-2, medium, mutation bypasses integrity

STATUS: FAIL for the operational timestamp repair pending closure of S014-2.
Earlier index and scheduler closure remains intact.

The assigned contract requires rejection of malformed UTC metadata and
state/attempt/timestamp inconsistency before public reads and lifecycle mutations.
`_job` enforces this for reconstructed rows, and `complete` reconstructs its
current row within the same `BEGIN IMMEDIATE` transaction as completion/indexing.
However, `fail` and `recover_interrupted_runner` never reconstruct their affected
rows. An existing RUNNING row with `finished_at` set to a corrupt BLOB is rejected
by `get_job`, then silently overwritten with a canonical finish by failure or
recovery. Recovery also deletes the lease. With two RUNNING rows, a missing start
in one row does not block recovery: both rows are mutated and the lease revoked,
even though the malformed row remains unreadable afterward.

`claim`, `cancel`, and `requeue` reconstruct their row through `get_job` before
opening the mutation transaction. A separate SQLite writer can commit malformed
metadata between that preflight read and `BEGIN IMMEDIATE`. Each transition then
overwrites the corrupt finish without rejecting it. This is a deterministic
interleaving of a real separate SQLite commit; the regression wraps only the
preflight read, preserving the actual SQL mutation implementation. CAS state
predicates continue to prevent duplicate ordinary transitions but do not establish
integrity of the current row when the write begins.

Permanent regressions in `tests/test_phase014_timestamp_security.py` cover
failure/recovery laundering, claim/cancel/requeue interleavings, and all-row
recovery rollback. Rejection assertions require the exact corrupted job rows and
lease to remain unchanged; the tests intentionally remain red for the implementer.

Executed independent evidence: elevated root `.venv/Scripts/python.exe -m pytest
tests/test_phase014_timestamp_security.py -q -p no:cacheprovider`, with
`PYTHONPATH=src` in `.phase014-workspace`: initial **3 failed in 1.62s**;
consolidated **6 failed in 2.14s**, all `DID NOT RAISE ResearchStoreError` at the
mutating operation. Public read rejection in the terminal tests passed first.
Root `.venv/Scripts/ruff.exe check tests/test_phase014_timestamp_security.py`:
**all checks passed**. Final `ruff format` reformatted the owned test file, and
`PYTHONPATH=src; mypy src/command_station/research/store.py
tests/test_phase014_timestamp_security.py --cache-dir .mypy-security014-timestamps`:
**success, no issues in two source files**. No production edits or publication by
Security.

UNPROVEN: transaction-scoped metadata integrity and preservation on rejection
cannot be established until this finding is repaired. Broader QA gates and prior
Windows privilege limitations remain owned/reported separately. No chronological
ordering requirement is imposed on operational wall-clock timestamps.

RECOMMENDATION: reconstruct and validate each affected current row inside its
mutation transaction before any UPDATE. For recovery, validate all RUNNING rows
before the bulk update or lease deletion so any rejection rolls back everything.
Keep completion's existing transaction-scoped validation and CAS/lease fences.
Then independently rerun the six permanent regressions and the existing timestamp
lifecycle acceptance cases.

## Independent S014-2 closure

STATUS: PASS for the bounded operational timestamp security review; S014-2 closed.

Independent rerun of the same six permanent adversarial regressions with elevated
root `.venv/Scripts/python.exe -m pytest tests/test_phase014_timestamp_security.py
-q -p no:cacheprovider`, `PYTHONPATH=src`, in `.phase014-workspace`:
**6 passed in 1.31s**. These assertions prove malformed bytes and exact lease/job
rows survive rejection unchanged, including the preflight/write interleavings and
multirow recovery rollback.

Targeted final diff inspection confirms `_current_job` reads and reconstructs the
current row inside the caller's `_connection` transaction. Claim, cancellation,
requeue, and failure invoke it before updating. `_connection` acquires
`BEGIN IMMEDIATE` before validation and rolls back on any exception. Recovery
reads and validates all RUNNING rows before its bulk UPDATE or lease deletion.
Completion retains its existing transaction-scoped reconstruction, identity checks,
index consistency checks, and claim-token CAS. Existing lease fencing is retained.

The metadata repair changes only JobView's two operational fields, initial job
schema, persisted-row validation, and operational lifecycle writes in the reviewed
production diff. BatchRunId/BatchJobId derivation, BacktestRunId/spec fingerprints,
ResultIndexRecord.deterministic(), financial runtime, and artifact publication
identity surfaces are unchanged. Timestamp chronology is intentionally unrestricted.

No additional concrete finding in the bounded repair. Earlier filesystem TOCTOU
and Windows privilege limitations remain unproven as documented above; broad
repository gates belong to QA. No production edits or publication by Security.

RECOMMENDATION: accept the bounded timestamp security closure; incorporate QA's
final lifecycle/regression and repository-gate evidence for phase acceptance.
