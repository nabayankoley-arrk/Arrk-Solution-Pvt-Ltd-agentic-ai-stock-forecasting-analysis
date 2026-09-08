"""State fields added by the User Memory extension.

This is NOT the full Chat Intent & Routing subgraph's state -- this repo
has no base implementation of that subgraph yet (see __init__.py). These
are only the fields the specification's "State" section adds on top of
whatever the base subgraph's own TypedDict turns out to be:

    Input (added):        user_id
    Intermediate (added): user_memory, memory_update
    Output (added):       updated_memory

`resolved_ticker` is included here too even though the specification
doesn't list it as "added" -- it's an existing base-subgraph field
update_user_memory reads (per that node's own Reads: user_id,
resolved_ticker, memory_update), so it must already exist on whatever
state object these nodes are merged into.

Merge UserMemoryFields into the base subgraph's own state TypedDict once
that subgraph is implemented; this class exists on its own for now so
load_user_memory.py/update_user_memory.py have something concrete to
type-hint against.
"""

from typing import Optional, TypedDict


class UserMemoryFields(TypedDict, total=False):
    user_id: Optional[str]
    user_memory: Optional[dict]  # {"watchlist": [...], "preferences": {...}}; set by load_user_memory
    memory_update: Optional[dict]  # e.g. {"preferences": {"default_horizon": "3m"}}; set by parse_and_route
    resolved_ticker: Optional[str]  # owned by the base subgraph; read by update_user_memory
    updated_memory: Optional[dict]  # set by update_user_memory


class ChatIntentRoutingState(UserMemoryFields, total=False):
    """State for graph.py's bridge graph (load_user_memory ->
    invoke_orchestrator -> update_user_memory). Not part of the
    specification -- see graph.py's docstring on why this bridge exists
    and what it stands in for.
    """

    # --- input, passed straight through to the Orchestrator Subgraph ---
    ticker: Optional[str]
    horizon: Optional[str]
    forecast_days: Optional[int]

    # --- invoke_orchestrator ---
    final_response: Optional[dict]
    error_response: Optional[dict]
