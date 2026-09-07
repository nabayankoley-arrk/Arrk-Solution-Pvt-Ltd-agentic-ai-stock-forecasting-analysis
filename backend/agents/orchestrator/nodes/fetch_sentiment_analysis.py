"""fetch_sentiment_analysis — baseline analysis node.

Sentiment Analysis is treated as a baseline interface, not yet a real
subgraph (see the specification's Architecture section). This exposes the
agreed (result, pillar_status, errors) shape without changing the
orchestrator's state contract, so wiring in the real subgraph later only
touches _pillar_runners.run_sentiment.
"""

from ._pillar_runners import run_sentiment


def fetch_sentiment_analysis(state):
    result, status, error = run_sentiment(state)
    return {
        "sentiment_analysis": result,
        "pillar_status": {"sentiment": status},
        "errors": {"sentiment": error},
    }
