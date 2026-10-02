# Phase 012 Security / Reliability evidence

Status: PASS after manifest-integrity repair.

Reviewed the bounded research orchestration, exact dataset resolution, strategy
catalog, analytics, replay-end extension, and immutable artifact publication.
No production code was changed by the reviewer.

The initial review found that public artifact verification accepted an incomplete
manifest. A real no-trade backtest was published; its manifest was replaced with
an otherwise identical manifest containing no artifact records, and its
`fills.parquet` was replaced with arbitrary corrupt bytes. Public `verify()`
returned successfully because it checked only the supplied artifact records.
The original reproduction is retained in `.security-review/probe_manifest.py`.

The repair validates exactly eight unique, canonically ordered fixed artifact
records, supported schema versions, valid identities and SHA-256 hashes,
nonnegative exact integer sizes and Parquet row counts, and absent JSON row
counts. Public verification repeats this validation, including when frozen
construction has been bypassed.

Independent closure validation used the existing Python environment with
`PYTHONPATH=src;.` and filesystem execution outside the blocked sandbox:

```text
..\.venv\Scripts\python.exe -m pytest tests/unit/research/test_artifacts.py -p no:cacheprovider --basetemp=.security-review\closure-temp -q
22 passed in 1.71s
```

The original probe now fails at empty-manifest construction with
`BacktestReproducibilityError: manifest requires exactly eight unique fixed artifacts`.
Focused regressions also reject incomplete and duplicate manifests after frozen
construction is bypassed and corrupt artifact bytes are installed.

No findings remain in the repaired manifest boundary. Native Windows symlink
attack execution remains UNPROVEN because symlink creation is unavailable
(`WinError 1314`); adversarial concurrent filesystem replacement was not exercised.
Repository-wide acceptance gates and exact-commit CI remain independently owned
by QA and Release.

After formatting the reviewer-owned scratch probe, requested root Ruff checks
were run independently outside the sandbox:

```text
..\.venv\Scripts\ruff.exe format --check .
179 files already formatted
..\.venv\Scripts\ruff.exe check .
All checks passed!
```

The preceding sandbox root format attempt crashed with access-denied traversal
and `Expected a ruff source file`; the outside-sandbox checks above succeeded.
