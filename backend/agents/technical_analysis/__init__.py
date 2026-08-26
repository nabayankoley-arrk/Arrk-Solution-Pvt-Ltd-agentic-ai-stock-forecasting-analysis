"""Technical Analysis Agent.

Deterministic, rule-based subgraph (zero LLM calls) that turns
`price_history` OHLCV data into a technical market outlook and, if a
validated setup exists, a trade setup (entry/stop-loss/target/RRR).
`build_graph()` in `graph.py` assembles the compiled LangGraph state graph.
"""

from .graph import build_graph

__all__ = ["build_graph"]
