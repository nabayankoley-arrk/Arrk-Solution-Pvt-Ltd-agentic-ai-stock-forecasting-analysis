"""seed_fundamentals — populates financial_statements and
analyst_price_targets with REAL data fetched live from yfinance (the same
library Technical Analysis already relies on for its own live price data).

Unlike Technical Analysis, the Fundamental Analysis Agent has no live-fetch
path of its own (see fetch_fundamentals_data.py's own docstring, and the
note in that module referencing this file by name) -- it only ever reads
whatever is already sitting in Postgres. Without this, every ticker fails
check_data_sufficiency.py's MIN_FILING_YEARS check ("insufficient
fundamentals history for analysis") regardless of how complete the real
company's financials actually are.

Seeds every ticker already present in `universe` -- both annual and
quarterly financial_statements rows (revenue, gross_profit,
operating_profit, net_profit, eps, total_debt, total_equity,
cash_flow_operations, inventory, receivables, shares_outstanding -- see
fetch_fundamentals_data.py's STATEMENT_COLUMNS), plus one
analyst_price_targets row per ticker from yfinance's own analyst
consensus (targetMeanPrice/numberOfAnalystOpinions). A field yfinance has
no data for (e.g. "Inventory" for a services company like Infosys) is
left NULL rather than fabricated -- the compute_* nodes already degrade
gracefully around missing fields via their own data_tier logic.

analyst_rating_changes is intentionally NOT seeded here: yfinance's
upgrades_downgrades endpoint returned no data for the tickers tested
against this project (a 404 from Yahoo's own API, not a bug in this
script) -- compute_analyst_consensus.py's "net upgrades vs. downgrades"
signal will simply have nothing to compute from, same as an empty result
set from any other data source.

Safe to re-run: every insert is an upsert keyed on the same primary key
the schema defines (ticker, period_end_date, period_type) / (ticker,
as_of_date).

Run from inside backend/:
    python -m db.seed_fundamentals
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import datetime
import math

import yfinance as yf

from .connection import get_connection

_STATEMENT_COLUMNS = (
    "ticker",
    "period_end_date",
    "period_type",
    "revenue",
    "gross_profit",
    "operating_profit",
    "net_profit",
    "eps",
    "total_debt",
    "total_equity",
    "cash_flow_operations",
    "inventory",
    "receivables",
    "shares_outstanding",
)

_UPSERT_STATEMENT_SQL = f"""
    INSERT INTO financial_statements ({", ".join(_STATEMENT_COLUMNS)})
    VALUES ({", ".join(f"%({col})s" for col in _STATEMENT_COLUMNS)})
    ON CONFLICT (ticker, period_end_date, period_type) DO UPDATE SET
        revenue = EXCLUDED.revenue,
        gross_profit = EXCLUDED.gross_profit,
        operating_profit = EXCLUDED.operating_profit,
        net_profit = EXCLUDED.net_profit,
        eps = EXCLUDED.eps,
        total_debt = EXCLUDED.total_debt,
        total_equity = EXCLUDED.total_equity,
        cash_flow_operations = EXCLUDED.cash_flow_operations,
        inventory = EXCLUDED.inventory,
        receivables = EXCLUDED.receivables,
        shares_outstanding = EXCLUDED.shares_outstanding
"""

_UPSERT_PRICE_TARGET_SQL = """
    INSERT INTO analyst_price_targets (ticker, as_of_date, avg_price_target, num_analysts)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (ticker, as_of_date) DO UPDATE SET
        avg_price_target = EXCLUDED.avg_price_target,
        num_analysts = EXCLUDED.num_analysts
"""


def _clean_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _clean_int(value):
    value = _clean_float(value)
    return None if value is None else int(value)


def _get_row(df, *row_names):
    for name in row_names:
        if df is not None and not df.empty and name in df.index:
            return df.loc[name]
    return None


def _build_statement_rows(ticker, financials, balance_sheet, cashflow, period_type):
    if financials is None or financials.empty:
        return []

    revenue_row = _get_row(financials, "Total Revenue", "Operating Revenue")
    gross_profit_row = _get_row(financials, "Gross Profit")
    operating_profit_row = _get_row(financials, "Operating Income", "Total Operating Income As Reported")
    net_profit_row = _get_row(financials, "Net Income")
    eps_row = _get_row(financials, "Diluted EPS", "Basic EPS")
    shares_row = _get_row(financials, "Diluted Average Shares", "Basic Average Shares")

    total_debt_row = _get_row(balance_sheet, "Total Debt")
    total_equity_row = _get_row(balance_sheet, "Stockholders Equity", "Common Stock Equity")
    inventory_row = _get_row(balance_sheet, "Inventory")
    receivables_row = _get_row(balance_sheet, "Receivables", "Accounts Receivable")

    cfo_row = _get_row(cashflow, "Operating Cash Flow")

    rows = []
    for period_end in financials.columns:
        def _at(row):
            return None if row is None else row.get(period_end)

        record = {
            "ticker": ticker,
            "period_end_date": period_end.date(),
            "period_type": period_type,
            "revenue": _clean_float(_at(revenue_row)),
            "gross_profit": _clean_float(_at(gross_profit_row)),
            "operating_profit": _clean_float(_at(operating_profit_row)),
            "net_profit": _clean_float(_at(net_profit_row)),
            "eps": _clean_float(_at(eps_row)),
            "total_debt": _clean_float(_at(total_debt_row)),
            "total_equity": _clean_float(_at(total_equity_row)),
            "cash_flow_operations": _clean_float(_at(cfo_row)),
            "inventory": _clean_float(_at(inventory_row)),
            "receivables": _clean_float(_at(receivables_row)),
            "shares_outstanding": _clean_int(_at(shares_row)),
        }
        # A period yfinance has essentially nothing for isn't worth a row.
        if record["revenue"] is None and record["net_profit"] is None:
            continue
        rows.append(record)
    return rows


def seed_ticker(ticker):
    """Fetches and upserts one ticker's annual + quarterly statements and
    latest analyst price target. Returns (annual_count, quarterly_count).
    """
    handle = yf.Ticker(ticker)

    annual_rows = _build_statement_rows(ticker, handle.financials, handle.balance_sheet, handle.cashflow, "annual")
    quarterly_rows = _build_statement_rows(
        ticker, handle.quarterly_financials, handle.quarterly_balance_sheet, handle.quarterly_cashflow, "quarterly"
    )

    with get_connection() as conn, conn.cursor() as cur:
        for record in annual_rows + quarterly_rows:
            cur.execute(_UPSERT_STATEMENT_SQL, record)

        info = handle.info or {}
        target_mean_price = _clean_float(info.get("targetMeanPrice"))
        if target_mean_price is not None:
            cur.execute(
                _UPSERT_PRICE_TARGET_SQL,
                (ticker, datetime.date.today(), target_mean_price, info.get("numberOfAnalystOpinions")),
            )

    return len(annual_rows), len(quarterly_rows)


def main():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker FROM universe ORDER BY ticker")
        tickers = [row[0] for row in cur.fetchall()]

    for ticker in tickers:
        try:
            annual_count, quarterly_count = seed_ticker(ticker)
            print(f"{ticker}: seeded {annual_count} annual + {quarterly_count} quarterly financial_statements rows")
        except Exception as exc:
            print(f"{ticker}: FAILED -- {exc}")


if __name__ == "__main__":
    main()
