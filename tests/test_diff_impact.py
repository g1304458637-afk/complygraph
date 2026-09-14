"""Rule diff + regulation-change impact."""

from __future__ import annotations

import copy
from datetime import date

from complygraph.diff import diff_rules
from complygraph.impact import catalog_impact
from complygraph.loader import load_evidence, load_product, load_rules, resolve_rule_inputs
from complygraph.models import MarketRegistry
from complygraph.receipt import content_hash
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 14)


def _rules(*paths):
    return load_rules(resolve_rule_inputs([Path(p) for p in paths]))


def test_diff_identical_sets_is_empty():
    old = _rules(REPO / "rulepacks")
    new = _rules(REPO / "rulepacks")
    assert diff_rules(old, new) == []


def test_diff_detects_version_bump_as_changed():
    old = _rules(REPO / "rulepacks")
    new = _rules(REPO / "examples" / "demo_v2" / "rulepacks")
    changes = diff_rules(old, new)
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "changed"
    assert c.rule_id == "de.packaging.lucid"
    assert c.old_version == "1.0.0" and c.new_version == "2.0.0"
    assert "requires" in c.fields_changed


def test_diff_detects_added_and_removed():
    old = _rules(REPO / "rulepacks")
    dropped = old[-1]
    new = old[:-1] + [copy.deepcopy(old[0]).model_copy(update={"id": "test.new.rule", "version": "1.0.0"})]
    changes = {c.rule_id: c.kind for c in diff_rules(old, new)}
    removed = [rid for rid, kind in changes.items() if kind == "removed"]
    added = [rid for rid, kind in changes.items() if kind == "added"]
    assert added == ["test.new.rule"]
    assert removed == [dropped.id]


def _load_catalog():
    base = REPO / "examples"
    return [
        (load_product(base / "products" / "pb100.yaml"), load_evidence(base / "evidence" / "pb100_evidence.yaml")),
        (load_product(base / "products" / "tee21.yaml"), load_evidence(base / "evidence" / "tee21_evidence.yaml")),
    ]


def test_impact_finds_affected_sku_and_generates_tasks():
    markets = MarketRegistry.model_validate(
        {"markets": {"de": {"country": "DE", "jurisdictions": ["EU", "DE", "GLOBAL"], "eu_member": True, "language": "de"}}}
    )
    old = _rules(REPO / "rulepacks")
    new = _rules(REPO / "examples" / "demo_v2" / "rulepacks")
    impacts = catalog_impact(old, new, _load_catalog(), "de", markets.markets["de"], None, AS_OF)
    by_sku = {i.sku: i for i in impacts}

    pb = by_sku["PB-100"]
    assert pb.impacted is True
    assert "de.packaging.lucid" in pb.new_blockers
    assert pb.readiness_after < pb.readiness_before
    change = next(sc for sc in pb.status_changes if sc.rule_id == "de.packaging.lucid")
    assert change.before == "verified" and change.after == "missing"
    task = next(t for t in pb.tasks if t.rule_id == "de.packaging.lucid")
    assert task.kind == "provide_product_attribute"
    assert task.severity == "major"

    tee = by_sku["TEE-21"]
    assert tee.impacted is False
    assert tee.tasks == []
    assert tee.readiness_before == tee.readiness_after == 1.0


def test_impact_is_deterministic():
    markets = MarketRegistry.model_validate(
        {"markets": {"de": {"country": "DE", "jurisdictions": ["EU", "DE", "GLOBAL"], "eu_member": True, "language": "de"}}}
    )
    old = _rules(REPO / "rulepacks")
    new = _rules(REPO / "examples" / "demo_v2" / "rulepacks")
    r1 = catalog_impact(old, new, _load_catalog(), "de", markets.markets["de"], None, AS_OF)
    r2 = catalog_impact(old, new, _load_catalog(), "de", markets.markets["de"], None, AS_OF)
    assert content_hash([i.model_dump(mode="json") for i in r1]) == content_hash(
        [i.model_dump(mode="json") for i in r2]
    )
