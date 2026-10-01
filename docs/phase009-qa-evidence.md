# Phase009 QA evidence

Date: 2026-10-01

STATUS: PASS (local Python 3.14 acceptance)

## Scope and coverage

Independently reviewed the Phase009 spot-accounting contract, accounting/runtime changes, and the test-package closure. Acceptance covers exact account/fill/reservation/lots/fees/portfolio behavior, same-time atomicity, deterministic replay, runtime chronology, and OCO exclusivity.

## Evidence

All `uv run` commands used `UV_CACHE_DIR` set to the workspace-local `.qa-phase009-uv-cache`.

- `uv run pytest` with `PYTHONPATH` unset — **287 passed, 3 skipped in 7.76s**; collected 290 items. This exact console entry point now imports all tests after adding package markers to the four accounting test directories. The run used the previously approved elevated context because sandbox execution had denied pytest temporary lock and Parquet writes.
- The three skipped tests are symlink cases requiring a Windows privilege unavailable here (WinError 1314).
- `uv run mypy src tests` — PASS, no issues in 96 source files.
- `uv run ruff format --check -- $trackedPy` where `$trackedPy = @(git ls-files '*.py')` — PASS, 92 tracked Python files formatted.
- `uv run ruff format --check -- $phase009Py` where `$phase009Py` contains all Python files under accounting and the Phase009 accounting test directories — PASS, 19 files formatted.
- `uv run ruff check -- $phase009Py` — PASS, all checks passed. Earlier full `uv run ruff check .` also passed.
- Earlier `uv lock --check` — PASS, 35 packages resolved; `uv run lint-imports` — PASS, 2 contracts kept, 0 broken. This repair changed only test package markers, with no dependency, lockfile, production, CI, or Ruff configuration changes.
- Literal local `uv run ruff format --check .` still crashes with Ruff `Expected a ruff source file`, also when UV cache is outside the repository. Explicit checks above cover all tracked Python and all Phase009-owned Python files. Initial CI's repository-wide format gate passed on the implementation commit; the test-only closure still awaits its CI run.

## Findings and limitations

The package markers in `tests/{unit,property,integration,golden}/accounting/__init__.py` resolve the console-entry collection failure. The two financial boundary regressions (future direct cancellation and double settlement of shared OCO exposure) pass as ordinary assertions in the 290-item full suite.

UNPROVEN: latest remote CI for the test-package closure, especially Python 3.13; the three symlink cases skipped under local Windows privilege limits; literal local Ruff `format --check .` traversal. All actual tracked and Phase009-owned Python files passed explicit formatting checks.

No production code, dependencies, lockfiles, CI workflow, or Ruff exclusions were changed by QA. No publication was performed.
