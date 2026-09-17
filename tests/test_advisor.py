"""Advisor: remediation plan, what-if, market recommendation (all deterministic)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from complygraph.advisor import market_recommendation, remediation_plan, what_if
from complygraph.intake import _rules
from complygraph.loader import load_evidence, load_markets, load_product
from complygraph.models import EvidenceBundle
from complygraph.registry import ROOT

REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 14)


@pytest.fixture(scope="module")
def markets():
    return load_markets(REPO / "config" / "markets.yaml")


@pytest.fixture(scope="module")
def pb100():
    return load_product(REPO / "examples" / "products" / "pb100.yaml")


@pytest.fixture(scope="module")
def bundle():
    return load_evidence(REPO / "examples" / "evidence" / "pb100_evidence.yaml")


def _eval(rules, markets, product, bundle, mid):
    from complygraph.engine import evaluate_market

    return evaluate_market(rules, product, bundle, mid, markets.markets[mid], None, AS_OF)


def test_remediation_plan_covers_missing_evidence(product, bundle, rules, markets):
    r = _eval(rules, markets, product, bundle, "jp")
    plan = remediation_plan(r.rules, lang="zh")
    texts = " ".join(x["text"] for x in plan)
    assert "PSE" in texts
    assert any(x["kind"] in ("evidence", "registration", "tip") for x in plan)


def test_remediation_includes_cb_scheme_tip_when_multiple_certs_missing():
    from complygraph.models import RequirementResult, RuleResult, Source

    src = Source(authority="test", provision="test")
    def fake_rule_result(rule_id, req_id, etype_hint):
        from complygraph.intake import _rules as _r

        rule = next(x for x in _r() if x.id == rule_id)
        req = rule.requires[0]
        return RuleResult(
            rule_id=rule.id, rule_version=rule.version, pack=rule.pack, pack_type="legal",
            title=rule.title, severity="blocker", jurisdiction=rule.jurisdiction,
            status="missing", reason=req.description,
            requirements=[RequirementResult(requirement=req.id, kind="evidence",
                                            status="missing", reason=req.description)],
            source=rule.source,
        )
    results = [
        fake_rule_result("ntm.jp.pse", "req.ntm.jp.pse", "pse"),
        fake_rule_result("ntm.jp.telec", "req.ntm.jp.telec", "telec"),
        fake_rule_result("ntm.kr.kc", "req.ntm.kr.kc", "kc"),
    ]
    plan = remediation_plan(results, lang="en")
    assert plan[0]["kind"] == "tip"
    assert "CB Test Certificate" in plan[0]["text"]


def test_what_if_removing_wireless_clears_red_rule(product, bundle, rules, markets):
    product_dict = product.model_dump()
    out = what_if(product_dict, {"features": {"wireless_charging": False}}, markets.markets, "de", bundle, rules)
    flipped = {f["rule_id"]: f for f in out["flipped"]}
    # pb100 has wireless off already; flip it ON to see RED appear
    out2 = what_if(product_dict, {"features": {"wireless_charging": True}}, markets.markets, "de", bundle, rules)
    flipped2 = {f["rule_id"]: (f["before"], f["after"]) for f in out2["flipped"]}
    assert flipped2.get("eu.red.radio_equipment") == ("not_applicable", "missing")
    assert out["state_before"] == out["state_after"] or flipped


def test_what_if_wireless_missing_blocks_market(product, bundle, rules, markets):
    from complygraph.models import Product

    wireless = product.model_copy(deep=True)
    wireless.features["wireless_charging"] = True
    out = what_if(wireless.model_dump(), {"features": {"wireless_charging": False}}, markets.markets, "de", bundle, rules)
    assert out["readiness_after"] > out["readiness_before"]


def test_market_recommendation_ranks_sensibly(pb100, bundle):
    from complygraph.advisor import market_recommendation as mr

    recs = mr(pb100, bundle, lang="en")
    assert len(recs) >= 10
    classes = [r["class"] for r in recs]
    rank = {"ready": 0, "minor": 1, "fixable": 2, "no-rules": 3, "costly": 4}
    assert classes == sorted(classes, key=lambda c: rank[c])
    top = recs[0]
    assert top["class"] in ("ready", "minor", "fixable")
    # already-targeted flag present
    assert any("already_targeted" in r for r in recs)


def test_what_if_maps_aliases_and_rejects_unknown_paths(product, bundle, rules, markets):
    """Short LLM-style names map to canonical fact paths; unknown paths return
    the known-path list instead of a silently-empty flip result."""
    probe = product.model_dump()
    probe["features"] = {"wireless_charging": True}
    out = what_if(probe, {"wireless": False}, markets.markets, "de", bundle, rules)
    flipped = {f["rule_id"] for f in out["flipped"]}
    assert "eu.red.radio_equipment" in flipped
    bad = what_if(probe, {"wireles": False}, markets.markets, "de", bundle, rules)
    assert "error" in bad and "features.wireless_charging" in bad["error"]


def test_advisor_loads_package_data_even_when_registry_root_rebound(monkeypatch, tmp_path):
    """advisor used to copy registry.ROOT at import time — whoever imported it
    after a test rebinding got tmp paths and a crash on config/markets.yaml."""
    import importlib

    from complygraph import advisor, registry

    monkeypatch.setattr(registry, "ROOT", tmp_path)
    reloaded = importlib.reload(advisor)
    try:
        assert len(reloaded._markets().markets) >= 20
        assert len(reloaded._all_rules()) >= 70
    finally:
        importlib.reload(advisor)  # restore lazy caches for other tests


def test_marking_checklist_lists_attribute_duties_with_basis(pb100, bundle, rules, markets):
    """Every applicable product_attribute requirement becomes a checklist item
    with its legal basis and a derived status; unknown markets are rejected."""
    from complygraph.advisor import marking_checklist

    out = marking_checklist(pb100, bundle, "de")
    by_marking = {i["marking"]: i for i in out["items"]}
    assert "traceability_marking" in by_marking
    assert by_marking["traceability_marking"]["legal_basis"]
    assert by_marking["traceability_marking"]["status"] in ("done", "claimed", "open")
    # battery Wh marking only applies to battery products — PB-100 is one
    assert "battery_wh_marking" in by_marking
    assert marking_checklist(pb100, bundle, "xx") == {"error": "unknown market xx"}


def test_markings_endpoint(tmp_path):
    from complygraph.web import api_markings

    payload, code = api_markings("PB-100", "fr")
    assert code == 200
    assert any(i["marking"] == "triman_info_tri" for i in payload["items"])
    payload, code = api_markings("GHOST", "de")
    assert code == 404


def test_battery_passport_preview_maps_fields_and_gaps(product, bundle):
    """Battery products get an Annex XIII readiness preview: known facts mapped,
    unmodelled groups honestly listed as gaps; non-battery products are N/A."""
    from complygraph.advisor import battery_passport_preview

    out = battery_passport_preview(product, bundle)
    assert out["applicable"] is True
    assert out["regulation"].startswith("Regulation (EU) 2023/1542")
    assert out["fields"]["composition"]["watt_hours"] == 37  # PB-100
    assert "carbon_footprint" in out["empty_groups"]
    assert "battery_conformity_declaration" in out["evidence_on_file"]
    assert 0 < out["filled_share"] < 1
    assert out["in_scope_by_watt_hours"] is False  # 37 Wh is portable class

    no_battery = product.model_copy(deep=True)
    no_battery.electrical = {"battery": {"present": False}}
    out2 = battery_passport_preview(no_battery, bundle)
    assert out2["applicable"] is False


def test_battery_passport_endpoint(tmp_path):
    from complygraph.web import api_battery_passport

    payload, code = api_battery_passport("PB-100")
    assert code == 200 and payload["applicable"] is True
    payload, code = api_battery_passport("GHOST")
    assert code == 404
