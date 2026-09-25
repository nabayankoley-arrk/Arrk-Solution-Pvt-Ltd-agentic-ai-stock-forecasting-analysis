"""The chat agent's tool-calling chat model.

Both providers expose an OpenAI-compatible /chat/completions endpoint, so one
ChatOpenAI client covers them, configured from the same settings as
agents/orchestrator/config.py (LLM_PROVIDER, OPENROUTER_*, OLLAMA_*,
LLM_TEMPERATURE). Tool calling needs a model that supports it: OpenRouter lists
this per model ("tools" in supported_parameters); small local models are weak
at it. TLS goes through Python's ssl module, which bootstrap.py points at the
OS trust store.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from agents.orchestrator import config as llm_config


@lru_cache(maxsize=1)
def chat_model():
    if llm_config.LLM_PROVIDER == "openrouter":
        if not llm_config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set (required when LLM_PROVIDER=openrouter)")
        return ChatOpenAI(
            model=llm_config.OPENROUTER_MODEL,
            base_url=llm_config.OPENROUTER_BASE_URL,
            api_key=llm_config.OPENROUTER_API_KEY,
            temperature=llm_config.LLM_TEMPERATURE,
            timeout=llm_config.OPENROUTER_TIMEOUT_SECONDS,
            max_retries=1,
        )
    if llm_config.LLM_PROVIDER == "ollama":
        return ChatOpenAI(
            model=llm_config.OLLAMA_MODEL,
            base_url=f"{llm_config.OLLAMA_BASE_URL}/v1",
            api_key="ollama",  # required by the client, ignored by Ollama
            temperature=llm_config.LLM_TEMPERATURE,
            timeout=llm_config.OLLAMA_TIMEOUT_SECONDS,
            max_retries=1,
        )
    raise ValueError(f"unknown LLM_PROVIDER: {llm_config.LLM_PROVIDER!r}")
