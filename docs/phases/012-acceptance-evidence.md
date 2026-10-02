# Phase 012 implementation evidence

Exact predecessor: `390dc8a746789f819bcc44f60e1ecf13175991ef` (main after merged
Phase 011 PR #1, accepted PR head `647e9263788e305318ea414a5211fb2eb6fdf09d`).
Implementation is isolated in `.phase012-workspace`; stale root work is preserved.

The synchronous service composes the actual HistoricalReplayFeed, SimulatedClock,
SimulatedBroker, SpotAccountingEngine, RiskEngine, StrategyRunner and
ReferenceTradingRuntime. No replacement simulator, financial semantic changes,
provider fallback, dependency changes, or later-phase surfaces are introduced.

The catalog treats explicit registrar-supplied code SHA-256 and Git identity as
provenance authority. It verifies definition, strategy ID, module and qualname,
and rejects reissued live strategy identities. It does not infer code hashes from
source inspection. Every run creates fresh financial/runtime/state objects.

Portfolio history is the sealed canonical mark evidence emitted before strategy
callbacks. `final_portfolio` preserves that snapshot unchanged. `final_account`
and `final_reservations` preserve accounting truth after the final callback,
including any newly active order reservation. No final liquidation, cancellation,
remark or accounting correction is performed. This distinction is approved by
the Director and represented in summary JSON and result identity.

Analytics exclude snapshots before trading start and after replay end. Financial
totals use exact Decimal/Fraction arithmetic; analytical ratios are finite floats
or null. Returns are consecutive one-minute simple returns with population
standard deviation, zero risk-free rate and annual factor 525600. CAGR uses 365
days; overflow or undefined statistics return null. Drawdown episodes begin at
the running peak and end at recovery or the final snapshot; average drawdown is
the mean episode depth. Closed-trade metrics describe FIFO lot-consumption
segments, not logical trades. Flat segments break streaks and remain in the
win-rate denominator. Loss summaries retain signed negative PnL.

Artifact root is explicit and absolute; layout is `root/backtests/<run-id>/`.
Parquet v1 has fixed nullable UTF-8 columns in dataclass field order, with explicit
artifact/schema metadata. Financial values use exact canonical decimal text,
timestamps use UTC ISO text, structured fields use canonical JSON. Row order is
by order/fill/decision/command ID, trade exit time then consumption ID, or equity
timestamp. No mutable root or temporary path enters identities or manifests.
Publication stages, verifies schemas/counts/hashes/JSON and atomically renames;
an exclusive per-run publication lock serializes cooperating writers. A stale
lock is an explicit failure requiring operator investigation, never overwritten.
Existing bundles are compared to the complete freshly produced manifest and
verified before reuse. Only the owned staging directory is cleaned on failure.

Readiness and independent acceptance evidence are recorded separately. No local
commit or publication is performed by implementation ownership.

Focused readiness: **43 passed, 1 skipped** on Python 3.14.6, running
`python -m pytest tests/unit/research tests/property/research
tests/integration/research tests/golden/research tests/unit/runtime -q
-p no:cacheprovider --basetemp=.pytest-phase012-ready-final --tb=short` with
the existing root virtualenv interpreter, isolated `PYTHONPATH=src`, and owned
workspace-local TEMP/TMP. Ruff format/check pass on the changed surface; strict
mypy passes on the 21 new source/test modules. `git diff --check` passes.
The symlink attack test skips locally with Windows privilege error 1314;
actual symlink creation coverage remains UNPROVEN until capable CI/review.

Infrastructure ledger: default uv cache `.git` access denied in sandbox;
workspace-local uv cache then managed Python `.lock` access denied; elevated uv
reported missing expected Python 3.14.6 target directory. Direct use of existing
root `.venv` executables works without changing that environment. Sandbox pytest
cannot reopen default or owned temporary directories (WinError 5); elevated
focused tests with owned temp paths work. Do not repeat these sandbox paths.
Implementation validation exceeded the six-execution boundary only to repair
concrete Ruff/mypy/serializer/assertion failures and establish previously blocked
filesystem-backed artifact tests; broad acceptance gates remain QA-owned.

After the complete readiness suite, the manifest fingerprint was aligned with
the serialized manifest semantic fields (excluding its own fingerprint).
Focused artifact rerun: **5 passed** using `python -m pytest
tests/unit/research/test_artifacts.py -q -p no:cacheprovider
--basetemp=.pytest-phase012-manifest --tb=short`. Targeted Ruff/mypy pass for the
two final changed modules. No financial/runtime behavior changed afterward.
