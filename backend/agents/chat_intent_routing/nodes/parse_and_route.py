"""parse_and_route — intent-classification and ticker-resolution node.

Minimal placeholder for this subgraph's own NLU step -- no specification
for real intent classification has been shared yet (see __init__.py), so
this only distinguishes two intents:

    'stock_market'  -- routed to route_to_orchestrator
    'out_of_scope'  -- routed to handle_out_of_scope

Intent is decided first, from `message` alone -- an explicit `ticker`, an
extracted one, or a stock keyword. The watchlist is deliberately NOT part
of that decision: a user having anything on their watchlist must never by
itself turn an unrelated message (e.g. "who is the PM of India?") into a
'stock_market' intent just because a ticker happened to be resolvable.
Only once intent is already 'stock_market' does an unresolved ticker fall
back to the watchlist -- purely to fill in *which* ticker a genuinely
stock-shaped follow-up (e.g. "what's the latest forecast?") is about.

Ticker resolution, in this order:
    1. an explicit `ticker` the caller supplied directly
    2. a ".NS"/".BO"-suffixed token found in `message` (NSE/BSE tickers,
       matching this codebase's own convention -- see e.g.
       agents/orchestrator/smoke_test.py's "TCS.NS", "WIPRO.NS")
    3. a bare ticker symbol ("TCS", "INFY") or company short name
       ("Infosys", "Titan") found in `message`, looked up against
       `universe` -- see _ticker_lookup.py. Tried only after step 2 finds
       nothing, since a suffixed token needs no database round trip and is
       unambiguous on its own.
    4. only if intent is already 'stock_market' from a keyword match: the
       most recent entry in user_memory["watchlist"] (loaded by
       load_user_memory, which runs before this node -- see graph.py) --
       the "Memory-Informed Routing" behavior the User Memory extension's
       specification describes. This used to live in
       agents/orchestrator/nodes/validate_input.py; it moved here now that
       the Orchestrator Subgraph no longer touches user_memory at all.

A 'stock_market' intent can still end up with no resolved ticker at all
(an explicit stock keyword, empty watchlist) -- route_to_orchestrator's
call into the Orchestrator Subgraph surfaces "ticker is required" as that
subgraph's own normal validation error in that case, rather than this
node duplicating that check.
"""

import re

from ..config import STOCK_KEYWORDS
from ._ticker_lookup import resolve_ticker_from_text

_TICKER_RE = re.compile(r"\b([A-Z]{1,15}\.(?:NS|BO))\b")


def _extract_ticker(message):
    if not message:
        return None
    match = _TICKER_RE.search(message.upper())
    if match:
        return match.group(1)
    return resolve_ticker_from_text(message)


def parse_and_route(state):
    message = state.get("message") or ""

    explicit_ticker = state.get("ticker") or _extract_ticker(message)
    keyword_matched = any(keyword in message.lower() for keyword in STOCK_KEYWORDS)

    if not explicit_ticker and not keyword_matched:
        return {
            "intent": "out_of_scope",
            "resolved_ticker": None,
            "routing_reason": "no ticker or stock-market keyword found",
        }

    resolved_ticker = explicit_ticker
    if not resolved_ticker:
        watchlist = (state.get("user_memory") or {}).get("watchlist") or []
        resolved_ticker = watchlist[0] if watchlist else None

    reason = "resolved ticker" if explicit_ticker else "stock-market keyword matched"
    if keyword_matched and not explicit_ticker and resolved_ticker:
        reason += "; ticker from watchlist"

    return {"intent": "stock_market", "resolved_ticker": resolved_ticker, "routing_reason": reason}
