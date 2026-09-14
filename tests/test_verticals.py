"""New verticals: toys / cosmetics / food contact / medical (educational skeleton)."""

from __future__ import annotations

from datetime import date

import pytest

from complygraph.intake import CATALOG
from complygraph.models import Evidence, EvidenceBundle, Product
from conftest import run


def _mk(sku="TOY-1", category="toys", **over):
    base = dict(
        sku=sku, name="Vertical test product", category=category,
        manufacturer={"name": "M", "country": "CN", "established_in_eu": False},
        offered_to_eu_consumer=True, offered_to_us_consumer=False,
        offered_to_uk_consumer=False, target_markets=[],
        features={"wireless_charging": False},
        electrical={"battery": {"present": False}},
        packaging={"packaged_for_end_consumer": True},
        attributes={}, channel_fields={},
    )
    base.update(over)
    return Product.model_validate(base)


def test_toys_en71_missing_is_blocked(rules, markets, bundle):
    p = _mk()
    r = run(rules, markets, p, EvidenceBundle(), market="de")
    rule = next(x for x in r.rules if x.rule_id == "eu.toys.safety")
    assert rule.status == "missing" and rule.severity == "blocker"
    assert "eu.toys.safety" in r.blockers


def test_toys_rules_do_not_fire_for_electronics(rules, markets, product, bundle):
    r = run(rules, markets, product, bundle, market="de")
    assert next(x for x in r.rules if x.rule_id == "eu.toys.safety").status == "not_applicable"


def test_cosmetics_cpnp_and_pif_required(rules, markets):
    p = _mk("COS-1", category="cosmetics")
    r = run(rules, markets, p, EvidenceBundle(), market="fr")
    ids = {x.rule_id: x.status for x in r.rules}
    assert ids.get("eu.cosmetics.cpnp") == "missing"
    assert ids.get("eu.cosmetics.responsible_person_pif") == "missing"
    assert ids.get("us.cosmetics.mocra") == "not_applicable"  # US rule not in FR scope


def test_food_contact_migration_major(rules, markets):
    p = _mk("FC-1", category="food_contact")
    r = run(rules, markets, p, EvidenceBundle(), market="de")
    rule = next(x for x in r.rules if x.rule_id == "eu.fc.framework")
    assert rule.status in ("missing", "mismatch")


def test_medical_rules_are_educational_skeleton(rules, markets):
    p = _mk("MED-1", category="medical_device")
    r = run(rules, markets, p, EvidenceBundle(), market="de")
    mdr = next(x for x in r.rules if x.rule_id == "eu.mdr.ce_and_qms")
    assert mdr.status == "missing"
    assert "EDUCATIONAL SKELETON" in (mdr.source and (next(x for x in rules if x.id == "eu.mdr.ce_and_qms").notes or ""))


def test_generated_evidence_questions_cover_verticals():
    ids = {q.id for q in CATALOG}
    assert "doc_ntm_eu.toys.safety" in ids
    assert "doc_ntm_eu.cosmetics.safety_assessment" in ids
    assert "doc_ntm_us.fda.device" in ids
    assert "doc_ntm_eu.fc.framework" in ids
