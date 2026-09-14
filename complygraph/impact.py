"""Regulation-change impact: new rule versions -> affected SKUs -> tasks.

`new rule version -> affected SKUs -> affected markets -> blockers/tasks`
implemented as: evaluate every catalog SKU against the old and the new rule
set with the same deterministic engine, and diff the results.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from .diff import diff_rules
from .engine import HARD_FAIL, evaluate_market
from .models import EvidenceBundle, MarketConfig, Product, Rule, Status


class StatusChange(BaseModel):
    rule_id: str
    before: Status | None
    after: Status | None


class RemediationTask(BaseModel):
    sku: str
    kind: str
    rule_id: str
    severity: str
    description: str


class SKUImpact(BaseModel):
    sku: str
    impacted: bool
    state_before: str
    state_after: str
    readiness_before: float
    readiness_after: float
    new_blockers: list[str] = Field(default_factory=list)
    status_changes: list[StatusChange] = Field(default_factory=list)
    tasks: list[RemediationTask] = Field(default_factory=list)


def _requirement_task_kind(req_kind: str) -> str:
    return {
        "evidence": "provide_evidence",
        "registration": "complete_registration",
        "product_attribute": "provide_product_attribute",
        "listing_field": "fill_channel_field",
    }.get(req_kind, "review_rule_change")


def _tasks_for_sku(sku: str, rules_new: list[Rule], readiness, focus_rule_ids: set[str]) -> list[RemediationTask]:
    tasks: list[RemediationTask] = []
    for rule_result in readiness.rules:
        if rule_result.rule_id not in focus_rule_ids or rule_result.status not in HARD_FAIL:
            continue
        if rule_result.status == "unknown" or not rule_result.requirements:
            tasks.append(
                RemediationTask(
                    sku=sku,
                    kind="complete_product_facts",
                    rule_id=rule_result.rule_id,
                    severity=rule_result.severity,
                    description=f"Product facts insufficient to evaluate {rule_result.rule_id}: {rule_result.reason}",
                )
            )
            continue
        by_id = {r.id: r for r in next(rr for rr in rules_new if rr.id == rule_result.rule_id).requires}
        for req_res in rule_result.requirements:
            if req_res.status not in HARD_FAIL:
                continue
            req = by_id.get(req_res.requirement)
            tasks.append(
                RemediationTask(
                    sku=sku,
                    kind=_requirement_task_kind(req.kind if req else ""),
                    rule_id=rule_result.rule_id,
                    severity=req.severity if req else rule_result.severity,
                    description=(req.description if req else "") or req_res.reason,
                )
            )
    return tasks


def sku_impact(
    rules_old: list[Rule],
    rules_new: list[Rule],
    product: Product,
    bundle: EvidenceBundle,
    market_id: str,
    market: MarketConfig,
    channel: str | None,
    as_of: date,
) -> SKUImpact:
    before = evaluate_market(rules_old, product, bundle, market_id, market, channel, as_of)
    after = evaluate_market(rules_new, product, bundle, market_id, market, channel, as_of)
    changes = diff_rules(rules_old, rules_new)
    changed_ids = {c.rule_id for c in changes if c.kind in ("added", "removed", "changed")}

    status_before = {r.rule_id: r.status for r in before.rules}
    status_after = {r.rule_id: r.status for r in after.rules}
    status_changes = [
        StatusChange(rule_id=rid, before=status_before.get(rid), after=status_after.get(rid))
        for rid in sorted(changed_ids)
        if status_before.get(rid) != status_after.get(rid)
    ]
    new_blockers = sorted(set(after.blockers) - set(before.blockers))
    impacted = bool(status_changes) or bool(new_blockers)
    tasks = (
        _tasks_for_sku(product.sku, rules_new, after, changed_ids | set(after.blockers))
        if impacted
        else []
    )
    return SKUImpact(
        sku=product.sku,
        impacted=impacted,
        state_before=before.state,
        state_after=after.state,
        readiness_before=before.readiness,
        readiness_after=after.readiness,
        new_blockers=new_blockers,
        status_changes=status_changes,
        tasks=tasks,
    )


def catalog_impact(
    rules_old: list[Rule],
    rules_new: list[Rule],
    catalog: list[tuple[Product, EvidenceBundle]],
    market_id: str,
    market: MarketConfig,
    channel: str | None,
    as_of: date,
) -> list[SKUImpact]:
    return [
        sku_impact(rules_old, rules_new, product, bundle, market_id, market, channel, as_of)
        for product, bundle in catalog
    ]
