"""Backtest the price forecast's volatility range, and the technical signal's direction.

Run manually, from the backend/ directory:

    python -m jobs.backtest_forecasts                      # all tickers, default horizons
    python -m jobs.backtest_forecasts --tickers TCS.NS INFY.NS --horizons 7 30
    python -m jobs.backtest_forecasts --csv backtest.csv   # also write every sample

For each ticker in "Technical".price_history, it steps through past dates.
At each date it uses ONLY the prices up to that date -- the same 250-session
window the technical pillar reads -- to build what the app would have
forecast, then looks up the actual close `horizon` calendar days later:

  - the baseline range (agents/orchestrator/forecast_price_range._baseline),
    with sigma from the technical pillar's own daily-return volatility
    (compute_volatility._daily_return_std_pct). Coverage is how often the
    actual close landed inside it: about 68% is right for 1 sigma. Calibration
    at 0.674 / 1 / 1.645 sigma (50% / 68% / 90%) shows whether the width is
    right, and `k for 68%` is the multiplier that would have made it exactly so.
  - the same range shifted by the technical signal (the "tilted" coverage), and
    that signal's direction hit rate: of the bullish/bearish calls, how often
    the price actually moved that way, next to the base rate of up moves.

What it cannot test, because there is no point-in-time history for it: the
fundamental and sentiment pillars, the analyst-target pull, and the LLM's
refinement of the range. Samples overlap (a new start date every --step
sessions), so they are not independent: treat differences of a few points as
noise. The tickers are today's top companies, which flatters any bullish rule
(survivorship).
"""

import argparse
import bisect
import csv
import datetime
import math
import statistics
import sys

from agents.orchestrator.forecast_price_range import _baseline
from agents.technical_analysis.config import LOOKBACK_DAYS
from agents.technical_analysis.nodes.aggregate_technical_signal import aggregate_technical_signal
from agents.technical_analysis.nodes.compute_momentum import compute_momentum
from agents.technical_analysis.nodes.compute_support_resistance import compute_support_resistance
from agents.technical_analysis.nodes.compute_trend import compute_trend
from agents.technical_analysis.nodes.compute_volatility import _daily_return_std_pct, compute_volatility
from agents.technical_analysis.nodes.fetch_price_history import PRICE_COLUMNS, _row_to_dict
from db.connection import get_connection

DEFAULT_HORIZONS = (7, 30, 90, 180, 365)
TRADING_DAYS_PER_YEAR = 252
Z_FOR = {"50%": 0.674, "68%": 1.0, "90%": 1.645}


def _load(tickers):
    """{ticker: [price row dict, ...] oldest first}, for the given tickers or all."""
    query = f'SELECT ticker, {", ".join(PRICE_COLUMNS)} FROM "Technical".price_history'
    params = ()
    if tickers:
        query += " WHERE ticker = ANY(%s)"
        params = (list(tickers),)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query + " ORDER BY ticker, trade_date", params)
        rows = cur.fetchall()
    history = {}
    for row in rows:
        history.setdefault(row[0], []).append(_row_to_dict(row[1:]))
    return history


def _technical_direction(window):
    """The technical pillar's direction from these rows alone, as it would have been."""
    state = {"price_history": window}
    for node in (compute_trend, compute_momentum, compute_volatility, compute_support_resistance):
        state.update(node(state))
    return aggregate_technical_signal(state)["technical_signal"]["direction"]


def _samples(ticker, rows, horizons, step):
    dates = [datetime.date.fromisoformat(r["trade_date"]) for r in rows]
    closes = [r["close_price"] for r in rows]
    for i in range(LOOKBACK_DAYS - 1, len(rows), step):
        window = rows[i - LOOKBACK_DAYS + 1:i + 1]
        price = closes[i]
        std_pct = _daily_return_std_pct([r["close_price"] for r in window])
        if not price or not std_pct:
            continue
        sigma = std_pct / 100
        direction = _technical_direction(window)
        for horizon in horizons:
            j = bisect.bisect_left(dates, dates[i] + datetime.timedelta(days=horizon))
            if j >= len(rows):
                continue  # the outcome is after the last stored price
            actual = closes[j]
            neutral = _baseline(price, sigma, horizon, {"direction": None})
            tilted = _baseline(price, sigma, horizon, {"direction": direction, "confidence": "medium"})
            move = math.log(actual / price)
            yield {
                "ticker": ticker,
                "origin": dates[i].isoformat(),
                "horizon": horizon,
                "price": price,
                "actual": actual,
                "direction": direction,
                "sigma_pct": round(std_pct, 3),
                "low": neutral["low"],
                "high": neutral["high"],
                "inside": neutral["low"] <= actual <= neutral["high"],
                "inside_tilted": tilted["low"] <= actual <= tilted["high"],
                "width_pct": (neutral["high"] - neutral["low"]) / price * 100,
                "z": move / (sigma * math.sqrt(horizon * TRADING_DAYS_PER_YEAR / 365)),
                "up": actual > price,
            }


def _pct(values):
    values = list(values)
    return f"{sum(values) / len(values) * 100:5.1f}%" if values else "    -"


def _quantile(values, q):
    values = sorted(values)
    return values[min(int(q * len(values)), len(values) - 1)] if values else float("nan")


def _report(samples, horizons):
    print(f"\n{'horizon':>8} {'n':>6} {'inside 1σ':>10} {'50% band':>9} {'68% band':>9} {'90% band':>9} "
          f"{'k for 68%':>10} {'width':>7} {'tilted':>7}   {'signal hit':>10} {'calls':>6} {'up rate':>8}")
    print(f"{'':>8} {'':>6} {'(want 68)':>10} {'(want 50)':>9} {'(want 68)':>9} {'(want 90)':>9} "
          f"{'':>10} {'median':>7} {'1σ':>7}   {'':>10} {'':>6} {'':>8}")
    for horizon in horizons:
        rows = [s for s in samples if s["horizon"] == horizon]
        if not rows:
            print(f"{horizon:>7}d {'0':>6}   (not enough history after the start dates)")
            continue
        abs_z = [abs(s["z"]) for s in rows]
        calls = [s for s in rows if s["direction"] in ("bullish", "bearish")]
        hits = [(s["up"] if s["direction"] == "bullish" else not s["up"]) for s in calls]
        print(
            f"{horizon:>7}d {len(rows):>6} {_pct(s['inside'] for s in rows):>10} "
            + " ".join(f"{_pct(z <= Z_FOR[b] for z in abs_z):>9}" for b in ("50%", "68%", "90%"))
            + f" {_quantile(abs_z, 0.68):>10.2f} {statistics.median(s['width_pct'] for s in rows):>6.1f}%"
            + f" {_pct(s['inside_tilted'] for s in rows):>7}   {_pct(hits):>10} {len(calls):>6} {_pct(s['up'] for s in rows):>8}"
        )


def _verdict(samples, horizons):
    """Plain-language reading of the table."""
    print("\nReading it:")
    for horizon in horizons:
        rows = [s for s in samples if s["horizon"] == horizon]
        if not rows:
            continue
        coverage = sum(s["inside"] for s in rows) / len(rows) * 100
        k = _quantile([abs(s["z"]) for s in rows], 0.68)
        if coverage < 60:
            note = f"too narrow -- widening sigma x{k:.2f} would have hit 68%"
        elif coverage > 76:
            note = f"too wide -- sigma x{k:.2f} would have hit 68%"
        else:
            note = "well calibrated"
        calls = [s for s in rows if s["direction"] in ("bullish", "bearish")]
        if calls:
            hit = sum((s["up"] if s["direction"] == "bullish" else not s["up"]) for s in calls) / len(calls) * 100
            up = sum(s["up"] for s in rows) / len(rows) * 100
            bullish_share = sum(s["direction"] == "bullish" for s in calls) / len(calls)
            chance = (bullish_share * up + (1 - bullish_share) * (100 - up))  # hit rate of random calls in these proportions
            edge = hit - chance
            signal = f"signal {hit:.0f}% vs {chance:.0f}% by chance ({edge:+.0f} pts)"
        else:
            signal = "no directional calls"
        print(f"  {horizon:>4}d: range {coverage:.0f}% inside, {note}; {signal}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m jobs.backtest_forecasts", description=__doc__.split("\n\n")[0])
    parser.add_argument("--tickers", nargs="+", help="NSE tickers (default: every ticker with price history)")
    parser.add_argument("--horizons", nargs="+", type=int, default=list(DEFAULT_HORIZONS), help="calendar days ahead")
    parser.add_argument("--step", type=int, default=5, help="sessions between start dates (default: %(default)s)")
    parser.add_argument("--csv", help="write every sample to this CSV file")
    args = parser.parse_args(argv)

    history = _load(args.tickers)
    if not history:
        print("No price history found. Seed it first: python -m db.seed_price_history", file=sys.stderr)
        return 2

    samples = []
    for ticker, rows in sorted(history.items()):
        if len(rows) <= LOOKBACK_DAYS:
            print(f"  skip {ticker}: {len(rows)} sessions, need more than {LOOKBACK_DAYS}")
            continue
        samples.extend(_samples(ticker, rows, args.horizons, args.step))

    span = sorted(s["origin"] for s in samples)
    print(f"{len(history)} ticker(s), {len(samples)} samples, start dates {span[0] if span else '-'} .. {span[-1] if span else '-'}"
          f", a new start every {args.step} sessions")
    _report(samples, args.horizons)
    _verdict(samples, args.horizons)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
            writer.writeheader()
            writer.writerows(samples)
        print(f"\nWrote {len(samples)} samples to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
