"""handle_out_of_scope — non-stock-market intent handler.

Every intent other than 'stock_market' (see parse_and_route.py's
docstring) reaches here. This application answers stock/market analysis
questions only -- it never routes a non-stock question to the Orchestrator
Subgraph, and it never generates an answer for one either. This node makes
no LLM call and returns the same fixed refusal (config.OUT_OF_SCOPE_MESSAGE)
for every out-of-scope query, regardless of topic, so no unrelated,
un-vetted, or potentially sensitive content (legal, medical, or otherwise)
is ever produced by this path.
"""

from ..config import OUT_OF_SCOPE_MESSAGE


def handle_out_of_scope(state):
    return {"orchestrator_result": None, "response": {"message": OUT_OF_SCOPE_MESSAGE}}
