"""Shared state threaded through the Chat Intent & Routing subgraph's nodes."""

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatIntentRoutingState(TypedDict, total=False):
    # --- conversation (persisted across turns by the checkpointer) ---
    messages: Annotated[list[AnyMessage], add_messages]  # human / AI (incl. tool calls) / tool messages
    current_ticker: Optional[str]  # the company under discussion: the last one analysed

    # --- input (per turn; see graph.turn_input) ---
    user_id: Optional[str]  # tags the audit log; the turn is not logged when omitted
    message: Optional[str]  # the user's latest message, as text (for the audit log)
    ticker: Optional[str]  # explicit override (POST /api/stock-analysis): skips the agent
    horizon: Optional[str]  # forwarded to the Orchestrator with an explicit ticker
    forecast_days: Optional[int]  # forwarded to the Orchestrator with an explicit ticker
    thread_id: Optional[str]  # session id, stored on each "Memory".conversation_history row

    # --- agent / tools (per turn) ---
    tool_rounds: Optional[int]  # rounds of tool calls so far this turn
    analyses: Optional[list]  # [{"ticker", "orchestrator_result", "response"}, ...] run this turn

    # --- output (per turn) ---
    action: Optional[str]  # 'analysis' | 'reply' | 'error' (chat); 'analyze' (explicit ticker)
    reply: Optional[str]  # the chat reply
    response_type: Optional[str]  # 'analysis' | 'reply' | 'error'
    resolved_ticker: Optional[str]  # the last ticker analysed this turn
    orchestrator_result: Optional[dict]  # its Orchestrator final state; None if it raised
    response: Optional[dict]  # its final_response or error_response
