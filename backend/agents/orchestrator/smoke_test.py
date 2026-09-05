"""Wiring smoke test for the Orchestrator Subgraph's state graph.

Needs a Postgres instance with both the Technical and Fundamental
Analysis Agents' tables populated for the ticker under test (see those
agents' own smoke_test.py docstrings), plus the "Orchestrator".
orchestrator_runs table (see db/schema.sql) -- persist_run writes to it
unconditionally on every run, including the invalid-input path, so it
must exist for this to complete without raising. reconcile_and_decide
falls back to a deterministic rule if a local Ollama server isn't
reachable (see llm_client.py and config.LLM_FALLBACK_ENABLED), so this
still runs without Ollama -- just without a real LLM Agent behind the
reconciliation. For a real LLM Agent: `ollama serve` plus
`ollama pull <config.OLLAMA_MODEL>`.

    python -m agents.orchestrator.smoke_test   # from the backend/ directory
"""

import uuid

from langgraph.types import Command

from .graph import build_graph

graph = build_graph()


def _thread_config():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def _pending_interrupt(thread_config):
    """Returns the paused request_human_review's Interrupt payload, or
    None if the run isn't paused.

    langgraph 0.2.x (pinned in requirements.txt) surfaces a pause via
    graph.get_state(...).tasks[*].interrupts, not via an "__interrupt__"
    key on invoke()'s return value -- that key was added in a later
    langgraph release.
    """
    for task in graph.get_state(thread_config).tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def _print_step(node_name, node_output):
    # "__interrupt__" is not a node -- stream_mode="updates" emits this
    # pseudo-entry when a node calls interrupt() (see request_human_review.py),
    # with node_output a tuple of langgraph Interrupt objects rather than a
    # state-update dict, so it needs its own branch here instead of
    # .items()-ing it like every real node's output.
    if node_name == "__interrupt__":
        print("[request_human_review] PAUSED -- awaiting reviewer_decision")
        for interrupt in node_output:
            for key, value in interrupt.value.items():
                print(f"    {key}: {value}")
        print()
        return

    print(f"[{node_name}]")
    for key, value in (node_output or {}).items():
        print(f"    {key}: {value}")
    print()


def _stream(stream_input, thread_config):
    """Runs the graph via graph.stream(..., stream_mode="updates") instead
    of graph.invoke(), printing each node's name and exactly the state
    fields it changed as soon as that node finishes -- one entry per
    LangGraph superstep (see graph.py's docstring for the node order/
    branches this makes visible: which pillar ran, whether
    reconcile_and_decide chose to finalize or call_tool, whether it paused
    for human review). Doesn't change graph.py or any node -- this is a
    read-only way of driving the same compiled graph, so it has zero
    effect on a normal graph.invoke() caller.

    stream_input is either the initial request dict (a fresh run) or a
    Command(resume=...) (continuing a paused run) -- same convention
    graph.invoke() itself uses. A node calling interrupt() shows up as the
    special "__interrupt__" entry handled by _print_step above; callers
    should still check _pending_interrupt(thread_config) afterwards to
    decide whether to resume.
    """
    for step in graph.stream(stream_input, config=thread_config, stream_mode="updates"):
        for node_name, node_output in step.items():
            _print_step(node_name, node_output)
    return graph.get_state(thread_config).values


def run_and_trace(ticker, horizon="medium_term", forecast_days=None, user_id=None):
    """Same run as run_and_approve (auto-approves any human-review pause),
    but prints every node's output as it executes instead of only the
    final result -- use this to see exactly which path a run took: which
    pillars ran, whether reconcile_and_decide finalized straight away or
    looped through execute_tool_call first, and whether it paused for
    human review.

    user_id is optional (see state.py's note on the User Memory extension
    fields) -- pass it to exercise load_user_memory/update_user_memory
    against a real "Memory".user_memory row; omitted, memory is skipped
    entirely and behavior is unchanged from before that extension was
    wired in."""
    thread_config = _thread_config()
    request = {"ticker": ticker, "horizon": horizon}
    if forecast_days is not None:
        request["forecast_days"] = forecast_days
    if user_id is not None:
        request["user_id"] = user_id

    print(f"=== {ticker}: tracing orchestrator run ===\n")
    state = _stream(request, thread_config)

    if _pending_interrupt(thread_config) is not None:
        # The pause itself was already printed by _stream/_print_step's
        # "__interrupt__" handling above -- this only decides what to do
        # about it.
        print(f"--- {ticker}: auto-approving paused review (trace demo) ---\n")
        state = _stream(
            Command(resume={"reviewer_decision": "approve", "review_notes": None}),
            thread_config,
        )

    print(f"=== {ticker}: final response ===")
    print(state.get("final_response"))
    print()


def run_invalid_input():
    result = graph.invoke({"ticker": "", "horizon": "medium_term"}, config=_thread_config())
    print("--- invalid input ---")
    print(result.get("error_response"))
    print()


def run_and_approve(ticker, horizon="medium_term", forecast_days=None, user_id=None):
    """Runs to completion; if the LLM Agent (or the deterministic
    fallback) flags requires_review, simulates a reviewer approving the
    response as-is.

    forecast_days is optional (see state.py's note on that field) -- pass
    it to also get final_response["price_forecast"] from
    forecast_price_range.py; omit it to skip that extra LLM call.

    user_id is optional -- pass it to exercise the User Memory extension
    (load_user_memory/update_user_memory); omitted, memory is skipped
    entirely.
    """
    thread_config = _thread_config()
    request = {"ticker": ticker, "horizon": horizon}
    if forecast_days is not None:
        request["forecast_days"] = forecast_days
    if user_id is not None:
        request["user_id"] = user_id
    result = graph.invoke(request, config=thread_config)

    interrupt_payload = _pending_interrupt(thread_config)
    if interrupt_payload is not None:
        print(f"--- {ticker}: paused for human review ---")
        print(interrupt_payload)
        print()
        result = graph.invoke(
            Command(resume={"reviewer_decision": "approve", "review_notes": None}),
            config=thread_config,
        )

    print(f"--- {ticker}: final response (review_status={result['final_response']['review_status']}) ---")
    print(result.get("final_response"))
    print()


def run_and_request_rerun(ticker, horizon="medium_term", user_id=None):
    """Same as run_and_approve, but if paused for review, simulates a
    reviewer requesting one more Technical Analysis rerun instead of
    approving -- exercises the request_human_review -> execute_tool_call
    -> reconcile_and_decide loop-back edge.

    user_id is optional -- see run_and_approve's docstring."""
    thread_config = _thread_config()
    request = {"ticker": ticker, "horizon": horizon}
    if user_id is not None:
        request["user_id"] = user_id
    result = graph.invoke(request, config=thread_config)

    if _pending_interrupt(thread_config) is None:
        print(f"--- {ticker}: finalized directly, nothing to rerun ---")
        print()
        return

    print(f"--- {ticker}: paused for human review, requesting a technical rerun ---")
    result = graph.invoke(
        Command(resume={"reviewer_decision": "rerun", "selected_tool": "rerun_technical", "tool_call_args": {}}),
        config=thread_config,
    )
    if _pending_interrupt(thread_config) is not None:
        result = graph.invoke(
            Command(resume={"reviewer_decision": "approve", "review_notes": None}),
            config=thread_config,
        )

    print(f"--- {ticker}: final response after reviewer-requested rerun ---")
    print(result.get("final_response"))
    print()


if __name__ == "__main__":
    run_invalid_input()
    run_and_approve("", forecast_days=30, user_id="")

