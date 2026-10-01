# Phase009 QA evidence

Date: 2026-10-01

STATUS: PASS (local Python 3.14 acceptance)

## Scope and coverage

Independently reviewed the Phase009 spot-accounting contract and implementation map. Tested account funding, BUY/SELL settlement, reservations and release, FIFO lots, fees, portfolio marks, exact Decimal behavior, fill-batch atomicity, runtime ordering, replay determinism, OCO exclusivity, and cancellation chronology.

## Evidence

All `uv run` commands used a workspace-local `UV_CACHE_DIR` unless an external OS temporary directory is stated.

- `uv lock --check` — PASS, 35 packages resolved.
- `uv run mypy src tests` — PASS, no issues in 90 source files (before owner repair). Owner's post-repair focused mypy check: PASS, 15 source files.
- `uv run ruff check .` — PASS, all checks passed; it emitted access-denied warnings for existing protected directories. Owner's post-repair focused Ruff checks: PASS.
- `uv run lint-imports` — PASS, 2 contracts kept, 0 broken.
- `uv run pytest` initially failed test imports because the console entry point did not resolve local `tests.*`. Setting `PYTHONPATH` to the repository root and `src` resolved collection.
- Full post-repair command: `$env:UV_CACHE_DIR = Join-Path (Get-Location) '.qa-phase009-uv-cache'; $env:PYTHONPATH = "$((Get-Location).Path);$((Join-Path (Get-Location) 'src'))"; uv run pytest -q -p no:cacheprovider --tb=short` — **287 passed, 3 skipped in 10.04s**. The run required an approved elevated retry after sandbox execution showed concrete temporary-filesystem denial: pytest could not create `.lock` under `%TEMP%\pytest-of-TradeStation`, and a property test could not create its temporary Parquet dataset. The elevated run completed; the three skips are symlink tests because this Windows environment lacks the required privilege (WinError 1314).
- `uv run ruff format --check .` — Ruff panicked with `Expected a ruff source file`, including with an external OS-temp UV cache. Literal directory traversal remains UNPROVEN.
- Explicit Ruff format check over **all 92 tracked Python files plus Phase009-owned Python files**: `uv run ruff format --check -- $pythonFiles` — PASS, `92 files already formatted`. This establishes formatting for all tracked and Phase009-owned Python source while avoiding the repository traversal panic. No project exclusions were changed.
- Post-repair security probes are ordinary assertions (the prior strict xfails were removed). The full suite passed with them included, covering both direct future cancellation and double settlement of shared OCO exposure.

## Findings and limitations

The two previously reproduced security defects are closed by the owner's bounded lifecycle-chronology and shared-OCO exclusivity repair; both regression probes passed in the full post-repair suite. QA made no production changes.

UNPROVEN: the literal `ruff format --check .` traversal command, Python 3.13 CI, and the three symlink cases skipped because of the environment privilege. The explicit 92-file Ruff formatting check passed. Remote CI should establish Python 3.13 and 3.14 clean-checkout results.

No dependencies or lockfiles were modified and no publication was performed.
