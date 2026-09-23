"""Shared pillar-invocation helpers.

fetch_technical_analysis/fetch_fundamental_analysis/fetch_sentiment_analysis
(the baseline pass) and execute_tool_call's rerun_technical/
rerun_fundamental/rerun_sentiment (a targeted rerun) both call the same
underlying subgraphs -- just from two different points in the
orchestrator's graph -- so the invoke/error-handling logic lives once here
instead of twice.

Each run_* function takes the orchestrator's state plus a `tool_call_args`
override dict (empty for a baseline fetch) and returns
(result_or_None, status, error_or_None), where status is one of
'ok' | 'error' | 'unavailable' | 'timeout'.
"""

from agents.fundamental_analysis.graph import build_graph as build_fundamental_graph
from agents.sentiment_analysis.graph import build_graph as build_sentiment_graph
from agents.technical_analysis.graph import build_graph as build_technical_graph

from ._current_price import get_current_price

_technical_graph = build_technical_graph()
_fundamental_graph = build_fundamental_graph()
_sentiment_graph = build_sentiment_graph()


def run_technical(state, tool_call_args=None):
    tool_call_args = tool_call_args or {}
    request = {
        "ticker": state["ticker"],
        "lookback_days": tool_call_args.get("lookback_days", state.get("lookback_days")),
    }
    try:
        result = _technical_graph.invoke(request)
    except Exception as exc:  # subgraph itself already handles expected failures; this is unexpected
        return None, "error", f"technical_analysis subgraph raised: {exc}"

    final_output = result.get("final_output")
    if final_output and final_output.get("error"):
        return final_output, "error", final_output["error"].get("reason")
    return final_output, "ok", None


def run_fundamental(state, tool_call_args=None):
    tool_call_args = tool_call_args or {}
    ticker = state["ticker"]
    current_price, price_error = get_current_price(ticker)

    request = {
        "ticker": ticker,
        "ratio_basis": tool_call_args.get("ratio_basis", state.get("ratio_basis")),
        "lookback_years": tool_call_args.get("lookback_years", state.get("lookback_years")),
        "current_price": current_price,
    }
    try:
        result = _fundamental_graph.invoke(request)
    except Exception as exc:
        return None, "error", f"fundamental_analysis subgraph raised: {exc}"

    final_output = result.get("final_output")
    if final_output and final_output.get("error"):
        reason = final_output["error"].get("reason")
        if price_error:
            reason = f"{reason} (also: {price_error})"
        return final_output, "error", reason

    if price_error:
        # Fundamentals still computed -- compute_relative_valuation
        # degrades gracefully without current_price -- but flag it, since
        # one signal was skipped for a fetch reason, not a genuine data
        # gap the Fundamental Analysis Agent itself detected.
        return final_output, "ok", f"current_price unavailable: {price_error}"
    return final_output, "ok", None


def run_sentiment(state, tool_call_args=None):
    request = {"ticker": state["ticker"]}
    try:
        result = _sentiment_graph.invoke(request)
    except Exception as exc:  # subgraph itself already handles expected failures; this is unexpected
        return None, "error", f"sentiment_analysis subgraph raised: {exc}"

    final_output = result.get("final_output")
    if final_output and final_output.get("error"):
        return final_output, "error", final_output["error"].get("reason")

    if final_output and final_output.get("direction") is None:
        source_status = final_output.get("source_status") or {}
        return (
            final_output,
            "unavailable",
            f"no transcript or annual-report sentiment available (source_status={source_status})",
        )
    return final_output, "ok", None
