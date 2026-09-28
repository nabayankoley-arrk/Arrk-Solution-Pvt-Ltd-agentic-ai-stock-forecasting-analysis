"""Tunable constants for the Sentiment Analysis Agent (transcript + annual report only).

The specification's "Technical Specifications" section states "No numeric
defaults are fixed here; provide them through deployment configuration,
consistent with the Orchestrator's and Chat Intent Router's own
parameters" -- so, like those two, every value below is read from the
environment with a locally-reasonable fallback, not a number taken from
the specification itself.

NEWS_INGESTION_INTERVAL / COVERAGE_INGESTION_INTERVAL /
TRANSCRIPT_INGESTION_TRIGGER aren't here -- ingestion scheduling belongs
to jobs/summarise_reports.py (run manually, per that job's own README),
not to this request-time subgraph. NEWS_LOOKBACK_DAYS and SOURCE_WEIGHTS'
"news" entry are likewise absent: see __init__.py for why news is out of
scope.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import os


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _env_float(name, default):
    value = os.environ.get(name)
    return float(value) if value else default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- fetch_transcript / fetch_annual_report ---
# Transcripts follow the specification's own ~6-month figure. Annual
# reports are filed once a year, so a 6-month window would routinely
# reject a company's only current report the moment it's half a year
# old; widened so "the latest annual report" stays available across a
# full filing cycle plus slack for late filers.
TRANSCRIPT_LOOKBACK_MONTHS = _env_int("SENTIMENT_TRANSCRIPT_LOOKBACK_MONTHS", 6)
ANNUAL_REPORT_LOOKBACK_MONTHS = _env_int("SENTIMENT_ANNUAL_REPORT_LOOKBACK_MONTHS", 15)

# --- score_transcript / score_annual_report: rebuild a missing or outdated profile at request time ---
RESCORE_ON_CACHE_MISS = _env_bool("SENTIMENT_RESCORE_ON_CACHE_MISS", True)

# --- combine_sentiment_signals ---
SOURCE_WEIGHTS = {
    "transcript": _env_float("SENTIMENT_WEIGHT_TRANSCRIPT", 0.5),
    "annual_report": _env_float("SENTIMENT_WEIGHT_ANNUAL_REPORT", 0.5),
}

# Halves a source's vote weight every RECENCY_HALF_LIFE_DAYS of document
# age -- the specification's "RECENCY_DECAY -- Decay function that
# discounts older documents within the lookback window", implemented as
# a half-life rather than a hard cutoff so a slightly stale document
# still counts, just for less.
RECENCY_HALF_LIFE_DAYS = _env_int("SENTIMENT_RECENCY_HALF_LIFE_DAYS", 180)

# Matches agents/fundamental_analysis/config.py's aggregate_composite_signal
# neutral band -- same -1..+1 weighted-vote shape, same convention.
NEUTRAL_BAND = _env_float("SENTIMENT_NEUTRAL_BAND", 0.15)
