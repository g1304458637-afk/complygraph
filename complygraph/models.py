"""Core domain models: product facts, evidence, rules, evaluation results."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal[
    "verified",
    "satisfied_unverified",
    "missing",
    "mismatch",
    "expired",
    "not_applicable",
    # reserved: produced by no rule path yet. Evidence conflicts are surfaced
    # via RequirementResult.reason instead of flipping the winning status.
    "needs_human_review",
    "unknown",
]

# Lower rank = less satisfied. Rule status is the worst requirement status;
# `unknown` deliberately ranks below every failure mode so it propagates.
RANK: dict[str, int] = {
    "verified": 5,
    "satisfied_unverified": 4,
    "needs_human_review": 3,
    "expired": 2,
    "mismatch": 2,
    "missing": 1,
    "unknown": 0,
    "not_applicable": -1,
}

Severity = Literal["blocker", "major", "minor"]


# ---------------------------------------------------------------- product


class Manufacturer(BaseModel):
    name: str | None = None
    country: str | None = None
    established_in_eu: bool | None = None


class Product(BaseModel):
    sku: str
    name: str
    category: str
    manufacturer: Manufacturer = Field(default_factory=Manufacturer)
    offered_to_eu_consumer: bool | None = None
    offered_to_us_consumer: bool | None = None
    offered_to_uk_consumer: bool | None = None
    target_markets: list[str] = Field(default_factory=list)  # ISO codes for NTM-skeleton markets
    hs_code: str | None = None  # HS chapter/prefix, e.g. "8507" — keys the global NTM skeleton
    features: dict[str, bool] = Field(default_factory=dict)
    electrical: dict[str, Any] = Field(default_factory=dict)
    packaging: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    channel_fields: dict[str, dict[str, str]] = Field(default_factory=dict)


# ---------------------------------------------------------------- evidence


class Evidence(BaseModel):
    id: str
    sku: str
    evidence_type: str
    issuer: str
    model_scope: list[str] = Field(default_factory=list)
    covers_family: bool = False
    standard: str | None = None
    issued: date
    valid_until: date | None = None
    jurisdictions: list[str] = Field(default_factory=list)
    language: str | None = None
    reviewed: bool = False
    extraction: Literal["human", "llm"] = "human"
    source_file: str | None = None


class Registration(BaseModel):
    id: str
    sku: str
    scheme: str
    number: str
    jurisdictions: list[str] = Field(default_factory=list)
    valid_until: date | None = None


class EvidenceBundle(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    registrations: list[Registration] = Field(default_factory=list)


# ---------------------------------------------------------------- rules


class Source(BaseModel):
    authority: str
    provision: str
    url: str | None = None


class Requirement(BaseModel):
    id: str
    kind: Literal["evidence", "registration", "product_attribute", "listing_field"]
    evidence_type: str | None = None
    registration_scheme: str | None = None
    attribute: str | None = None
    field: str | None = None
    severity: Severity = "blocker"
    description: str = ""


class Rule(BaseModel):
    id: str
    title: str
    version: str
    pack: str
    pack_type: Literal["legal", "channel"] = "legal"
    channel: str | None = None
    jurisdiction: str
    effective_from: date
    effective_to: date | None = None
    superseded_by: str | None = None
    applies_if: dict[str, Any]
    requires: list[Requirement]
    source: Source
    last_verified: date | None = None
    notes: str | None = None


class MarketConfig(BaseModel):
    country: str
    jurisdictions: list[str]
    eu_member: bool
    language: str


class MarketRegistry(BaseModel):
    markets: dict[str, MarketConfig]


# ---------------------------------------------------------------- results


class RequirementResult(BaseModel):
    requirement: str
    kind: str
    status: Status
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class RuleResult(BaseModel):
    rule_id: str
    rule_version: str
    pack: str
    pack_type: str
    title: str
    severity: Severity
    jurisdiction: str
    status: Status
    reason: str = ""
    requirements: list[RequirementResult] = Field(default_factory=list)
    source: Source | None = None


class MarketReadiness(BaseModel):
    market: str
    channel: str | None
    as_of: date
    state: Literal["green", "amber", "red"]
    readiness: float
    blockers: list[str] = Field(default_factory=list)
    rules: list[RuleResult] = Field(default_factory=list)
