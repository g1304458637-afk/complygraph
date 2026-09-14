"""Semantic diff between two versions of a rule set.

Rules are keyed by stable id; a version bump on the same id is a `changed`
entry, which is what drives regulation-change impact analysis (Phase 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import Rule
from .receipt import canonical

ChangeKind = Literal["added", "removed", "changed"]


@dataclass
class RuleChange:
    kind: ChangeKind
    rule_id: str
    old_version: str | None = None
    new_version: str | None = None
    fields_changed: list[str] = field(default_factory=list)


def _rule_dict(rule: Rule) -> dict:
    return canonical(rule.model_dump(mode="json")).decode("utf-8")


def diff_rules(old: list[Rule], new: list[Rule]) -> list[RuleChange]:
    old_by_id = {r.id: r for r in old}
    new_by_id = {r.id: r for r in new}
    changes: list[RuleChange] = []
    for rule_id in sorted(old_by_id.keys() | new_by_id.keys()):
        o, n = old_by_id.get(rule_id), new_by_id.get(rule_id)
        if o is None:
            changes.append(RuleChange("added", rule_id, new_version=n.version))
        elif n is None:
            changes.append(RuleChange("removed", rule_id, old_version=o.version))
        else:
            o_raw, n_raw = o.model_dump(mode="json"), n.model_dump(mode="json")
            fields = sorted(k for k in o_raw.keys() | n_raw.keys() if o_raw.get(k) != n_raw.get(k))
            if fields:
                changes.append(RuleChange("changed", rule_id, o.version, n.version, fields))
    return changes
