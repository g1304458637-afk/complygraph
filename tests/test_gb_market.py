"""UK market: GB rules fire for GB-bound SKUs and stay out of other markets."""

from __future__ import annotations

import copy
from datetime import date

from conftest import run


def status_of(readiness, rule_id):
    return next(r for r in readiness.rules if r.rule_id == rule_id).status


def test_gb_market_requires_uk_registrations(product, bundle):
    readiness = run(None, None, product, bundle, market="gb")
    assert status_of(readiness, "uk.product_safety.responsible_person") != "not_applicable"
    assert status_of(readiness, "uk.weee.registration") == "missing"
    assert status_of(readiness, "uk.batteries.registration") == "missing"
    assert status_of(readiness, "uk.packaging.epr") == "missing"
    assert "uk.weee.registration" in readiness.blockers
    assert readiness.state == "red"


def test_gb_rules_do_not_fire_for_other_markets(product, bundle):
    de = run(None, None, product, bundle, market="de")
    assert status_of(de, "uk.weee.registration") == "not_applicable"
    us = run(None, None, product, bundle, market="us")
    assert status_of(us, "uk.product_safety.responsible_person") == "not_applicable"


def test_gb_without_uk_intent_is_not_applicable(product, bundle):
    stripped = product.model_copy(deep=True)
    stripped.offered_to_uk_consumer = False
    readiness = run(None, None, stripped, bundle, market="gb")
    assert status_of(readiness, "uk.product_safety.responsible_person") == "not_applicable"
    assert readiness.state != "red" or not any(r.startswith("uk.") for r in readiness.blockers)


def test_gb_unknown_intent_is_safe(product, bundle):
    stripped = product.model_copy(deep=True)
    stripped.offered_to_uk_consumer = None
    readiness = run(None, None, stripped, bundle, market="gb")
    assert status_of(readiness, "uk.product_safety.responsible_person") == "unknown"
    assert "uk.product_safety.responsible_person" in readiness.blockers


def test_gb_green_path_with_all_uk_evidence(product, bundle):
    from complygraph.models import Evidence, EvidenceBundle, Registration

    today = date(2026, 9, 14)
    bundle2 = copy.deepcopy(bundle)
    bundle2.registrations += [
        Registration(id="reg.gb.weee", sku=product.sku, scheme="gb.weee", number="WEE/AA1234AB", jurisdictions=["GB"]),
        Registration(id="reg.gb.bat", sku=product.sku, scheme="gb.batteries", number="BPRN001", jurisdictions=["GB"]),
        Registration(id="reg.gb.pack", sku=product.sku, scheme="gb.packaging", number="PEPR007", jurisdictions=["GB"]),
    ]
    bundle2.evidence += [
        Evidence(id="ev.gb.rpa", sku=product.sku, evidence_type="responsible_person_agreement",
                 issuer="UK RP Ltd", model_scope=[product.sku], issued=today,
                 jurisdictions=["GB"], reviewed=True),
        Evidence(id="ev.gb.safety", sku=product.sku, evidence_type="safety_information",
                 issuer="Mfr", model_scope=[product.sku], issued=today,
                 jurisdictions=["GB"], reviewed=True),
    ]
    readiness = run(None, None, product, bundle2, market="gb")
    assert status_of(readiness, "uk.weee.registration") == "verified"
    assert status_of(readiness, "uk.batteries.registration") == "verified"
    assert status_of(readiness, "uk.packaging.epr") == "verified"
    assert status_of(readiness, "uk.product_safety.responsible_person") == "verified"
    uk_blockers = [b for b in readiness.blockers if b.startswith("uk.")]
    assert uk_blockers == []
