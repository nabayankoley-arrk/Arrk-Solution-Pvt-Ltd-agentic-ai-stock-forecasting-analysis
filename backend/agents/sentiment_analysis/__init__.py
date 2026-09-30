"""Sentiment Analysis Agent: sentiment from a company's annual report, call transcript and recent news.

Reads document_summaries, which jobs/summarise_reports.py fills with one
summary per filing. For one ticker, the latest stored transcript and annual
report are fetched and each is given a sentiment profile -- overall label,
management tone, guidance, per-theme stances, positives, concerns and quotes
(prompts.py, profile.py) -- built once from the stored summary with one LLM
call and cached on the row.

Recent news is the third source. It is never ingested or stored: on each
request it is searched live (nodes/fetch_news.py, via agents/web_search.py)
and given a profile of the same shape with one LLM call (nodes/score_news.py).

The three labels are combined into one recency-weighted direction (graph.py).
A ticker with no stored filing, or no recent news found, reports that source
as "unavailable"; third-party coverage reports are not a source.

Import the graph from .graph (agents/orchestrator/nodes/_pillar_runners does);
this package deliberately does not build it on import.
"""
