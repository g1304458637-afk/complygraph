"""Conversational intake agent: question flow, live advice, report, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

import complygraph.intake as intake
from complygraph.intake import SESSIONS, apply_answer, finish, next_turn, start


@pytest.fixture(autouse=True)
def tmp_registry(tmp_path, monkeypatch):
    from complygraph import registry

    examples = tmp_path / "examples"
    (examples / "products").mkdir(parents=True)
    (examples / "evidence").mkdir(parents=True)
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "USER_REGISTRY", tmp_path / "user_catalog.yaml")
    yield


def _answer_all(session, scripted: dict, skip=()):
    transcript = []
    for _ in range(200):
        turn = next_turn(session)
        if turn["done"]:
            return transcript
        qid = turn["question"]["id"]
        if qid in skip:
            value = None if turn["question"]["kind"] == "text" else "unknown"
        else:
            value = scripted.get(qid, "yes" if turn["question"]["kind"] == "bool" else ("unknown" if turn["question"]["kind"] in ("choice",) else "1"))
        apply_answer(session, qid, value)
        transcript.append(qid)
    raise AssertionError("dialogue did not terminate in 200 turns")


def test_first_question_is_sku_then_name():
    session = SESSIONS[start()["session_id"]]
    assert next_turn(session)["question"]["id"] == "sku"
    apply_answer(session, "sku", "AGT-1")
    assert next_turn(session)["question"]["id"] == "name"


def test_questions_are_rule_driven():
    """Evidence questions must not appear until the triggering rule is applicable."""
    session = SESSIONS[start()["session_id"]]
    apply_answer(session, "sku", "AGT-2")
    apply_answer(session, "name", "Agent test")
    apply_answer(session, "category", "consumer_electronics")
    apply_answer(session, "mkt_eu", "yes")
    apply_answer(session, "mfr_eu", "no")
    # markets + manufacturer known, but battery unanswered -> UN38.3 postponed
    for _ in range(30):
        t = next_turn(session)
        if t.get("done"):
            break
        qid = t["question"]["id"]
        assert qid != "doc_un383", "UN38.3 question must wait for the battery fact"
        apply_answer(session, qid, "unknown" if t["question"]["kind"] == "choice" else None)
    apply_answer(session, "battery", "yes")
    # now the battery fact is known -> UN38.3 question becomes active
    seen = {next_turn(session)["question"].get("id")}
    for _ in range(30):
        t = next_turn(session)
        if t.get("done"):
            break
        seen.add(t["question"]["id"])
        apply_answer(session, t["question"]["id"], None)
    assert "doc_un383" in seen


def test_full_dialogue_reaches_report_and_persists(tmp_path):
    session = SESSIONS[start(lang="zh")["session_id"]]
    scripted = {
        "sku": "AGT-3",
        "name": "Agent power bank",
        "category": "consumer_electronics",
        "mkt_eu": "yes",
        "mkt_uk": "no",
        "mkt_us": "no",
        "mfr_eu": "no",
        "mfr_name": "ACME Mfg",
        "battery": "yes",
        "battery_wh": "37",
        "wireless": "yes",
        "retail": "yes",
        "trace_marking": "yes",
        "doc_rpa": "yes",
        "doc_safety": "yes",
        "doc_techdoc": "yes",
        "doc_batdec": "yes",
        "doc_un383": "yes",
        "doc_red": "no",
        "reg_lucid": "DE777",
        "reg_weee_de": "DE 4444",
        "reg_battg_de": "BattG-9",
        "reg_fr_pack": "FR-1",
        "reg_fr_weee": "FR-2",
        "reg_fr_bat": "FR-3",
        "attr_triman": "yes",
        "ch_amazon_de": "yes",
    }
    transcript = _answer_all(session, scripted)
    assert "doc_un383" in transcript  # triggered by battery answer
    assert "doc_red" in transcript    # triggered by wireless answer
    assert "reg_gb_weee" not in transcript  # UK not selected -> rule not applicable

    report = finish(session)
    assert report["ok"] and report["sku"] == "AGT-3"
    markets = {m["market"]: m for m in report["markets"]}
    assert set(markets) == {"de", "fr"}  # only selected markets
    # missing RED report -> blocker in DE and FR
    assert "eu.red.radio_equipment" in markets["de"]["blockers"]
    # everything else provided -> LUCID verified, no packaging blocker
    assert "de.packaging.lucid" not in markets["de"]["blockers"]
    # persisted into the registry
    data = (tmp_path / "user_catalog.yaml").read_text(encoding="utf-8")
    assert "AGT-3" in data


def test_advice_appears_when_rule_triggers():
    session = SESSIONS[start()["session_id"]]
    apply_answer(session, "sku", "AGT-4")
    apply_answer(session, "name", "x")
    apply_answer(session, "category", "consumer_electronics")
    apply_answer(session, "mfr_eu", "no")
    r = apply_answer(session, "mkt_eu", "yes")
    # after selecting EU with a non-EU manufacturer, GPSR should surface as advice
    joined = " ".join(a["text"] for a in r["advice"])
    assert "eu.gpsr.responsible_person" in joined


def test_unknown_survives_the_dialogue():
    """Answering '不确定' to manufacturer-EU keeps the rule unknown, never green."""
    session = SESSIONS[start()["session_id"]]
    _answer_all(session, {"sku": "AGT-5", "name": "n", "mfr_eu": "unknown", "category": "consumer_electronics"})
    report = finish(session)
    de = next(m for m in report["markets"] if m["market"] == "de")
    assert "eu.gpsr.responsible_person" in de["unknowns"]


def json_of(market_report) -> str:
    import json

    return json.dumps(market_report, ensure_ascii=False)


def test_eu_electronics_doc_attestations_all_recorded():
    """RoHS/EMC/LVD 'yes' answers must land in the evidence attestation set
    (regression: the handler chain silently dropped these three)."""
    session = SESSIONS[start()["session_id"]]
    for qid, value in [("sku", "AGT-6"), ("doc_rohs", "yes"),
                       ("doc_emc", "yes"), ("doc_lvd", "yes")]:
        apply_answer(session, qid, value)
    assert {"rohs_test_report", "emc_test_report", "lvd_test_report"} <= set(session.documents)


def test_unknown_answers_stay_unknown_not_no():
    """'不确定' keeps the fact undetermined: a maybe-battery is never a
    no-battery, and unknown markets must not flip rules to not_applicable."""
    session = SESSIONS[start()["session_id"]]
    apply_answer(session, "sku", "AGT-7")
    apply_answer(session, "mkt_eu", "unknown")
    apply_answer(session, "battery", "unknown")
    apply_answer(session, "wireless", "unknown")
    apply_answer(session, "retail", "unknown")
    p = intake.partial_product(session)
    assert p.offered_to_eu_consumer is None
    assert "present" not in p.electrical.get("battery", {})
    assert "wireless_charging" not in p.features
    assert "packaged_for_end_consumer" not in p.packaging


def test_ntm_attestation_keeps_its_jurisdiction():
    """finish() must hand the rule's jurisdiction to save_user_product under the
    `jurisdictions` key (regression: singular `jurisdiction` was silently widened
    to GLOBAL, letting one country's evidence cover every market)."""
    import yaml

    from complygraph import registry

    ntm_qid = next(q.id for q in intake.CATALOG if q.id.startswith("doc_ntm_ntm.ae"))
    session = SESSIONS[start()["session_id"]]
    apply_answer(session, "sku", "AGT-8")
    apply_answer(session, "name", "Jurisdiction probe")
    apply_answer(session, ntm_qid, "yes")
    report = finish(session)
    assert report["ok"]
    data = yaml.safe_load(
        (registry.ROOT / "examples" / "evidence" / "user_AGT-8.yaml").read_text(encoding="utf-8")
    )
    ecas = next(e for e in data["evidence"] if e["evidence_type"] == "ecas_certificate")
    assert ecas["jurisdictions"] == ["AE"]
