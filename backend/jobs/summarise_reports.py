"""Download, read, summarise and store the latest AR and TR for a set of companies.

Run manually, from the backend/ directory:

    python -m jobs.summarise_reports --check       # what would happen, and what it costs
    python -m jobs.summarise_reports --dry-run     # download and read, no model, no database
    python -m jobs.summarise_reports               # the real run, top 20 by market cap

The pipeline, per company:

    latest annual report + latest call transcript   ingestion.collect
        -> PDF on disk                              ingestion.downloader
        -> text                                     ingestion.extract  (PyMuPDF)
        -> short summary                            ingestion.summarise (Claude)
        -> one row, keyed on the PDF's sha256       db.upsert

Stored as report_type "AR" for an annual report and "TR" for a transcript.

Three things make a rerun cheap and safe. A document already downloaded is not
downloaded again; a document whose sha256 is already in document_summaries is
not sent to the model again; and a row is written with ON CONFLICT so the same
document updates rather than duplicating.

Cost is the reason for --check. An annual report runs to several hundred
thousand tokens, so twenty of them is real money, and the run tells you the
figure before spending it rather than after.
"""

import argparse
import datetime
import sys

import psycopg2

from db import upsert as store
from ingestion import collect as collector
from ingestion import config, downloader, extract, summarise
from ingestion.errors import ConfigurationError, IngestionError, SourceUnavailable
from ingestion.http import HttpClient
from ingestion.sources import scrip_master

from . import top20

# The two document types this job exists for.
WANTED_TYPES = ["annual_report", "transcript"]
LATEST_PER_TYPE = 1

# Published rates for claude-opus-5, US dollars per million tokens. Used only
# to print an estimate; nothing depends on them being current.
INPUT_USD_PER_MTOK = 5.00
OUTPUT_USD_PER_MTOK = 25.00

# A model spend above this needs an explicit --yes, mirroring the download
# guard. Twenty annual reports can exceed it comfortably.
CONFIRM_ABOVE_USD = 10.0


def _human_bytes(count):
    if not count:
        return "0 B"
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _estimated_usd(input_tokens, output_tokens=0):
    return (
        input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK
    )


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m jobs.summarise_reports",
        description="Download the latest annual report and call transcript for the "
        "top 20 companies, summarise each with Claude, and store the summaries.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        metavar="SYMBOL",
        help="run against these companies instead of the top 20, by ticker, name "
        "or scrip code. Use this to pin a repeatable set.",
    )
    parser.add_argument(
        "--count", type=int, default=top20.DEFAULT_COUNT,
        help="how many of the top companies to run (default: %(default)s)",
    )
    parser.add_argument(
        "--years", type=int, default=1,
        help="how far back to look for the latest of each document (default: %(default)s)",
    )
    parser.add_argument(
        "--out", default=config.DEFAULT_OUTPUT_DIR,
        help="where the PDFs are written (default: %(default)s)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="report the plan, the token count and the estimated cost, then stop. "
        "Downloads the PDFs and reads them, but calls no model and writes no rows.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="download and extract, but neither summarise nor store",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-summarise documents already in the database",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help=f"proceed without confirmation when the estimate exceeds ${CONFIRM_ABOVE_USD:.0f}",
    )
    parser.add_argument(
        "--effort", default=summarise.DEFAULT_EFFORT,
        choices=("low", "medium", "high", "xhigh", "max"),
        help="how hard the model works on each summary (default: %(default)s)",
    )
    parser.add_argument(
        "--model", default=summarise.MODEL,
        help="model id (default: %(default)s)",
    )
    parser.add_argument(
        "--delay", type=float, default=config.REQUEST_DELAY_SECONDS,
        help="seconds between requests to a given host (default: %(default)s)",
    )
    return parser


# --- stage 1: what to work on ---

def _companies(client, args):
    if args.symbols:
        chosen = []
        for symbol in args.symbols:
            try:
                chosen.append(scrip_master.resolve(client, symbol))
            except ConfigurationError as exc:
                print(f"  skipping {symbol}: {exc}".splitlines()[0], file=sys.stderr)
        return chosen
    return top20.top_companies(client, count=args.count)


def _documents_for(client, scrip, args):
    """The latest AR and TR for one company, already narrowed to one each."""
    from_date, to_date = collector.resolve_window(years=args.years)
    collected = collector.collect(
        client, scrip, from_date, to_date, wanted_types=WANTED_TYPES
    )
    selected = downloader.select(collected["all"], wanted_types=WANTED_TYPES)
    selected = downloader.keep_latest(selected, LATEST_PER_TYPE, wanted_types=WANTED_TYPES)
    return selected, collected["warnings"]


# --- stage 2: fetch and read ---

def _prepare(client, scrip, args, seen_checksums):
    """Download, read and stage every document for one company.

    Returns a list of items, each carrying enough to summarise and store, plus
    a per-item status so the caller can report what happened without inferring
    it from a short list.
    """
    items = []
    selected, warnings = _documents_for(client, scrip, args)

    for warning in warnings:
        print(f"    note: {warning[:110]}")

    if not selected:
        print("    nothing found")
        return items

    summary = downloader.download(client, selected, args.out, progress=None)
    manifest = downloader.load_manifest(args.out)

    for result in summary["results"]:
        entry = manifest.get(result["doc_id"]) or {}
        report_type = store.report_type_for(result["doc_types"])
        title = result["title"] or "(untitled)"

        if result["status"] == "failed" or not entry.get("path"):
            print(f"    FAIL  {title[:56]}: {result['error'] or 'not downloaded'}")
            continue
        if report_type is None:
            print(f"    skip  {title[:56]}: neither AR nor TR")
            continue

        checksum = entry.get("sha256") or ""
        if checksum in seen_checksums and not args.force:
            print(f"    have  {report_type}  {title[:52]} (already summarised)")
            continue

        path = f"{args.out}/{entry['path']}"
        try:
            read = extract.extract(path)
        except extract.NotExtractable as exc:
            print(f"    FAIL  {report_type}  {str(exc)[:80]}")
            continue

        print(
            f"    read  {report_type}  {read['pages']:>4} pages  "
            f"{read['chars']:>9,} chars  {title[:40]}"
        )
        items.append(
            {
                "scrip_code": str(scrip["scrip_code"]),
                "ticker": scrip.get("ticker") or "",
                "company_name": entry.get("company") or scrip.get("name") or "",
                "report_name": title,
                "report_type": report_type,
                "filed_on": entry.get("filed_on") or None,
                "source": entry.get("source") or "",
                "source_url": entry.get("source_url") or "",
                "local_path": entry.get("path") or "",
                "sha256": checksum,
                "page_count": read["pages"],
                "char_count": read["chars"],
                "text": read["text"],
            }
        )
    return items


# --- stage 3: cost, summarise, store ---

def _estimate(anthropic_client, items, model):
    total = 0
    for item in items:
        item["input_tokens"] = summarise.count_tokens(
            anthropic_client,
            item["text"],
            item["report_type"],
            item["company_name"],
            item["report_name"],
            item["filed_on"] or "",
            model=model,
        )
        total += item["input_tokens"]
    return total


def _summarise_and_store(anthropic_client, items, args):
    written = {"inserted": 0, "updated": 0}
    failed = 0
    spent_input = spent_output = 0

    for item in items:
        label = f"{item['report_type']}  {item['ticker'] or item['scrip_code']:<10} {item['report_name'][:40]}"
        try:
            result = summarise.summarise(
                anthropic_client,
                item["text"],
                item["report_type"],
                item["company_name"],
                item["report_name"],
                item["filed_on"] or "",
                model=args.model,
                effort=args.effort,
            )
        except summarise.SummaryFailed as exc:
            print(f"  FAIL  {label}: {exc}")
            failed += 1
            continue

        spent_input += result["input_tokens"]
        spent_output += result["output_tokens"]

        record = {key: item[key] for key in (
            "scrip_code", "ticker", "company_name", "report_name", "report_type",
            "filed_on", "source", "source_url", "local_path", "sha256",
            "page_count", "char_count",
        )}
        record["summary"] = result["summary"]
        record["model"] = result["model"]

        outcome = store.save_document_summary(record)
        written[outcome] += 1
        first_line = result["summary"].splitlines()[0]
        print(f"  {outcome[:8]:<8} {label}")
        print(f"           {first_line[:96]}")

    return written, failed, spent_input, spent_output


def main(argv=None):
    args = _build_parser().parse_args(argv)
    started = datetime.datetime.now()

    # The database is checked before any work, not after: discovering it is
    # unreachable having already spent money on the model is the wrong order.
    seen_checksums = set()
    if not (args.check or args.dry_run):
        try:
            seen_checksums = store.existing_document_checksums()
        except psycopg2.OperationalError as exc:
            print(f"Database unreachable: {str(exc).strip()}", file=sys.stderr)
            print(
                "\nSet DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD, in your shell\n"
                "or in backend/.env. Use --check or --dry-run to work without a database.",
                file=sys.stderr,
            )
            return 2
        except psycopg2.errors.UndefinedTable:
            print("Database reachable, but document_summaries does not exist.", file=sys.stderr)
            print(
                "\nRun 'python -m db.apply_schema' to create it, or "
                "'python -m db.apply_schema --check' to see what is there.",
                file=sys.stderr,
            )
            return 2
        print(f"Database: connected, {len(seen_checksums)} document(s) already summarised")

    staged = []
    try:
        with HttpClient(delay_seconds=args.delay) as client:
            companies = _companies(client, args)
            if not companies:
                print("No companies to run.", file=sys.stderr)
                return 2

            print(f"Companies: {len(companies)}\n")
            for position, scrip in enumerate(companies, 1):
                label = scrip.get("ticker") or scrip["scrip_code"]
                print(f"  {position:>2}. {label} - {scrip.get('name') or ''}")
                try:
                    staged.extend(_prepare(client, scrip, args, seen_checksums))
                except (ConfigurationError, SourceUnavailable) as exc:
                    print(f"    FAIL  {str(exc)[:96]}")
    except IngestionError as exc:
        print(f"\nRun stopped: {exc}", file=sys.stderr)
        return 3

    print(f"\nStaged {len(staged)} document(s) to summarise.")
    if not staged:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("Dry run: no model call, nothing stored.")
        return 0

    try:
        anthropic_client = summarise.build_client()
    except summarise.CredentialsMissing as exc:
        print(f"\nClaude API: {exc}", file=sys.stderr)
        print(
            "\nThe documents above were downloaded and read successfully; only the "
            "summarising step needs a key. Re-run with --dry-run to stop before it.",
            file=sys.stderr,
        )
        return 2
    print("Counting tokens...")
    input_tokens = _estimate(anthropic_client, staged, args.model)
    output_tokens = len(staged) * summarise.MAX_SUMMARY_TOKENS
    estimate = _estimated_usd(input_tokens, output_tokens)
    print(
        f"  {input_tokens:,} input tokens across {len(staged)} document(s); "
        f"about ${estimate:.2f} at {args.model} rates"
    )

    if args.check:
        print("\nCheck only: no model call, nothing stored.")
        return 0

    if estimate > CONFIRM_ABOVE_USD and not args.yes:
        print(
            f"\nThis run would cost about ${estimate:.2f}, above the "
            f"${CONFIRM_ABOVE_USD:.0f} threshold.\n"
            "  Narrow it with --symbols or --count, or confirm with --yes.",
            file=sys.stderr,
        )
        return 2

    print()
    written, failed, spent_input, spent_output = _summarise_and_store(
        anthropic_client, staged, args
    )

    elapsed = (datetime.datetime.now() - started).total_seconds()
    print(f"\nSummary  ({elapsed:.0f}s)")
    print(f"  inserted   {written['inserted']}")
    print(f"  updated    {written['updated']}")
    if failed:
        print(f"  failed     {failed}")
    print(f"  tokens     {spent_input:,} in / {spent_output:,} out")
    print(f"  cost       about ${_estimated_usd(spent_input, spent_output):.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
