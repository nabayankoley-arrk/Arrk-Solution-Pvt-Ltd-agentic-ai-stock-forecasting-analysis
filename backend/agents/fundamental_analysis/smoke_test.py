"""Wiring smoke test for the Fundamental Analysis Agent's state graph.

The "invalid input" case needs no database. The other two exercise
fetch_fundamentals_data for real, so they need a Postgres instance with
backend/db/schema.sql applied and, for the DEMO ticker, the sample data
from backend/db/seed_fundamentals.py loaded:

    python backend/db/seed_fundamentals.py
    python -m agents.fundamental_analysis.smoke_test   # from the backend/ directory

Without a reachable database, the fetch retries and then routes to
build_error_response with a "database connection failed" reason — the
graph's control flow still runs end to end, it just can't reach the
compute_*/aggregate_composite_signal path.
"""

from .graph import build_graph

graph = build_graph()


def run(label, request):
    result = graph.invoke(request)
    print(f"--- {label} ---")
    print(result["final_output"])
    print()


if __name__ == "__main__":
    run("invalid input", {"ticker": "", "ratio_basis": "TTM", "lookback_years": 5})

