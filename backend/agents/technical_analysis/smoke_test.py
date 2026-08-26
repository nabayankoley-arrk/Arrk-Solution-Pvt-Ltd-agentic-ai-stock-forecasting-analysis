"""Wiring smoke test for the Technical Analysis Agent's state graph.

The "invalid input" case needs no database. The other cases exercise
fetch_price_history for real, so they need a Postgres instance with
universe + price_history populated -- see backend/ingestion/
yfinance_price_history_demo.py to seed a ticker.

    python -m agents.technical_analysis.smoke_test   # from the backend/ directory

Without a reachable database, the fetch retries and then routes to
build_error_response with a "database connection failed" reason -- the
graph's control flow still runs end to end, it just can't reach the
compute_*/aggregate_technical_signal path.
"""

from .graph import build_graph

graph = build_graph()


def run(label, request):
    result = graph.invoke(request)
    print(f"--- {label} ---")
    print(result["final_output"])
    print()


if __name__ == "__main__":
    run("invalid input", {"ticker": "", "lookback_days": ""})
