"""Market Access Map web UI. Stdlib http.server only — no extra dependencies.

Run from anywhere:  python -m complygraph.web --port 8765
Endpoints:
  GET /                    -> web/index.html
  GET /app.js, /style.css  -> static assets
  GET /api/map             -> SKU x market/channel readiness matrix
  GET /api/eval?sku=&market=&channel=  -> full evaluation + receipt
  GET /api/impact          -> regulation-change impact (Demo D)
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .diff import diff_rules
from .engine import evaluate_market
from .impact import catalog_impact
from .intake import SESSIONS, apply_answer, finish as finish_intake, get as get_session, start as start_intake
from .loader import (
    default_rule_paths,
    load_evidence,
    load_markets,
    load_product,
    load_rules,
    resolve_rule_inputs,
)
from .receipt import build_receipt
from .registry import ROOT, catalog_entries, save_user_product

WEB = Path(__file__).resolve().parent / "web"

CHANNEL_LABELS = {
    ("de", "amazon.de"): "DE / Amazon.de",
    ("fr", None): "FR / direct",
    ("gb", None): "UK / direct",
    ("us", "amazon.us"): "US / Amazon.us",
}

# NTM skeleton markets (Tier-1 global coverage) — generated from the seed
try:
    from .sources.ntm import seed_market_iso_codes

    NTM_MARKETS = [iso.lower() for iso in seed_market_iso_codes()]
except Exception:
    NTM_MARKETS = []


def get_columns():
    """Dynamic columns: curated channels first, then every other registered market
    (VN, JP, KR, ... — anything that has rules) as direct-evaluation columns."""
    columns = [
        {"market": "de", "channel": "amazon.de", "label": "DE / Amazon.de"},
        {"market": "fr", "channel": None, "label": "FR / direct"},
        {"market": "gb", "channel": None, "label": "UK / direct"},
        {"market": "us", "channel": "amazon.us", "label": "US / Amazon.us"},
    ]
    seen = {"de", "fr", "gb", "us"}
    for mid in sorted(STORE.markets.markets.keys()):
        if mid in seen:
            continue
        channel = "amazon.de" if False else None  # channels stay curated for now
        star = "*" if mid in NTM_MARKETS else ""
        columns.append({"market": mid, "channel": None, "label": f"{mid.upper()} / direct{star}"})
        seen.add(mid)
    return columns

class Store:
    def __init__(self) -> None:
        self.rules = load_rules(default_rule_paths(ROOT))
        self.markets = load_markets(ROOT / "config" / "markets.yaml")
        self.rules_v2 = load_rules(resolve_rule_inputs([ROOT / "examples" / "demo_v2" / "rulepacks"]))

    def catalog(self):
        out = []
        for product_rel, evidence_rel, deletable in catalog_entries():
            try:
                out.append((load_product(ROOT / "examples" / product_rel),
                            load_evidence(ROOT / "examples" / evidence_rel),
                            deletable))
            except Exception:
                continue
        return out

    def find(self, sku: str):
        for product, bundle, _ in self.catalog():
            if product.sku == sku:
                return product, bundle
        return None, None


STORE = Store()


def coverage(readiness) -> dict:
    applicable = [r for r in readiness.rules if r.status != "not_applicable"]
    counts: dict[str, int] = {}
    for r in applicable:
        counts[r.status] = counts.get(r.status, 0) + 1
    verified = counts.get("verified", 0)
    return {
        "verified_share": round(verified / len(applicable), 4) if applicable else 0.0,
        "counts": counts,
        "applicable": len(applicable),
    }


def api_map():
    columns = get_columns()
    rows = []
    for product, bundle, deletable in STORE.catalog():
        cells = []
        for col in columns:
            market = STORE.markets.markets[col["market"]]
            r = evaluate_market(STORE.rules, product, bundle, col["market"], market, col["channel"], date.today())
            cells.append({
                "market": col["market"],
                "channel": col["channel"],
                "state": r.state,
                "readiness": r.readiness,
                "blockers": len(r.blockers),
            })
        rows.append({"sku": product.sku, "name": product.name or product.sku,
                     "category": product.category, "deletable": deletable, "cells": cells})
    return {
        "columns": columns,
        "rows": rows,
        "as_of": date.today().isoformat(),
        "modelled_rules": len(STORE.rules),
        "modelled_markets": len(columns),
    }


def api_eval(sku: str, market_id: str, channel: str | None):
    product, bundle = STORE.find(sku)
    if product is None:
        return {"error": f"unknown sku {sku}"}, 404
    if market_id not in STORE.markets.markets:
        return {"error": f"unknown market {market_id}"}, 404
    market = STORE.markets.markets[market_id]
    readiness = evaluate_market(STORE.rules, product, bundle, market_id, market, channel, date.today())
    receipt = build_receipt(product, bundle, STORE.rules, readiness)
    return (
        {
            "readiness": readiness.model_dump(mode="json"),
            "coverage": coverage(readiness),
            "receipt_sha256": receipt["sha256"],
        },
        200,
    )


def api_impact():
    impacts = catalog_impact(
        STORE.rules, STORE.rules_v2,
        [(p, b) for p, b, _ in STORE.catalog()],
        "de", STORE.markets.markets["de"], None, date.today()
    )
    changes = diff_rules(STORE.rules, STORE.rules_v2)
    return {
        "market": "de",
        "changes": [
            {"kind": c.kind, "rule_id": c.rule_id, "old_version": c.old_version,
             "new_version": c.new_version, "fields": c.fields_changed}
            for c in changes
        ],
        "skus": [i.model_dump(mode="json") for i in impacts],
    }



class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802 (stdlib API)
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        try:
            if route == "/api/map":
                self._json(api_map())
            elif route == "/api/eval":
                payload, code = api_eval(
                    query.get("sku", [""])[0],
                    query.get("market", [""])[0],
                    query.get("channel", [None])[0],
                )
                self._json(payload, code)
            elif route == "/api/impact":
                self._json(api_impact())
            elif route == "/" or route == "/index.html":
                self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif route == "/app.js":
                self._send(200, (WEB / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            elif route == "/i18n.js":
                self._send(200, (WEB / "i18n.js").read_bytes(), "text/javascript; charset=utf-8")
            elif route == "/style.css":
                self._send(200, (WEB / "style.css").read_bytes(), "text/css; charset=utf-8")
            elif route.startswith("/assets/"):
                fname = Path(route[len("/assets/"):]).name
                f = WEB / "assets" / fname
                mime = "image/png" if f.suffix == ".png" else "application/octet-stream"
                if f.exists():
                    self._send(200, f.read_bytes(), mime)
                else:
                    self._json({"error": "not found"}, 404)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # surface API errors to the page
            self._json({"error": str(exc)}, 500)

    def do_POST(self):  # noqa: N802 (stdlib API)
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if parsed.path == "/api/products":
                self._json(save_user_product(body))
            elif parsed.path == "/api/agent/start":
                result = start_intake(body.get("lang", "zh"))
                result["brain"] = "llm" if (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("CG_LLM_API_KEY")) else "deterministic"
                self._json(result)
            elif parsed.path == "/api/agent/chat":
                try:
                    from .agent_brain import chat as brain_chat
                except ImportError as exc:
                    self._json({"error": "LLM 大脑未启用：pip install 'complygraph[brain]' "
                                         f"并配置 DEEPSEEK_API_KEY（原始错误: {exc}）"}, 400)
                    return
                session = get_session(body["session_id"])
                result = brain_chat(session, body.get("message", ""))
                self._json({"session_id": session.id, **result})
            elif parsed.path == "/api/agent/answer":
                session = get_session(body["session_id"])
                result = apply_answer(session, body["qid"], body.get("value"))
                self._json({"session_id": session.id, **result})
            elif parsed.path == "/api/agent/finish":
                session = get_session(body["session_id"])
                self._json(finish_intake(session))
            elif parsed.path == "/api/agent/stop":
                SESSIONS.pop(body.get("session_id", ""), None)
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 400)

    def do_DELETE(self):  # noqa: N802 (stdlib API)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/products/"):
            from .registry import delete_user_product

            sku = parsed.path.rsplit("/", 1)[-1]
            try:
                self._json(delete_user_product(sku))
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):  # quiet
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="complygraph.web")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ComplyGraph Market Access Map: http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
