# Phase 013 independent QA evidence

Local behavioral verdict: **PASS**. Final cross-version acceptance remains
**UNPROVEN** until exact-commit GitHub CI on Python 3.13 and 3.14 succeeds.

## Scope and authority

Reviewed project AGENTS, Phase013 requirements, master §§61–66/73, relevant
financial-truth/runtime/reference-engine/service ADRs, the new tests and evidence
documents, and targeted existing historical protecting tests. HEAD and
origin/main both remain `de09476701f609f36e14accbfa87f00ea3a51937`.
Tracked production/dependency/lock diff is empty. New files are tests and phase
evidence only. QA edited documentation only, with Director authorization.

## Exact independent commands and results

Windows PowerShell, CPython 3.14.6; commands ran in the isolated Phase013 checkout.
Elevated test/setup execution was used because the inherited sandbox cache/temp
failures are already recorded. No equivalent blocked sandbox path was retried.

```powershell
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.uv-cache'
uv sync --locked --python C:\Users\TradeStation\AppData\Roaming\uv\python\cpython-3.14.6-windows-x86_64-none\python.exe
uv lock --check
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy src tests
uv run --no-sync lint-imports
```

- Sync: resolved/checked 35 packages; success.
- Lock: resolved 35 packages; success.
- Format: 196 files already formatted.
- Ruff lint: all checks passed.
- Strict mypy: no issues in 165 source files.
- Import linter: 84 files/408 dependencies; four contracts kept, zero broken.

```powershell
.venv\Scripts\python.exe -m pytest tests/golden/system tests/property/system tests/integration/system tests/regression -q -p no:cacheprovider --tb=short
```

**48 passed in 17.62 s**, independently establishing the new golden/property/
permutation/Decimal/root/fresh-process/failure/corruption scenarios.

```powershell
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.uv-cache'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
uv run --no-sync pytest -p no:cacheprovider --tb=short
```

**508 collected; 504 passed, four skipped in 41.39 s**. Every historical protecting
test named in the inventory executed successfully. Normal collection with
PYTHONPATH unset establishes package collection protection. `--no-sync` uses the
environment just established by locked sync; `-p no:cacheprovider` disables only
pytest's result cache.

## Acceptance observations

The eleven required service golden scenarios use real BacktestService publication,
and exact persisted Fill/order/equity/risk rows assert their financial facts.
Generated accounting observations inspect public settlement boundaries, replay
ledger truth, quantities/lots, fees and realized consumptions; the cash oracle
independently sums persisted Fill facts. Partial fills use immutable accounting
fixtures as explicitly required by the accepted full-fill broker contract.
Existing risk/resampling/strategy tests directly establish the mapped component
invariants; no coverage was accepted solely from a document mapping.

Complete result and verified logical artifact equality passed across independent
roots, source/declaration permutations, ambient Decimal contexts and fresh
processes with hash seeds 1/987. All ten material identity variants changed run
and result identities. Separate-root exact observed IDs/fingerprints are recorded
in `013-reproducibility-evidence.md`; that direct inspection additionally read all
JSON members and Parquet rows and verified both manifests.

Nine corrupted bundle members fail reuse without overwriting any existing member.
Hardlinked artifact and existing publication-lock tests pass. Injected dataset,
strategy, parameter, warmup, callback, accounting and serializer failures publish
no completed bundle; unrelated staging survives. Existing frozen-manifest forgery,
dataset corruption and derived-cache reconstruction tests also pass.

The inventory now explicitly records phase, commit attribution limits, severity
availability and COVERED/GAP CLOSED IN 013 status. No production defect was found.

## Unproven claims and risks

Four symlink checks skip with **WinError 1314: required privilege not held**:
canonical-store staging, external canonical manifest, derived-cache staging, and
research artifact root. These cases remain unproven locally; hardlink coverage
passes. Python 3.13/3.14 exact-commit CI, intentional golden agreement across both
versions, and independent Security/Reliability acceptance remain external to this
QA execution. No publication was attempted. No runtime performance target or
partial-liquidity simulation is claimed.
