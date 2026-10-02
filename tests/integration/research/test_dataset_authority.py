from dataclasses import replace
from pathlib import Path

import pytest

from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    DatasetVersion,
    ProductSpecProvenance,
)
from command_station.research import BacktestDatasetRef
from tests.execution_fixtures import timestamp
from tests.research_fixtures import NoTrade, setup
from tests.runtime_fixtures import canonical


def test_wrong_version_product_and_corrupt_resolver_rejected(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, NoTrade)
    source = service.datasets.load(spec.datasets[0].dataset_version)

    class Resolver:
        def __init__(self, value: CanonicalCandleDataset):
            self.value = value

        def load(self, version: DatasetVersion) -> CanonicalCandleDataset:
            return self.value

    service.datasets = Resolver(canonical("ETH-USD", minutes=10))
    with pytest.raises(ValueError, match="identity/product"):
        service.run(spec)
    service.datasets = Resolver(source)
    wrong = replace(
        spec, datasets=(BacktestDatasetRef(source.product_id, DatasetVersion("c" * 64)),)
    )
    with pytest.raises(ValueError, match="identity/product"):
        service.run(wrong)
    object.__setattr__(source, "logical_candle_content_sha256", "f" * 64)
    with pytest.raises(ValueError, match="integrity"):
        service.run(spec)


def test_product_spec_provenance_mismatch_and_explicit_absence(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, NoTrade)
    source = service.datasets.load(spec.datasets[0].dataset_version)
    changed = CanonicalCandleDataset(
        product_id=source.product_id,
        start=source.start,
        end=source.end,
        as_of=source.as_of,
        candles=source.candles,
        gaps=source.gaps,
        source_pages=source.source_pages,
        product_spec_provenance=ProductSpecProvenance("d" * 64, timestamp(0)),
    )
    from command_station.market_data.parquet_store import LocalCanonicalDatasetStore

    assert isinstance(service.datasets, LocalCanonicalDatasetStore)
    service.datasets.publish(changed)
    other = replace(spec, datasets=(BacktestDatasetRef(changed.product_id, changed.version),))
    with pytest.raises(ValueError, match="ProductSpec"):
        service.run(other)
    result = service.run(spec)
    assert result.provenance.datasets[0].product_spec_provenance is None
    assert (
        result.provenance.datasets[0].account_product_spec_fingerprint
        == spec.account.product_specs[0].fingerprint
    )


def test_nonzero_slippage_exact_from_real_fills(tmp_path: Path) -> None:
    from decimal import Decimal

    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    from command_station.execution import ReferenceExecutionSpec

    service, spec = setup(tmp_path)
    result = service.run(
        replace(spec, execution=ReferenceExecutionSpec(slippage_bps=10, fee_bps=100))
    )
    fills = pq.read_table(service.artifacts.directory(result.run_id) / "fills.parquet").to_pylist()
    expected = sum(
        (Decimal(f["slippage_per_base"]) * Decimal(f["base_quantity"]) for f in fills), Decimal(0)
    )
    assert result.metrics.total_slippage_cost == expected == Decimal("0.21")
    assert (
        result.metrics.total_fees
        == result.execution_summary.total_fees
        == result.final_portfolio.fees_to_date
    )
