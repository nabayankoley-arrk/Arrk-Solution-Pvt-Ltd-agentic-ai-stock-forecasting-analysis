"""execute_tool_call — deterministic orchestration step.

Dispatches to whichever pillar rerun tool reconcile_and_decide (or a
selected, bounded by
TOOL_CALL_TIMEOUT_SECONDS, and folds the refreshed pillar result back into
state before control returns to reconcile_and_decide. The tools
(rerun_technical/rerun_fundamental/rerun_sentiment) are plain functions
dispatched from a dict here rather than separate LangGraph nodes -- the
specification frames the selected_tool -> tool dispatch as internal
branching within one "Tool Execution" step, not as more graph nodes.

rerun_sentiment re-invokes the same agents/sentiment_analysis subgraph
run_sentiment already calls for the baseline fetch -- a genuine rerun,
unlike the retired stub this replaced (see git history / that module's
own docstring), since a second pass can pick up a document ingested since
the baseline fetch ran, or a cache-miss score that RESCORE_ON_CACHE_MISS
computed and stored on the first pass.

Dispatch tuple is (pillar_status_key, state_field, runner) -- kept
separate because pillar_status/errors are always keyed by the bare pillar
name (technical/fundamental/sentiment) while the state field storing the
actual result is "{pillar}_analysis" (see state.py).
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from .. import config
from ._pillar_runners import run_fundamental, run_sentiment, run_technical

_TOOL_DISPATCH = {
    "rerun_technical": ("technical", "technical_analysis", run_technical),
    "rerun_fundamental": ("fundamental", "fundamental_analysis", run_fundamental),
    "rerun_sentiment": ("sentiment", "sentiment_analysis", run_sentiment),
}


def execute_tool_call(state):
    selected_tool = state.get("selected_tool")
    tool_loop_count = state.get("tool_loop_count", 0) + 1
    dispatch = _TOOL_DISPATCH.get(selected_tool)

    if dispatch is None:
        return {
            "tool_result": {"tool": selected_tool, "status": "error", "error": "unknown or disabled rerun tool"},
            "tool_loop_count": tool_loop_count,
        }

    pillar, state_field, runner = dispatch
    tool_call_args = state.get("tool_call_args") or {}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runner, state, tool_call_args)
        try:
            result, status, error = future.result(timeout=config.TOOL_CALL_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            result, status, error = (
                None,
                "timeout",
                f"{selected_tool} timed out after {config.TOOL_CALL_TIMEOUT_SECONDS}s",
            )

    return {
        state_field: result,
        "pillar_status": {pillar: status},
        "errors": {pillar: error},
        "tool_result": {"tool": selected_tool, "status": status, "error": error},
        "tool_loop_count": tool_loop_count,
    }
