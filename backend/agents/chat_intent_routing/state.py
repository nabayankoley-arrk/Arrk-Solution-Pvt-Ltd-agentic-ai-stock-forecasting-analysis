"""Shared state object threaded through the Chat Intent & Routing
subgraph's nodes.

This is now the base subgraph's own state, not just the User Memory
extension's added fields -- see __init__.py's note on the minimal
parse_and_route this repo implements (a 'stock_market' vs. 'out_of_scope'
split, no free-form NLU). user_id/user_memory/memory_update/updated_memory
are the same fields the "User Memory — Specification (Chat Intent &
Routing Subgraph Extension)" document added; they're no longer described
as an addition on top of something else, since this is that something
else now.
"""

from typing import Optional, TypedDict


class ChatIntentRoutingState(TypedDict, total=False):
    # --- input ---
    user_id: Optional[str]  # caller-supplied; memory is skipped entirely when omitted -- see nodes/load_user_memory.py
    message: Optional[str]  # raw free-text query, e.g. "what's the trend on TCS.NS?"
    ticker: Optional[str]  # optional explicit override -- skips extraction/keyword classification in parse_and_route
    horizon: Optional[str]  # forwarded to the Orchestrator Subgraph as-is; see its own config.VALID_HORIZONS
    forecast_days: Optional[int]  # forwarded to the Orchestrator Subgraph as-is

    # thread_id: an optional caller-supplied conversation/session id, logged
    # alongside each conversation_history row (see nodes/persist_conversation_turn.py)
    # so history can later be filtered per-session, not just per-user. Kept
    # separate from LangGraph's own checkpoint thread_id (the value passed
    # via config={"configurable": {"thread_id": ...}} on invoke()) -- same
    # reasoning as agents/orchestrator/state.py's run_id note: that value is
    # this graph's own checkpointer's concern, not guaranteed to mean
    # anything to conversation_history's schema, and this graph works fine
    # without it (conversation_history is queried by user_id alone).
    thread_id: Optional[str]

    # --- load_user_memory / update_user_memory ---
    user_memory: Optional[dict]  # {"watchlist": [...], "preferences": {...}}; set by load_user_memory
    memory_update: Optional[dict]  # e.g. {"preferences": {"default_horizon": "3m"}}; caller-supplied
    updated_memory: Optional[dict]  # set by update_user_memory

    # --- load_conversation_history / persist_conversation_turn ---
    # conversation_history: this user's past turns, oldest-first, each
    # {"message":..., "intent":..., "resolved_ticker":..., "response":...,
    # "created_at":...} -- set by load_conversation_history. Not consumed
    # by parse_and_route yet (see that node's own docstring); loaded so
    # it's already available in state for whenever something does.
    conversation_history: Optional[list]

    # --- parse_and_route ---
    intent: Optional[str]  # 'stock_market' | 'out_of_scope'
    resolved_ticker: Optional[str]  # ticker after explicit/extracted/watchlist resolution; None if none of those applied
    routing_reason: Optional[str]  # why parse_and_route picked this intent -- a debugging aid, not part of the response

    # --- route_to_orchestrator ---
    # The Orchestrator Subgraph's own final state (its invoke() return
    # value) -- only set for intent='stock_market'. Kept around
    # unsummarized in case a caller wants pillar-level detail beyond
    # `response` below.
    orchestrator_result: Optional[dict]

    # --- output ---
    response: Optional[dict]  # the one response shape this graph always returns, regardless of intent
