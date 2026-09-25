"""The agent's tools, and the node that executes its tool calls.

analyze_stock is the only tool: it validates the ticker against `universe`
(so a hallucinated symbol comes back as an error the agent can act on, never
reaching the Orchestrator), runs the Orchestrator, and returns
reply.analysis_digest() -- the user-facing facts only, internal detail removed.

Tool calls are executed here rather than by LangGraph's ToolNode because each
call also records state (current_ticker, analyses), and ToolNode runs parallel
calls -- "compare TCS and Infosys" -- as concurrent updates to the same keys.
Calls in one message run in order instead.
"""

import json
from typing import Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from ..reply import analysis_digest, is_internal_detail
from ._orchestrator import run_orchestrator
from ._ticker_lookup import resolve_tracked_ticker, tracked_companies


@tool
def analyze_stock(ticker: str, horizon: Optional[Literal["short_term", "medium_term", "long_term"]] = None) -> str:
    """Run the technical, fundamental and sentiment analysis for ONE tracked company and
    return its current price, signals, support/resistance, risk flags and which pillars
    were unavailable. Call this before stating any figure or view about a company.

    ticker: the company's NSE ticker exactly as listed among the tracked companies, e.g. "TCS.NS".
    horizon: only if the user states a timeframe -- days/weeks = short_term,
        months = medium_term, a year or more = long_term.
    """
    raise NotImplementedError("executed by the tools node, which also records state")


TOOLS = [analyze_stock]


def _analyze(args):
    """-> (tool result for the model, analysis record or None)."""
    raw_ticker = args.get("ticker")
    ticker = resolve_tracked_ticker(raw_ticker)
    if not ticker:
        names = ", ".join(f"{t} ({n})" for t, n in tracked_companies())
        return {"error": f"{raw_ticker!r} is not a tracked company. Tracked: {names or 'unavailable'}"}, None

    orchestrator_result, response = run_orchestrator(ticker, args.get("horizon"))
    record = {"ticker": ticker, "orchestrator_result": orchestrator_result, "response": response}
    if orchestrator_result is not None and orchestrator_result.get("final_response"):
        return analysis_digest(response), record

    if orchestrator_result is None:
        print(f"[chat] orchestrator failed for {ticker}: {(response or {}).get('reason')}", flush=True)
    reason = (response or {}).get("reason")
    shown = reason if reason and not is_internal_detail(reason) and orchestrator_result is not None else None
    return {"ticker": ticker, "error": shown or "the analysis could not be completed right now"}, record


def tools(state):
    messages, analyses, current_ticker = [], list(state.get("analyses") or []), state.get("current_ticker")
    for call in state["messages"][-1].tool_calls:
        if call["name"] == "analyze_stock":
            result, record = _analyze(call.get("args") or {})
            if record:
                analyses.append(record)
                current_ticker = record["ticker"]
        else:
            result = {"error": f"unknown tool {call['name']!r}"}
        messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))

    return {
        "messages": messages,
        "analyses": analyses,
        "current_ticker": current_ticker,
        "tool_rounds": (state.get("tool_rounds") or 0) + 1,
    }
