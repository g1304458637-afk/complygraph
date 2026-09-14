"""YAML loading for rule packs, products, evidence bundles and market config.

The predicate DSL is a plain nested structure:

    all:  [node, ...]     # conjunction
    any:  [node, ...]     # disjunction
    fact: <dotted.path>
    op:   eq | neq | in | not_in | exists | gt | gte | lt | lte | contains
    value: <literal>      # optional for op: exists

A predicate evaluates to True / False / None(None = unknown: the fact is absent
or null). Loader validation rejects malformed predicate trees up front.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import EvidenceBundle, MarketRegistry, Product, Rule

OPS = {"eq", "neq", "in", "not_in", "exists", "gt", "gte", "lt", "lte", "contains", "startswith"}


def _validate_predicate(node: Any, where: str) -> None:
    if not isinstance(node, dict):
        raise ValueError(f"{where}: predicate node must be a mapping, got {type(node).__name__}")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        children = node[key]
        if not isinstance(children, list) or not children:
            raise ValueError(f"{where}: '{key}' must be a non-empty list")
        for i, child in enumerate(children):
            _validate_predicate(child, f"{where}.{key}[{i}]")
        return
    fact = node.get("fact")
    if not isinstance(fact, str) or not fact:
        raise ValueError(f"{where}: leaf predicate requires a non-empty 'fact' path")
    op = node.get("op", "eq")
    if op not in OPS:
        raise ValueError(f"{where}: unknown op '{op}' (allowed: {sorted(OPS)})")
    if op != "exists" and "value" not in node:
        raise ValueError(f"{where}: op '{op}' requires a 'value'")


def load_rules(paths: list[Path]) -> list[Rule]:
    rules: list[Rule] = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not data:
            continue
        for i, raw in enumerate(data.get("rules", [])):
            rule = Rule.model_validate(
                {
                    "pack": data["pack"],
                    "pack_type": data.get("pack_type", "legal"),
                    "channel": data.get("channel"),
                    **raw,
                }
            )
            _validate_predicate(rule.applies_if, f"{path.name}:{rule.id}")
            if rule.pack_type == "channel" and not rule.channel:
                raise ValueError(f"{rule.id}: channel packs must declare a channel")
            rules.append(rule)
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise ValueError(f"duplicate rule id: {rule.id}")
        seen.add(rule.id)
    return rules


def load_product(path: Path) -> Product:
    return Product.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_evidence(path: Path) -> EvidenceBundle:
    return EvidenceBundle.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_markets(path: Path) -> MarketRegistry:
    return MarketRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def default_rule_paths(root: Path) -> list[Path]:
    packs = root / "rulepacks"
    return sorted(packs.glob("**/*.yaml")) if packs.exists() else []


def resolve_rule_inputs(paths: list[Path]) -> list[Path]:
    """Expand directories to their YAML files; keep explicit files as-is."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("**/*.yaml")))
        else:
            files.append(path)
    return files
