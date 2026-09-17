"""MCP stdio server: protocol handshake, tool listing, real verdict round-trip."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from complygraph import mcp_server


def _rpc(method: str, params: dict | None = None, msg_id: int | None = 1) -> dict:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if msg_id is not None:
        msg["id"] = msg_id
    return msg


def test_initialize_and_tools_list_roundtrip_subprocess():
    """Drive the real binary over stdio exactly like an MCP host would."""
    repo = Path(__file__).resolve().parents[1]
    py = Path(repo) / ".venv" / "bin" / "python"
    python = str(py) if py.exists() else sys.executable
    lines = [
        _rpc("initialize", {"protocolVersion": "2024-11-05"}),
        _rpc("notifications/initialized", msg_id=None),
        _rpc("tools/list"),
    ]
    payload = "\n".join(json.dumps(m) for m in lines) + "\n"
    proc = subprocess.run(
        [python, "-m", "complygraph.mcp_server"],
        input=payload, capture_output=True, text=True, timeout=60, cwd=repo,
    )
    out = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    init = out[0]["result"]
    assert init["serverInfo"]["name"] == "complygraph"
    assert init["protocolVersion"] == "2024-11-05"
    names = {t["name"] for t in out[1]["result"]["tools"]}
    assert {"evaluate_market", "map_overview", "advise",
            "recommend_markets", "expiring", "what_if", "markings", "battery_passport",
            "list_catalog"} <= names
    assert proc.returncode == 0


def test_tools_call_returns_verdict_with_citation():
    result = mcp_server.handle(_rpc("tools/call", {
        "name": "evaluate_market",
        "arguments": {"sku": "PB-100", "market": "de", "channel": "amazon.de"},
    }))
    data = json.loads(result["result"]["content"][0]["text"])
    assert data["state"] in ("green", "amber", "red")
    rules = [r for r in data["rules"] if r["rule_id"] == "eu.batteries.conformity"]
    assert rules, "battery rule should apply for a power bank"
    assert rules[0]["source"], "audit trail keeps the legal provision"


def test_unknown_tool_is_a_jsonrpc_error():
    out = mcp_server.handle(_rpc("tools/call", {"name": "nope", "arguments": {}}))
    assert out["error"]["code"] == -32602


def test_notification_gets_no_response():
    assert mcp_server.handle(_rpc("notifications/initialized", msg_id=None)) is None


def test_markings_tool_returns_checklist():
    out = mcp_server.handle(_rpc("tools/call", {
        "name": "markings", "arguments": {"sku": "PB-100", "market": "de"},
    }))
    data = json.loads(out["result"]["content"][0]["text"])
    markings = {i["marking"] for i in data["items"]}
    assert "traceability_marking" in markings


def test_battery_passport_tool():
    out = mcp_server.handle(_rpc("tools/call", {
        "name": "battery_passport", "arguments": {"sku": "PB-100"},
    }))
    data = json.loads(out["result"]["content"][0]["text"])
    assert data["applicable"] is True and "carbon_footprint" in data["empty_groups"]
