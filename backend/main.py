"""FastAPI application exposing the agentic analysis graphs over HTTP.

Run from inside `backend/` (matching the smoke tests' convention):

    uvicorn main:app --reload

Both endpoints below call straight into
agents.chat_intent_routing.graph.build_graph() -- Sourabh Shetti's
implementation of the Chat Intent & Routing subgraph (keyword-based
intent classification, watchlist-aware ticker resolution, per-user
conversation history) -- rather than reimplementing any of that here.
Nothing under agents/chat_intent_routing or agents/orchestrator is
modified by this file; this only adapts the HTTP contract to what that
subgraph actually accepts and returns:

    invoke: {"user_id", "message", "ticker" (optional override),
             "horizon", "forecast_days", "thread_id"}
    -> {"intent", "resolved_ticker", "routing_reason", "response", ...}

`response` is one of:
  - the Orchestrator Subgraph's final_response (has "technical_summary")
  - the Orchestrator Subgraph's (or this subgraph's own) error_response
    (has "reason", no "technical_summary")
  - the fixed out-of-scope refusal (has "message", no "ticker")
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import uuid
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.chat_intent_routing.graph import build_graph as build_chat_intent_routing_graph

app = FastAPI(title="Agentic AI Stock Analysis API")

chat_intent_routing_graph = build_chat_intent_routing_graph()


def _invoke_chat_intent_routing(**state):
    """Every call gets its own LangGraph checkpointer thread_id -- this
    graph is compiled with a MemorySaver (see its own build_graph), which
    route_to_orchestrator.py's nested Orchestrator Subgraph call needs to
    support request_human_review's interrupt()/resume. This is unrelated
    to the caller-facing `thread_id` *state* field (see ChatRequest.session_id
    below), which is only a conversation_history tag, not a checkpoint id.
    """
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return chat_intent_routing_graph.invoke(
        {key: value for key, value in state.items() if value is not None}, config=thread_config
    )


def _is_error_response(response):
    return "reason" in response and "technical_summary" not in response


def _is_out_of_scope_response(response):
    return "message" in response and "ticker" not in response


class StockAnalysisRequest(BaseModel):
    stock_name: str = Field(..., description="Stock ticker symbol, e.g. 'AAPL' or 'RELIANCE.NS'")
    forecast_days: Optional[int] = Field(
        None,
        gt=0,
        description=(
            "Optional. When supplied, the Orchestrator also produces an LLM-reasoned qualitative "
            "price range over this many days (not a trained forecasting model)."
        ),
    )
    horizon: Optional[str] = Field(
        None,
        description="One of 'short_term', 'medium_term', 'long_term'. Defaults to 'medium_term' if omitted.",
    )
    user_id: Optional[str] = Field(
        None, description="Optional. Enables watchlist/preference memory across requests for this user."
    )


@app.post("/api/stock-analysis")
def run_stock_analysis(request: StockAnalysisRequest):
    """Direct, structured entry point. Passes `ticker` as an explicit
    override -- per parse_and_route.py's own resolution order, an
    explicit ticker always wins over keyword matching, so this always
    reaches route_to_orchestrator regardless of what `message` says;
    `message` itself is just a human-readable label logged to
    conversation_history, not part of the routing decision here.
    """
    result = _invoke_chat_intent_routing(
        user_id=request.user_id,
        message=f"structured analysis request for {request.stock_name}",
        ticker=request.stock_name,
        horizon=request.horizon,
        forecast_days=request.forecast_days,
    )
    response = result.get("response") or {}

    if _is_error_response(response) or _is_out_of_scope_response(response):
        error_detail = response if "reason" in response else {"ticker": request.stock_name, "reason": response.get("message")}
        raise HTTPException(status_code=422, detail=error_detail)
    return response


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., description="Free-text chat message, e.g. 'how's INFY.NS looking today?'")
    session_id: Optional[str] = Field(
        None,
        description=(
            "Omit on the first message of a conversation -- a new session_id is generated and returned. "
            "Passed through as this subgraph's own `thread_id` state field, tagging this turn in "
            "\"Memory\".conversation_history for later filtering; it does not currently change routing "
            "behavior (this subgraph's memory-informed routing is keyed by user_id's watchlist, not by "
            "session)."
        ),
    )
    user_id: Optional[str] = Field(
        None, description="Optional. Enables watchlist/preference memory and conversation history for this user."
    )
    conversation_history: Optional[List[ChatMessage]] = Field(
        None,
        description=(
            "Accepted for forward-compatibility only -- the underlying subgraph loads its own history "
            "from Postgres by user_id and does not currently accept a caller-supplied transcript."
        ),
    )


class ChatResponse(BaseModel):
    reply: str
    response_type: Literal["analysis", "out_of_scope", "error"]
    session_id: str
    ticker: Optional[str] = None


# Phrases that mark a string as an internal/operational detail rather than
# something a caller asked about: an unbuilt subgraph, an unreachable LLM
# provider, a database problem, a raw exception or a leaked URL. The
# Orchestrator puts these in `risk_flags` and in the decision `reason` (which
# becomes `narrative`) on purpose -- they belong in orchestrator_runs and in
# the logs, where they are needed for debugging. They just should not be read
# back to someone who asked how a stock looks: "Sentiment Analysis subgraph is
# not yet implemented" and "LLM Agent unavailable (429 Client Error ... )" are
# statements about this deployment, not about the ticker.
#
# Matched case-insensitively as substrings, so the surrounding wording (the
# "sentiment: " prefix the Orchestrator adds, the exception text appended after
# a marker) does not have to be predicted exactly.
_INTERNAL_DETAIL_MARKERS = (
    "not yet implemented",
    "not implemented",
    "llm agent unavailable",
    "deterministic fallback",
    "database connection failed",
    "connection failed",
    "client error",
    "server error",
    "traceback",
    "://",
)


def _is_internal_detail(text):
    if not text:
        return False
    lowered = str(text).lower()
    return any(marker in lowered for marker in _INTERNAL_DETAIL_MARKERS)


def _is_unavailable_summary(label, summary):
    """A pillar can come back without an "error" key and still be empty --
    the Sentiment Agent returns a well-formed dict of Nones (see
    agents/orchestrator/nodes/fetch_sentiment_analysis.py). Treat a summary
    whose own directional verdict is missing as unavailable."""
    if label == "technical":
        return not (summary.get("technical_signal") or {}).get("direction")
    if label == "fundamental":
        return not (summary.get("composite") or {}).get("direction")
    return not summary.get("direction")


def _user_facing_flags(risk_flags):
    """Drops operational noise, keeping genuine analytical risk flags (e.g.
    the Fundamental Agent's own composite risk_flags, or a real pillar
    disagreement) -- those are about the ticker and belong in the reply."""
    return [flag for flag in risk_flags if not _is_internal_detail(flag)]


def _format_analysis_reply(response):
    """response here is the Orchestrator's final_response (has
    "technical_summary"/"fundamental_summary"/"sentiment_summary" --
    see agents/orchestrator/nodes/build_final_response.py, unchanged by
    Sourabh's commit). Turns it into a short, readable chat reply --
    mirrors the same field-extraction this project used previously in
    chat_intent_routing/llm_client.py's deterministic template, kept here
    now since that module no longer exists in Sourabh's implementation.
    """
    ticker = response.get("ticker")
    technical = response.get("technical_summary") or {}
    fundamental = response.get("fundamental_summary") or {}
    sentiment = response.get("sentiment_summary") or {}
    fundamental_composite = fundamental.get("composite") or {}

    direction = (
        (technical.get("technical_signal") or {}).get("direction")
        or fundamental_composite.get("direction")
        or sentiment.get("direction")
    )
    confidence = technical.get("confidence")
    if confidence is None:
        confidence = fundamental_composite.get("confidence")
    support_resistance = technical.get("support_resistance") or {}
    support = support_resistance.get("support")
    resistance = support_resistance.get("resistance")
    current_price = technical.get("current_price")
    risk_flags = _user_facing_flags(response.get("risk_flags") or [])
    narrative = response.get("narrative")
    if _is_internal_detail(narrative):
        narrative = None

    parts = [f"Here's what I found for {ticker}:" if ticker else "Here's what I found:"]
    if current_price is not None:
        parts.append(f"Current price: {current_price}.")
    if direction:
        parts.append(f"Overall signal: {direction}.")
    if confidence is not None:
        parts.append(f"Confidence: {confidence}.")
    if support is not None and resistance is not None:
        parts.append(f"Support around {support}, resistance around {resistance}.")
    if risk_flags:
        parts.append(f"Flags to note: {', '.join(str(flag) for flag in risk_flags[:3])}.")

    # Filtering the internal flags above would otherwise let a partial read
    # look like a complete one. Name the missing pillars plainly instead --
    # which pillar had nothing to say is the caller's business; why it had
    # nothing to say is not.
    missing = [
        label
        for label, summary in (
            ("technical", technical),
            ("fundamental", fundamental),
            ("sentiment", sentiment),
        )
        if not summary or "error" in summary or _is_unavailable_summary(label, summary)
    ]
    if missing:
        listed = " and ".join(missing) if len(missing) < 3 else ", ".join(missing[:-1]) + " and " + missing[-1]
        parts.append(f"This read is based on partial data -- {listed} analysis wasn't available.")

    if narrative:
        parts.append(f"Note: {narrative}")
    if len(parts) == 1:
        parts.append("The underlying data didn't have a clear signal to summarize.")
    return " ".join(parts)


@app.post("/api/chat", response_model=ChatResponse)
def run_chat(request: ChatRequest):
    """The Chat Intent & Routing subgraph's own front door -- see
    agents/chat_intent_routing/graph.py. Distinct from /api/stock-analysis
    above (structured input, ticker forced): this endpoint accepts a
    free-text message and lets parse_and_route's own keyword-based
    classification decide intent.
    """
    session_id = request.session_id or str(uuid.uuid4())
    result = _invoke_chat_intent_routing(
        user_id=request.user_id,
        message=request.message,
        thread_id=session_id,
    )
    response = result.get("response") or {}

    if _is_out_of_scope_response(response):
        response_type, reply = "out_of_scope", response["message"]
    elif _is_error_response(response):
        reason = response.get("reason")
        response_type = "error"
        reply = reason if reason and not _is_internal_detail(reason) else "Something went wrong processing that request."
    else:
        response_type, reply = "analysis", _format_analysis_reply(response)

    return ChatResponse(
        reply=reply,
        response_type=response_type,
        session_id=session_id,
        ticker=result.get("resolved_ticker"),
    )


# Serves the Next.js chat frontend's static export (frontend/ is that
# app's source; `npm run build` there outputs the deployable site to
# frontend/out -- see frontend/next.config.js). Mounted last, after every
# @app.post route above and after FastAPI's own auto-registered /docs,
# /openapi.json -- Starlette matches routes in registration order, so this
# catch-all mount never shadows them. Same-origin as the API (both served
# by this one uvicorn process), so the page's fetch("/api/chat") calls need
# no CORS configuration.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "out"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
