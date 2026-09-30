"""score_news — the sentiment profile of the recent news (see _score_helpers.build_score).

Scored with one LLM call on every request that finds news, and never stored in
the database. When the same set of articles comes back within
config.NEWS_SCORE_CACHE_SECONDS (web_search caches its results for as long),
the profile already built for them in this process is reused instead.
"""

import time

from ..config import NEWS_SCORE_CACHE_SECONDS
from ._score_helpers import build_score

_cache = {}


def score_news(state):
    doc = state.get("news_doc")
    if doc is None:
        return {"news_score": None}

    key = tuple(a.get("url") for a in doc["articles"])
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < NEWS_SCORE_CACHE_SECONDS:
        return {"news_score": {**cached[1], "source": "memory"}}

    score = build_score(doc, "NW", "live")
    if score["source"] != "error":
        _cache[key] = (time.monotonic(), score)
    return {"news_score": score}
