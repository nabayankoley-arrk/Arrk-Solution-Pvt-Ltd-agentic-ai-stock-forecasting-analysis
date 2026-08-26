"""Fundamental Analysis Agent.

See docs/fundamental-analysis-design.md for the full design rationale.
`build_graph()` in `graph.py` assembles the compiled LangGraph state graph.
"""

from .graph import build_graph

__all__ = ["build_graph"]