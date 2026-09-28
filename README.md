# Crypto Command Station

Crypto Command Station is a deterministic, auditable crypto trading platform being built
backtesting-first. Coinbase Advanced is the canonical external venue; current work is only
the project foundation and does not yet implement trading, market data, or provider access.

## Local setup

Install Python 3.13 or 3.14 and [uv](https://docs.astral.sh/uv/), then create the locked
development environment:

```bash
uv sync --locked
```

## Validation

Run the same finite validation sequence used by CI:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

Project architecture and engineering constraints are defined in [AGENTS.md](AGENTS.md) and
[MASTER_ENGINEERING_SPEC.md](MASTER_ENGINEERING_SPEC.md).
