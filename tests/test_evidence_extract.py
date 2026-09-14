"""Evidence extraction pipeline: provider output -> unreviewed draft -> review.

Pipeline-level False Green invariant: nothing that flows through the LLM can
satisfy a blocker as `verified` until a human flips `reviewed`.
"""

from __future__ import annotations

import copy
from datetime import date

import yaml

from complygraph.evidence_extract import (
    FakeKeywordProvider,
    OpenAICompatibleProvider,
    build_evidence,
    extract_text,
)
from complygraph.models import EvidenceBundle

from conftest import run

SAMPLE_UN383 = """Issuer: CTI Certification Laboratory
Certificate of UN 38.3 Test Summary

Model: PB-100
Tested according to UN 38.3 (Rev.7).
Issued: 2025-02-20
Valid until: 2027-02-20
Language: English. Accepted in the EU and the United States.
"""


def test_fake_provider_extract_structure():
    fields = FakeKeywordProvider().extract(SAMPLE_UN383, sku="PB-100")
    assert fields["document_type"] == "un383_test_summary"
    assert fields["issuer"] == "CTI Certification Laboratory"
    assert "PB-100" in fields["model_scope"]
    assert fields["issued"] == "2025-02-20"
    assert fields["valid_until"] == "2027-02-20"
    assert "EU" in fields["jurisdictions"] and "US" in fields["jurisdictions"]


def test_draft_is_always_unreviewed_llm():
    fields = FakeKeywordProvider().extract(SAMPLE_UN383, sku="PB-100")
    fields["reviewed"] = True  # provider output cannot forge the review flag
    draft = build_evidence(fields, sku="PB-100", source_file="fake.pdf")
    assert draft.reviewed is False
    assert draft.extraction == "llm"
    assert draft.evidence_type == "un383_test_summary"


def test_pipeline_draft_stays_amber_until_human_review(product, bundle):
    draft = build_evidence(FakeKeywordProvider().extract(SAMPLE_UN383, sku="PB-100"), sku="PB-100")
    bundle2 = EvidenceBundle(
        evidence=bundle.evidence + [draft], registrations=bundle.registrations
    )
    # a reviewed:false draft never lifts a rule to verified even next to reviewed evidence
    readiness = run(None, None, product, bundle2, market="de")
    battery = next(r for r in readiness.rules if r.rule_id == "eu.batteries.conformity")
    assert battery.status == "satisfied_unverified"

    # replace the reviewed UN38.3 evidence with only the draft -> cannot be verified
    bundle3 = copy.deepcopy(bundle2)
    bundle3.evidence = [e for e in bundle3.evidence if e.id != "ev.un383.001"]
    readiness3 = run(None, None, product, bundle3, market="de")
    transport3 = next(r for r in readiness3.rules if r.rule_id == "transport.un383.test_summary")
    assert transport3.status == "satisfied_unverified"
    assert readiness3.state == "amber"

    # human review flips the flag (on the copy actually inside the bundle) -> verified
    next(e for e in bundle3.evidence if e.id == draft.id).reviewed = True
    readiness4 = run(None, None, product, bundle3, market="de")
    transport4 = next(r for r in readiness4.rules if r.rule_id == "transport.un383.test_summary")
    assert transport4.status == "verified"


def test_openai_provider_requires_configuration_and_parses_payload():
    import os

    saved = {k: os.environ.pop(k, None) for k in ("CG_LLM_BASE_URL", "CG_LLM_API_KEY", "CG_LLM_MODEL")}
    try:
        try:
            OpenAICompatibleProvider()
            raise AssertionError("expected RuntimeError without configuration")
        except RuntimeError:
            pass
    finally:
        os.environ.update({k: v for k, v in saved.items() if v is not None})

    provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1", api_key="k", model="m")
    payload = provider.build_payload(SAMPLE_UN383, sku="PB-100")
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0
    assert "UN 38.3" in payload["messages"][1]["content"]
    assert provider.parse_response({"choices": [{"message": {"content": '{"document_type": "other"}'}}]}) == {
        "document_type": "other"
    }


def test_extract_text_passthrough_for_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    assert extract_text(f) == "hello"


def test_build_evidence_unknown_document_type_falls_back_conservatively():
    draft = build_evidence({"document_type": "not_in_list", "issuer": "x", "model_scope": None, "issued": None}, sku="PB-100")
    assert draft.evidence_type == "other"
    assert draft.model_scope == ["PB-100"]  # scope falls back to the SKU, never assumes family coverage
    assert draft.jurisdictions == []  # no jurisdiction claim -> evaluator stays conservative
    assert yaml.safe_load(yaml.safe_dump(draft.model_dump(mode="json")))
