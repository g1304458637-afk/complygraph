"""Invariants: safe-unknown semantics, honest coverage, deterministic replay."""

from __future__ import annotations

import copy

from complygraph.engine import eval_predicate, resolve_fact
from complygraph.models import Product
from complygraph.receipt import build_receipt

from conftest import AS_OF, run


def test_unknown_never_passes(run_factory, product, bundle):
    """Missing applicability facts must yield `unknown` + red, never green."""
    stripped = product.model_copy(deep=True)
    stripped.manufacturer.established_in_eu = None
    readiness = run_factory(None, None, stripped, bundle, market="de")
    rule = next(r for r in readiness.rules if r.rule_id == "eu.gpsr.responsible_person")
    assert rule.status == "unknown"
    assert "manufacturer.established_in_eu" in rule.reason
    assert "eu.gpsr.responsible_person" in readiness.blockers
    assert readiness.state == "red"
    assert readiness.readiness < 1.0


def test_absent_fact_is_also_unknown(run_factory, product, bundle):
    stripped = product.model_copy(deep=True)
    stripped.packaging = {}
    readiness = run_factory(None, None, stripped, bundle, market="de")
    rule = next(r for r in readiness.rules if r.rule_id == "de.packaging.lucid")
    assert rule.status == "unknown"


def test_unknown_facts_are_reported_not_swallowed(run_factory, product, bundle):
    product2 = product.model_copy(deep=True)
    product2.electrical = {}
    readiness = run_factory(None, None, product2, bundle, market="us")
    unknown_rules = [r.rule_id for r in readiness.rules if r.status == "unknown"]
    assert "transport.un383.test_summary" in unknown_rules
    assert readiness.state == "red"


def test_predicate_unknown_propagation():
    facts = {"a": True}
    assert eval_predicate({"all": [{"fact": "a", "op": "eq", "value": True}]}, facts) == (True, [])
    value, missing = eval_predicate({"all": [{"fact": "a", "op": "eq", "value": True},
                                             {"fact": "b.c", "op": "eq", "value": 1}]}, facts)
    assert value is None and missing == ["b.c"]
    # `any` with one False and one unknown -> still unknown
    value, _ = eval_predicate({"any": [{"fact": "a", "op": "eq", "value": False},
                                       {"fact": "zz", "op": "eq", "value": 1}]}, facts)
    assert value is None
    # `any` with one True wins over unknown
    value, _ = eval_predicate({"any": [{"fact": "a", "op": "eq", "value": True},
                                       {"fact": "zz", "op": "eq", "value": 1}]}, facts)
    assert value is True
    # type-incomparable comparison -> unknown, not crash
    value, _ = eval_predicate({"fact": "a", "op": "gt", "value": "x"}, facts)
    assert value is None


def test_resolve_fact_paths():
    facts = {"a": {"b": [1, 2]}, "n": None}
    assert resolve_fact(facts, "a.b") == [1, 2]
    missing = resolve_fact(facts, "x.y.z")
    assert missing is not None and missing != [1, 2]  # sentinel, distinguishable from a real value
    assert resolve_fact(facts, "n") is None  # explicit null -> predicate layer treats as unknown


def test_replay_determinism(product, bundle, rules, markets):
    from complygraph.engine import evaluate_market

    r1 = evaluate_market(rules, product, bundle, "de", markets.markets["de"], "amazon.de", AS_OF)
    r2 = evaluate_market(rules, product, bundle, "de", markets.markets["de"], "amazon.de", AS_OF)
    receipt1 = build_receipt(product, bundle, rules, r1)
    receipt2 = build_receipt(product, bundle, rules, r2)
    assert receipt1["sha256"] == receipt2["sha256"]


def test_receipt_is_sensitive_to_inputs(product, bundle, rules, markets):
    from complygraph.engine import evaluate_market

    as_of = AS_OF
    r1 = evaluate_market(rules, product, bundle, "de", markets.markets["de"], None, as_of)
    bundle2 = copy.deepcopy(bundle)
    bundle2.evidence[0].issuer = "Someone Else GmbH"
    r2 = evaluate_market(rules, product, bundle2, "de", markets.markets["de"], None, as_of)
    receipt1 = build_receipt(product, bundle, rules, r1)
    receipt2 = build_receipt(product, bundle2, rules, r2)
    assert receipt1["sha256"] != receipt2["sha256"]
    # and to rule-pack content
    r3_rules = [r.model_copy(deep=True) for r in rules]
    r3_rules[0].title += " (edited)"
    r3 = evaluate_market(r3_rules, product, bundle, "de", markets.markets["de"], None, as_of)
    receipt3 = build_receipt(product, bundle, r3_rules, r3)
    assert receipt1["sha256"] != receipt3["sha256"]
