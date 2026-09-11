"""Shared state object threaded through the Chat Intent & Routing
Subgraph's nodes.

Field set matches the "Chat Intent & Routing Subgraph — Specification"
document's own "State" section (Input / Intermediate / Output), plus the
"User Memory — Specification (Chat Intent & Routing Subgraph Extension)"
document's added fields (user_id, user_memory, memory_update,
updated_memory), plus a small number of implementation-only fields
neither document names but that correctness requires -- each flagged
below with why, following the same convention as
agents/orchestrator/state.py.
"""

from typing import Optional, TypedDict


class ChatIntentRoutingState(TypedDict, total=False):
    # --- input (base subgraph) ---
    raw_message: Optional[str]
    conversation_history: Optional[list]  # [{"role": "user"|"assistant", "content": str}, ...]
    session_id: Optional[str]

    # --- input (User Memory extension) ---
    user_id: Optional[str]

    # --- intermediate (base subgraph) ---
    parsed_entities: Optional[dict]  # {"candidate_ticker": str|None, "horizon_text": str|None, "scope_guess": [...]}
    resolved_ticker: Optional[str]
    resolved_horizon: Optional[str]
    resolved_scope: Optional[list]  # e.g. ["technical", "fundamental"]
    routing_decision: Optional[str]  # 'tool_call' | 'clarify' | 'out_of_scope' | 'finalize'
    clarification_question: Optional[str]
    downstream_result: Optional[dict]
    requery_count: int

    # selected_tool/tool_call_args/out_of_scope_reason: not listed
    # separately in the "State" section's Intermediate bullet list, but
    # required by the "LLM Agent Decision Contract" section and by
    # execute_tool_call's own "Reads: selected tool name and arguments" --
    # kept as explicit state fields the same way the Orchestrator
    # Subgraph's state.py already does for its own decision contract
    # (decision/selected_tool/tool_call_args).
    selected_tool: Optional[str]  # 'lookup_ticker' | 'invoke_orchestrator' | 'invoke_single_pillar' |
    #                               'answer_general_question' | None
    tool_call_args: Optional[dict]
    out_of_scope_reason: Optional[str]

    # --- intermediate (User Memory extension) ---
    user_memory: Optional[dict]  # {"watchlist": [...], "preferences": {...}}; set by load_user_memory
    memory_update: Optional[dict]  # e.g. {"preferences": {"default_horizon": "medium_term"}}; set by parse_and_route

    # --- intermediate (session continuity -- not in either specification
    # document; see nodes/load_conversation_context.py's module docstring
    # for why a stateless HTTP endpoint needs this to make session_id
    # actually carry conversation continuity across separate requests) ---
    session_context: Optional[dict]  # {"last_ticker", "last_horizon", "last_scope"} loaded from conversation_sessions

    # --- output (base subgraph) ---
    conversational_reply: Optional[str]
    updated_context: Optional[dict]
    final_output: Optional[dict]

    # --- output (User Memory extension) ---
    updated_memory: Optional[dict]
