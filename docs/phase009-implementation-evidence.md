# Phase009 implementation readiness

Implementation readiness: PASS. Independent QA, Security/Reliability, full repository gates, and Python 3.13/3.14 CI remain separate acceptance gates.

## Working map

- `accounting/models.py`: immutable USD account input, deterministic local identities, ledger, reservation, lot, position, portfolio evidence and explicit versions.
- `accounting/_exact.py`: Fraction-backed terminating exact Decimal arithmetic, context-free negation, canonical logical fingerprints. No broker-private helper dependency.
- `accounting/ledger.py`: replay from zero is the balance authority; no mutable balance cache.
- `accounting/reservations.py`: pure normalization/product/funding preflight; explicit market/stop/BUY OCO quote caps; SELL inventory and exact BUY LIMIT settlement funding.
- `accounting/engine.py`: staged immutable financial state; batch reconciliation and one commit; Fill identity/provenance/lifecycle/fee/resource checks; separate fees; FIFO lot consumption; terminal shared-reservation release.
- `accounting/positions.py`: account/lot reconciliation, exact remaining cost and gross PnL, retained dust, eight-decimal ROUND_HALF_EVEN display-only average.
- `accounting/portfolio.py`: current completed canonical 1m closes only, missing owned mark failure, exact equity and unrealized PnL.
- `runtime/engine.py`, `runtime/events.py`: accounting-required order APIs; fresh compatible composition; reject direct unaccounted broker paths; ACCOUNTING_APPLIED and PORTFOLIO_UPDATED before publication; immutable step/result financial evidence.
- `tests/accounting_fixtures.py`; unit/property/integration/golden accounting directories: synthetic real-broker fixtures, constructed partial Fill/order facts, bounded generated sequences, real replay composition, golden financial history/stop/OCO.
- Existing integration/execution runtime tests and golden/execution stop test now use funded account composition. Market-only runtime tests retain their market-only trace.

## Accepted bounded decisions

1. Account products must exactly match canonical replay product IDs. Initial holdings must have explicit unit cost. USD is the sole cash/quote asset; registered noncash bases are unique.
2. Financial projections replay the ledger from zero; immutable tuple histories are staged and replaced only after all batch checks. A failed Fill batch leaves ledger, reservations, lots, consumption, applied-fill evidence, and fingerprint unchanged.
3. A BUY market/stop quote cap authorizes resources only. Execution remains Phase008 execution. An over-cap Fill is fatal and cannot resize or borrow.
4. Director-approved cancellation boundary: `cancel_order` rejects an OCO peer before mutation; `cancel_oco(group_id)` validates both peers and shared reservation, cancels both at one ready boundary, and releases once. Phase008 broker requires two active OCO peers; its implementation is unchanged.
5. Fee bps must be below 10000. Display average uses fixed eight places, rational ROUND_HALF_EVEN; it never participates in financial truth.

## Focused checks

Native existing Python 3.14 virtual environment, no dependency or lockfile changes.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/accounting tests/property/accounting tests/integration/accounting tests/golden/accounting tests/integration/execution/test_runtime_execution.py tests/golden/execution/test_reference_scenarios.py -q -p no:cacheprovider --basetemp=.qa-phase009-impl-final
```

Result: **61 passed in 3.63s**. The bounded Hypothesis sequence covers thirteen reconciliation/conservation/determinism claims, including repeat execution under generated Decimal precision 1 through 9.

```powershell
.venv/Scripts/mypy.exe src/command_station/accounting src/command_station/runtime tests/accounting_fixtures.py tests/unit/accounting tests/property/accounting tests/integration/accounting tests/golden/accounting tests/integration/execution/test_runtime_execution.py tests/golden/execution/test_reference_scenarios.py
```

Result: **Success: no issues found in 20 source files**.

```powershell
.venv/Scripts/ruff.exe format --check src/command_station/accounting src/command_station/runtime/engine.py src/command_station/runtime/events.py tests/accounting_fixtures.py tests/unit/accounting tests/property/accounting tests/integration/accounting tests/golden/accounting tests/integration/execution/test_runtime_execution.py tests/golden/execution/test_reference_scenarios.py
.venv/Scripts/ruff.exe check src/command_station/accounting src/command_station/runtime/engine.py src/command_station/runtime/events.py tests/accounting_fixtures.py tests/unit/accounting tests/property/accounting tests/integration/accounting tests/golden/accounting tests/integration/execution/test_runtime_execution.py tests/golden/execution/test_reference_scenarios.py
git diff --check
```

Results: **17 files already formatted; All checks passed; diff whitespace check clean**.

Validation exceeded six executions to repair concrete test collection/static failures and establish the still-required golden stop/OCO, runtime batch rollback, and activation timestamp preflight claims. Initial failures were a ProductSpec-invalid parameter constructed at collection, and mypy frozen-write/tuple-test typing issues; all were test code and repaired. No production contract was relaxed.

## Environment ledger and pending gates

Default `uv run` could not initialize `C:\Users\TradeStation\AppData\Local\uv\cache\sdists-v9\.git`: Access denied (os error 5), native Windows sandbox. Those commands ran no code checks. Director approved direct existing `.venv` tools; these ran successfully. QA should use a workspace-local UV_CACHE_DIR for exact full gate commands, avoiding the blocked default cache.

Full lock/format/lint/type/import/test acceptance and remote Python 3.13/3.14 CI are not claimed by this implementation handoff. No staging, commit, push, or publication was performed. Existing user-owned untracked phase specifications and QA artifacts were preserved.

## SEC009-1/2 bounded repair readiness

Owner repair readiness: PASS; independent closure remains with QA and Security/Reliability.

- SEC009-1: broker-state validation now requires the current explicit timestamp. Before runtime market processing and before accounting batch mutation, validate creation <= activation <= current boundary, activation <= cancellation <= boundary, and no applied/new Fill execution after cancellation. Direct reservation binding also rejects creation later than activation. Future normal, partial, and OCO terminal facts cannot release funding or suppress eligible runtime activity early.
- SEC009-2: for each shared OCO reservation, collect distinct covered OrderIds from previously applied plus new Fill facts. More than one filled peer fails before staging or committing. Multiple partial fills of the same chosen peer remain supported.
- Production changes limited to `accounting/engine.py`. New owner regressions: `tests/unit/accounting/test_lifecycle_repair.py`. Reviewer authorized removal of only the three temporary strict xfail decorators from `test_phase009_security_boundary.py`; probe bodies remain unchanged. No broker semantics or dependencies changed.

Focused commands:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/accounting/test_lifecycle_repair.py tests/unit/accounting/test_phase009_security_boundary.py tests/unit/accounting/test_spot_accounting.py tests/property/accounting tests/integration/accounting tests/golden/accounting tests/integration/execution/test_runtime_execution.py tests/golden/execution/test_reference_scenarios.py -q -p no:cacheprovider --basetemp=.qa-phase009-repair-one
.venv/Scripts/mypy.exe src/command_station/accounting src/command_station/runtime tests/unit/accounting/test_lifecycle_repair.py tests/unit/accounting/test_phase009_security_boundary.py
.venv/Scripts/ruff.exe format --check src/command_station/accounting/engine.py tests/unit/accounting/test_lifecycle_repair.py tests/unit/accounting/test_phase009_security_boundary.py
.venv/Scripts/ruff.exe check src/command_station/accounting/engine.py tests/unit/accounting/test_lifecycle_repair.py tests/unit/accounting/test_phase009_security_boundary.py
git diff --check
```

Results: **73 passed in 3.00s; strict mypy clean in 15 source files; 3 files already formatted; Ruff lint clean; diff whitespace clean**. The repair required one focused pytest execution and one focused mypy execution; no broad acceptance checks were duplicated.

Inherited QA environment ledger preserved: full Ruff format scanning `.` panics with Expected a ruff source file; full pytest temporary teardown scanning produces WinError5 and unresolved E/F indicators; `uv run pytest` console form cannot resolve local `tests` modules while `uv run python -m pytest` focused composition passes. Default uv cache denial remains unchanged. Existing `.venv` focused repair commands introduced no additional environment blocker.
