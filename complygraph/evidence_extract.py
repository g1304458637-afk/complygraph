"""Evidence extraction pipeline: document -> structured draft -> human review.

The LLM classifies and extracts; it can never mark evidence as verified.
Drafts are created with `reviewed: false`, and the evaluator treats unreviewed
evidence as `satisfied_unverified` at best (False Green invariant).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Protocol

from .models import Evidence

EVIDENCE_TYPES = [
    "responsible_person_agreement",
    "safety_information",
    "technical_documentation",
    "un383_test_summary",
    "battery_conformity_declaration",
    "red_test_report",
    "fcc_test_report",
    "declaration_of_conformity",
    "sds",
    "registration_proof",
    "supplier_declaration",
    "other",
]

JURISDICTION_TOKENS = ["EU", "DE", "FR", "US", "GLOBAL"]

EXTRACTION_PROMPT = """You extract structured compliance-evidence metadata from documents.
Return ONLY a JSON object with exactly these fields:
  document_type: one of {types}
  issuer: string (laboratory / authority / manufacturer name)
  model_scope: array of product model strings the document covers
  standard: string or null (e.g. "EN 62368-1:2020", "UN 38.3 (Rev.7)")
  issued: "YYYY-MM-DD" or null
  valid_until: "YYYY-MM-DD" or null
  jurisdictions: array subset of {jurs}
  language: ISO-639 code or null

Document text:
---
{text}
---"""


class LLMProvider(Protocol):
    def extract(self, text: str, sku: str) -> dict: ...


class FakeKeywordProvider:
    """Deterministic offline provider for tests and demos. Not used in production."""

    def extract(self, text: str, sku: str) -> dict:
        low = text.lower()
        if "un 38.3" in low or "38.3" in low:
            doc = "un383_test_summary"
        elif "responsible person" in low:
            doc = "responsible_person_agreement"
        elif "radio equipment" in low or "red test" in low:
            doc = "red_test_report"
        elif "fcc part 15" in low:
            doc = "fcc_test_report"
        elif "technical documentation" in low or "technical file" in low:
            doc = "technical_documentation"
        elif "safety information" in low or "warnings" in low:
            doc = "safety_information"
        elif "declaration of conformity" in low:
            doc = (
                "battery_conformity_declaration"
                if "battery" in low or "batteries" in low
                else "declaration_of_conformity"
            )
        elif "safety data sheet" in low or "sds" in low:
            doc = "sds"
        else:
            doc = "other"

        models = re.findall(r"\b[A-Z]{2,4}-?\d{2,5}[A-Z]?\b", text) or [sku]
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        issuer = "unknown"
        for line in text.splitlines():
            if line.lower().startswith("issuer:"):
                issuer = line.split(":", 1)[1].strip()
                break

        jurisdictions = set()
        for token, needles in {
            "EU": ["eu ", "european union"],
            "DE": ["germany", "de "],
            "FR": ["france", "fr "],
            "US": ["united states", "usa", " us "],
        }.items():
            if any(n in low for n in needles):
                jurisdictions.add(token)
        if not jurisdictions:
            jurisdictions = {"GLOBAL"}

        return {
            "document_type": doc,
            "issuer": issuer,
            "model_scope": models[:5],
            "standard": None,
            "issued": dates[0] if dates else date.today().isoformat(),
            "valid_until": dates[1] if len(dates) > 1 else None,
            "jurisdictions": sorted(jurisdictions, key=JURISDICTION_TOKENS.index),
            "language": "de" if "german" in low else ("en" if "english" in low else None),
        }


class OpenAICompatibleProvider:
    """Calls an OpenAI-compatible /chat/completions endpoint with JSON output."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.environ.get("CG_LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("CG_LLM_API_KEY", "")
        self.model = model or os.environ.get("CG_LLM_MODEL", "gpt-4o-mini")
        if not self.base_url or not self.api_key:
            raise RuntimeError(
                "OpenAICompatibleProvider needs CG_LLM_BASE_URL and CG_LLM_API_KEY "
                "(or pass base_url/api_key). For offline use, choose --provider fake."
            )

    def build_payload(self, text: str, sku: str) -> dict:
        prompt = EXTRACTION_PROMPT.format(types=", ".join(EVIDENCE_TYPES), jurs="/".join(JURISDICTION_TOKENS), text=text)
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise information-extraction engine. Output JSON only."},
                {"role": "user", "content": f"(Evidence will be attached to SKU {sku}.){prompt}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

    def parse_response(self, body: dict) -> dict:
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)

    def extract(self, text: str, sku: str) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(self.build_payload(text, sku)).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return self.parse_response(json.loads(resp.read().decode("utf-8")))


def get_provider(name: str) -> LLMProvider:
    if name == "fake":
        return FakeKeywordProvider()
    if name == "openai":
        return OpenAICompatibleProvider()
    raise ValueError(f"unknown provider '{name}' (fake | openai)")


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                f"PDF support needs pypdf: pip install 'complygraph[extract]' (file: {path})"
            ) from exc
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8")


def build_evidence(fields: dict, sku: str, source_file: str | None = None) -> Evidence:
    """Validate provider output into an Evidence draft. Always unreviewed."""
    doc_type = fields.get("document_type", "other")
    if doc_type not in EVIDENCE_TYPES:
        doc_type = "other"
    model_scope = [str(m) for m in (fields.get("model_scope") or [sku])]
    issued = fields.get("issued") or date.today().isoformat()
    jurisdictions = [j for j in (fields.get("jurisdictions") or []) if j in JURISDICTION_TOKENS]
    digest = hashlib.sha256(f"{sku}|{doc_type}|{model_scope}|{issued}".encode()).hexdigest()[:6]
    return Evidence(
        id=f"ev.{doc_type}.{digest}",
        sku=sku,
        evidence_type=doc_type,
        issuer=fields.get("issuer") or "unknown",
        model_scope=model_scope,
        standard=fields.get("standard"),
        issued=issued,
        valid_until=fields.get("valid_until"),
        jurisdictions=jurisdictions,
        language=fields.get("language"),
        reviewed=False,
        extraction="llm",
        source_file=source_file,
    )


def extract_evidence(document: Path, sku: str, provider: LLMProvider) -> Evidence:
    text = extract_text(document)
    fields = provider.extract(text, sku)
    return build_evidence(fields, sku, source_file=str(document))
