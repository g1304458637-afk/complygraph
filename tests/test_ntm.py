"""Tier-1 NTM skeleton: seed -> rules -> any-country evaluation."""

from __future__ import annotations

from datetime import date

from complygraph.sources.ntm import generate_rules, load_seed, seed_market_iso_codes
from complygraph.models import Evidence, MarketRegistry

from conftest import AS_OF, run


def test_seed_generates_valid_rules():
    rules = generate_rules()
    assert len(rules) == 36
    ids = {r.id for r in rules}
    assert "ntm.jp.pse" in ids and "ntm.jp.telec" in ids and "ntm.sg.safety" in ids
    assert "ntm.cn.ccc" in ids and "ntm.sa.saber" in ids and "ntm.ru.eac" in ids
    for r in rules:
        assert r.jurisdiction == r.id.split(".")[1].upper()
        assert r.source.authority


def test_seed_market_registry_covers_all_iso():
    seed = load_seed()
    assert seed_market_iso_codes(seed) == [
        "JP", "KR", "CA", "AU", "BR", "IN", "AE", "MX", "SG", "CH",
        "CN", "TW", "ID", "TH", "MY", "PH", "SA", "IL", "ZA", "TR", "RU", "AR", "CL", "CO",
    ]
    cfgs = None
    from complygraph.sources.ntm import seed_market_configs
    cfgs = seed_market_configs(seed)
    assert cfgs["jp"]["jurisdictions"] == ["JP", "GLOBAL"]


def _mk_registry():
    return MarketRegistry.model_validate({
        "markets": {"jp": {"country": "JP", "jurisdictions": ["JP", "GLOBAL"], "eu_member": False, "language": "ja"}}
    })


def _product(**over):
    from complygraph.models import Product

    base = dict(
        sku="NP-1",
        name="NTM test product",
        category="consumer_electronics",
        manufacturer={"name": "M", "country": "CN", "established_in_eu": False},
        offered_to_eu_consumer=False,
        offered_to_us_consumer=False,
        offered_to_uk_consumer=False,
        target_markets=["JP"],
        hs_code="8507.60",
        features={"wireless_charging": False},
        electrical={"battery": {"present": True, "watt_hours": 37}},
        packaging={"packaged_for_end_consumer": True},
        attributes={},
        channel_fields={},
    )
    base.update(over)
    return Product.model_validate(base)


def test_jp_product_without_pse_is_blocked(product, bundle, rules, markets):
    markets2 = _mk_registry()
    p = _product()
    readiness = run(rules, markets2, p, bundle, market="jp")
    rule = next(r for r in readiness.rules if r.rule_id == "ntm.jp.pse")
    assert rule.status == "missing"
    assert "ntm.jp.pse" in readiness.blockers
    # no HS/wireless/other-market leakage
    assert next(r for r in readiness.rules if r.rule_id == "ntm.jp.telec").status == "not_applicable"
    assert next(r for r in readiness.rules if r.rule_id == "ntm.kr.kc").status == "not_applicable"


def test_jp_product_with_certificate_passes(product, bundle, rules):
    from complygraph.models import EvidenceBundle

    markets2 = _mk_registry()
    p = _product()
    bundle2 = EvidenceBundle(
        evidence=[Evidence(
            id="ev.pse", sku=p.sku, evidence_type="pse_certificate", issuer="METI lab",
            model_scope=[p.sku], issued=AS_OF, jurisdictions=["JP"], reviewed=True,
        )],
        registrations=[],
    )
    readiness = run(rules, markets2, p, bundle2, market="jp")
    rule = next(r for r in readiness.rules if r.rule_id == "ntm.jp.pse")
    assert rule.status == "verified"


def test_missing_hs_code_is_unknown_not_green(product, bundle, rules):
    markets2 = _mk_registry()
    p = _product(hs_code=None)
    readiness = run(rules, markets2, p, bundle, market="jp")
    rule = next(r for r in readiness.rules if r.rule_id == "ntm.jp.pse")
    assert rule.status == "unknown"
    assert "ntm.jp.pse" in readiness.blockers
    assert readiness.state == "red"


def test_non_targeted_market_is_not_applicable(product, bundle, rules):
    markets2 = _mk_registry()
    p = _product(target_markets=["KR"])
    readiness = run(rules, markets2, p, bundle, market="jp")
    assert next(r for r in readiness.rules if r.rule_id == "ntm.jp.pse").status == "not_applicable"
