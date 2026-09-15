"""Deterministic evaluation engine: facts + rule packs + evidence -> readiness.

Pure functions, no I/O. Same inputs always produce the same result and the same
receipt hash (see receipt.py). LLM output can only enter through the evidence
bundle, and unreviewed extractions can never yield `verified`.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from .models import (
    RANK,
    Evidence,
    EvidenceBundle,
    MarketConfig,
    Product,
    Requirement,
    RequirementResult,
    Rule,
    RuleResult,
    MarketReadiness,
    Status,
)

_MISSING = object()

# Statuses that make a blocker-severity rule a hard blocker. `unknown` is in
# this set on purpose: unevaluable is treated as unsafe, never as pass.
HARD_FAIL: frozenset[str] = frozenset({"missing", "mismatch", "expired", "unknown"})

SCORE: dict[str, float] = {
    "verified": 1.0,
    "satisfied_unverified": 0.5,
    "needs_human_review": 0.5,
}


# ---------------------------------------------------------------- facts


def resolve_fact(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def eval_predicate(node: dict[str, Any], facts: dict[str, Any]) -> tuple[bool | None, list[str]]:
    """Return (value, missing_fact_paths). value is None when undeterminable."""
    if "all" in node:
        value, missing = True, []
        for child in node["all"]:
            v, m = eval_predicate(child, facts)
            missing.extend(m)
            if v is False:
                value = False
            elif v is None and value is True:
                value = None
        return value, missing
    if "any" in node:
        any_true, all_false, missing = False, True, []
        for child in node["any"]:
            v, m = eval_predicate(child, facts)
            missing.extend(m)
            if v is True:
                any_true = True
            if v is not False:
                all_false = False
        if any_true:
            return True, missing
        if all_false:
            return False, missing
        return None, missing

    path = node["fact"]
    raw = resolve_fact(facts, path)
    if raw is _MISSING or raw is None:
        return None, [path]
    op = node.get("op", "eq")
    value = node.get("value")
    try:
        if op == "exists":
            return True, []
        if op == "eq":
            return raw == value, []
        if op == "neq":
            return raw != value, []
        if op == "in":
            return raw in value, []
        if op == "not_in":
            return raw not in value, []
        if op == "contains":
            return value in raw, []
        if op == "startswith":
            return str(raw).startswith(str(value)), []
        if op == "gt":
            return raw > value, []
        if op == "gte":
            return raw >= value, []
        if op == "lt":
            return raw < value, []
        if op == "lte":
            return raw <= value, []
    except TypeError:
        return None, [path]
    raise ValueError(f"unhandled op: {op}")


# ---------------------------------------------------------------- evidence checks


def _jurisdiction_covered(declared: list[str], market: MarketConfig) -> bool:
    return bool(
        "GLOBAL" in declared
        or market.country in declared
        or (market.eu_member and "EU" in declared)
    )


def check_evidence(ev: Evidence, product: Product, market: MarketConfig, as_of: date) -> Status | None:
    """Deterministic evidence checks. None = candidate satisfies the checks."""
    if product.sku not in ev.model_scope and not ev.covers_family:
        return "mismatch"
    if ev.valid_until is not None and ev.valid_until < as_of:
        return "expired"
    if not _jurisdiction_covered(ev.jurisdictions, market):
        return "mismatch"
    return None


def evaluate_requirement(
    req: Requirement,
    product: Product,
    bundle: EvidenceBundle,
    market: MarketConfig,
    channel: str | None,
    as_of: date,
) -> RequirementResult:
    def result(status: Status, ids: list[str] | None = None, reason: str = "") -> RequirementResult:
        return RequirementResult(
            requirement=req.id, kind=req.kind, status=status, evidence_ids=ids or [], reason=reason
        )

    if req.kind == "evidence":
        if not req.evidence_type:
            return result("unknown", reason="requirement misconfigured: no evidence_type")
        candidates = [e for e in bundle.evidence if e.evidence_type == req.evidence_type]
        if not candidates:
            return result("missing", reason=f"no evidence of type '{req.evidence_type}' on file")
        passing: list[Evidence] = []
        failures: list[Status] = []
        for ev in candidates:
            failed = check_evidence(ev, product, market, as_of)
            if failed:
                failures.append(failed)
            else:
                passing.append(ev)
        if passing:
            best = "verified" if any(e.reviewed for e in passing) else "satisfied_unverified"
            notes = []
            if best == "satisfied_unverified":
                notes.append("evidence not yet human-reviewed")
            if failures:
                # passing docs win, but conflicting siblings of the same type
                # must be visible in the audit trail, not silently ignored
                notes.append(
                    f"{len(failures)} further document(s) of this type failed scope/validity checks"
                    " — human review recommended"
                )
            return result(best, [e.id for e in passing], "; ".join(notes))  # type: ignore[arg-type]
        worst = min(failures, key=lambda s: RANK[s])
        ids = [e.id for e in candidates]
        if worst == "expired":
            return result("expired", ids, "evidence past its validity date")
        if worst == "mismatch":
            return result("mismatch", ids, "evidence scope does not cover this SKU/jurisdiction")
        return result(worst, ids)

    if req.kind == "registration":
        if not req.registration_scheme:
            return result("unknown", reason="requirement misconfigured: no registration_scheme")
        regs = [
            r
            for r in bundle.registrations
            if r.scheme == req.registration_scheme and r.sku == product.sku
        ]
        if not regs:
            return result("missing", reason=f"no registration in scheme '{req.registration_scheme}'")
        expired = [r for r in regs if r.valid_until is not None and r.valid_until < as_of]
        covered = [r for r in regs if _jurisdiction_covered(r.jurisdictions, market)]
        if not covered:
            return result("mismatch", [r.id for r in regs], "registration not valid for this jurisdiction")
        if covered and any(r.valid_until is None or r.valid_until >= as_of for r in covered):
            return result("verified", [r.id for r in covered if r.valid_until is None or r.valid_until >= as_of])
        if expired:
            return result("expired", [r.id for r in expired], "registration lapsed")
        return result("missing")

    if req.kind == "product_attribute":
        value = product.attributes.get(req.attribute or "")
        if value is None or value == "":
            return result("missing", reason=f"product attribute '{req.attribute}' not provided")
        return result("verified")

    if req.kind == "listing_field":
        if not channel:
            return result("unknown", reason="channel requirement evaluated without a channel")
        fields = product.channel_fields.get(channel, {})
        value = fields.get(req.field or "")
        if value is None or value == "":
            return result("missing", reason=f"channel field '{req.field}' not filled")
        return result("verified")

    return result("unknown", reason=f"unhandled requirement kind: {req.kind}")


# ---------------------------------------------------------------- rule evaluation


def evaluate_rule(
    rule: Rule,
    product: Product,
    bundle: EvidenceBundle,
    market: MarketConfig,
    channel: str | None,
    as_of: date,
) -> RuleResult:
    base = dict(
        rule_id=rule.id,
        rule_version=rule.version,
        pack=rule.pack,
        pack_type=rule.pack_type,
        title=rule.title,
        jurisdiction=rule.jurisdiction,
        source=rule.source,
    )

    def result(status: Status, reason: str = "", severity: str = "blocker", reqs=None) -> RuleResult:
        return RuleResult(status=status, reason=reason, severity=severity, requirements=reqs or [], **base)  # type: ignore[arg-type]

    if rule.superseded_by:
        return result("not_applicable", f"superseded by {rule.superseded_by}")
    if as_of < rule.effective_from:
        return result("not_applicable", f"effective {rule.effective_from.isoformat()}, evaluated as of {as_of.isoformat()}")
    if rule.effective_to is not None and as_of > rule.effective_to:
        return result("not_applicable", f"expired {rule.effective_to.isoformat()}")
    if rule.jurisdiction not in market.jurisdictions:
        return result("not_applicable", f"rule jurisdiction {rule.jurisdiction} not in market scope")
    if rule.pack_type == "channel":
        if channel is None:
            return result("not_applicable", "no channel selected")
        if rule.channel != channel:
            return result("not_applicable", f"channel rule for {rule.channel}")

    applies, missing_facts = eval_predicate(rule.applies_if, product.model_dump())
    if applies is None:
        return result(
            "unknown",
            "product facts insufficient to decide applicability: " + ", ".join(sorted(set(missing_facts))),
        )
    if applies is False:
        return result("not_applicable", "applicability condition not met")
    if not rule.requires:
        # a rule with no modelled requirements proves nothing: unevaluable,
        # never vacuously satisfied (unknown is never pass)
        return result("unknown", "rule has no modelled requirements")

    req_results = [
        evaluate_requirement(req, product, bundle, market, channel, as_of) for req in rule.requires
    ]
    worst = min((r.status for r in req_results), key=lambda s: RANK[s])
    severity = max((req.severity for req in rule.requires), key=lambda s: {"minor": 0, "major": 1, "blocker": 2}[s])
    reason = "; ".join(r.reason for r in req_results if r.reason and r.status == worst)
    return result(worst, reason, severity, req_results)  # type: ignore[arg-type]


# ---------------------------------------------------------------- readiness


def evaluate_market(
    rules: list[Rule],
    product: Product,
    bundle: EvidenceBundle,
    market_id: str,
    market: MarketConfig,
    channel: str | None,
    as_of: date,
) -> MarketReadiness:
    results = [evaluate_rule(rule, product, bundle, market, channel, as_of) for rule in rules]
    applicable = [r for r in results if r.status != "not_applicable"]
    readiness = (
        sum(SCORE.get(r.status, 0.0) for r in applicable) / len(applicable) if applicable else 0.0
    )
    blockers = sorted(
        r.rule_id
        for r in applicable
        if r.severity == "blocker" and r.status in HARD_FAIL
    )
    amber_gaps = [
        r
        for r in applicable
        if r.status != "verified" and not (r.severity == "blocker" and r.status in HARD_FAIL)
    ]
    # Zero applicable rules is NOT green: nothing has been checked yet.
    if not applicable:
        state = "amber"
    else:
        state = "red" if blockers else ("amber" if amber_gaps else "green")
    return MarketReadiness(
        market=market_id,
        channel=channel,
        as_of=as_of,
        state=state,  # type: ignore[arg-type]
        readiness=round(readiness, 4),
        blockers=blockers,
        rules=results,
    )
