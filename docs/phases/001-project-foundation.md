# Phase 001 — Project Foundation

**Status:** Ready for implementation  
**Date:** 2026-09-28  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009

## 1. Objective

Establish a clean, reproducible, cross-platform Python project foundation for Crypto Command Station without implementing trading behavior.

This phase creates the repository mechanics that all later financial/domain work will rely on:

- Python project/package structure;
- dependency locking;
- formatting/linting;
- strict type-check baseline;
- testing baseline;
- property-test capability;
- dependency-boundary tooling foundation;
- CI;
- documentation directories;
- simple developer commands;
- minimal package import/smoke test.

The output of this phase should make subsequent bounded Codex phases predictable and independently verifiable.

## 2. Why this phase exists

Financial correctness depends on repeatable environments and enforceable architecture.

Before adding Coinbase data, orders, accounting, or risk, the repository needs:

- one declared Python support range;
- one authoritative dependency workflow;
- one-shot validation commands;
- CI that matches local commands;
- a package layout that supports dependency boundaries;
- tests that run in a locked environment.

Do not use this phase to "get ahead" on the trading engine.

## 3. Current repository state

At phase start, the repository should contain the foundational documentation only, including:

- `AGENTS.md`;
- `MASTER_ENGINEERING_SPEC.md`;
- accepted ADRs under `docs/adr/`;
- this phase specification.

If implementation discovers unexpected existing files or conflicts, the Director must inspect before authorizing overwrite/removal.

## 4. Expected Codex routing

Follow the user's global Codex engineering rules.

Because the repository is new and the relevant source-of-truth files are obvious, broad Explorer mapping is **not required by default**.

Recommended routing:

- **Director — Sol / Medium:** orient, confirm scope, integrate evidence, accept/reject.
- **Back-End Engineer — Terra / Medium:** own the bounded project/tooling implementation.
- **QA Engineer — Luna / Medium:** independently validate the acceptance contract.
- **Security/Reliability:** not required by default for Phase 001; add only if a concrete supply-chain, permission, workflow-authority, or reliability issue justifies it.
- **Release Engineer — Luna / Low:** stage/commit/push if Codex is authorized to publish.

The Director should not duplicate routine implementation or QA validation.

## 5. Technical baseline

### 5.1 Python

Supported interpreter range for the initial foundation:

```text
Python >=3.13,<3.15
```

CI should test both Python 3.13 and 3.14 unless a concrete dependency incompatibility is proven.

Do not target Python 3.15 prerelease in Phase 001.

### 5.2 Project/dependency management

Use:

```text
uv
```

with:

- `pyproject.toml` as project metadata/dependency authority;
- committed `uv.lock`;
- locked CI execution;
- repository-local `.venv` behavior managed by uv.

Do not add Poetry, Pipenv, Conda, or a second dependency manager.

### 5.3 Build backend

Use a lightweight PEP 517 backend suitable for a normal `src/` package.

Preferred baseline:

```text
hatchling
```

If the implementer identifies a concrete compatibility issue, escalate rather than silently switching build systems.

### 5.4 Formatting/linting

Use:

```text
ruff
```

for:

- linting;
- import hygiene where supported;
- formatting.

Do not add Black/isort separately unless a future accepted decision justifies redundant tooling.

### 5.5 Type checking

Use:

```text
mypy
```

with a strict baseline for project code.

If a specific third-party library later requires targeted exclusions/stubs, keep them narrow and documented.

Do not globally disable strictness to accommodate one dependency.

### 5.6 Testing

Use:

```text
pytest
hypothesis
```

Phase 001 itself needs only smoke/foundation tests, but Hypothesis is included now because property/invariant testing is a core project contract for later financial phases.

Do not establish an arbitrary code-coverage percentage as a release gate in this phase.

### 5.7 Dependency-boundary enforcement

Add:

```text
import-linter
```

or an equivalently small, explicit dependency-contract mechanism.

Phase 001 should establish the tooling and at least one meaningful package-boundary contract that can grow with the repository.

Do not create fictional module layers solely to satisfy the tool. Contracts should apply to package structure actually introduced by this phase.

## 6. Required repository outputs

The implementation owner should create the minimum useful foundation.

Expected files/areas include approximately:

```text
.gitignore
README.md
pyproject.toml
uv.lock

.github/
  workflows/
    ci.yml

src/
  command_station/
    __init__.py

tests/
  test_package_smoke.py

docs/
  adr/
  phases/
```

Additional small configuration files are allowed when the selected tools genuinely require them.

Do not scaffold all future domain/runtime modules in this phase.

## 7. Project metadata requirements

`pyproject.toml` should define at minimum:

- project name: `crypto-command-station`;
- import package: `command_station`;
- supported Python range;
- build backend;
- development dependency group;
- Ruff configuration;
- mypy configuration;
- pytest configuration where useful;
- import-linter configuration or reference to its config.

Do not declare a software license unless the user has explicitly selected one.

Do not invent author/contact metadata beyond what is already safely established and necessary.

## 8. README requirements

Create a concise README containing:

- product name;
- one-paragraph purpose;
- current status: foundational/backtesting-first;
- Coinbase-first scope;
- local environment setup;
- authoritative validation commands;
- pointers to `AGENTS.md` and `MASTER_ENGINEERING_SPEC.md`.

Do not write marketing copy or claim features that do not exist.

## 9. Git ignore requirements

At minimum ignore:

- `.venv/`;
- Python bytecode/cache;
- pytest/mypy/Ruff caches;
- build/dist artifacts;
- local coverage outputs;
- IDE/OS noise where appropriate;
- local secrets/environment files such as `.env`;
- future local market-data/artifact directories if they are not intended for Git.

Do **not** ignore `uv.lock`.

Do not add actual secret values.

## 10. Package baseline

The package must be importable:

```python
import command_station
```

The initial package should not contain trading logic.

A package version constant is optional; if present, do not create a separate manual version source that can drift from project metadata without reason.

## 11. Validation commands

Provide one-shot commands that work without watch mode.

The authoritative local validation sequence should be equivalent to:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

Exact argument details may be adjusted for correct tool behavior, but the commands documented in README and executed in CI must remain materially aligned.

On Windows Codex workers, do not introduce watch/dev-server validation paths.

## 12. CI requirements

Create a GitHub Actions workflow for pushes/pull requests.

CI must:

1. check out the repository;
2. install uv using an appropriate maintained action/mechanism;
3. run against Python 3.13 and 3.14;
4. use the committed lockfile rather than opportunistically upgrading dependencies;
5. run the required validation gates;
6. terminate after completion;
7. avoid services/databases not needed by Phase 001.

It is acceptable to factor invariant validation into a single matrix job or small set of jobs.

Keep CI easy to understand.

Do not add deployment, publishing, release, Docker, Coinbase, or credential workflows.

## 13. Architecture boundary foundation

The project is a modular monolith.

Phase 001 should establish a minimal dependency-enforcement capability without pretending later modules already exist.

At minimum:

- project package must not depend on test code;
- package structure should use `src/` layout;
- future architectural import contracts must be easy to add centrally.

If a meaningful domain/infrastructure boundary does not yet exist, do not fabricate empty packages simply to enforce one.

The acceptance criterion is that dependency-boundary tooling is installed/configured and successfully checks a real current contract.

## 14. Reproducibility expectations

A fresh checkout with a supported Python installation and uv must be able to reproduce the development environment from:

```text
pyproject.toml
uv.lock
```

CI must fail if the lockfile is out of sync.

Routine validation must not implicitly upgrade dependencies.

## 15. Testing requirements

Create at least one smoke test that proves:

- the package imports from the installed project;
- foundational project metadata/package wiring is valid.

Do not add placeholder tests asserting meaningless constants solely to inflate test counts.

The QA Engineer should inspect the configuration itself in addition to executing commands.

## 16. Acceptance criteria

Phase 001 is accepted only if all applicable claims are evidenced:

1. `uv sync` or the equivalent locked project setup succeeds on a supported interpreter.
2. `uv.lock` is committed and current.
3. `import command_station` succeeds through the project environment.
4. Ruff formatting check passes.
5. Ruff lint check passes.
6. mypy passes with the agreed strict baseline.
7. import dependency checks pass.
8. pytest passes.
9. CI configuration covers Python 3.13 and 3.14.
10. CI uses the locked dependency graph.
11. README documents setup and the same validation workflow.
12. No trading/domain/provider implementation was introduced.
13. No Coinbase credentials or live authority exists.
14. No license was selected without user authorization.
15. The repository structure remains minimal and consistent with the modular-monolith ADR.

If an environment prevents a required command from running, classify the evidence according to the global Codex infrastructure/QA rules rather than claiming success.

## 17. Implementation-owner validation

The Back-End Engineer should run only the focused checks necessary to show the changed foundation is ready for QA, normally:

- dependency sync/lock health;
- Ruff checks;
- mypy;
- import-linter;
- pytest.

Return exact evidence using the global worker evidence contract.

Do not perform a broad invented validation program beyond these claims.

## 18. Independent QA assignment

QA receives:

- this phase specification;
- changed-file list;
- implementation evidence;
- relevant project/global rules.

QA should independently verify:

- setup/config consistency;
- locked dependency behavior;
- package importability;
- lint/format/type/test gates;
- import-linter contract;
- CI matrix and lock usage;
- absence of out-of-scope trading/provider code;
- README command accuracy.

QA should use the smallest evidence set that establishes those claims.

## 19. Security/Reliability review

Not required by default.

Escalate to Security/Reliability if implementation introduces any of:

- credential handling;
- external write authority;
- unusual GitHub workflow permissions;
- third-party executable download patterns with unclear trust;
- dependency/supply-chain behavior outside ordinary uv/PyPI use;
- persistence or concurrency behavior beyond this phase.

## 20. Explicitly out of scope

Phase 001 must not implement:

- Coinbase REST or WebSocket clients;
- historical data import;
- ProductSpec domain model;
- Candle domain model;
- TradingRuntime;
- event dispatcher;
- orders;
- fills;
- broker;
- accounting;
- risk;
- strategies;
- indicators;
- analytics;
- database schema;
- Parquet datasets;
- MCP server;
- FastAPI;
- frontend;
- Docker deployment;
- paper/live trading;
- secrets;
- authenticated Coinbase access.

Those belong to later phases.

## 21. Stop/escalate conditions

Stop and escalate to the Director rather than silently deciding if:

- the supported Python range is incompatible with required foundation tooling;
- uv cannot support the required locked workflow;
- a selected tool forces architecture changes beyond this phase;
- repository state contains unexpected user work;
- a license decision becomes necessary;
- CI requires elevated GitHub permissions;
- an existing global Codex rule conflicts with this phase.

## 22. Definition of done

Phase 001 is done when a fresh developer or Codex worker can clone the repository, create the locked environment, import the package, and run one documented finite validation sequence that independently passes locally and is represented in CI—without any trading functionality having been implemented.
