# Phase 012 independent QA evidence

Post security-repair verification ran in `.phase012-workspace` at baseline
`390dc8a746789f819bcc44f60e1ecf13175991ef` (`main`). The existing sealed
Phase 011 predecessor recorded in `012-acceptance-evidence.md` is unchanged.

The repair validates an exact eight-record manifest with unique fixed relative
paths, strict record types/versions/identities, hashes, sizes, and row counts.
The public `verify` method repeats those checks. New artifact tests exercise
empty, incomplete, duplicate, and construction-bypass manifests, plus malformed
record and manifest metadata. No defect reproduced.

Final regression command, using the existing workspace virtualenv, `PYTHONPATH=src`,
owned workspace temp paths, and `-p no:cacheprovider`:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest-phase012-qa-security --tb=short
456 passed, 4 skipped
```

All four skips are Windows symlink tests blocked by WinError 1314. Exact Phase012
surface checks passed: Ruff format (22 files), Ruff lint, strict mypy (151 source
files), import-linter (4 contracts), and `git diff --check`. `pyproject.toml` and
`uv.lock` have no diff. Full repository Ruff format/check also ran, but included
the separate untracked `.security-review/probe_manifest.py` scratch script, which
has formatting/import-order issues; the Phase012 production and test surface
passes both Ruff checks.

`uv lock --check` remains unverified under the previously recorded uv/cache and
configured-interpreter blockers. Python 3.13/3.14 CI and symlink-capable filesystem
coverage remain outstanding. This QA pass made no production or dependency edits.
