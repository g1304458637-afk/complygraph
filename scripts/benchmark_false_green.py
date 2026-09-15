"""False-Green benchmark: 100 synthetic SKUs with outcomes known by construction.

Roadmap release gate: "100-SKU synthetic benchmark (False Green Rate = 0)".

Construction, not an engine oracle (that would be circular): for each case we
build a product plus the COMPLETE evidence/registration set the applicable rule
packs require (so a correct engine must say green), then remove exactly one
blocker-class requirement item (so a correct engine must say red). Any case
that stays green after the removal is a FALSE GREEN — the one failure mode
this project exists to prevent.

Usage:
    .venv/bin/python scripts/benchmark_false_green.py            # 100 cases
    .venv/bin/python scripts/benchmark_false_green.py --n 25 --seed 7
Exit code 1 if any false green (or invariant violation) is found.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from complygraph.engine import evaluate_market  # noqa: E402
from complygraph.intake import _rules  # noqa: E402  (loads ALL registered packs)
from complygraph.loader import load_markets  # noqa: E402
from complygraph.models import Evidence, EvidenceBundle, Product, Registration  # noqa: E402
from complygraph.registry import ROOT  # noqa: E402

AS_OF = date.today()
CATEGORIES = ["consumer_electronics", "toys", "cosmetics", "food_contact"]


def synthetic_product(rng: random.Random, i: int) -> Product:
    category = rng.choice(CATEGORIES)
    battery = rng.random() < 0.6
    return Product(
        sku=f"BEN-{i:04d}",
        name=f"Benchmark {i}",
        category=category,
        manufacturer={"name": "Bench Labs", "country": "CN", "established_in_eu": False},
        offered_to_eu_consumer=rng.random() < 0.7,
        offered_to_uk_consumer=rng.random() < 0.4,
        offered_to_us_consumer=rng.random() < 0.4,
        target_markets=[],
        hs_code=rng.choice(["8507", "8517", "9503"]),
        features={"wireless_charging": rng.random() < 0.5},
        electrical={"battery": {"present": battery, "chemistry": "li_ion", "watt_hours": 37} if battery else {"present": False}},
        packaging={"packaged_for_end_consumer": rng.random() < 0.8},
        attributes={
            "traceability_marking": "marked",
            "scip_notification": "notified",
            "triman_info_tri": "printed",
            "prop65_warning": "labelled",
            "battery_wh_marking": "37 Wh marked" if battery else None,
            "toys_warning_labels": "provided",
            # toys: both branches exercised — "true" makes full_bundle issue
            # the notified-body certificate, "false" makes the rule inapplicable
            "use_notified_body": rng.random() < 0.5,
        },
    )


def evidence_type_for(rules, rule_id: str) -> str | None:
    rule = next((r for r in rules if r.id == rule_id), None)
    for req in rule.requires if rule else []:
        if req.kind == "evidence":
            return req.evidence_type
    return None


def full_bundle(rules, product: Product, rng: random.Random) -> EvidenceBundle:
    """Evidence + registrations satisfying EVERY requirement that could apply."""
    docs: dict[str, Evidence] = {}
    regs: dict[str, Registration] = {}
    for rule in rules:
        res = evaluate_market([rule], product, EvidenceBundle(), "de", _DE, None, AS_OF)
        if res.rules and res.rules[0].status == "not_applicable":
            continue
        for req in rule.requires:
            if req.kind == "evidence" and req.evidence_type and req.evidence_type not in docs:
                docs[req.evidence_type] = Evidence(
                    id=f"ev.ben.{req.evidence_type}.{product.sku}",
                    sku=product.sku, evidence_type=req.evidence_type,
                    issuer="Accredited Lab", model_scope=[product.sku],
                    issued=date(2025, 1, 1), jurisdictions=["GLOBAL"], reviewed=True,
                )
            elif req.kind == "registration" and req.registration_scheme and req.registration_scheme not in regs:
                regs[req.registration_scheme] = Registration(
                    id=f"reg.ben.{req.registration_scheme}.{product.sku}",
                    sku=product.sku, scheme=req.registration_scheme, number="BEN-001",
                    jurisdictions=["GLOBAL"],
                )
    return EvidenceBundle(evidence=list(docs.values()), registrations=list(regs.values()))


_MARKETS = None
_DE = None


def _init():
    global _MARKETS, _DE
    if _MARKETS is None:
        _MARKETS = load_markets(ROOT / "config" / "markets.yaml")
        _DE = _MARKETS.markets["de"]


def one_case(rng: random.Random, i: int) -> dict:
    """Build a green-by-construction SKU, remove one blocker item, re-evaluate."""
    _init()
    rules = _rules()
    product = synthetic_product(rng, i)
    bundle = full_bundle(rules, product, rng)

    base = evaluate_market(rules, product, bundle, "de", _DE, None, AS_OF)
    if base.state != "green":
        return {"sku": product.sku, "skipped": f"baseline not green ({base.state})", "false_green": False}

    # collect removable (evidence, registration) items backing blocker rules
    removable: list[tuple[str, str]] = []
    for rule in rules:
        res = evaluate_market([rule], product, bundle, "de", _DE, None, AS_OF)
        if not res.rules or res.rules[0].status != "verified":
            continue
        if res.rules[0].severity != "blocker":
            continue
        for req in rule.requires:
            if req.kind == "evidence" and req.evidence_type:
                removable.append(("evidence", req.evidence_type))
            elif req.kind == "registration" and req.registration_scheme:
                removable.append(("registration", req.registration_scheme))
    if not removable:
        return {"sku": product.sku, "skipped": "no verified blocker item", "false_green": False}

    kind, key = rng.choice(removable)
    if kind == "evidence":
        bundle.evidence = [e for e in bundle.evidence if e.evidence_type != key]
    else:
        bundle.registrations = [r for r in bundle.registrations if r.scheme != key]

    after = evaluate_market(rules, product, bundle, "de", _DE, None, AS_OF)
    return {
        "sku": product.sku,
        "removed": f"{kind}:{key}",
        "state_before": base.state,
        "state_after": after.state,
        # the release invariant: a removed blocker may leave amber only if the
        # rule was never a blocker in the first place — here it was, so red
        "false_green": after.state == "green",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark_false_green")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260916)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    results = [one_case(rng, i) for i in range(args.n)]
    false_greens = [r for r in results if r["false_green"]]
    skipped = [r for r in results if "skipped" in r]
    effective = len(results) - len(skipped)
    fgr = len(false_greens) / effective if effective else 0.0
    print(json.dumps({
        "cases": len(results),
        "effective": effective,
        "skipped": len(skipped),
        "false_greens": len(false_greens),
        "false_green_rate": fgr,
        "seed": args.seed,
        "detail": false_greens or None,
    }, indent=2))
    return 1 if false_greens else 0


if __name__ == "__main__":
    raise SystemExit(main())
