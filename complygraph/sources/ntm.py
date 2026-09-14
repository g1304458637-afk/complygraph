"""Tier-1 global coverage: UNCTAD TRAINS/MacMap NTM data -> ComplyGraph rule packs.

Two paths:
  * seed (shipped): hand-curated v0 subset in data/ntm_seed.yaml — 10 major
    markets, real regulators, candidate quality.
  * refresh (connector): WITS/TRAINS bulk NTM download keyed by HS code —
    requires a (free) WITS account; regenerates the seed to ~190 countries.

The mapper turns NTM requirements into ordinary ComplyGraph rules
(applies_if: target_markets CONTAINS iso AND hs_code STARTSWITH chapter),
so the engine, dialogue agent and UI need zero changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..models import Rule

PKG_ROOT = Path(__file__).resolve().parents[2]  # repo root
SEED_PATH = PKG_ROOT / "data" / "ntm_seed.yaml"

FEATURE_FACT = "features.wireless_charging"


def load_seed(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or SEED_PATH).read_text(encoding="utf-8"))


def seed_markets(seed: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return (seed or load_seed()).get("markets", [])


def seed_market_iso_codes(seed: dict[str, Any] | None = None) -> list[str]:
    return [m["iso"] for m in seed_markets(seed)]


def _applies_if(req: dict[str, Any], iso: str) -> dict[str, Any]:
    conds: list[dict[str, Any]] = [
        {"fact": "target_markets", "op": "contains", "value": iso},
    ]
    chapters = req.get("applies_hs", [])
    chapter_conds = [{"fact": "hs_code", "op": "startswith", "value": ch} for ch in chapters]
    if len(chapter_conds) == 1:
        conds.append(chapter_conds[0])
    elif chapter_conds:
        conds.append({"any": chapter_conds})
    if req.get("applies_feature"):
        conds.append({"fact": FEATURE_FACT, "op": "eq", "value": True})
    if len(conds) == 1:
        return conds[0]
    return {"all": conds}


def requirement_to_rule(market_iso: str, req: dict[str, Any]) -> Rule:
    requires = {k: v for k, v in req["requires"].items() if k in
                ("kind", "evidence_type", "registration_scheme", "attribute", "field", "severity", "description")}
    requires["id"] = f"req.ntm.{market_iso.lower()}.{req['id']}"
    return Rule.model_validate({
        "id": f"ntm.{market_iso.lower()}.{req['id']}",
        "title": req["title"],
        "version": "0.1.0",
        "pack": f"ntm.{market_iso.lower()}",
        "pack_type": "legal",
        "jurisdiction": market_iso,
        "effective_from": "2000-01-01",
        "applies_if": _applies_if(req, market_iso),
        "requires": [requires],
        "source": req["source"],
        "notes": "Generated from NTM seed v0 (candidate, last_verified: null). Refresh via TRAINS/WITS connector.",
    })


def generate_rules(seed: dict[str, Any] | None = None) -> list[Rule]:
    rules: list[Rule] = []
    for market in seed_markets(seed):
        for req in market.get("requirements", []):
            rules.append(requirement_to_rule(market["iso"], req))
    return rules


def seed_market_configs(seed: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Market registry entries for every ISO in the seed."""
    out: dict[str, dict[str, Any]] = {}
    for market in seed_markets(seed):
        iso = market["iso"]
        out[iso.lower()] = {
            "country": iso,
            "jurisdictions": [iso, "GLOBAL"],
            "eu_member": False,
            "language": "en",
        }
    return out


def fetch_trains_refresh() -> None:
    """Live WITS/TRAINS NTM bulk refresh — requires a free WITS account.

    Kept as an explicit stub so the upgrade path is code, not a rewrite:
    download the TRAINS NTM bulk file, group measures by (reporter, HS
    chapter, NTM branch), emit requirements like the seed's and regenerate.
    """
    raise NotImplementedError(
        "TRAINS/WITS NTM bulk download needs a WITS account (https://wits.worldbank.org/tariff/"
        "non-tariff-measures/en/ntm-datadownload). Until configured, use the shipped seed."
    )
