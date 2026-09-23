"""fetch_sentiment_analysis — baseline analysis node.

Invokes the real agents/sentiment_analysis subgraph (transcript + annual
report sources -- see that package's own docstring) via
_pillar_runners.run_sentiment, exposing the same (result, pillar_status,
errors) shape fetch_technical_analysis/fetch_fundamental_analysis already
use. Kept as a thin wrapper deliberately: this node never changes when
the subgraph behind run_sentiment does.
"""

from ._pillar_runners import run_sentiment


def fetch_sentiment_analysis(state):
    result, status, error = run_sentiment(state)
    return {
        "sentiment_analysis": result,
        "pillar_status": {"sentiment": status},
        "errors": {"sentiment": error},
    }
