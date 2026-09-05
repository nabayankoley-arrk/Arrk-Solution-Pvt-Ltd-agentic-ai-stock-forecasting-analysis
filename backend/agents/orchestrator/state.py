"""Shared state object threaded through the Orchestrator Subgraph's nodes.

Field set matches the specification's "State" section (Input /
Intermediate State / Output), plus a small number of implementation-only
fields the specification doesn't name but that correctness requires --
each flagged below with why. See docs/ for the source specification.
"""

from typing import Annotated, Optional, TypedDict


def _merge_dicts(current, update):
    """Reducer for pillar_status/errors.

    fetch_technical_analysis, fetch_fundamental_analysis, and
    fetch_sentiment_analysis run concurrently (see graph.py) and each
    contributes only its own pillar's key. Without an explicit reducer,
    three nodes writing to the same top-level state key in one superstep
    raises LangGraph's InvalidUpdateError -- this merges their partial
    dicts instead of overwriting.
    """
    return {**(current or {}), **(update or {})}


class OrchestratorState(TypedDict, total=False):
    # --- input ---
    ticker: Optional[str]  # required unless resolvable from user_memory's watchlist -- see validate_input.py
    horizon: Optional[str]  # defaulted by validate_input

    # --- User Memory extension (agents/chat_intent_routing) ---
    # Not part of the lead's original Orchestrator Subgraph specification --
    # wired in from the "User Memory — Specification (Chat Intent & Routing
    # Subgraph Extension)" document so the orchestrator can be used stand-
    # alone (without the not-yet-implemented Chat Intent & Routing base
    # subgraph) while still getting memory-informed ticker resolution and
    # watchlist/preference persistence. See nodes/load_user_memory.py and
    # nodes/update_user_memory.py -- both thin adapters over
    # agents.chat_intent_routing.nodes' shared implementation.
    user_id: Optional[str]  # caller-supplied; memory is skipped entirely when omitted
    user_memory: Optional[dict]  # {"watchlist": [...], "preferences": {...}}; set by load_user_memory
    memory_update: Optional[dict]  # optional caller-supplied preferences to merge, e.g. {"preferences": {...}}
    updated_memory: Optional[dict]  # set by update_user_memory after persisting

    # forecast_days: optional, caller-supplied (e.g.
    # {"ticker": ..., "horizon": "medium_term", "forecast_days": 30}). Not
    # part of the lead's original specification and not tied to any
    # trained model -- when present, build_final_response asks
    # forecast_price_range.py to reason a price range over the same
    # Technical/Fundamental/Sentiment outputs it already assembles, and
    # attaches it to final_response as "price_forecast". Left None (the
    # default) to skip that extra LLM call entirely.
    forecast_days: Optional[int]

    # --- validate_input ---
    is_valid: bool
    validation_error: Optional[str]

    # run_id: not in the specification's field list. Generated once in
    # validate_input (before the pass/fail check, so it exists on both
    # the error and success paths) and used as the primary key for the
    # optional orchestrator_runs audit table -- see persist_run.py. Kept
    # separate from LangGraph's own thread_id (the caller-supplied value
    # used to resume a paused run): thread_id is that caller's concern
    # and isn't guaranteed to be a valid UUID, which the orchestrator_runs
    # table's run_id column requires.
    run_id: Optional[str]

    # validate_input also resolves horizon into each pillar subgraph's own
    # request shape (see config.HORIZON_TO_PILLAR_PARAMS). Kept out of the
    # specification's documented cross-pillar fields deliberately -- it's
    # an internal detail of *how* fetch_technical_analysis/
    # fetch_fundamental_analysis call their subgraphs, not part of the
    # orchestrator's own reconciliation/decision contract.
    lookback_days: Optional[int]
    ratio_basis: Optional[str]
    lookback_years: Optional[int]

    # --- baseline analysis / tool reruns ---
    technical_analysis: Optional[dict]  # Technical Analysis Agent's final_output, or None
    fundamental_analysis: Optional[dict]  # Fundamental Analysis Agent's final_output, or None
    sentiment_analysis: Optional[dict]  # Sentiment Analysis's final_output, or the "unavailable" stub

    pillar_status: Annotated[dict, _merge_dicts]  # {"technical": "ok"|"error"|"unavailable"|"timeout", ...}
    errors: Annotated[dict, _merge_dicts]  # {"technical": "reason" | None, ...}

    # --- reconcile_and_decide (the LLM Agent's decision contract) ---
    decision: Optional[str]  # 'finalize' | 'call_tool'
    selected_tool: Optional[str]  # 'rerun_technical' | 'rerun_fundamental' | 'rerun_sentiment' | None
    reason: Optional[str]
    tool_call_args: Optional[dict]
    requires_review: bool
    tool_loop_count: int

    # loop_guard_override: not in the specification's field list. Set for
    # exactly one reconcile_and_decide pass by request_human_review when a
    # reviewer explicitly requests a rerun, so that pass doesn't
    # immediately re-trip MAX_TOOL_LOOPS ("this explicit request bypasses
    # MAX_TOOL_LOOPS" -- see request_human_review.py). Cleared by
    # reconcile_and_decide after one use.
    loop_guard_override: bool

    # --- execute_tool_call ---
    tool_result: Optional[dict]

    # --- request_human_review ---
    reviewer_decision: Optional[str]  # 'approve' | 'edit' | 'rerun'
    review_notes: Optional[str]

    # --- output ---
    final_response: Optional[dict]
    error_response: Optional[dict]
