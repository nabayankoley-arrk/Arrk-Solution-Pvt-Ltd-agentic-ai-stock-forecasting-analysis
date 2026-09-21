"""fetch_fundamental_analysis — baseline analysis node.

Invokes the Fundamental Analysis Agent for the requested ticker/horizon.
Resolves its own current_price independently (see _current_price.py)
rather than waiting on fetch_technical_analysis, since the three baseline
passes run in parallel and join at reconcile_and_decide (see graph.py).
"""

from ._pillar_runners import run_fundamental


def fetch_fundamental_analysis(state):
    result, status, error = run_fundamental(state)
    return {
        "fundamental_analysis": result,
        "pillar_status": {"fundamental": status},
        "errors": {"fundamental": error},
    }
