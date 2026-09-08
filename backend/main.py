"""FastAPI application exposing the agentic analysis graphs over HTTP.

Run from inside `backend/` (matching the smoke tests' convention):

    uvicorn main:app --reload
"""

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
    graph_input = {
        key: value
        for key, value in {
            "ticker": request.stock_name,
            "forecast_days": request.forecast_days,
            "horizon": request.horizon,
            "user_id": request.user_id,
        }.items()
        if value is not None
    }

    result = chat_intent_routing_graph.invoke(graph_input)
    if result.get("error_response"):
        raise HTTPException(status_code=422, detail=result["error_response"])
    return result["final_response"]
