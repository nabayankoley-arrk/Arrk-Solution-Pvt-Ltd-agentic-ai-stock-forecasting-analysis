"""The four tools parse_and_route may select, per the specification's
"Tools" section. Plain functions dispatched from execute_tool_call.py's
own dict -- same convention as the Orchestrator Subgraph's
execute_tool_call.py, which frames selected_tool -> tool dispatch as
internal branching within one "Tool Execution" step, not as separate
LangGraph nodes.

None of these tools independently decide the routing outcome -- each
returns its result to parse_and_route (via execute_tool_call), which
alone remains the one decision-making component in this subgraph.
"""

import difflib
import re
import uuid

import psycopg2
from langgraph.types import Command

from db.connection import get_connection

from ..orchestrator.config import HORIZON_TO_PILLAR_PARAMS
from ..orchestrator.graph import build_graph as build_orchestrator_graph
from ..orchestrator.nodes._pillar_runners import run_fundamental, run_sentiment, run_technical
from .config import TICKER_MATCH_CONFIDENCE_THRESHOLD, VALID_PILLARS
from .llm_client import answer_general_question as _answer_general_question_llm

_orchestrator_graph = build_orchestrator_graph()

_PILLAR_RUNNERS = {
    "technical": run_technical,
    "fundamental": run_fundamental,
    "sentiment": run_sentiment,
}


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.&-]*")


def lookup_ticker(candidate_name):
    """Fuzzy-matches candidate_name against the tracked universe (the
    `universe` table's ticker and company_name columns). Returns a
    matched ticker, no match, or an ambiguous list, per the specification.

    Uses difflib (standard library) rather than a new fuzzy-matching
    dependency -- adequate for matching a short company name/ticker
    string against a bounded universe table.

    candidate_name is not always a clean, already-extracted name --
    execute_tool_call.py falls back to the raw chat message itself when
    parse_and_route's LLM didn't populate tool_call_args["candidate_name"]
    (observed with smaller/local models: see that module's docstring).
    Scoring the *whole* candidate_name string against a short ticker/
    company_name would score poorly for a full sentence even when it
    contains the ticker verbatim, so this checks for a known ticker
    appearing as a whole word/token in candidate_name first, then falls
    back to per-token fuzzy matching (a token against company_name/
    ticker, not the whole string) before finally trying the whole string
    -- covering "INFY.NS", "how is INFY.NS looking?", and "how's infosys
    doing?" alike.
    """
    if not candidate_name or not isinstance(candidate_name, str):
        return {"match": None, "confidence": 0.0, "ambiguous": [], "candidates": []}

    try:
        conn = get_connection()
    except psycopg2.OperationalError as exc:
        return {"match": None, "confidence": 0.0, "ambiguous": [], "candidates": [], "error": str(exc)}

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, company_name FROM universe")
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        return {"match": None, "confidence": 0.0, "ambiguous": [], "candidates": [], "error": str(exc)}
    finally:
        conn.close()

    if not rows:
        return {"match": None, "confidence": 0.0, "ambiguous": [], "candidates": []}

    stripped = candidate_name.strip()
    tokens = _WORD_RE.findall(stripped) or [stripped]
    tokens_lower = {t.lower() for t in tokens}

    # 1. A known ticker appearing verbatim as a whole word/token --
    # highest-confidence signal available, and the common case for
    # "INFY.NS" or "...about INFY.NS?" alike.
    exact_ticker_hits = [ticker for ticker, _ in rows if ticker and ticker.lower() in tokens_lower]
    if len(exact_ticker_hits) == 1:
        return {"match": exact_ticker_hits[0], "confidence": 1.0, "ambiguous": [], "candidates": []}
    if len(exact_ticker_hits) > 1:
        return {"match": None, "confidence": 1.0, "ambiguous": exact_ticker_hits, "candidates": exact_ticker_hits}

    # 2. Fuzzy match each token (not the whole message) against
    # ticker/company_name -- catches a bare company name mentioned inside
    # a longer sentence.
    needle_candidates = tokens + [stripped.lower()]
    scored = []
    for ticker, company_name in rows:
        best = max(
            difflib.SequenceMatcher(None, needle.lower(), (ticker or "").lower()).ratio()
            for needle in needle_candidates
        )
        best = max(
            best,
            max(
                difflib.SequenceMatcher(None, needle.lower(), (company_name or "").lower()).ratio()
                for needle in needle_candidates
            ),
        )
        scored.append((best, ticker))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return {"match": None, "confidence": 0.0, "ambiguous": [], "candidates": []}

    top_score, top_ticker = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0

    if top_score >= TICKER_MATCH_CONFIDENCE_THRESHOLD and (top_score - runner_up_score) >= 0.05:
        return {"match": top_ticker, "confidence": round(top_score, 3), "ambiguous": [], "candidates": []}

    # Below threshold, or too close to call between the top matches --
    # route to clarification instead of guessing, per the specification.
    close_candidates = [ticker for score, ticker in scored[:5] if score >= TICKER_MATCH_CONFIDENCE_THRESHOLD - 0.15]
    return {
        "match": None,
        "confidence": round(top_score, 3),
        "ambiguous": close_candidates,
        "candidates": close_candidates,
    }


def _pending_interrupt(thread_config):
    for task in _orchestrator_graph.get_state(thread_config).tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def invoke_orchestrator(ticker, horizon, user_id=None, forecast_days=None):
    """The full three-pillar path -- the same Orchestrator Subgraph the
    now-superseded bridge graph.py used to call directly (see this
    package's git history / __init__.py). Auto-approves any human-review
    pause so this tool still returns a single result per call, mirroring
    the orchestrator's own smoke_test.py run_and_approve helper -- swap
    for a real human-in-the-loop flow later if the chat surface needs one.
    """
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    request = {
        key: value
        for key, value in {
            "ticker": ticker,
            "horizon": horizon,
            "user_id": user_id,
            "forecast_days": forecast_days,
        }.items()
        if value is not None
    }

    result = _orchestrator_graph.invoke(request, config=thread_config)
    if _pending_interrupt(thread_config) is not None:
        result = _orchestrator_graph.invoke(
            Command(resume={"reviewer_decision": "approve", "review_notes": None}),
            config=thread_config,
        )

    if result.get("error_response"):
        return {"error": result["error_response"]}
    return result.get("final_response")


def invoke_single_pillar(ticker, pillar_name, params=None):
    """Direct call to Technical, Fundamental, or Sentiment Analysis,
    skipping the Orchestrator's reconciliation since there's nothing to
    reconcile with a single source. Reuses
    agents.orchestrator.nodes._pillar_runners' run_technical/
    run_fundamental/run_sentiment -- the same functions the Orchestrator's
    own baseline fetch and rerun-tool paths call -- instead of
    reimplementing pillar invocation here.
    """
    params = params or {}
    if pillar_name not in VALID_PILLARS:
        return {"error": f"unknown pillar_name: {pillar_name!r}, expected one of {VALID_PILLARS}"}

    runner = _PILLAR_RUNNERS[pillar_name]
    horizon = params.get("horizon") or "medium_term"
    pillar_params = HORIZON_TO_PILLAR_PARAMS.get(horizon, HORIZON_TO_PILLAR_PARAMS["medium_term"])

    fake_state = {"ticker": ticker, **pillar_params}
    result, status, error = runner(fake_state, params)

    if status != "ok":
        return {"pillar": pillar_name, "ticker": ticker, "status": status, "error": error, "result": result}
    return {"pillar": pillar_name, "ticker": ticker, "status": status, "result": result}


def answer_general_question(question):
    """Plain LLM completion for educational questions, never touching an
    analysis pillar. Returns an error dict instead of raising if the LLM
    Agent can't be reached -- there is no rule-based fallback for an open
    question, so the caller (parse_and_route, on the next loop) sees this
    as a failed tool call and can decide to clarify instead.
    """
    try:
        answer = _answer_general_question_llm(question)
    except Exception as exc:
        return {"error": f"answer_general_question failed: {exc}"}
    return {"answer": answer}
