"""execute_tool_call — deterministic orchestration step.

Runs whichever tool parse_and_route selected (see ..tools), bounded by
TOOL_CALL_TIMEOUT_SECONDS, and returns control to parse_and_route (see
graph.py's unconditional execute_tool_call -> parse_and_route edge).

lookup_ticker's result folds into parsed_entities (and resolved_ticker,
when it resolved a single confident match) rather than downstream_result,
per the specification: "Writes: downstream_result (or an updated
parsed_entities if the tool was lookup_ticker), requery_count". Every
other tool's result becomes downstream_result.

requery_count is incremented here (once per actual tool call), not in
parse_and_route -- matching the specification's own split of
responsibilities between the two nodes.
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from .. import tools
from ..config import TOOL_CALL_TIMEOUT_SECONDS

def _invoke_single_pillar(args):
    # invoke_single_pillar's own `params` dict is where it looks for
    # "horizon" (see tools.invoke_single_pillar) -- the generic
    # ticker/horizon/user_id fallback execute_tool_call applies to every
    # tool's top-level args lands as a *sibling* of params, so it must be
    # folded in here rather than left at the top level where
    # invoke_single_pillar would never see it.
    params = dict(args.get("params") or {})
    params.setdefault("horizon", args.get("horizon"))
    return tools.invoke_single_pillar(args.get("ticker"), args.get("pillar_name"), params)


_TOOL_DISPATCH = {
    "lookup_ticker": lambda args: tools.lookup_ticker(args.get("candidate_name")),
    "invoke_orchestrator": lambda args: tools.invoke_orchestrator(
        args.get("ticker"), args.get("horizon"), args.get("user_id"), args.get("forecast_days")
    ),
    "invoke_single_pillar": _invoke_single_pillar,
    "answer_general_question": lambda args: tools.answer_general_question(args.get("question")),
}


def execute_tool_call(state):
    selected_tool = state.get("selected_tool")
    tool_call_args = dict(state.get("tool_call_args") or {})
    requery_count = state.get("requery_count", 0) + 1

    # invoke_orchestrator/invoke_single_pillar need the resolved ticker
    # even when the LLM's tool_call_args didn't repeat it explicitly.
    tool_call_args.setdefault("ticker", state.get("resolved_ticker"))
    tool_call_args.setdefault("horizon", state.get("resolved_horizon"))
    tool_call_args.setdefault("user_id", state.get("user_id"))

    # Observed with smaller/local models: parse_and_route sometimes
    # selects lookup_ticker without actually populating
    # tool_call_args["candidate_name"] at all. tools.lookup_ticker is
    # written to tolerate a whole raw chat message as candidate_name (see
    # its own docstring -- token-level matching, not just a whole-string
    # comparison), so falling back to raw_message here is still useful
    # instead of calling lookup_ticker(None) and guaranteeing "no match".
    if selected_tool == "lookup_ticker":
        tool_call_args.setdefault("candidate_name", state.get("raw_message"))

    runner = _TOOL_DISPATCH.get(selected_tool)
    if runner is None:
        return {
            "downstream_result": {"error": f"unknown or disabled tool: {selected_tool!r}"},
            "requery_count": requery_count,
        }

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runner, tool_call_args)
        try:
            result = future.result(timeout=TOOL_CALL_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            result = {"error": f"{selected_tool} timed out after {TOOL_CALL_TIMEOUT_SECONDS}s"}
        except Exception as exc:  # tools already handle their own expected failures; this is unexpected
            result = {"error": f"{selected_tool} raised: {exc}"}

    if selected_tool == "lookup_ticker":
        parsed_entities = dict(state.get("parsed_entities") or {})
        parsed_entities["ticker_lookup"] = result
        update = {"parsed_entities": parsed_entities, "requery_count": requery_count}
        if result.get("match"):
            update["resolved_ticker"] = result["match"]
        return update

    return {"downstream_result": result, "requery_count": requery_count}
