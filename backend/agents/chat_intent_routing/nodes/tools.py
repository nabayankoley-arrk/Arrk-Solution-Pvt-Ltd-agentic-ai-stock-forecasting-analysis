"""The agent's tools, and the node that executes its tool calls.

  analyze_stock        -- the full analysis via the Orchestrator, which picks the
                          pillars and weights for the horizon; with
                          forecast_days, also a price range. Returns
                          reply.analysis_digest().
  get_filing_sentiment -- sentiment from the latest annual report and call
                          transcript only (agents/sentiment_analysis): each
                          document's profile plus its stored summary.
  screen_stocks        -- every tracked company side by side (screening.py), for
                          general questions such as "which is better for a
                          beginner?". No LLM call.

Companies are passed as the user named them -- and if the LLM expanded the
user's words anyway ("Mahindra" -> "Mahindra & Mahindra Ltd"), the words the
user actually typed are used (_company_resolver.users_words). Before anything
runs, every company in the message is resolved; a name that fits
several listed companies -- "Mahindra", "Reliance" -- pauses the run with
LangGraph's interrupt() and asks the user which one, with the candidates as
options. The caller resumes with the answer (main.py), and the node re-runs
from the top: resolution is repeated (cheap, cached) and nothing expensive has
run yet, which is why resolution comes first.

A company the database does not track -- listed on BSE but not in `universe`
("Tata Steel"), or not found at all -- has no analysis to run, so its tool
result carries recent web news about it instead (web_search.py), marked as
web information for the agent to present as such.

Tool calls are executed here rather than by LangGraph's ToolNode because each
call also records state (current_ticker, analyses), and ToolNode runs parallel
calls -- "compare TCS and Infosys" -- as concurrent updates to the same keys.

Each call emits a {"type": "status", ...} event on LangGraph's custom stream
before it starts (see main.py's /api/chat/stream). A no-op when not streaming.
"""

import json
from functools import lru_cache
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from ..reply import analysis_digest, is_internal_detail
from ._company_resolver import find_companies, resolve_answer, users_words
from ._orchestrator import run_orchestrator
from ._ticker_lookup import tracked_companies
from .screening import CRITERIA, screen
from .web_search import search_company_news

Horizon = Optional[Literal["short_term", "medium_term", "long_term"]]


@tool
def analyze_stock(company: str, horizon: Horizon = None, forecast_days: Optional[int] = None) -> str:
    """Run the analysis for ONE company and return its current price, overall verdict
    (direction, confidence, drivers, conflicts), signals, support/resistance, risk flags and,
    with forecast_days, a price range. Call this before stating any figure or view about a
    company, and for any price prediction or target.

    company: the company exactly as the user named it ("Mahindra", "RELIANCE", "Infosys"), or
        the ticker of the company already under discussion for a follow-up. Do not pick a
        ticker yourself when the user's name could mean several companies -- the tool asks them.
    horizon: the user's timeframe -- days/weeks = short_term, months = medium_term, a year or
        more = long_term. Omit if they give none.
    forecast_days: how many days ahead a price prediction is wanted ("next week" = 7, "in a
        month" = 30, "by year end" = the days left). Only for price predictions or targets.
    """
    raise NotImplementedError("executed by the tools node, which also records state")


@tool
def get_filing_sentiment(company: str) -> str:
    """Get the sentiment of ONE company from its latest annual report and latest
    earnings/AGM call transcript: for each document its overall label, management tone,
    guidance, per-theme stances with supporting points, positives, concerns, notable quotes
    and the full stored summary. Use this for questions about what management said, their
    tone or confidence, guidance, risks, strategy, or anything else in the filings. Faster
    than analyze_stock, which you do not also need for these questions.

    company: the company exactly as the user named it, or the ticker already under discussion.
    """
    raise NotImplementedError("executed by the tools node")


@tool
def screen_stocks(criteria: Literal["beginner", "growth", "value", "momentum", "all"] = "all") -> str:
    """Compare every tracked company side by side -- price, volatility, trend, technical and
    fundamental direction, financial health, growth, valuation, filing sentiment -- ranked for
    the criteria. Use for general questions across companies: "which stock is good for a
    beginner?", "which companies look undervalued?", "what has the strongest momentum?".

    criteria: beginner (steadier, financially healthy, lower volatility), growth, value,
        momentum, or all.
    """
    raise NotImplementedError("executed by the tools node")


TOOLS = [analyze_stock, get_filing_sentiment, screen_stocks]
_COMPANY_TOOLS = ("analyze_stock", "get_filing_sentiment")


def _tracked_list():
    return ", ".join(f"{t} ({n})" for t, n in tracked_companies()) or "unavailable"


def _resolve(company):
    """-> (tracked ticker or None, tool error or None, clarification or None).

    Pauses the run to ask the user when the name fits several listed
    companies. `clarification` records what was asked and what the user
    answered, so the model knows the choice: the answer to a pause is not a
    message in the conversation."""
    resolution = find_companies(company)
    clarification = None
    if resolution.ambiguous:
        answer = interrupt({
            "type": "clarification",
            "query": company,
            "question": f'Which company do you mean by "{company}"?',
            "options": resolution.candidates,
        })
        clarification = {"asked_which_company": company, "user_answered": answer}
        resolution = resolve_answer(answer, resolution.candidates)
        if resolution.ambiguous or not (resolution.ticker or resolution.untracked):
            names = "; ".join(f"{c['name']} ({c['ticker']})" for c in find_companies(company).candidates)
            return None, {"error": f"the user's answer did not pick one company. Ask which of: {names}"}, clarification
    if resolution.ticker:
        return resolution.ticker, None, clarification
    if resolution.untracked:
        return None, {"untracked_company": resolution.untracked["name"], "listed": True}, clarification
    return None, {"untracked_company": company, "listed": False}, clarification


def _web_fallback(error, write_event):
    """The tool result for an untracked company: recent web news, leading with
    what matters so the model does not get lost in a list of other companies
    (it already has the tracked list in its prompt)."""
    company = error["untracked_company"]
    write_event({"type": "status", "message": f"Searching the web for {company}..."})
    web = search_company_news(company)
    found = web.get("available") and web.get("results")
    return {
        "company": company,
        "tracked": False,
        "status": ("listed on BSE, but" if error["listed"] else "not found among listed companies, and") + " not tracked "
                  "by this app, so there is no analysis for it",
        "instructions": (
            "Answer the user about this company from web_results below: summarise the recent news, cite each "
            "source and date, and label it as recent web news, not this app's analysis. No buy/sell view or "
            "price prediction."
        ) if found else (
            "Tell the user the app has no analysis for this company, and that web search is not set up on "
            "this server, so no recent news could be looked up."
            if web.get("reason") == "web search is not configured on this server"
            else "Tell the user the app has no analysis or recent news for this company right now."
        ),
        "web_results": web.get("results") or [],
        **({} if found else {"web_search": web.get("reason")}),
    }


def _analyze(ticker, args, write_event):
    """-> (tool result for the model, analysis record)."""
    forecast_days = args.get("forecast_days")
    if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days <= 0:
        forecast_days = None
    write_event({"type": "status", "ticker": ticker, "message": f"Analysing {ticker}..."})
    orchestrator_result, response = run_orchestrator(ticker, args.get("horizon"), forecast_days)
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
    calls = state["messages"][-1].tool_calls

    # 1. Resolve every company first -- this is where the run may pause.
    user_message = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
    )
    resolved = {}
    for call in calls:
        if call["name"] in _COMPANY_TOOLS:
            args = call.get("args") or {}
            company = args.get("company") or args.get("ticker")
            resolved[call["id"]] = _resolve(users_words(company, str(user_message)))

    # 2. Then run the calls.
    messages, analyses, current_ticker = [], list(state.get("analyses") or []), state.get("current_ticker")
    for call in calls:
        args = call.get("args") or {}
        if call["name"] == "screen_stocks":
            criteria = args.get("criteria") if args.get("criteria") in CRITERIA else "all"
            write_event({"type": "status", "message": "Comparing the tracked companies..."})
            result = screen(criteria)
        elif call["name"] in _COMPANY_TOOLS:
            ticker, error, clarification = resolved[call["id"]]
            if error and error.get("untracked_company"):
                result = _web_fallback(dict(error), write_event)
            elif error:
                result = error
            elif call["name"] == "analyze_stock":
                result, record = _analyze(ticker, args, write_event)
                analyses.append(record)
                current_ticker = ticker
            else:
                result = _filing_sentiment(ticker, write_event)
                current_ticker = ticker
        else:
            result = {"error": f"unknown tool {call['name']!r}"}
        if call["name"] in _COMPANY_TOOLS and resolved[call["id"]][2] and isinstance(result, dict):
            result = {"clarification": resolved[call["id"]][2], **result}
        messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))

    return {
        "messages": messages,
        "analyses": analyses,
        "current_ticker": current_ticker,
        "tool_rounds": (state.get("tool_rounds") or 0) + 1,
    }
