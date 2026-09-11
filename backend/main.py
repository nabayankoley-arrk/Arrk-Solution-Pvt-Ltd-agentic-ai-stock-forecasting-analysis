"""FastAPI application exposing the agentic analysis graphs over HTTP.

Run from inside `backend/` (matching the smoke tests' convention):

    uvicorn main:app --reload
"""

import uuid
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.chat_intent_routing import tools as chat_intent_routing_tools
from agents.chat_intent_routing.graph import build_graph as build_chat_intent_routing_graph

app = FastAPI(title="Agentic AI Stock Analysis API")

chat_intent_routing_graph = build_chat_intent_routing_graph()


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
    """Direct, structured entry point into the Orchestrator Subgraph --
    bypasses parse_and_route entirely, unlike /api/chat below. Calls
    agents.chat_intent_routing.tools.invoke_orchestrator (the same tool
    parse_and_route itself uses for a full three-pillar analysis) so this
    endpoint's underlying behavior -- including auto-approving any
    human-review pause -- doesn't need its own separate copy of that
    logic.
    """
    result = chat_intent_routing_tools.invoke_orchestrator(
        ticker=request.stock_name,
        horizon=request.horizon,
        user_id=request.user_id,
        forecast_days=request.forecast_days,
    )
    if result is None or result.get("error"):
        error_detail = (result or {}).get("error") or {"ticker": request.stock_name, "reason": "unknown error"}
        raise HTTPException(status_code=422, detail=error_detail)
    return result


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., description="Free-text chat message, e.g. 'how's INFY.NS looking today?'")
    session_id: Optional[str] = Field(
        None,
        description=(
            "Omit on the first message of a conversation -- a new session_id is generated and returned. "
            "Pass the session_id from a prior response to continue that conversation; conversation_history "
            "and the last-resolved ticker/horizon/scope are then recovered automatically from that session."
        ),
    )
    user_id: Optional[str] = Field(
        None, description="Optional. Enables watchlist/preference memory across sessions for this user."
    )
    conversation_history: Optional[List[ChatMessage]] = Field(
        None,
        description=(
            "Optional. Overrides the session's own stored history for this turn only, e.g. if the client "
            "maintains its own transcript. Most callers should omit this and rely on session_id instead."
        ),
    )


class ChatResponse(BaseModel):
    reply: str
    response_type: Literal["analysis", "single_pillar", "clarification", "out_of_scope"]
    session_id: str
    ticker: Optional[str] = None
    updated_context: Optional[dict] = None


@app.post("/api/chat", response_model=ChatResponse)
def run_chat(request: ChatRequest):
    """The Chat Intent & Routing Subgraph's own front door -- see
    agents/chat_intent_routing/graph.py. Distinct from /api/stock-analysis
    above (which calls the Orchestrator Subgraph directly with structured
    input): this endpoint accepts a free-text message and is what a
    conversational client should call turn after turn, using the returned
    session_id to keep asking follow-up questions without repeating
    context.
    """
    graph_input = {
        "raw_message": request.message,
        "session_id": request.session_id or str(uuid.uuid4()),
        "user_id": request.user_id,
        "conversation_history": (
            [message.model_dump() for message in request.conversation_history]
            if request.conversation_history
            else None
        ),
    }

    result = chat_intent_routing_graph.invoke(graph_input)
    return result["final_output"]


# Serves frontend/index.html (a minimal, dependency-free chat page against
# /api/chat) at the site root. Mounted last, after every @app.post route
# above and after FastAPI's own auto-registered /docs, /openapi.json --
# Starlette matches routes in registration order, so this catch-all mount
# never shadows them. Same-origin as the API (both served by this one
# uvicorn process), so the page's fetch("/api/chat") calls need no CORS
# configuration.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
