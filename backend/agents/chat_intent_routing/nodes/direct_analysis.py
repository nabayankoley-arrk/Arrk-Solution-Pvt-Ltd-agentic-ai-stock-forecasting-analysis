"""direct_analysis — a caller-supplied ticker (POST /api/stock-analysis).

The request is already structured, so the agent is skipped: the Orchestrator
runs straight away and its raw result is returned.
"""

from ._orchestrator import run_orchestrator


def direct_analysis(state):
    ticker = state["ticker"]
    orchestrator_result, response = run_orchestrator(ticker, state.get("horizon"), state.get("forecast_days"))
    return {
        "action": "analyze",
        "resolved_ticker": ticker,
        "orchestrator_result": orchestrator_result,
        "response": response,
    }
