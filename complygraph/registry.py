"""Catalog registry: demo + user SKUs, and persistence for user-submitted products."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .models import Evidence, EvidenceBundle, Product, Registration

ROOT = Path(__file__).resolve().parents[1]
USER_REGISTRY = ROOT / "examples" / "user_catalog.yaml"

DEMO_CATALOG = [
    ("products/pb100.yaml", "evidence/pb100_evidence.yaml"),
    ("products/tee21.yaml", "evidence/tee21_evidence.yaml"),
    ("products/airpro2.yaml", "evidence/airpro2_evidence.yaml"),
]


def catalog_entries():
    """Demo SKUs + user-submitted SKUs (registry read fresh on every request).

    Yields (product_rel, evidence_rel, deletable)."""
    entries = [(p, e, False) for (p, e) in DEMO_CATALOG]
    if USER_REGISTRY.exists():
        data = yaml.safe_load(USER_REGISTRY.read_text(encoding="utf-8")) or {}
        for e in data.get("skus", []):
            entries.append((e["product"], e["evidence"], True))
    return entries


def delete_user_product(sku: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", sku or ""):
        raise ValueError(f"非法 SKU: {sku!r}")
    rel = f"products/user_{sku}.yaml"
    if not USER_REGISTRY.exists():
        raise ValueError(f"SKU {sku} 不存在（演示 SKU 不可删除）")
    data = yaml.safe_load(USER_REGISTRY.read_text(encoding="utf-8")) or {"skus": []}
    entry = next((e for e in data.get("skus", []) if e.get("product") == rel), None)
    if not entry:
        raise ValueError(f"SKU {sku} 不存在（演示 SKU 不可删除）")
    (ROOT / "examples" / entry["product"]).unlink(missing_ok=True)
    (ROOT / "examples" / entry["evidence"]).unlink(missing_ok=True)
    data["skus"] = [e for e in data["skus"] if e is not entry]
    USER_REGISTRY.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return {"ok": True, "sku": sku}


def doc_jurisdictions(doc_type: str, product: Product) -> list[str]:
    if doc_type == "un383_test_summary":
        return ["GLOBAL"]
    if doc_type == "fcc_test_report":
        return ["US"]
    if doc_type == "red_test_report":
        juris = ["EU"] if product.offered_to_eu_consumer else []
        if product.offered_to_uk_consumer:
            juris.append("GB")
        return juris or ["EU", "GB"]
    if doc_type == "battery_conformity_declaration":
        return ["EU"] if product.offered_to_eu_consumer else ["GLOBAL"]
    juris: list[str] = []
    if product.offered_to_eu_consumer:
        juris.append("EU")
    if product.offered_to_uk_consumer:
        juris.append("GB")
    if product.offered_to_us_consumer:
        juris.append("US")
    return juris or ["GLOBAL"]


def save_user_product(body: dict) -> dict:
    product = Product.model_validate(body.get("product") or {})
    if not product.sku or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", product.sku):
        raise ValueError(f"SKU 只能包含字母/数字/横线/下划线: {product.sku!r}")
    if not product.name:
        product.name = product.sku
    product_path = ROOT / "examples" / "products" / f"user_{product.sku}.yaml"
    evidence_path = ROOT / "examples" / "evidence" / f"user_{product.sku}.yaml"
    if product_path.exists():
        raise ValueError(f"SKU {product.sku} 已存在，请换一个编号")

    docs = [
        Evidence(
            id=f"ev.user.{doc_type}.{product.sku}",
            sku=product.sku,
            evidence_type=doc_type,
            issuer="user-attested（用户确认持有）",
            model_scope=[product.sku],
            issued=date.today().isoformat(),
            jurisdictions=doc_jurisdictions(doc_type, product),
            reviewed=True,
            extraction="human",
        )
        for doc_type in body.get("documents", [])
    ]
    regs = [
        Registration(
            id=f"reg.user.{r['scheme']}.{product.sku}",
            sku=product.sku,
            scheme=r["scheme"],
            number=r["number"],
            jurisdictions=r["jurisdictions"],
        )
        for r in body.get("registrations", [])
        if r.get("scheme") and r.get("number")
    ]
    for extra in body.get("extra_evidence", []):
        etype = extra.get("evidence_type")
        if not etype:
            continue
        jurisdictions = (
            extra.get("jurisdictions")
            or ([extra["jurisdiction"]] if extra.get("jurisdiction") else ["GLOBAL"])
        )
        docs.append(
            Evidence(
                id=f"ev.user.{etype}.{product.sku}",
                sku=product.sku,
                evidence_type=etype,
                issuer="user-attested（用户确认持有）",
                model_scope=[product.sku],
                issued=date.today().isoformat(),
                jurisdictions=jurisdictions,
                reviewed=True,
                extraction="human",
            )
        )
    bundle = EvidenceBundle(evidence=docs, registrations=regs)

    product_path.write_text(
        yaml.safe_dump(product.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    evidence_path.write_text(
        yaml.safe_dump(bundle.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    registry = {"skus": []}
    if USER_REGISTRY.exists():
        registry = yaml.safe_load(USER_REGISTRY.read_text(encoding="utf-8")) or {"skus": []}
    rel_product = product_path.relative_to(ROOT / "examples").as_posix()
    rel_evidence = evidence_path.relative_to(ROOT / "examples").as_posix()
    if not any(s.get("product") == rel_product for s in registry.get("skus", [])):
        registry.setdefault("skus", []).append({"product": rel_product, "evidence": rel_evidence})
    USER_REGISTRY.write_text(
        yaml.safe_dump(registry, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return {
        "ok": True,
        "sku": product.sku,
        "product_path": str(product_path),
        "evidence_path": str(evidence_path),
    }
