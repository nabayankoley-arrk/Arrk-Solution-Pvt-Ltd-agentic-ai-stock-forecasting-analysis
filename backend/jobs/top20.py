"""Which companies count as "the top 20".

Taken from BSE's own scrip list, which carries a market capitalisation per
scrip, ranked descending. That makes the list reproducible and sourced rather
than hand-maintained, and it moves as the market does.

    python -m jobs.top20          # print the current list

It is a property of the data, not a fixed roster: re-running it after a big
move can return a different twentieth name. Pin the list with --symbols on the
summarise job if a run needs to be repeatable against an exact set.
"""

import sys

from ingestion.http import HttpClient
from ingestion.sources import scrip_master

DEFAULT_COUNT = 20


def top_companies(client, count=DEFAULT_COUNT, refresh=False):
    """The `count` largest BSE-listed companies by market capitalisation.

    Returns scrip records in the shape scrip_master.resolve() produces, so they
    drop straight into ingestion.collect.collect().
    """
    entries = scrip_master.load(client, refresh=refresh)
    ranked = sorted(entries, key=lambda e: e.get("market_cap") or 0.0, reverse=True)
    # A zero market cap means BSE did not report one, so the rest of the list
    # is unranked rather than tiny -- stop there instead of padding with it.
    return [entry for entry in ranked if (entry.get("market_cap") or 0) > 0][:count]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    count = DEFAULT_COUNT
    for index, value in enumerate(argv):
        if value == "--count" and index + 1 < len(argv):
            count = int(argv[index + 1])

    with HttpClient() as client:
        companies = top_companies(client, count=count)

    print(f"Top {len(companies)} BSE-listed companies by market capitalisation\n")
    print(f"  {'#':>2}  {'code':<8} {'ticker':<12} {'company':<38} market cap")
    for position, record in enumerate(companies, 1):
        crore = record["market_cap"] / 100000
        print(
            f"  {position:>2}. {record['scrip_code']:<8} {record['ticker']:<12} "
            f"{record['name'][:38]:<38} {crore:>7.2f} lakh cr"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
