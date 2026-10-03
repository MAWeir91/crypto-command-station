"""Strict reconstruction of the sealed canonical experiment representation."""

import json
from dataclasses import fields
from decimal import Decimal
from typing import Any

from command_station.accounting import InitialHolding, SpotAccountSpec
from command_station.domain import (
    AssetSymbol,
    ProductId,
    ProductSpec,
    ProductType,
    UtcTimestamp,
    Venue,
)
from command_station.execution import ReferenceExecutionSpec
from command_station.market_data.datasets import DatasetVersion
from command_station.research.specs import (
    BacktestDatasetRef,
    BacktestPeriod,
    BacktestSpec,
    StrategyArtifactRef,
    canonical_json,
)
from command_station.risk import RiskPolicy


class SpecCodecError(ValueError):
    """Persisted experiment bytes cannot be trusted."""


def strict_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise SpecCodecError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=pairs)
        if canonical_json(value) != data:
            raise SpecCodecError("noncanonical JSON")
        return value
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SpecCodecError("invalid canonical JSON") from exc


def encode_spec(spec: BacktestSpec) -> bytes:
    if type(spec) is not BacktestSpec:
        raise SpecCodecError("exact BacktestSpec required")
    return canonical_json(spec.to_dict())


def decode_spec(data: bytes) -> BacktestSpec:
    try:
        d = strict_json(data)
        parameters = []
        for p in d["parameters"]:
            if set(p) != {"name", "type", "value"} or type(p["name"]) is not str:
                raise SpecCodecError("invalid parameter")
            value = p["value"]
            if p["type"] == "Decimal":
                if type(value) is not str:
                    raise SpecCodecError("decimal text required")
                value = Decimal(value)
            elif p["type"] != type(value).__name__ or type(value) not in (
                int,
                bool,
                float,
                str,
                type(None),
            ):
                raise SpecCodecError("parameter type mismatch")
            parameters.append((p["name"], value))
        a = d["account"]
        products = []
        decimal_names = {
            "base_increment",
            "quote_increment",
            "price_increment",
            "base_min_size",
            "base_max_size",
            "quote_min_size",
            "quote_max_size",
        }
        for raw in a["product_specs"]:
            p = dict(raw)
            for name in decimal_names:
                if type(p[name]) is not str:
                    raise SpecCodecError("product decimal text required")
                p[name] = Decimal(p[name])
            p["venue"], p["product_type"] = Venue(p["venue"]), ProductType(p["product_type"])
            p["product_id"] = ProductId(p["product_id"]["value"])
            for name in ("base_currency", "quote_currency"):
                p[name] = AssetSymbol(p[name]["value"])
            products.append(ProductSpec(**p))
        holdings = tuple(
            InitialHolding(ProductId(h["product_id"]["value"]), h["base_quantity"], h["unit_cost"])
            for h in a["initial_holdings"]
        )
        risk = {f.name: d["risk_policy"][f.name] for f in fields(RiskPolicy)}
        for name in (
            "max_order_notional",
            "max_product_exposure",
            "max_portfolio_exposure",
            "minimum_cash_reserve",
        ):
            if risk[name] is not None:
                if type(risk[name]) is not str:
                    raise SpecCodecError("risk decimal text required")
                risk[name] = Decimal(risk[name])
        spec = BacktestSpec(
            StrategyArtifactRef(d["strategy_artifact"]["fingerprint"]),
            tuple(parameters),
            tuple(
                BacktestDatasetRef(
                    ProductId(r["product_id"]["value"]),
                    DatasetVersion(r["dataset_version"]["value"]),
                )
                for r in d["datasets"]
            ),
            BacktestPeriod(
                UtcTimestamp.parse(d["period"]["trading_start"]),
                UtcTimestamp.parse(d["period"]["replay_end"]),
            ),
            SpotAccountSpec(
                initial_cash=a["initial_cash"],
                product_specs=tuple(products),
                initial_holdings=holdings,
            ),
            RiskPolicy(**risk),
            ReferenceExecutionSpec(d["execution"]["slippage_bps"], d["execution"]["fee_bps"]),
            d["random_seed"],
        )
        if encode_spec(spec) != data:
            raise SpecCodecError("spec schema or canonical roundtrip mismatch")
        return spec
    except Exception as exc:
        raise SpecCodecError("invalid persisted BacktestSpec") from exc
