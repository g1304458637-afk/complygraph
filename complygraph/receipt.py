"""Reproducible evaluation receipts: canonical JSON + SHA-256 content hash."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from .models import EvidenceBundle, MarketReadiness, Product, Rule

RECEIPT_VERSION = "cg.receipt.v1"


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def build_receipt(
    product: Product,
    bundle: EvidenceBundle,
    rules: list[Rule],
    readiness: MarketReadiness,
) -> dict[str, Any]:
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "as_of": readiness.as_of.isoformat() if isinstance(readiness.as_of, date) else readiness.as_of,
        "market": readiness.market,
        "channel": readiness.channel,
        "product": product.model_dump(mode="json"),
        "evidence": bundle.model_dump(mode="json"),
        "rules": [
            {
                "id": r.id,
                "version": r.version,
                "pack": r.pack,
                "pack_type": r.pack_type,
                "jurisdiction": r.jurisdiction,
                "effective_from": r.effective_from.isoformat(),
                "superseded_by": r.superseded_by,
                "source": r.source.model_dump(),
                "sha256": content_hash(r.model_dump(mode="json")),
            }
            for r in rules
        ],
        "result": readiness.model_dump(mode="json"),
    }
    receipt["sha256"] = content_hash(receipt)
    return receipt
