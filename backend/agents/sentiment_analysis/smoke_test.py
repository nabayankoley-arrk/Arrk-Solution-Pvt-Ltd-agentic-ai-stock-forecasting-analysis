"""Wiring smoke test for the Sentiment Analysis Agent's state graph.

The "invalid input" case needs no database. The other case exercises
fetch_transcript/fetch_annual_report for real, so it needs a Postgres
instance with backend/db/schema.sql applied and at least one row in
document_summaries for the ticker under test -- see
backend/jobs/README.md to populate it (python -m jobs.summarise_reports).

Without a reachable database, both fetches retry and then report
"error"/"unavailable" for that source -- the graph's control flow still
runs end to end and reaches build_success_response with direction=None
rather than failing, since an unavailable source is not this subgraph's
error path (see nodes/build_error_response.py).

    python -m agents.sentiment_analysis.smoke_test   # from the backend/ directory
"""

from .graph import build_graph

graph = build_graph()


def run(label, request):
    result = graph.invoke(request)
    print(f"--- {label} ---")
    print(result["final_output"])
    print()


if __name__ == "__main__":
    # run("invalid input", {"ticker": ""})
    run("INFY", {"ticker": "HDFCBANK.NS"})
