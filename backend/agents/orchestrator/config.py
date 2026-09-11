"""Tunable constants for the Orchestrator Subgraph.

The specification's "Technical Specifications" section names five
configurable parameters (MAX_TOOL_LOOPS, ANALYSIS_HORIZON,
ENABLED_RERUN_TOOLS, TOOL_CALL_TIMEOUT, HUMAN_REVIEW_TIMEOUT) but states
"No numeric defaults for these parameters are defined in the supplied
architecture diagram; they should be provided through deployment
configuration." All five are read from the environment below, falling
back to this implementation's own default (chosen for a reasonable
local/dev setup, not a value taken from the specification itself) when
unset.

The LLM provider settings (OLLAMA_*/OPENROUTER_*/LLM_*) aren't named in
the specification, but are exactly as deployment-specific -- different
environments point at different endpoints/models/keys -- so they're
sourced from the environment too. OPENROUTER_API_KEY in particular must
never be hardcoded here: it defaults to "" and is required only when
LLM_PROVIDER=openrouter actually sends a request (see
llm_client._call_openrouter_chat, which raises a clear error instead of
sending an unauthenticated request if it's unset).
"""

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

MAX_TOOL_LOOPS = _env_int("MAX_TOOL_LOOPS", 3)

ENABLED_RERUN_TOOLS = _env_tuple("ENABLED_RERUN_TOOLS", ("rerun_technical", "rerun_fundamental"))

# --- execute_tool_call ---
TOOL_CALL_TIMEOUT_SECONDS = _env_int("TOOL_CALL_TIMEOUT_SECONDS", 30)

HUMAN_REVIEW_TIMEOUT_SECONDS = _env_int("HUMAN_REVIEW_TIMEOUT_SECONDS", 3600)

OLLAMA_BASE_URL = _env_str("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env_str("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = _env_int("OLLAMA_TIMEOUT_SECONDS", 120)

OPENROUTER_BASE_URL = _env_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")  # required only when LLM_PROVIDER=openrouter
# google/gemma-4-31b-it:free -- OpenRouter's free-tier slug for "Google:
# Gemma 4 31B (free)", per explicit direction to use that model with a
# fallback to Ollama (see LLM_PROVIDER_FALLBACK_ENABLED below) rather than
# a paid model.
OPENROUTER_MODEL = _env_str("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
OPENROUTER_TIMEOUT_SECONDS = _env_int("OPENROUTER_TIMEOUT_SECONDS", 60)

# OpenRouter is the hard default; set LLM_PROVIDER=ollama in the environment
# to make Ollama the primary provider instead (LLM_PROVIDER_FALLBACK_ENABLED
# below still applies in either direction).
LLM_PROVIDER = _env_str("LLM_PROVIDER", "openrouter")

# When True (default), call_llm_chat() automatically retries against the
# *other* provider (Ollama <-> OpenRouter) if LLM_PROVIDER's own call
# raises -- e.g. OpenRouter's free-tier daily rate limit, or a paid model
# with no credits -- before giving up. This is a distinct, cheaper-to-hit
# safety net from LLM_FALLBACK_ENABLED below: that one is the *last*
# resort (a deterministic non-LLM rule) reached only once *both*
# providers have failed. Set to False to fail over to the deterministic
# fallback immediately on the primary provider's first error, without
# trying the secondary provider at all.
LLM_PROVIDER_FALLBACK_ENABLED = _env_bool("LLM_PROVIDER_FALLBACK_ENABLED", True)

LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.1)  # low: structured routing decision, not creative writing

LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)

FORECAST_DISCLAIMER = (
    "This is a qualitative estimate reasoned by an LLM Agent from existing technical, fundamental, and "
    "sentiment signals. It is not a statistically validated or trained forecasting model and should not "
    "be the sole basis for an investment decision."
)
