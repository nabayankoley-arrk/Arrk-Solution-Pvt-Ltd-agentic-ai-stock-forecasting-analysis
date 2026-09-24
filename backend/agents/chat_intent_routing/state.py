"""Shared state threaded through the Chat Intent & Routing subgraph's nodes."""

from typing import Annotated, Optional, TypedDict


def _append(existing, new):
    return (existing or []) + (new or [])


class ChatIntentRoutingState(TypedDict, total=False):
    # --- conversation (persisted across turns by the checkpointer) ---
    messages: Annotated[list, _append]  # [{"role": "user" | "assistant", "content": str}, ...]
    current_ticker: Optional[str]  # the company under discussion: the last one analysed

    # --- input (per turn; see graph.turn_input) ---
    user_id: Optional[str]  # tags the audit log; the turn is not logged when omitted
    message: Optional[str]  # the user's latest message
    ticker: Optional[str]  # explicit override (POST /api/stock-analysis): skips both LLM calls
    horizon: Optional[str]  # forwarded to the Orchestrator; interpret may set it from the message
    forecast_days: Optional[int]  # forwarded to the Orchestrator as-is
    thread_id: Optional[str]  # session id, stored on each "Memory".conversation_history row

    # --- interpret ---
    action: Optional[str]  # 'analyze' | 'reply' | 'out_of_scope' | 'error'
    resolved_ticker: Optional[str]  # set when action is 'analyze'
    routing_reason: Optional[str]  # debugging aid, not part of the response

    # --- route_to_orchestrator ---
    orchestrator_result: Optional[dict]  # the Orchestrator's final state; None if it raised
    response: Optional[dict]  # its final_response or error_response

    # --- output ---
    reply: Optional[str]  # the chat reply (interpret's, or respond's after an analysis)
