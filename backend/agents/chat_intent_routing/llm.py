"""The chat agent's tool-calling chat model.

OpenRouter, OpenAI and Ollama all expose an OpenAI-compatible
/chat/completions endpoint, so one ChatOpenAI client covers them, configured
from the same settings as agents/orchestrator/config.py (LLM_PROVIDER,
OPENROUTER_*, OPENAI_*, OLLAMA_*, LLM_TEMPERATURE). Tool calling needs a
model that supports it: all current OpenAI chat models do; OpenRouter lists it
per model ("tools" in supported_parameters); small local models are weak at it. TLS goes through Python's ssl module, which bootstrap.py points at the
OS trust store.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from agents.orchestrator import config as llm_config


@lru_cache(maxsize=1)
def chat_model():
    hosted = llm_config.hosted_provider()  # OpenRouter or OpenAI
    if hosted:
        if not hosted["api_key"]:
            raise RuntimeError(f"{hosted['key_name']} is not set (required when LLM_PROVIDER={llm_config.LLM_PROVIDER})")
        return ChatOpenAI(
            model=hosted["model"],
            base_url=hosted["base_url"],
            api_key=hosted["api_key"],
            **llm_config.model_params(),  # temperature, or reasoning_effort for reasoning models
            timeout=hosted["timeout"],
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
