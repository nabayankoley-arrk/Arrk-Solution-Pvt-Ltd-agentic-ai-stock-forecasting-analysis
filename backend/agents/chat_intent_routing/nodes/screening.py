"""screening — every tracked company side by side, for the screen_stocks tool.

For general questions across companies ("which is better for a beginner?").
Each company gets its technical and fundamental pillar run directly (both are
rule-based: no LLM), plus the sentiment labels already stored for its latest
transcript and annual report (no LLM either -- a missing profile just shows as
unknown). Companies run in parallel and the table is cached for
CACHE_TTL_SECONDS, so repeated questions are instant.

Ranking is a transparent points score per criteria preset (_SCORES), not a
recommendation: the agent is told to present it as general information.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from ._ticker_lookup import tracked_companies

CRITERIA = ("beginner", "growth", "value", "momentum", "all")
CACHE_TTL_SECONDS = 600
MAX_WORKERS = 5

# The medium-term pillar settings (agents/orchestrator/config.py).
_TECHNICAL_REQUEST = {"lookback_days": 250}
_FUNDAMENTAL_REQUEST = {"ratio_basis": "TTM", "lookback_years": 5}

_cache = {"at": 0.0, "rows": None}

# points per field value, per preset
_SCORES = {
    "beginner": {
        "volatility": {"low": 2, "medium": 1, "high": -1},
        "financial_health": {"strong": 2, "stable": 1, "weak": -2},
        "fundamental": {"bullish": 1, "bearish": -1},
        "valuation": {"expensive": -0.5},
        "technical": {"bearish": -0.5},
    },
    "growth": {
        "growth": {"accelerating": 2, "stable": 0.5, "decelerating": -1},
        "fundamental": {"bullish": 1, "bearish": -1},
        "technical": {"bullish": 1, "bearish": -1},
        "sentiment": {"bullish": 0.5, "bearish": -0.5},
    },
    "value": {
        "valuation": {"cheap": 2, "fair": 0.5, "expensive": -1.5},
        "financial_health": {"strong": 1, "weak": -1},
        "analyst_consensus": {"bullish": 0.5, "bearish": -0.5},
    },
    "momentum": {
        "technical": {"bullish": 2, "bearish": -2},
        "momentum": {"bullish": 1, "bearish": -1},
        "sentiment": {"bullish": 0.5, "bearish": -0.5},
    },
}
_RISK_FLAG_PENALTY = {"beginner": 0.5, "value": 0.25}


def _pillars():
    # Imported lazily: agents.orchestrator builds its graphs on import.
    from agents.orchestrator.nodes._pillar_runners import run_fundamental, run_technical

    return run_technical, run_fundamental


def _stored_sentiment(ticker):
    """The overall label of the stored filing profiles, or None (no LLM call)."""
    from agents.sentiment_analysis import prompts
    from db.upsert import latest_document_summary_by_ticker

    labels = []
    for report_type in ("TR", "AR"):
        try:
            doc = latest_document_summary_by_ticker(ticker.split(".")[0], report_type)
        except Exception:
            return None
        profile = (doc or {}).get("sentiment_profile")
        if profile and doc.get("sentiment_prompt_version") == prompts.PROMPT_VERSION:
            labels.append(profile.get("label"))
    labels = [label for label in labels if label]
    if not labels:
        return None
    return labels[0] if len(set(labels)) == 1 else "mixed"


def _row(ticker, name):
    run_technical, run_fundamental = _pillars()
    technical, t_status, _ = run_technical({"ticker": ticker, **_TECHNICAL_REQUEST})
    fundamental, f_status, _ = run_fundamental({"ticker": ticker, **_FUNDAMENTAL_REQUEST})
    technical = technical if t_status == "ok" else {}
    fundamental = fundamental if f_status == "ok" else {}

    signal = technical.get("technical_signal") or {}
    summary = signal.get("summary") or {}
    volatility = technical.get("volatility") or {}
    composite = fundamental.get("composite") or {}
    row = {
        "ticker": ticker,
        "company": name,
        "price": technical.get("current_price"),
        "volatility": volatility.get("classification") or summary.get("volatility"),
        "atr_pct": (volatility.get("detail") or {}).get("atr_pct"),
        "trend": summary.get("trend"),
        "momentum": summary.get("momentum"),
        "technical": signal.get("direction"),
        "fundamental": composite.get("direction"),
        "financial_health": (fundamental.get("financial_health") or {}).get("classification"),
        "growth": (fundamental.get("growth") or {}).get("classification"),
        "valuation": (fundamental.get("relative_valuation") or {}).get("classification"),
        "analyst_consensus": (fundamental.get("analyst_consensus") or {}).get("classification"),
        "risk_flags": list(composite.get("risk_flags") or [])[:3],
        "sentiment": _stored_sentiment(ticker),
    }
    row["data_gaps"] = [k for k in ("technical", "fundamental", "sentiment") if row[k] is None]
    return row


def _rows():
    if _cache["rows"] is not None and time.monotonic() - _cache["at"] < CACHE_TTL_SECONDS:
        return _cache["rows"]
    companies = tracked_companies()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        rows = list(pool.map(lambda pair: _row(*pair), companies))
    if rows:
        _cache.update(at=time.monotonic(), rows=rows)
    return rows


def score(row, criteria):
    points = sum(table.get(row.get(field), 0) for field, table in _SCORES[criteria].items())
    points -= _RISK_FLAG_PENALTY.get(criteria, 0) * len(row.get("risk_flags") or [])
    return round(points, 2)


def screen(criteria="all"):
    """The comparison table, ranked for `criteria` (unranked for "all")."""
    rows = [dict(r) for r in _rows()]
    if not rows:
        return {"error": "no tracked companies could be compared right now"}
    if criteria in _SCORES:
        for row in rows:
            row["score"] = score(row, criteria)
        rows.sort(key=lambda r: (-r["score"], r["ticker"]))
    return {
        "criteria": criteria,
        "companies": rows,
        "how_ranked": {field: table for field, table in _SCORES.get(criteria, {}).items()},
        "note": "A rule-based comparison of the latest data, not personalised investment advice.",
    }
