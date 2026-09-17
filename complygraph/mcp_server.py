"""Minimal MCP (Model Context Protocol) server over stdio — zero dependencies.

Roadmap item: "MCP server: let any agent call the compliance verdict".

Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout (the MCP stdio
transport). Tools reuse the web layer's Store and API functions, so an MCP
client (Claude, Cursor, any MCP host) gets exactly the same deterministic
verdicts the UI does. Run:

    .venv/bin/python -m complygraph.mcp_server
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from . import web

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "complygraph", "version": "0.2.0"}


def _sku_enum() -> list[str]:
    return [p.sku for p, _, _ in web.STORE.catalog()]


def _market_enum() -> list[str]:
    return sorted(web.STORE.markets.markets.keys())


def tool_evaluate_market(args: dict) -> dict:
    payload, code = web.api_eval(args.get("sku", ""), args.get("market", ""), args.get("channel"))
    if code != 200:
        return payload
    r = payload["readiness"]
    return {
        "sku": args.get("sku"), "market": r["market"], "channel": r["channel"],
        "state": r["state"], "readiness": r["readiness"],
        "blockers": r["blockers"],
        "rules": [
            {"rule_id": x["rule_id"], "status": x["status"], "severity": x["severity"],
             "title": x["title"], "reason": x["reason"],
             "source": x["source"]["provision"] if x.get("source") else None}
            for x in r["rules"] if x["status"] != "not_applicable"
        ],
        "receipt_sha256": payload["receipt_sha256"],
    }


def tool_map_overview(_args: dict) -> dict:
    m = web.api_map()
    return {
        "as_of": m["as_of"], "modelled_rules": m["modelled_rules"],
        "markets": [c["market"] for c in m["columns"]],
        "skus": [
            {"sku": row["sku"], "name": row["name"],
             "cells": {c["market"] + (f"/{c['channel']}" if c["channel"] else ""):
                       f'{cell["state"]} {cell["readiness"]:.0%} ({cell["blockers"]} blockers)'
                       for c, cell in zip(m["columns"], row["cells"])}}
            for row in m["rows"]
        ],
    }


def tool_advise(args: dict) -> dict:
    payload, code = web.api_advise(args.get("sku", ""), args.get("market", "de"))
    return payload if code != 200 else {"plan": payload["plan"], "state": payload["state"]}


def tool_recommend(args: dict) -> dict:
    payload, code = web.api_recommend(args.get("sku", ""))
    return payload if code != 200 else {"recommendations": payload["recommendations"]}


def tool_expiring(args: dict) -> dict:
    return web.api_expiring(int(args.get("days", 90)))


def tool_what_if(args: dict) -> dict:
    payload, code = web.api_whatif(args.get("sku", ""), args.get("market", "de"), args.get("changes") or {})
    return payload


def tool_markings(args: dict) -> dict:
    payload, code = web.api_markings(args.get("sku", ""), args.get("market", "de"))
    return payload


def tool_battery_passport(args: dict) -> dict:
    payload, code = web.api_battery_passport(args.get("sku", ""))
    return payload


def tool_list(args: dict) -> dict:
    return {"skus": _sku_enum(), "markets": _market_enum()}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "evaluate_market",
        "description": "Deterministic compliance verdict for one SKU in one market: state, readiness, blockers, per-rule statuses with legal citations. The engine decides; unknown is never pass.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "market": {"type": "string", "description": "market id, e.g. de/fr/gb/us/jp"},
                "channel": {"type": "string", "description": "optional channel, e.g. amazon.de"},
            },
            "required": ["sku", "market"],
        },
    },
    {
        "name": "map_overview",
        "description": "Full SKU x market readiness matrix (compact strings per cell).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "advise",
        "description": "Remediation plan: how to obtain each missing document / complete each registration for a SKU in a market.",
        "inputSchema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}, "market": {"type": "string"}},
            "required": ["sku", "market"],
        },
    },
    {
        "name": "recommend_markets",
        "description": "Rank all modelled markets for a SKU: ready / minor / fixable / costly, with blocker titles.",
        "inputSchema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "expiring",
        "description": "Evidence & registrations that expired or lapse within N days, across the catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 90}},
        },
    },
    {
        "name": "what_if",
        "description": "Counterfactual: apply fact changes (dotted path -> value, e.g. {'features.wireless_charging': false}) to a copy of the SKU and report which rule statuses would flip.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "market": {"type": "string"},
                "changes": {"type": "object", "additionalProperties": True},
            },
            "required": ["sku", "market", "changes"],
        },
    },
    {
        "name": "battery_passport",
        "description": "Battery Passport readiness preview against EU Regulation 2023/1542 Annex XIII: maps facts/evidence already on file onto the passport field groups and lists the gaps honestly.",
        "inputSchema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    },
    {
        "name": "markings",
        "description": "Printable marking/label checklist for a SKU in one market: every modelled marking duty with legal basis and status (on file / claimed / missing).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "market": {"type": "string"},
            },
            "required": ["sku", "market"],
        },
    },
    {
        "name": "list_catalog",
        "description": "Known SKUs and modelled market ids.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

DISPATCH: dict[str, Callable[[dict], dict]] = {
    "evaluate_market": tool_evaluate_market,
    "map_overview": tool_map_overview,
    "advise": tool_advise,
    "recommend_markets": tool_recommend,
    "expiring": tool_expiring,
    "what_if": tool_what_if,
    "markings": tool_markings,
    "battery_passport": tool_battery_passport,
    "list_catalog": tool_list,
}


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, response message out (None for notifications)."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        handler = DISPATCH.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            out = handler(params.get("arguments") or {})
            text = json.dumps(out, ensure_ascii=False, indent=1)
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": text}]}}
    if msg_id is not None:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"unknown method {method}"}}
    return None


def serve(stdin=None, stdout=None) -> int:
    """Serve one stdio session. stdin/stdout overridable for tests."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle(msg)
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
