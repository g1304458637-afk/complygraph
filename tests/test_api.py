"""API 级功能测试：删除流程、名字兜底、NTM 代理工具（离线）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import complygraph.intake as intake
import complygraph.registry as registry
from complygraph.intake import SESSIONS, start, next_turn, apply_answer
from complygraph.registry import catalog_entries, delete_user_product, save_user_product
from complygraph.loader import load_product


@pytest.fixture(autouse=True)
def tmp_registry(tmp_path, monkeypatch):
    examples = tmp_path / "examples"
    (examples / "products").mkdir(parents=True)
    (examples / "evidence").mkdir(parents=True)
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "USER_REGISTRY", tmp_path / "user_catalog.yaml")
    yield


def _save(sku, **over):
    product = {"sku": sku, "name": over.pop("name", None) or sku,
               "category": "consumer_electronics"}
    product.update(over)
    return save_user_product({"product": product, "documents": [], "registrations": []})


def test_save_and_delete_roundtrip():
    _save("DEL-1")
    entries = catalog_entries()
    assert any(e[0].endswith("user_DEL-1.yaml") and e[2] is True for e in entries)
    out = delete_user_product("DEL-1")
    assert out["ok"] and out["sku"] == "DEL-1"
    entries = catalog_entries()
    assert not any("DEL-1" in e[0] for e in entries)


def test_delete_demo_sku_is_rejected():
    with pytest.raises(ValueError, match="不可删除"):
        delete_user_product("PB-100")


def test_delete_nonexistent_is_rejected():
    with pytest.raises(ValueError, match="不存在"):
        delete_user_product("GHOST-1")


def test_delete_rejects_bad_sku():
    with pytest.raises(ValueError, match="非法"):
        delete_user_product("../evil")


def test_empty_name_falls_back_to_sku(tmp_path):
    _save("NAMED-1", name=None)
    product_file = registry.ROOT / "examples" / "products" / "user_NAMED-1.yaml"
    assert product_file.exists()
    loaded = load_product(product_file)
    assert loaded.name == "NAMED-1"  # not None / not "None"


# ---- agent_brain 纯工具（离线，不调 LLM） ----

try:
    import pydantic_ai  # noqa: F401
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False

needs_brain = pytest.mark.skipif(not HAS_BRAIN, reason="pydantic-ai not installed (brain extra)")


def _session_with_brain_tools():
    turn = start(lang="zh")
    session = SESSIONS[turn["session_id"]]
    ctx = SimpleNamespace(deps=session)
    from complygraph import agent_brain

    return session, ctx, agent_brain


@needs_brain
def test_brain_current_question_tool():
    session, ctx, ab = _session_with_brain_tools()
    out = ab._current_question(ctx)
    assert out["question"]["id"] == "sku"


@needs_brain
def test_brain_answer_tool_advances_flow():
    session, ctx, ab = _session_with_brain_tools()
    out = ab._answer_current_question(ctx, "AGT-7")
    assert out["answered"] == "sku"
    assert session.sku == "AGT-7"
    nxt = ab._current_question(ctx)
    assert nxt["question"]["id"] == "name"


@needs_brain
def test_brain_evaluate_market_unknown_id():
    session, ctx, ab = _session_with_brain_tools()
    out = ab._evaluate_market(ctx, "xx")
    assert "error" in out
    out2 = ab._evaluate_market(ctx, "de")
    assert "state" in out2 and "blockers" in out2


def test_expiry_radar_flags_expiring_and_expired(tmp_path):
    """The expiry radar lists evidence/registrations that lapse within the
    window (expired -> red) and ignores undated entries."""
    from datetime import date, timedelta

    import yaml

    from complygraph.web import api_expiring

    save_user_product({
        "product": {"sku": "EXP-1", "name": "Radar probe", "category": "consumer_electronics"},
        "documents": ["un383_test_summary"],
        "registrations": [{"scheme": "de.lucid", "number": "L-1", "jurisdictions": ["DE"]}],
    })
    today = date.today()
    ev_path = registry.ROOT / "examples" / "evidence" / "user_EXP-1.yaml"
    data = yaml.safe_load(ev_path.read_text(encoding="utf-8"))
    data["evidence"][0]["valid_until"] = (today + timedelta(days=10)).isoformat()
    data["registrations"][0]["valid_until"] = (today - timedelta(days=1)).isoformat()
    ev_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    out = api_expiring(days=90)
    by_id = {i["id"]: i for i in out["items"]}
    ev = next(v for k, v in by_id.items() if k.startswith("ev."))
    reg = next(v for k, v in by_id.items() if k.startswith("reg."))
    assert ev["status"] == "expiring" and ev["days_left"] == 10
    assert reg["status"] == "expired" and reg["days_left"] == -1
    assert [i["sku"] for i in out["items"]] == ["EXP-1", "EXP-1"]  # sorted by date: expired first
