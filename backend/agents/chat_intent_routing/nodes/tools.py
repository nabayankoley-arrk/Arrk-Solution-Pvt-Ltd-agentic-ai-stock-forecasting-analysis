"""The agent's tools, and the node that executes its tool calls.

  analyze_stock        -- the full analysis (technical, fundamental, sentiment)
                          via the Orchestrator; returns reply.analysis_digest().
  get_filing_sentiment -- sentiment from the latest annual report and call
                          transcript only (agents/sentiment_analysis): each
                          document's sentiment profile plus its stored summary,
                          so questions like "what did management say about
                          margins?" or "what risks did the annual report flag?"
                          can be answered from the source. No Orchestrator run,
                          and no LLM call when the profiles are current.

Both validate the ticker against `universe` first, so a hallucinated symbol
comes back as an error the agent can act on.

Tool calls are executed here rather than by LangGraph's ToolNode because each
call also records state (current_ticker, analyses), and ToolNode runs parallel
calls -- "compare TCS and Infosys" -- as concurrent updates to the same keys.
Calls in one message run in order instead.

Each call emits a {"type": "status", ...} event on LangGraph's custom stream
before it starts, so a streaming caller can show progress (see main.py's
/api/chat/stream). A no-op when not streaming.
"""

import json
from functools import lru_cache
from typing import Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

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


@tool
def get_filing_sentiment(ticker: str) -> str:
    """Get the sentiment of ONE tracked company from its latest annual report and latest
    earnings/AGM call transcript: for each document its overall label, management tone,
    guidance, per-theme stances with supporting points, positives, concerns, notable quotes
    and the full stored summary. Use this for questions about what management said, their
    tone or confidence, guidance, risks, strategy, or anything else in the filings. Faster
    than analyze_stock, which you do not also need for these questions.

    ticker: the company's NSE ticker exactly as listed among the tracked companies, e.g. "TCS.NS".
    """
    raise NotImplementedError("executed by the tools node")


TOOLS = [analyze_stock, get_filing_sentiment]


def _not_tracked(raw_ticker):
    names = ", ".join(f"{t} ({n})" for t, n in tracked_companies())
    return {"error": f"{raw_ticker!r} is not a tracked company. Tracked: {names or 'unavailable'}"}


def _analyze(ticker, args, write_event):
    """-> (tool result for the model, analysis record)."""
    write_event({"type": "status", "ticker": ticker, "message": f"Analysing {ticker}..."})
    orchestrator_result, response = run_orchestrator(ticker, args.get("horizon"))
    finished = orchestrator_result is not None and bool(orchestrator_result.get("final_response"))
    record = {"ticker": ticker, "ok": finished, "response": response}
    if finished:
        return analysis_digest(response), record

    if orchestrator_result is None:
        print(f"[chat] orchestrator failed for {ticker}: {(response or {}).get('reason')}", flush=True)
    reason = (response or {}).get("reason")
    shown = reason if reason and not is_internal_detail(reason) and orchestrator_result is not None else None
    return {"ticker": ticker, "error": shown or "the analysis could not be completed right now"}, record


@lru_cache(maxsize=1)
def _sentiment_graph():
    from agents.sentiment_analysis.graph import build_graph

    return build_graph()


def _filing_sentiment(ticker, write_event):
    """The sentiment pillar's result for one ticker, with each source's stored summary."""
    write_event({"type": "status", "ticker": ticker, "message": f"Reading the filings for {ticker}..."})
    try:
        state = _sentiment_graph().invoke({"ticker": ticker})
    except Exception as exc:
        print(f"[chat] sentiment graph failed for {ticker}: {type(exc).__name__}: {exc}", flush=True)
        return {"ticker": ticker, "error": "the filing sentiment could not be read right now"}

    output = state.get("final_output") or {}
    if output.get("error"):
        return {"ticker": ticker, "error": "the filing sentiment could not be read right now"}
    sources = {}
    for source, doc_key in (("transcript", "transcript_doc"), ("annual_report", "annual_report_doc")):
        entry = dict((output.get("sources") or {}).get(source) or {})
        entry.pop("error", None)  # internal detail; status says it was unusable
        doc = state.get(doc_key) or {}
        if doc.get("summary"):
            entry["document_summary"] = doc["summary"]
        sources[source] = entry
    return {
        "ticker": ticker,
        "direction": output.get("direction"),
        "summary": output.get("summary"),
        "sources": sources,
    }


def tools(state):
    write_event = get_stream_writer()
    messages, analyses, current_ticker = [], list(state.get("analyses") or []), state.get("current_ticker")
    for call in state["messages"][-1].tool_calls:
        args = call.get("args") or {}
        if call["name"] not in ("analyze_stock", "get_filing_sentiment"):
            result = {"error": f"unknown tool {call['name']!r}"}
        elif not (ticker := resolve_tracked_ticker(args.get("ticker"))):
            result = _not_tracked(args.get("ticker"))
        elif call["name"] == "analyze_stock":
            result, record = _analyze(ticker, args, write_event)
            analyses.append(record)
            current_ticker = ticker
        else:
            result = _filing_sentiment(ticker, write_event)
            current_ticker = ticker
        messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))

    return {
        "messages": messages,
        "analyses": analyses,
        "current_ticker": current_ticker,
        "tool_rounds": (state.get("tool_rounds") or 0) + 1,
    }
