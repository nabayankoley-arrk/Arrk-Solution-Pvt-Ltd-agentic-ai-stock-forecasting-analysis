"""The sentiment analysis prompt: one stored filing summary -> its sentiment profile.

Annual reports and call transcripts share one profile schema and one vocabulary
below; only the rules for `label` and `management_tone` differ by document
type. The summaries themselves are written by ingestion/summarise.py's own
prompts (jobs/summarise_reports.py), which are separate from this.

Bump PROMPT_VERSION on any edit here: stored profiles carry the version they
were built with, and a mismatch makes them be rebuilt on the next request.
"""

import json

PROMPT_VERSION = "v2"

DOCUMENT_TYPES = {
    "AR": "annual report",
    "TR": "earnings or AGM call transcript",
}

# Overall read of a document, for the company's direction. Also the pillar's
# vote in combine_sentiment_signals.
LABELS = ("bullish", "neutral", "bearish")

# How management came across -- in a transcript, on the call; in an annual
# report, in the chairman's letter and management discussion.
MANAGEMENT_TONES = ("confident", "cautious", "defensive")

GUIDANCE = ("raised", "maintained", "lowered", "withdrawn", "not_given")

THEMES = (
    "financial_performance",
    "demand_and_growth",
    "margins_and_costs",
    "guidance_and_outlook",
    "capital_allocation",
    "balance_sheet_and_cash",
    "risks_and_headwinds",
    "governance_and_management",
)

STANCES = ("positive", "neutral", "negative")


def _one_of(values):
    return " | ".join(json.dumps(v) for v in values)


_SCHEMA = (
    "{\n"
    f'  "label": {_one_of(LABELS)},\n'
    f'  "management_tone": {_one_of(MANAGEMENT_TONES)} | null,\n'
    f'  "guidance": {_one_of(GUIDANCE)},\n'
    '  "rationale": "two sentences: what in the summary drove the label",\n'
    f'  "themes": [{{"theme": one of THEMES, "stance": {_one_of(STANCES)}, '
    '"point": "one sentence, with the figure or wording from the summary"}],\n'
    '  "positives": ["up to three short points"],\n'
    '  "concerns": ["up to three short points"],\n'
    '  "notable_quotes": ["verbatim quotes copied from the summary"]\n'
    "}"
)

_TYPE_RULES = {
    "AR": """- "label" judges the business's direction as the report presents it. The \
fundamental analysis already scores the reported financials, so weigh outlook, \
strategy, capital allocation and newly prominent risks more than the headline \
figures. Upbeat wording without concrete support is "neutral".
- "management_tone" is how the chairman's letter and management discussion come \
across.""",
    "TR": """- "label" judges the business's direction as management presented it on the \
call, including how the analysts' main concerns were answered.
- "management_tone" is how management came across on the call: "confident" \
(assured, little hedging), "cautious" (flags uncertainty, measured about risks), \
"defensive" (explains away weak results, deflects, hedges where confidence would \
be expected).""",
}


def profile_prompt(report_type):
    """System prompt: one stored summary -> one JSON sentiment profile."""
    return (
        f"You read the summary of one {DOCUMENT_TYPES[report_type]} of an Indian listed company "
        "and produce its sentiment profile.\n\n"
        f"Respond with ONLY one JSON object, no other text:\n{_SCHEMA}\n\n"
        f"THEMES: {', '.join(THEMES)}.\n\n"
        "Rules:\n"
        f"{_TYPE_RULES[report_type]}\n"
        '- "management_tone" is null when the summary does not show how management came across; '
        "do not guess it from the figures.\n"
        '- "guidance" is "not_given" unless the summary says guidance was given; "raised" or '
        '"lowered" only when it says guidance changed.\n'
        "- Include a theme only if the summary covers it; one entry per theme.\n"
        '- "notable_quotes" must be copied exactly from the summary; use [] if it has none.\n'
        "- Base everything only on the summary. Never infer beyond it or invent figures."
    )


def profile_user_prompt(report_type, company, report_name, filed_on, summary):
    return (
        f"Company: {company or 'unknown'}\n"
        f"Document: {report_name or '(untitled)'} ({DOCUMENT_TYPES[report_type]})\n"
        f"Filed: {filed_on or 'unknown'}\n\n"
        f"Summary:\n{summary or ''}"
    )
