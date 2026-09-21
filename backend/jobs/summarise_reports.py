"""Download, read, summarise and store the latest AR and TR for a set of companies.

Run manually, from the backend/ directory:

    python -m jobs.summarise_reports --check       # what would happen, and how big it is
    python -m jobs.summarise_reports --dry-run     # download and read, no model, no database
    python -m jobs.summarise_reports               # the real run, top 20 by market cap

The pipeline, per company:

    latest annual report + latest call transcript   ingestion.collect
        -> PDF on disk                              ingestion.downloader
        -> text                                     ingestion.extract  (PyMuPDF)
        -> short summary                            ingestion.summarise (OpenRouter)
        -> one row, keyed on the PDF's sha256       db.upsert

Stored as report_type "AR" for an annual report and "TR" for a transcript.

Three things make a rerun cheap and safe. A document already downloaded is not
downloaded again; a document whose sha256 is already in document_summaries is
not sent to the model again; and a row is written with ON CONFLICT so the same
document updates rather than duplicating.

Provider, model and API key come from agents/orchestrator/config.py and the
environment (LLM_PROVIDER, OPENROUTER_MODEL, OPENROUTER_API_KEY) -- this job
never picks a provider of its own. An annual report too large for the
model's context window is read in parts and those notes summarised together.
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

# What matters per document is now whether it fits the model's context
# window, not what it costs: the configured model is free. A document over
# this many characters is summarised in parts -- see ingestion/summarise.py.


def _human_bytes(count):
    if not count:
        return "0 B"
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024




def _build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m jobs.summarise_reports",
        description="Download the latest annual report and call transcript for the "
        "top 20 companies, summarise each with the configured LLM, and store them.",
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
        help="report the plan, the character counts and which documents will be "
        "read in parts, then stop. Downloads and reads the PDFs, but calls no "
        "model and writes no rows.",
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



def _summarise_and_store(items, args):
    written = {"inserted": 0, "updated": 0}
    failed = 0
    chunked = 0

    for item in items:
        label = f"{item['report_type']}  {item['ticker'] or item['scrip_code']:<10} {item['report_name'][:40]}"
        try:
            result = summarise.summarise(
                item["text"],
                item["report_type"],
                item["company_name"],
                item["report_name"],
                item["filed_on"] or "",
                # A document read in parts takes minutes; say so while it runs
                # rather than appearing to hang.
                progress=lambda note: print(f"           {note}", flush=True),
            )
        except summarise.SummaryFailed as exc:
            print(f"  FAIL  {label}: {exc}")
            failed += 1
            continue

        if result["chunks"] > 1:
            chunked += 1

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

    return written, failed, chunked


def main(argv=None):
    args = _build_parser().parse_args(argv)
    started = datetime.datetime.now()

    # Both prerequisites are checked before any downloading. Discovering a
    # missing key or an unreachable database after fetching twenty documents
    # is the wrong order.
    if not (args.check or args.dry_run):
        try:
            summarise.check_ready()
        except summarise.NotConfigured as exc:
            print(f"LLM provider: {exc}", file=sys.stderr)
            return 2

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

    total_chars = sum(item["char_count"] for item in staged)
    oversized = [item for item in staged if item["char_count"] > summarise.MAX_INPUT_CHARS]
    print(f"  {total_chars:,} characters across {len(staged)} document(s)")
    print(f"  model: {summarise.describe_provider()}")
    if oversized:
        print(
            f"  {len(oversized)} of them exceed the {summarise.MAX_INPUT_CHARS:,}-character "
            "window and will be read in parts:"
        )
        for item in oversized:
            parts = -(-item["char_count"] // summarise.MAX_INPUT_CHARS)
            print(
                f"    {item['report_type']}  {item['ticker'] or item['scrip_code']:<10} "
                f"{item['char_count']:>9,} chars -> {parts} parts"
            )

    if args.check:
        print("\nCheck only: no model call, nothing stored.")
        return 0

    print()
    written, failed, chunked = _summarise_and_store(staged, args)

    elapsed = (datetime.datetime.now() - started).total_seconds()
    print(f"\nSummary  ({elapsed:.0f}s)")
    print(f"  inserted   {written['inserted']}")
    print(f"  updated    {written['updated']}")
    if failed:
        print(f"  failed     {failed}")
    if chunked:
        print(f"  in parts   {chunked}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
