"""Tunable constants for the Orchestrator Subgraph.

Every value is read from the environment, falling back to the default below.
There is no human-review timeout: pillar disagreement is reported in the
verdict's conflicts rather than paused on (see nodes/_verdict.py).

The LLM provider settings (OLLAMA_*/OPENROUTER_*/LLM_*) aren't named in
the specification, but are exactly as deployment-specific -- different
environments point at different endpoints/models/keys -- so they're
sourced from the environment too. OPENROUTER_API_KEY in particular must
never be hardcoded here: it defaults to "" and is required only when
LLM_PROVIDER=openrouter actually sends a request (see
llm_client._call_openrouter_chat, which raises a clear error instead of
sending an unauthenticated request if it's unset).
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import os


def _env_str(name, default):
    return os.environ.get(name) or default


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


def _env_tuple(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


VALID_HORIZONS = ("short_term", "medium_term", "long_term")

DEFAULT_HORIZON = _env_str("ANALYSIS_HORIZON", "medium_term")
if DEFAULT_HORIZON not in VALID_HORIZONS:
    raise ValueError(f"ANALYSIS_HORIZON must be one of {VALID_HORIZONS}, got {DEFAULT_HORIZON!r}")

HORIZON_TO_PILLAR_PARAMS = {
    "short_term": {"lookback_days": 90, "ratio_basis": "MRQ", "lookback_years": 2},
    "medium_term": {"lookback_days": 250, "ratio_basis": "TTM", "lookback_years": 5},
    "long_term": {"lookback_days": 500, "ratio_basis": "TTM", "lookback_years": 7},
}

# --- plan_analysis: which pillars run for a horizon, and how much each counts ---
# Short term is price action: fundamentals barely move a price over days to
# weeks, so that pillar is skipped. Long term is the business: technicals keep
# a small say (the primary trend), fundamentals lead.
HORIZON_PLAN = {
    "short_term": {"technical": 0.7, "sentiment": 0.3},
    "medium_term": {"technical": 0.4, "fundamental": 0.35, "sentiment": 0.25},
    "long_term": {"technical": 0.15, "fundamental": 0.6, "sentiment": 0.25},
}

# What each horizon means for the reconciliation prompt (llm_client.py).
HORIZON_GUIDANCE = {
    "short_term": "days to a few weeks: price action, momentum, support/resistance and recent "
                  "management commentary matter most; fundamentals are not considered.",
    "medium_term": "a few months: trend and momentum, earnings quality and valuation, and "
                   "management's outlook all matter.",
    "long_term": "a year or more: business quality, growth, balance sheet and valuation lead; "
                 "technicals only show the primary trend.",
}

# forecast_days -> horizon, when a caller asks for a forecast without a horizon.
SHORT_TERM_MAX_DAYS = _env_int("SHORT_TERM_MAX_DAYS", 14)
MEDIUM_TERM_MAX_DAYS = _env_int("MEDIUM_TERM_MAX_DAYS", 120)


def horizon_for_days(days):
    if days <= SHORT_TERM_MAX_DAYS:
        return "short_term"
    return "medium_term" if days <= MEDIUM_TERM_MAX_DAYS else "long_term"


# --- the verdict (nodes/_verdict.py) ---
# A weighted direction score within +/- this band reads as neutral.
VERDICT_NEUTRAL_BAND = _env_float("VERDICT_NEUTRAL_BAND", 0.2)
# Confidence is "low" when pillars carrying at least this share of the available
# weight point against the verdict; a smaller dissent only makes it "medium".
VERDICT_LOW_CONFIDENCE_OPPOSITION = _env_float("VERDICT_LOW_CONFIDENCE_OPPOSITION", 0.35)

MAX_TOOL_LOOPS = _env_int("MAX_TOOL_LOOPS", 3)

ENABLED_RERUN_TOOLS = _env_tuple(
    "ENABLED_RERUN_TOOLS", ("rerun_technical", "rerun_fundamental", "rerun_sentiment")
)

# --- execute_tool_call ---
TOOL_CALL_TIMEOUT_SECONDS = _env_int("TOOL_CALL_TIMEOUT_SECONDS", 30)

OLLAMA_BASE_URL = _env_str("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env_str("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = _env_int("OLLAMA_TIMEOUT_SECONDS", 120)

OPENROUTER_BASE_URL = _env_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")  # required only when LLM_PROVIDER=openrouter
OPENROUTER_MODEL = _env_str("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-fin:free")
OPENROUTER_TIMEOUT_SECONDS = _env_int("OPENROUTER_TIMEOUT_SECONDS", 60)

OPENAI_BASE_URL = _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # required only when LLM_PROVIDER=openai
OPENAI_MODEL = _env_str("OPENAI_MODEL", "gpt-5.6-sol")
OPENAI_TIMEOUT_SECONDS = _env_int("OPENAI_TIMEOUT_SECONDS", 60)

# openai (default) | openrouter | ollama (local/offline).
LLM_PROVIDER = _env_str("LLM_PROVIDER", "openai")
PROVIDERS = ("openrouter", "openai", "ollama")


def hosted_provider():
    """The active OpenAI-compatible hosted provider as
    {"base_url", "api_key", "model", "timeout", "key_name"}, or None for Ollama.
    OpenRouter and OpenAI share one request format, so every caller builds the
    same /chat/completions request from this."""
    if LLM_PROVIDER == "openrouter":
        return {"base_url": OPENROUTER_BASE_URL, "api_key": OPENROUTER_API_KEY, "model": OPENROUTER_MODEL,
                "timeout": OPENROUTER_TIMEOUT_SECONDS, "key_name": "OPENROUTER_API_KEY"}
    if LLM_PROVIDER == "openai":
        return {"base_url": OPENAI_BASE_URL, "api_key": OPENAI_API_KEY, "model": OPENAI_MODEL,
                "timeout": OPENAI_TIMEOUT_SECONDS, "key_name": "OPENAI_API_KEY"}
    return None


def active_model():
    """The model name in use, for logs and for recording which model built a result."""
    hosted = hosted_provider()
    return hosted["model"] if hosted else OLLAMA_MODEL


# OpenAI's reasoning models (GPT-5 and later, o-series) reject any temperature
# but the default, and on the gpt-5.6 models function tools in
# /chat/completions need reasoning_effort="none". They get reasoning_effort
# (OPENAI_REASONING_EFFORT; "none" = no hidden reasoning step, fastest) and no
# temperature; older chat models (gpt-4o, gpt-4.1) keep LLM_TEMPERATURE.
REASONING_MODEL_PREFIXES = _env_tuple("REASONING_MODEL_PREFIXES", ("gpt-5", "gpt-6", "o1", "o3", "o4"))
OPENAI_REASONING_EFFORT = _env_str("OPENAI_REASONING_EFFORT", "none")


def model_params():
    """Sampling parameters for a hosted request to the active model."""
    if LLM_PROVIDER == "openai" and active_model().startswith(REASONING_MODEL_PREFIXES):
        return {"reasoning_effort": OPENAI_REASONING_EFFORT} if OPENAI_REASONING_EFFORT else {}
    return {"temperature": LLM_TEMPERATURE}

LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.1)  # low: structured routing decision, not creative writing

LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)

# --- forecast_price_range: the volatility baseline the LLM's range is anchored on ---
# Baseline = centre * exp(+/- FORECAST_SIGMA_MULTIPLIER * sigma * sqrt(trading days)),
# sigma being the daily return volatility; 1.0 is roughly a 68% range.
FORECAST_SIGMA_MULTIPLIER = _env_float("FORECAST_SIGMA_MULTIPLIER", 1.0)
TRADING_DAYS_PER_YEAR = 252
# How far the verdict may shift the baseline's centre, as a share of its half-width.
FORECAST_TILT = _env_float("FORECAST_TILT", 0.3)
# Short-term forecasts (up to SHORT_TERM_MAX_DAYS) are not shifted at all: their
# verdict is 70% the technical signal, which showed no directional edge in the
# backtest (jobs/backtest_forecasts.py: ~48% right vs ~50% by chance), and
# shifting toward it lowered the range's hit rate. Set True to shift them again.
FORECAST_TILT_SHORT_TERM = _env_bool("FORECAST_TILT_SHORT_TERM", False)
# The LLM's range must lie within this many baseline half-widths of the centre.
FORECAST_MAX_BAND_MULTIPLE = _env_float("FORECAST_MAX_BAND_MULTIPLE", 2.0)
# Beyond this, a price range says nothing useful: no range is given.
FORECAST_MAX_DAYS = _env_int("FORECAST_MAX_DAYS", 730)
# From this horizon, the centre moves toward the analysts' average (12-month)
# target -- up to FORECAST_ANALYST_MAX_PULL of the way at a year -- when at
# least FORECAST_ANALYST_MIN_COUNT analysts cover the stock.
FORECAST_ANALYST_FROM_DAYS = _env_int("FORECAST_ANALYST_FROM_DAYS", 180)
FORECAST_ANALYST_MAX_PULL = _env_float("FORECAST_ANALYST_MAX_PULL", 0.5)
FORECAST_ANALYST_MIN_COUNT = _env_int("FORECAST_ANALYST_MIN_COUNT", 5)

FORECAST_DISCLAIMER = (
    "This is a qualitative estimate reasoned by an LLM Agent from existing technical, fundamental, and "
    "sentiment signals. It is not a statistically validated or trained forecasting model and should not "
    "be the sole basis for an investment decision."
)
