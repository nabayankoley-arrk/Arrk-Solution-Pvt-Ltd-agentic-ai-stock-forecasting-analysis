"""Orchestrator Subgraph.

Coordinates Technical, Fundamental, and Sentiment Analysis and uses an LLM
Agent to reconcile their outputs, deciding whether to finalize or rerun a
specific pillar for more information. Implements the Orchestrator Subgraph
specification shared by the lead: validate -> parallel baseline analysis
-> LLM-driven reconcile/decide -> optional tool rerun loop -> optional
human review -> final response. `build_graph()` in `graph.py` assembles
the compiled LangGraph state graph.
"""

from .graph import build_graph

__all__ = ["build_graph"]
