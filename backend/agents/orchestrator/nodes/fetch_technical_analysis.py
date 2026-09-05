"""fetch_technical_analysis — baseline analysis node.

Invokes the Technical Analysis Agent for the requested ticker/horizon.
Runs independently of fetch_fundamental_analysis and
fetch_sentiment_analysis -- all three fan out from validate_input and join
at reconcile_and_decide (see graph.py) -- so this must not depend on
either of their results.
"""

from ._pillar_runners import run_technical


def fetch_technical_analysis(state):
    result, status, error = run_technical(state)
    return {
        "technical_analysis": result,
        "pillar_status": {"technical": status},
        "errors": {"technical": error},
    }
