"""Shared fixtures: load the real rule packs and market registry once."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from complygraph.engine import evaluate_market
from complygraph.loader import default_rule_paths, load_evidence, load_markets, load_product, load_rules
from complygraph.models import EvidenceBundle, MarketRegistry, Product, Rule

REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 14)


@pytest.fixture(scope="session")
def rules() -> list[Rule]:
    return load_rules(default_rule_paths(REPO))


@pytest.fixture(scope="session")
def markets() -> MarketRegistry:
    return load_markets(REPO / "config" / "markets.yaml")


@pytest.fixture(scope="session")
def product() -> Product:
    return load_product(REPO / "examples" / "products" / "pb100.yaml")


@pytest.fixture(scope="session")
def bundle() -> EvidenceBundle:
    return load_evidence(REPO / "examples" / "evidence" / "pb100_evidence.yaml")


_cache: dict = {}


def _loaded():
    if "rules" not in _cache:
        _cache["rules"] = load_rules(default_rule_paths(REPO))
        _cache["markets"] = load_markets(REPO / "config" / "markets.yaml")
    return _cache["rules"], _cache["markets"]


def run(rules, markets, product, bundle, market="de", channel=None, as_of=AS_OF):
    if rules is None or markets is None:
        default_rules, default_markets = _loaded()
        rules = rules or default_rules
        markets = markets or default_markets
    return evaluate_market(rules, product, bundle, market, markets.markets[market], channel, as_of)


@pytest.fixture(scope="session")
def run_factory(rules, markets):
    return run
