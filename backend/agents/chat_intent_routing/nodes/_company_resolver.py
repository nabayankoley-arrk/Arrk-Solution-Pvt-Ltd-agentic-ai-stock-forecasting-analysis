"""_company_resolver — decides which company a user's words refer to, or that it is ambiguous.

find_companies("Mahindra") looks in two places:

  - the tracked companies (`universe`, via _ticker_lookup) -- the only ones that
    can be analysed;
  - BSE's list of every listed equity (ingestion.sources.scrip_master, cached
    on disk for a week) -- so "Reliance" is ambiguous even though only
    Reliance Industries is tracked, because Reliance Power and others exist.

It returns a Resolution: `ticker` when exactly one company fits, otherwise the
`candidates` the user must choose between (tracked first, then by market
capitalisation). The tools node turns an ambiguous result into a
LangGraph interrupt() that asks the user (see tools.py).

Only these count as unambiguous on their own: an exact NSE ticker
("RELIANCE.NS") or an exact company name ("Reliance Industries Ltd",
"Mahindra & Mahindra"). Anything shorter is checked against the whole
market. Funds and ETFs (non-"INE" ISINs) are ignored, since BSE's names for
them otherwise match company words ("Nippon India ETF" was once "Reliance").
If the BSE list cannot be loaded, only tracked companies are considered.
"""

import re
from dataclasses import dataclass, field

from . import _ticker_lookup

MAX_CANDIDATES = 6

# Common abbreviations that do not appear in the company's own name. Each adds
# that tracked company as a candidate -- it does not resolve on its own, since
# "SBI" is also SBI Life and SBI Cards.
ALIASES = {
    "sbi": "SBIN.NS",
    "l&t": "LT.NS",
    "ril": "RELIANCE.NS",
    "hul": "HINDUNILVR.NS",
    "lic": "LICI.NS",
    "airtel": "BHARTIARTL.NS",
    "maruti": "MARUTI.NS",
}

_CORPORATE_SUFFIX = re.compile(r"\b(ltd|limited|pvt|private)\b\.?", re.IGNORECASE)
_scrip_cache = {"entries": None}


@dataclass
class Resolution:
    ticker: str = None  # the tracked NSE ticker, when resolved to one tracked company
    candidates: list = field(default_factory=list)  # [{"ticker", "name", "tracked"}], when ambiguous
    untracked: dict = None  # the one listed-but-untracked company it resolved to, if that

    @property
    def ambiguous(self):
        return len(self.candidates) > 1


def _normalise(name):
    return " ".join(_CORPORATE_SUFFIX.sub(" ", (name or "").lower().replace("&", " & ")).split())


def _words_match(query, name):
    """Every word of the query appears in the name as a whole word, in order."""
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in query.split()) + r"(?![a-z0-9])"
    return re.search(pattern, name) is not None


def _listed_equities():
    if _scrip_cache["entries"] is None:
        try:
            from ingestion.http import HttpClient
            from ingestion.sources import scrip_master

            with HttpClient() as client:
                entries = scrip_master.load(client)
            _scrip_cache["entries"] = [e for e in entries if (e.get("isin") or "").startswith("INE")]
        except Exception as exc:
            print(f"[chat] BSE scrip list unavailable, resolving against tracked companies only: {exc}", flush=True)
            _scrip_cache["entries"] = []
    return _scrip_cache["entries"]


def find_companies(query):
    """-> Resolution for the user's words (a ticker, a name or part of one)."""
    raw = str(query or "").strip()
    if not raw:
        return Resolution()
    tracked = _ticker_lookup.tracked_companies()
    by_symbol = {t.split(".")[0].upper(): t for t, _ in tracked}

    lowered, normalised = raw.lower(), _normalise(raw)
    for ticker, name in tracked:
        if lowered == ticker.lower() or normalised == _normalise(name):
            return Resolution(ticker=ticker)

    alias = ALIASES.get(lowered)
    candidates = [
        {"ticker": ticker, "name": name, "tracked": True}
        for ticker, name in tracked
        if _words_match(normalised, _normalise(name)) or raw.upper() == ticker.split(".")[0] or ticker == alias
    ]
    seen = {c["ticker"].split(".")[0] for c in candidates}
    listed = []
    for entry in _listed_equities():
        symbol = (entry.get("ticker") or "").upper()
        if symbol in seen:
            continue
        if raw.upper() == symbol or _words_match(normalised, _normalise(entry.get("name"))):
            if symbol in by_symbol:  # a tracked company matched by its BSE name
                candidates.append({"ticker": by_symbol[symbol], "name": entry["name"], "tracked": True})
            else:
                listed.append((entry.get("market_cap") or 0, {"ticker": symbol, "name": entry["name"], "tracked": False}))
            seen.add(symbol)
    listed.sort(key=lambda pair: pair[0], reverse=True)
    candidates = (candidates + [c for _, c in listed])[:MAX_CANDIDATES]

    if len(candidates) == 1:
        only = candidates[0]
        return Resolution(ticker=only["ticker"]) if only["tracked"] else Resolution(untracked=only)
    if not candidates and not _scrip_cache["entries"]:
        # BSE list unavailable: fall back to the tracked-only lookup ("Infosys shares").
        return Resolution(ticker=_ticker_lookup.resolve_tracked_ticker(raw) if tracked else None)
    return Resolution(candidates=candidates)


# Words that never identify a company on their own.
_GENERIC_WORDS = {
    "&", "and", "of", "the", "india", "indian", "bank", "company", "group", "industries",
    "services", "finance", "financial", "limited", "corporation", "enterprises",
}


def users_words(name, message):
    """The part of `name` the user actually typed in `message`.

    The LLM sometimes expands what the user wrote ("Mahindra" -> "Mahindra &
    Mahindra Ltd"), which would skip the question the user should be asked.
    When `name` is not in the message, this returns the longest run of its
    words that is ("mahindra"); when none is -- a ticker for a follow-up, or an
    abbreviation the LLM expanded -- `name` is kept as given.
    """
    normalised_name, normalised_message = _normalise(name), _normalise(message)
    if not normalised_name or not normalised_message or _words_match(normalised_name, normalised_message):
        return name
    words = normalised_name.split()
    best = ""
    for start in range(len(words)):
        for end in range(len(words), start, -1):
            phrase = " ".join(words[start:end])
            if len(phrase) <= len(best) or (end - start == 1 and phrase in _GENERIC_WORDS):
                continue
            if _words_match(phrase, normalised_message):
                best = phrase
                break
    return best or name


def resolve_answer(answer, candidates):
    """The user's reply to a clarification question -> Resolution. Accepts an
    option's ticker or name (what the frontend's buttons send), or free text."""
    text = str(answer or "").strip()

    def chosen(option):
        return Resolution(ticker=option["ticker"]) if option["tracked"] else Resolution(untracked=option)

    for option in candidates:
        if text.lower() in (option["ticker"].lower(), option["name"].lower()):
            return chosen(option)
    # "the auto one, Mahindra & Mahindra": exactly one option's name inside the reply.
    mentioned = [o for o in candidates if _words_match(_normalise(o["name"]), _normalise(text))]
    if len(mentioned) == 1:
        return chosen(mentioned[0])
    return find_companies(text)
