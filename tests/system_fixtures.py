"""Small Phase013 extensions of the accepted research composition fixture."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from command_station.domain import Candle
from command_station.market_data.datasets import CanonicalCandleDataset
from command_station.research import (
    BacktestDatasetRef,
    BacktestResult,
    BacktestService,
    BacktestSpec,
)
from command_station.strategy import Strategy
from tests.research_fixtures import setup


def scenario(
    root: Path,
    factory: Callable[[], Strategy],
    bars: tuple[Candle, ...],
    **options: Any,
) -> tuple[BacktestService, BacktestSpec]:
    service, spec = setup(root, factory, minutes=len(bars), **options)
    source = service.datasets.load(spec.datasets[0].dataset_version)
    source = CanonicalCandleDataset(
        product_id=source.product_id,
        start=source.start,
        end=source.end,
        as_of=source.as_of,
        candles=bars,
        gaps=(),
        source_pages=source.source_pages,
        product_spec_provenance=source.product_spec_provenance,
    )
    service.datasets.publish(source)  # type: ignore[attr-defined]
    return service, replace(spec, datasets=(BacktestDatasetRef(source.product_id, source.version),))


def rows(service: BacktestService, result: BacktestResult, name: str) -> list[dict[str, Any]]:
    return pq.read_table(service.artifacts.directory(result.run_id) / name).to_pylist()  # type: ignore[no-any-return]


def bundle(service: BacktestService, result: BacktestResult) -> dict[str, object]:
    folder = service.artifacts.directory(result.run_id)
    assert result.artifact_manifest is not None
    service.artifacts.verify(result.artifact_manifest)
    return {
        p.name: rows(service, result, p.name)
        if p.suffix == ".parquet"
        else json.loads(p.read_bytes())
        for p in folder.iterdir()
    }
