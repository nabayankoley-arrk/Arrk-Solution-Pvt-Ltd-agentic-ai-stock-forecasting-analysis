"""interpret — the LLM reads the latest message in the context of the
conversation so far and decides what to do with it:

    analyze       -- the user wants an analysis of one tracked company;
                     route_to_orchestrator runs next, then respond
    reply         -- answer directly: a clarifying question ("which Tata
                     company?"), a greeting, or something already answered
                     earlier in the conversation
    out_of_scope  -- not about stocks or markets; a short polite refusal
    error         -- the LLM could not be reached or returned nothing usable

The LLM is asked for one JSON object rather than a tool call: tool calling is
inconsistent across the free models this runs on (same reasoning as
agents/orchestrator/llm_client.py). Its ticker is validated against
`universe`, so a hallucinated symbol becomes a clarification, not a failed run.

A caller-supplied `ticker` (POST /api/stock-analysis) skips the LLM entirely:
the request is already structured, so there is nothing to interpret.
"""

import json

from agents.orchestrator.llm_client import call_llm_chat, extract_json_object

from .. import config
from ._conversation import format_history
from ._ticker_lookup import resolve_ticker_from_text, tracked_companies

_VALID_HORIZONS = ("short_term", "medium_term", "long_term")

_SYSTEM_PROMPT = """You are the chat assistant of a stock-analysis app for Indian listed companies. \
An analysis engine can produce a technical, fundamental and sentiment read for the tracked \
companies listed in the user's prompt -- and only those.

Decide what to do with the user's LATEST message, reading it in the context of the conversation \
so far. Respond with ONLY one JSON object, no other text:
{"action": "analyze" | "reply" | "out_of_scope",
 "ticker": "<a ticker exactly as listed>" | null,
 "horizon": "short_term" | "medium_term" | "long_term" | null,
 "reply": "<message to the user>" | null}

- "analyze": the user wants an outlook, trend, valuation, forecast, buy/sell view or any other \
analysis of ONE tracked company. Resolve follow-ups ("what about its valuation?", "and Infosys?") \
from the conversation and the company currently under discussion. Set "ticker"; "reply" is \
null. Set "horizon" only if the user states a \
timeframe (days/weeks = short_term, months = medium_term, a year or more = long_term).
- "reply": anything you should answer yourself -- a clarifying question when the company is \
unclear or not tracked, a greeting, a question about something already said in this \
conversation, or a general stock/market question (answer briefly, without inventing figures).
- "out_of_scope": the message is not about stocks, markets, companies or investing. "reply" is \
one polite sentence saying you only help with stock and market questions.

Never invent prices or figures. Keep replies short and conversational."""


def _companies_block(companies):
    if not companies:
        return "(the tracked-company list is unavailable right now; use NSE tickers such as TCS.NS)"
    return "\n".join(f"- {ticker}: {name}" for ticker, name in companies)


def _build_prompt(state, companies):
    return (
        f"Tracked companies:\n{_companies_block(companies)}\n\n"
        f"Company currently under discussion: {state.get('current_ticker') or 'none yet'}\n\n"
        f"Conversation so far:\n{format_history(state.get('messages'))}\n\n"
        f"Latest message: {state.get('message') or ''}"
    )


def _resolve_ticker(raw, companies):
    """The LLM's ticker if it is tracked, else whatever the company-name lookup
    makes of it ("Infosys" -> "INFY.NS"), else None."""
    if not raw:
        return None
    candidate = str(raw).strip().upper()
    tracked = {ticker.upper(): ticker for ticker, _ in companies}
    if not tracked:
        return candidate  # universe unavailable -- let the Orchestrator decide
    return tracked.get(candidate) or tracked.get(f"{candidate}.NS") or resolve_ticker_from_text(str(raw))


def _decide(state):
    companies = tracked_companies()
    raw = call_llm_chat(_SYSTEM_PROMPT, _build_prompt(state, companies))
    decision = extract_json_object(raw)

    action = decision.get("action")
    reply = (decision.get("reply") or "").strip() or None

    if action == "analyze":
        ticker = _resolve_ticker(decision.get("ticker"), companies)
        if ticker:
            horizon = decision.get("horizon")
            return {
                "action": "analyze",
                "resolved_ticker": ticker,
                "current_ticker": ticker,
                "horizon": horizon if horizon in _VALID_HORIZONS else None,
                "routing_reason": f"llm: analyze {ticker}",
            }
        names = ", ".join(name for _, name in companies[:8])
        return {
            "action": "reply",
            "reply": f"I couldn't match that to a company I track. I can analyse companies such as {names}.",
            "routing_reason": f"llm: analyze with untracked ticker {decision.get('ticker')!r}",
        }

    if action in ("reply", "out_of_scope") and reply:
        return {"action": action, "reply": reply, "routing_reason": f"llm: {action}"}

    raise ValueError(f"unusable decision: {json.dumps(decision)[:200]}")


def interpret(state):
    explicit_ticker = state.get("ticker")
    if explicit_ticker:
        return {"action": "analyze", "resolved_ticker": explicit_ticker, "routing_reason": "explicit ticker"}

    user_message = {"role": "user", "content": state.get("message") or ""}
    try:
        result = _decide(state)
    except Exception as exc:
        print(f"[chat] interpret failed: {type(exc).__name__}: {exc}", flush=True)
        result = {"action": "error", "reply": config.UNAVAILABLE_REPLY, "routing_reason": f"llm failed: {exc}"}

    new_messages = [user_message]
    if result["action"] != "analyze":
        new_messages.append({"role": "assistant", "content": result["reply"]})
    return {**result, "messages": new_messages}
