"""Smoke test for the Orchestrator Subgraph: one ticker across the three horizons,
plus a forecast and the invalid-input path.

Needs Postgres with price history and fundamentals seeded for the ticker (see
the README's Seeding data), and the orchestrator_runs table (persist_run
writes to it on every run). Without a reachable LLM, reconciliation and the
forecast fall back to the weighted verdict and the volatility baseline, so it
still runs end to end.

    python -m agents.orchestrator.smoke_test   # from the backend/ directory
"""

from .graph import build_graph

TICKER = "RELIANCE.NS"

graph = build_graph()


def run(label, request):
    result = graph.invoke(request)
    response = result.get("final_response") or result.get("error_response") or {}
    verdict = response.get("verdict") or {}
    forecast = response.get("price_forecast") or {}
    print(f"--- {label} ---")
    print("planned:", response.get("planned_pillars"), "| status:", result.get("pillar_status"))
    print("verdict:", verdict.get("direction"), "/", verdict.get("confidence"),
          "| drivers:", verdict.get("key_drivers"), "| conflicts:", verdict.get("conflicts"))
    print("narrative:", response.get("narrative") or response.get("reason"))
    if forecast:
        print("forecast:", {k: forecast.get(k) for k in ("method", "expected_price_low", "expected_price_high", "confidence")})
    print()


if __name__ == "__main__":
    run("short term", {"ticker": TICKER, "horizon": "short_term"})
    run("medium term, 30-day forecast", {"ticker": TICKER, "forecast_days": 30})
    run("long term", {"ticker": TICKER, "horizon": "long_term"})
    run("invalid input", {"ticker": ""})
