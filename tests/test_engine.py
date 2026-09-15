"""Core evaluator behaviour: statuses, evidence checks, readiness."""

from __future__ import annotations

import copy
from datetime import date

from complygraph.models import Evidence, Product

from conftest import run


def status_of(readiness, rule_id):
    return next(r for r in readiness.rules if r.rule_id == rule_id).status


def test_example_product_is_amber_with_unreviewed_evidence(run_factory, product, bundle):
    readiness = run_factory(None, None, product, bundle, market="de", channel="amazon.de")
    assert readiness.state == "amber"
    assert readiness.blockers == []
    assert status_of(readiness, "eu.batteries.conformity") == "satisfied_unverified"


def test_reviewed_battery_declaration_makes_it_green(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    for ev in bundle2.evidence:
        if ev.evidence_type == "battery_conformity_declaration":
            ev.reviewed = True
    readiness = run_factory(None, None, product, bundle2, market="de", channel="amazon.de")
    assert readiness.state == "green"
    assert readiness.readiness == 1.0


def test_model_mismatch_is_a_hard_blocker(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    next(e for e in bundle2.evidence if e.id == "ev.un383.001").model_scope = ["PB-100A"]
    readiness = run_factory(None, None, product, bundle2, market="de")
    assert status_of(readiness, "transport.un383.test_summary") == "mismatch"
    assert "transport.un383.test_summary" in readiness.blockers
    assert readiness.state == "red"


def test_expired_evidence_is_a_hard_blocker(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    next(e for e in bundle2.evidence if e.id == "ev.un383.001").valid_until = date(2026, 1, 1)
    readiness = run_factory(None, None, product, bundle2, market="de")
    assert status_of(readiness, "transport.un383.test_summary") == "expired"
    assert readiness.state == "red"


def test_missing_evidence_is_a_hard_blocker(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    bundle2.evidence = [e for e in bundle2.evidence if e.evidence_type != "un383_test_summary"]
    readiness = run_factory(None, None, product, bundle2, market="de")
    assert status_of(readiness, "transport.un383.test_summary") == "missing"
    assert readiness.state == "red"


def test_date_boundary_gpsr(run_factory, product, bundle):
    before = run_factory(None, None, product, bundle, market="de", as_of=date(2024, 12, 12))
    assert status_of(before, "eu.gpsr.responsible_person") == "not_applicable"
    on = run_factory(None, None, product, bundle, market="de", as_of=date(2024, 12, 13))
    assert status_of(on, "eu.gpsr.responsible_person") != "not_applicable"


def test_wireless_feature_changes_regulatory_path(run_factory, product, bundle):
    off = run_factory(None, None, product, bundle, market="de")
    assert status_of(off, "eu.red.radio_equipment") == "not_applicable"

    wireless = product.model_copy(deep=True)
    wireless.features["wireless_charging"] = True
    on = run_factory(None, None, wireless, bundle, market="de")
    assert status_of(on, "eu.red.radio_equipment") == "missing"
    assert "eu.red.radio_equipment" in on.blockers
    assert on.state == "red"


def test_channel_rules_only_fire_for_their_channel(run_factory, product, bundle):
    de_only = run_factory(None, None, product, bundle, market="de", channel=None)
    assert status_of(de_only, "channel.amazon_de.gpsr_responsible_person") == "not_applicable"

    stripped = product.model_copy(deep=True)
    stripped.channel_fields = {}
    failing = run_factory(None, None, stripped, bundle, market="de", channel="amazon.de")
    assert status_of(failing, "channel.amazon_de.gpsr_responsible_person") == "missing"
    assert failing.state == "red"


def test_us_market_ignores_eu_and_de_rules(run_factory, product, bundle):
    readiness = run_factory(None, None, product, bundle, market="us", channel=None)
    statuses = {r.rule_id: r.status for r in readiness.rules}
    assert statuses["eu.gpsr.responsible_person"] == "not_applicable"
    assert statuses["de.weee.registration"] == "not_applicable"
    assert statuses["de.packaging.lucid"] == "not_applicable"
    assert statuses["transport.un383.test_summary"] == "verified"
    assert statuses["transport.lithium.wh_marking"] == "verified"
    assert readiness.state == "green"


def test_registration_numbers_drive_de_readiness(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    bundle2.registrations = []
    readiness = run_factory(None, None, product, bundle2, market="de")
    assert status_of(readiness, "de.packaging.lucid") == "missing"
    assert status_of(readiness, "de.weee.registration") == "missing"
    assert status_of(readiness, "de.battg.registration") == "missing"
    assert readiness.state == "red"
    assert len(readiness.blockers) == 3


def test_product_attribute_requirement(run_factory, product, bundle):
    stripped = product.model_copy(deep=True)
    stripped.attributes.pop("battery_wh_marking")
    readiness = run_factory(None, None, stripped, bundle, market="de")
    assert status_of(readiness, "transport.lithium.wh_marking") == "missing"


def test_fr_market_requires_french_epr_ids(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    bundle2.registrations = [r for r in bundle2.registrations if not r.scheme.startswith("fr.")]
    readiness = run_factory(None, None, product, bundle2, market="fr")
    assert status_of(readiness, "fr.epr.packaging_idu") == "missing"
    assert status_of(readiness, "fr.epr.weee_idu") == "missing"
    assert status_of(readiness, "fr.epr.battery_idu") == "missing"
    assert set(readiness.blockers) == {"fr.epr.packaging_idu", "fr.epr.weee_idu", "fr.epr.battery_idu"}
    assert readiness.state == "red"


def test_fr_market_rules_verified_with_registrations(run_factory, product, bundle):
    readiness = run_factory(None, None, product, bundle, market="fr")
    assert status_of(readiness, "fr.epr.packaging_idu") == "verified"
    assert status_of(readiness, "fr.epr.weee_idu") == "verified"
    assert status_of(readiness, "fr.epr.battery_idu") == "verified"
    assert status_of(readiness, "fr.labeling.triman_info_tri") == "verified"
    assert readiness.blockers == []
    # the shared EU battery-evidence gap is visible in FR too
    assert status_of(readiness, "eu.batteries.conformity") == "satisfied_unverified"


def test_us_market_requires_fcc_report(run_factory, product, bundle):
    bundle2 = copy.deepcopy(bundle)
    bundle2.evidence = [e for e in bundle2.evidence if e.evidence_type != "fcc_test_report"]
    readiness = run_factory(None, None, product, bundle2, market="us")
    assert status_of(readiness, "us.fcc.part15b") == "missing"
    assert "us.fcc.part15b" in readiness.blockers
    assert readiness.state == "red"


def test_us_channel_fields_verified(run_factory, product, bundle):
    readiness = run_factory(None, None, product, bundle, market="us", channel="amazon.us")
    assert status_of(readiness, "channel.amazon_us.battery_wh_declaration") == "verified"
    assert status_of(readiness, "channel.amazon_us.un383_reference") == "verified"


def test_rule_without_requires_is_unknown_not_crash():
    """A rule pack entry with no modelled requirements proves nothing: it must
    evaluate to `unknown` (never vacuous `verified`, never a crash)."""
    from complygraph.engine import evaluate_rule
    from complygraph.models import EvidenceBundle, MarketConfig, Rule, Source

    rule = Rule(
        id="test.empty", title="Empty rule", version="1", pack="test", pack_type="legal",
        jurisdiction="DE", effective_from=date(2020, 1, 1),
        applies_if={"fact": "sku", "op": "exists"}, requires=[],
        source=Source(authority="Test Authority", provision="s.0"),
    )
    market = MarketConfig(country="DE", jurisdictions=["DE"], eu_member=True, language="de")
    result = evaluate_rule(rule, Product(sku="X", name="X", category="consumer_electronics"),
                           EvidenceBundle(), market, None, date.today())
    assert result.status == "unknown"
    assert "no modelled requirements" in result.reason


def test_conflicting_evidence_sibling_is_surfaced_in_reason(run_factory, product, bundle):
    """When passing and failing documents of one type coexist (family cert +
    stale model-specific cert), the passing doc still decides — but the
    conflict must appear in the audit reason, not vanish."""
    bundle2 = copy.deepcopy(bundle)
    bundle2.evidence.append(
        Evidence(
            id="ev.un383.stale", sku="PB-100", evidence_type="un383_test_summary",
            issuer="Old Lab", model_scope=["PB-100-OLD"], issued=date(2020, 1, 1),
            jurisdictions=["GLOBAL"],
        )
    )
    readiness = run_factory(None, None, product, bundle2, market="de")
    result = next(r for r in readiness.rules if r.rule_id == "transport.un383.test_summary")
    assert result.status in ("verified", "satisfied_unverified")
    assert "further document" in result.reason
