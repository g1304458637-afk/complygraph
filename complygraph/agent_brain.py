"""LLM brain for the conversational intake agent — powered by PydanticAI.

The LLM understands free-form user messages and orchestrates the conversation,
but every fact it accepts goes through intake.apply_answer and every verdict
still comes from the deterministic engine. The model proposes; the engine
decides (unknown is never pass).

Requires DEEPSEEK_API_KEY (or CG_LLM_API_KEY + CG_LLM_BASE_URL) in the env.
Without a key, the deterministic dialogue keeps working unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import date
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .intake import Session, apply_answer, next_turn, partial_product
from .loader import load_markets
from .registry import save_user_product  # noqa: F401 (re-exported for web layer)

# Rule packs and the market registry are shipped with the package — resolve from
# this file, NOT from registry.ROOT (tests redirect that to a temp sandbox).
_PKG_ROOT = Path(__file__).resolve().parents[1]

_MARKETS = None
_RULES = None


def _markets():
    global _MARKETS
    if _MARKETS is None:
        _MARKETS = load_markets(_PKG_ROOT / "config" / "markets.yaml")
    return _MARKETS


def _all_rules():
    global _RULES
    if _RULES is None:
        from .loader import default_rule_paths, load_rules

        _RULES = load_rules(default_rule_paths(_PKG_ROOT))
    return _RULES


def evaluate_session_market(session: Session, mid: str) -> dict[str, Any]:
    from .engine import evaluate_market

    readiness = evaluate_market(
        _all_rules(), partial_product(session), _bundle_stub(),
        mid, _markets().markets[mid], None, date.today(),
    )
    return {
        "market": mid,
        "state": readiness.state,
        "readiness": readiness.readiness,
        "blockers": [
            {"rule_id": rid,
             "reason": next((rr.reason for rr in readiness.rules if rr.rule_id == rid), "")}
            for rid in readiness.blockers
        ],
    }


def _bundle_stub():
    from .models import EvidenceBundle

    return EvidenceBundle()


INSTRUCTIONS = """You are ComplyGraph's cross-border compliance intake assistant.
You help the user figure out what is required to sell their product in target markets.

You have tools that read and drive a STRUCTURED INTAKE SESSION:
- current_question: the question the user should answer right now (with why it matters)
- answer_current_question(value): submit the user's answer to the current question
  (bool questions accept yes/no; unknown means the user is not sure — that is allowed)
- evaluate_market(market_id): run the deterministic engine for one market
- list_blockers(market_id): current blockers for one market
- list_markets: available market ids
- what_if(market_id, changes): hypothetical — apply fact changes (dotted path
  -> value, e.g. {{"attributes.traceability_marking": "marked"}}) to a COPY of
  the product and report which rules would flip. Use for 'what if I...' questions.

HARD RULES:
1. When the user's message answers the current question, call answer_current_question
   with a properly mapped value, then tell them what changed (new rules triggered,
   blockers) and surface the next question briefly.
2. NEVER invent compliance requirements, verdicts, or timelines. Only report what the
   tools return. If something is not modelled, say it is not modelled yet.
3. "unknown" is never pass. If the user is unsure, keep the slot unknown and reassure them.
4. Answer in the user's language ({lang}). Be concise (2-4 sentences unless listing blockers).
5. You are decision support, not legal advice — say so when giving a summary.
"""


def _current_question(ctx: RunContext[Session]) -> dict[str, Any]:
    turn = next_turn(ctx.deps)
    return {"done": turn.get("done", False), "question": turn.get("question"), "progress": turn.get("progress")}


def _answer_current_question(ctx: RunContext[Session], value: str) -> dict[str, Any]:
    """Submit the user's answer to the current question.

    Map free text to the question's expected value: bool -> yes/no;
    choice -> one of its option values; text/number -> the raw text."""
    turn = next_turn(ctx.deps)
    q = turn.get("question") or {}
    qid = q.get("id")
    if not qid:
        return {"done": True}
    result = apply_answer(ctx.deps, qid, value)
    return {
        "answered": qid,
        "advice": result.get("advice", []),
        "next_question": result.get("question"),
        "done": result.get("done", False),
        "progress": result.get("progress"),
    }


def _evaluate_market(ctx: RunContext[Session], market_id: str) -> dict[str, Any]:
    """Deterministic readiness for one market (id like de/fr/gb/us/jp...)."""
    mid = market_id.lower().strip()
    if mid not in _markets().markets:
        return {"error": f"unknown market {market_id}"}
    return evaluate_session_market(ctx.deps, mid)


def _list_blockers(ctx: RunContext[Session], market_id: str) -> list[dict[str, Any]]:
    return _evaluate_market(ctx, market_id).get("blockers", [])


def _list_markets(ctx: RunContext[Session]) -> list[str]:
    return sorted(_markets().markets.keys())


def _what_if(ctx: RunContext[Session], market_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Counterfactual: apply fact changes (dotted path -> value) to a copy of
    the product and report which rule statuses would flip in that market.
    Use it to answer 'what would change if I did X?' — never mutate the session.
    On error, retry with a path from the error's known-path list (short names
    like 'wireless' are accepted and mapped)."""
    mid = market_id.lower().strip()
    if mid not in _markets().markets:
        return {"error": f"unknown market {market_id}"}
    if not isinstance(changes, dict) or not changes:
        return {"error": "changes must be a non-empty object of {fact.path: value}"}
    from .advisor import what_if

    return what_if(
        partial_product(ctx.deps).model_dump(), changes,
        _markets().markets, mid, _bundle_stub(), _all_rules(), ctx.deps.lang,
    )


def _build_agent(lang: str) -> Agent:
    model = OpenAIChatModel(
        os.environ.get("CG_LLM_MODEL", "deepseek-chat"),
        provider=OpenAIProvider(
            base_url=os.environ.get("CG_LLM_BASE_URL", "https://api.deepseek.com"),
            api_key=os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("CG_LLM_API_KEY", ""),
        ),
    )
    return Agent(
        model,
        instructions=INSTRUCTIONS.format(lang=lang),
        deps_type=Session,
        tools=[_current_question, _answer_current_question, _evaluate_market, _list_blockers, _list_markets, _what_if],
    )


def chat(session: Session, message: str) -> dict[str, Any]:
    """One LLM turn: free-form user message -> agent reply + engine state."""
    history = getattr(session, "_history", None)
    agent = _build_agent(session.lang)
    result = agent.run_sync(message, message_history=history or None, deps=session)
    session._history = result.all_messages()
    turn = next_turn(session)
    return {
        "reply": result.output,
        "done": turn.get("done", False),
        "question": turn.get("question"),
        "progress": turn.get("progress"),
    }
