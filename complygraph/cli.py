"""CLI: `python -m complygraph.cli evaluate <product.yaml> --market de ...`"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .engine import evaluate_market
from .loader import (
    default_rule_paths,
    load_evidence,
    load_markets,
    load_product,
    load_rules,
    resolve_rule_inputs,
)
from .receipt import build_receipt

ICON = {"green": "✓", "amber": "⚠", "red": "✗"}


def _default_as_of() -> date:
    return date.today()


def cmd_evaluate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    product = load_product(Path(args.product))
    bundle = load_evidence(Path(args.evidence)) if args.evidence else None
    bundle = bundle or _empty_bundle()
    paths = [Path(p) for p in args.rules] if args.rules else default_rule_paths(root)
    rules = load_rules(paths)
    registry = load_markets(root / "config" / "markets.yaml")
    if args.market not in registry.markets:
        print(f"error: unknown market '{args.market}' (known: {', '.join(registry.markets)})", file=sys.stderr)
        return 2
    market = registry.markets[args.market]
    as_of = date.fromisoformat(args.as_of) if args.as_of else _default_as_of()

    readiness = evaluate_market(rules, product, bundle, args.market, market, args.channel, as_of)
    receipt = build_receipt(product, bundle, rules, readiness)

    if args.json:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0

    target = f"{readiness.market}" + (f"/{readiness.channel}" if readiness.channel else "")
    print(f"\nSKU {product.sku} -> {target}   as of {readiness.as_of}")
    print(f"state {ICON[readiness.state]} {readiness.state.upper()}   readiness {readiness.readiness:.1%}")
    if readiness.blockers:
        print(f"hard blockers ({len(readiness.blockers)}):")
        for rule_id in readiness.blockers:
            print(f"  - {rule_id}")
    print()
    width = max(len(r.rule_id) for r in readiness.rules)
    for r in readiness.rules:
        mark = {"verified": "+", "satisfied_unverified": "~", "not_applicable": "-"}.get(r.status, "!")
        line = f" [{mark}] {r.rule_id:<{width}}  {r.status}"
        if r.reason:
            line += f"  ({r.reason})"
        print(line)
    print(f"\nreceipt sha256 {receipt['sha256']}")
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"receipt written to {args.receipt}")
    return 0


def cmd_diff_rules(args: argparse.Namespace) -> int:
    from .diff import diff_rules

    old = load_rules(resolve_rule_inputs([Path(p) for p in args.old]))
    new = load_rules(resolve_rule_inputs([Path(p) for p in args.new]))
    changes = diff_rules(old, new)
    if not changes:
        print("rule sets identical")
        return 0
    counts = {"added": 0, "removed": 0, "changed": 0}
    for c in changes:
        counts[c.kind] += 1
        arrow = f"{c.old_version} -> {c.new_version}" if c.kind == "changed" else c.new_version or c.old_version
        detail = f"  fields: {', '.join(c.fields_changed)}" if c.fields_changed else ""
        print(f"[{c.kind.upper():7s}] {c.rule_id}  ({arrow}){detail}")
    print(f"\nsummary: {counts['changed']} changed, {counts['added']} added, {counts['removed']} removed")
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    import json as _json

    from .impact import catalog_impact

    old = load_rules(resolve_rule_inputs([Path(p) for p in args.old]))
    new = load_rules(resolve_rule_inputs([Path(p) for p in args.new]))
    catalog_path = Path(args.catalog)
    catalog_data = _yaml_load(catalog_path)
    catalog = [
        (load_product(catalog_path.parent / entry["product"]),
         load_evidence(catalog_path.parent / entry["evidence"]))
        for entry in catalog_data["skus"]
    ]
    registry = load_markets(Path(args.root) / "config" / "markets.yaml")
    market = registry.markets[args.market]
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    impacts = catalog_impact(old, new, catalog, args.market, market, args.channel, as_of)
    if args.json:
        print(_json.dumps({"market": args.market, "as_of": as_of.isoformat(),
                           "skus": [i.model_dump(mode="json") for i in impacts]}, indent=2))
    else:
        n = sum(1 for i in impacts if i.impacted)
        print(f"\nregulation change impact on {n}/{len(impacts)} SKUs  (market {args.market}, as of {as_of})")
        for i in impacts:
            mark = "!" if i.impacted else "="
            print(f"\n [{mark}] {i.sku}: {i.state_before} {i.readiness_before:.1%} -> {i.state_after} {i.readiness_after:.1%}")
            for rid in i.new_blockers:
                print(f"     new blocker: {rid}")
            for sc in i.status_changes:
                print(f"     {sc.rule_id}: {sc.before} -> {sc.after}")
            for t in i.tasks:
                print(f"     task [{t.kind}] {t.rule_id}: {t.description}")
    return 0


def _yaml_load(path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def cmd_evidence_extract(args: argparse.Namespace) -> int:
    import yaml as _yaml

    from .evidence_extract import get_provider, extract_evidence

    provider = get_provider(args.provider)
    draft = extract_evidence(Path(args.file), args.sku, provider)
    data = draft.model_dump(mode="json")
    if args.out:
        Path(args.out).write_text(
            _yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"draft written to {args.out} (reviewed: false)")
    else:
        print(_yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(
        "# NOTE: draft is unreviewed; it can never satisfy a blocker as 'verified'.\n"
        "# After human review, set reviewed: true and append to the SKU evidence bundle,\n"
        f"# then: complygraph evidence-approve --bundle <bundle.yaml> --id {draft.id}"
    )
    return 0


def cmd_evidence_approve(args: argparse.Namespace) -> int:
    import yaml as _yaml

    bundle_path = Path(args.bundle)
    data = _yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    hits = 0
    for entry in data.get("evidence", []):
        if entry.get("id") == args.id:
            entry["reviewed"] = True
            hits += 1
    if not hits:
        print(f"error: no evidence with id '{args.id}' in {bundle_path}", file=sys.stderr)
        return 1
    bundle_path.write_text(_yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"approved {args.id} (reviewed: true) in {bundle_path}")
    return 0


def _empty_bundle():
    from .models import EvidenceBundle

    return EvidenceBundle()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="complygraph")
    sub = parser.add_subparsers(dest="command", required=True)

    ev = sub.add_parser("evaluate", help="evaluate a SKU against a market/channel")
    ev.add_argument("product", help="path to product YAML")
    ev.add_argument("--evidence", help="path to evidence bundle YAML")
    ev.add_argument("--market", required=True, help="market id from config/markets.yaml (de, fr, us)")
    ev.add_argument("--channel", help="channel id (e.g. amazon.de)")
    ev.add_argument("--rules", nargs="*", help="rule pack YAML files (default: rulepacks/**/*.yaml)")
    ev.add_argument("--root", default=".", help="repo root containing rulepacks/ and config/")
    ev.add_argument("--as-of", help="evaluation date ISO-8601 (default: today)")
    ev.add_argument("--json", action="store_true", help="emit full evaluation receipt as JSON")
    ev.add_argument("--receipt", help="also write receipt JSON to this path")
    ev.set_defaults(func=cmd_evaluate)

    dif = sub.add_parser("diff-rules", help="semantic diff between two rule sets")
    dif.add_argument("--old", nargs="+", help="old rule pack files/directories")
    dif.add_argument("--new", nargs="+", help="new rule pack files/directories")
    dif.set_defaults(func=cmd_diff_rules)

    imp = sub.add_parser("impact", help="regulation-change impact over a product catalog")
    imp.add_argument("--old", nargs="+", help="old rule pack files/directories")
    imp.add_argument("--new", nargs="+", help="new rule pack files/directories")
    imp.add_argument("--catalog", required=True, help="catalog YAML ({skus: [{product, evidence}]})")
    imp.add_argument("--market", required=True)
    imp.add_argument("--channel", default=None)
    imp.add_argument("--root", default=".")
    imp.add_argument("--as-of", help="evaluation date ISO-8601 (default: today)")
    imp.add_argument("--json", action="store_true")
    imp.set_defaults(func=cmd_impact)

    ex = sub.add_parser("evidence-extract", help="extract a structured evidence draft from a document")
    ex.add_argument("--file", required=True, help="document path (.txt now, .pdf with pypdf installed)")
    ex.add_argument("--sku", required=True)
    ex.add_argument("--provider", default="fake", help="fake | openai | deepseek (default: fake)")
    ex.add_argument("--out", help="write draft YAML here instead of stdout")
    ex.set_defaults(func=cmd_evidence_extract)

    ap = sub.add_parser("evidence-approve", help="flip reviewed: true for one evidence entry")
    ap.add_argument("--bundle", required=True, help="evidence bundle YAML")
    ap.add_argument("--id", required=True, help="evidence id to approve")
    ap.set_defaults(func=cmd_evidence_approve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
