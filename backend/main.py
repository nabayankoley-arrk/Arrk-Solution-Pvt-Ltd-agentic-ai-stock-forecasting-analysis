"""FastAPI entry point: the HTTP API and the built frontend.

Run from inside `backend/`:

    python -m uvicorn main:app --reload

POST /api/chat           -> free-text message; the Chat Intent & Routing graph's
                            tool-calling agent reads it in the context of the
                            session's conversation, runs the Orchestrator when an
                            analysis is needed, and writes the reply.
POST /api/stock-analysis -> structured request; the ticker is passed as an
                            explicit override, so it skips the agent and returns
                            the Orchestrator's raw final_response.

Everything else is served from the Next.js static export in frontend/out.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.chat_intent_routing import config as chat_config
from agents.chat_intent_routing.checkpointer import build_checkpointer
from agents.chat_intent_routing.graph import build_graph as build_chat_intent_routing_graph
from agents.chat_intent_routing.graph import turn_input
from agents.chat_intent_routing.reply import outcome

app = FastAPI(title="Agentic AI Stock Analysis API")

chat_intent_routing_graph = build_chat_intent_routing_graph(checkpointer=build_checkpointer())


def _invoke_chat_intent_routing(checkpoint_thread, **fields):
    """One turn on LangGraph checkpoint thread `checkpoint_thread` -- the session's conversation."""
    return chat_intent_routing_graph.invoke(
        turn_input(**fields), config={"configurable": {"thread_id": checkpoint_thread}}
    )


class StockAnalysisRequest(BaseModel):
    stock_name: str = Field(..., description="Stock ticker symbol, e.g. 'AAPL' or 'RELIANCE.NS'")
    forecast_days: Optional[int] = Field(
        None, gt=0, description="Adds an LLM-reasoned price range over this many days (not a trained model)."
    )
    horizon: Optional[Literal["short_term", "medium_term", "long_term"]] = Field(
        None, description="Defaults to 'medium_term' if omitted."
    )
    user_id: Optional[str] = Field(None, description="Tags this request in the conversation audit log.")


@app.post("/api/stock-analysis")
def run_stock_analysis(request: StockAnalysisRequest):
    """An explicit ticker skips the agent and goes straight to the
    Orchestrator. A throwaway checkpoint thread, deleted afterwards: there is
    no conversation to keep. `message` is only a label for conversation_history."""
    thread_id = f"stock-analysis-{uuid.uuid4()}"
    try:
        result = _invoke_chat_intent_routing(
            thread_id,
            user_id=request.user_id,
            message=f"structured analysis request for {request.stock_name}",
            ticker=request.stock_name,
            horizon=request.horizon,
            forecast_days=request.forecast_days,
        )
    except Exception as exc:
        print(f"[api] /api/stock-analysis failed for {request.stock_name}: {type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(status_code=503, detail="Analysis service unavailable.") from exc
    finally:
        chat_intent_routing_graph.checkpointer.delete_thread(thread_id)

    response = result.get("response") or {}
    result_outcome = outcome(result)
    if result_outcome == "analysis":
        return response
    if result_outcome == "failed":
        # run_orchestrator's reason carries the raw exception text: log it, don't return it.
        print(f"[api] orchestrator failed for {request.stock_name}: {response.get('reason')}", flush=True)
        raise HTTPException(status_code=502, detail={"ticker": request.stock_name, "reason": "Analysis failed."})
    reason = response.get("reason")
    raise HTTPException(status_code=422, detail={"ticker": request.stock_name, "reason": reason})


class ChatRequest(BaseModel):
    message: str = Field(..., description="Free-text chat message, e.g. 'how's INFY.NS looking today?'")
    session_id: Optional[str] = Field(
        None,
        description="Omit on the first message; send back the returned one. The conversation so far is restored from it.",
    )
    user_id: Optional[str] = Field(None, description="Tags this turn in the conversation audit log.")


class ChatResponse(BaseModel):
    reply: str
    response_type: Literal["analysis", "reply", "error"]
    session_id: str
    ticker: Optional[str] = None


@app.post("/api/chat", response_model=ChatResponse)
def run_chat(request: ChatRequest):
    """Free-text chat. The graph writes the reply itself; a failure anywhere
    comes back as an error reply, never a 500."""
    session_id = request.session_id or str(uuid.uuid4())
    try:
        result = _invoke_chat_intent_routing(
            session_id, user_id=request.user_id, message=request.message, thread_id=session_id
        )
    except Exception as exc:
        print(f"[api] /api/chat failed for session_id={session_id}: {type(exc).__name__}: {exc}", flush=True)
        return ChatResponse(reply=chat_config.ERROR_REPLY, response_type="error", session_id=session_id)

    return ChatResponse(
        reply=result.get("reply") or chat_config.ERROR_REPLY,
        response_type=result.get("response_type") or "error",
        session_id=session_id,
        ticker=result.get("resolved_ticker"),
    )


# The frontend's static export (`npm run build` in frontend/). Mounted last:
# Starlette matches in registration order, so this catch-all never shadows
# the API routes or /docs. Same origin as the API, so no CORS is needed.
# Skipped when there is no build yet, so the API still starts on a fresh checkout.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
else:
    print(f"[api] {_FRONTEND_DIR} not found -- run `npm run build` in frontend/ to serve the UI.", flush=True)
