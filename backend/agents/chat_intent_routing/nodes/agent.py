"""agent — the chat LLM, with tools.

Each turn it reads the conversation so far and either answers or calls
analyze_stock (see tools.py); after the tool results come back it runs again,
and so on until it answers without a tool call. So one node interprets the
question, decides whether an analysis is needed, and writes the reply.

History is trimmed to the last config.MAX_HISTORY_MESSAGES messages, starting on
a user message so a tool call is never separated from its result. After
config.MAX_TOOL_ROUNDS rounds of tool calls in one turn, tools are disabled
(tool_choice="none") so the model has to answer with what it has.

If the LLM call fails, the reply falls back to the fixed template for any
analysis already finished this turn, else to config.UNAVAILABLE_REPLY.
"""

from langchain_core.messages import AIMessage, SystemMessage, trim_messages

from .. import config
from ..llm import chat_model
from ..reply import format_analysis_reply
from ._ticker_lookup import tracked_companies
from .tools import TOOLS

_SYSTEM_PROMPT = """You are the chat assistant of a stock-analysis app for Indian listed companies.

Tracked companies (the only ones that can be analysed):
{companies}

Company currently under discussion: {current_ticker}

- For any outlook, trend, valuation, forecast, buy/sell view or figure about a tracked company, \
call analyze_stock. Never state prices, signals or figures that did not come from an \
analyze_stock result in this conversation. You may reuse an earlier result from this \
conversation unless the user asks for a fresh view.
- Resolve follow-ups ("what about its valuation?", "and Infosys?") from the conversation and the \
company under discussion. To compare companies, call analyze_stock once per company.
- If the company is unclear or not tracked, ask which one, naming a few tracked companies.
- If the message is not about stocks, markets, companies or investing, reply in one polite \
sentence that you only help with stock and market questions.
- Keep answers short: lead with what was asked, then the overall signal. Say plainly when a \
pillar (technical, fundamental, sentiment) was unavailable. This is information, not \
personalised investment advice."""


def _system_prompt(state):
    companies = tracked_companies()
    listed = "\n".join(f"- {t}: {n}" for t, n in companies) or "(list unavailable right now; use NSE tickers such as TCS.NS)"
    return _SYSTEM_PROMPT.format(companies=listed, current_ticker=state.get("current_ticker") or "none yet")


def _fallback_reply(state):
    finished = [
        a["response"] for a in state.get("analyses") or []
        if a.get("orchestrator_result") and a["orchestrator_result"].get("final_response")
    ]
    return format_analysis_reply(finished[-1]) if finished else config.UNAVAILABLE_REPLY


def agent(state):
    history = trim_messages(
        state.get("messages") or [],
        strategy="last",
        token_counter=len,
        max_tokens=config.MAX_HISTORY_MESSAGES,
        start_on="human",
        allow_partial=False,
    )
    tool_choice = None if (state.get("tool_rounds") or 0) < config.MAX_TOOL_ROUNDS else "none"
    try:
        model = chat_model().bind_tools(TOOLS, tool_choice=tool_choice)
        message = model.invoke([SystemMessage(_system_prompt(state)), *history])
    except Exception as exc:
        print(f"[chat] agent LLM call failed: {type(exc).__name__}: {exc}", flush=True)
        fallback = _fallback_reply(state)
        return {"messages": [AIMessage(fallback)], "action": None if fallback != config.UNAVAILABLE_REPLY else "error"}
    return {"messages": [message]}
