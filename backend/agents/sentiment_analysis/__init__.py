"""Sentiment Analysis Agent: sentiment from a company's annual report and call transcript.

Reads document_summaries, which jobs/summarise_reports.py fills with one
summary per filing. For one ticker, the latest stored transcript and annual
report are fetched and each is given a sentiment profile -- overall label,
management tone, guidance, per-theme stances, positives, concerns and quotes
(prompts.py, profile.py) -- built once from the stored summary with one LLM
call and cached on the row. The two labels are combined into one
recency-weighted direction (graph.py).

News and third-party coverage reports are not ingested, so they are not
sources here. A ticker with no stored filing reports that source as
"unavailable".

Import the graph from .graph (agents/orchestrator/nodes/_pillar_runners does);
this package deliberately does not build it on import.
"""
