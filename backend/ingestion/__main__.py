"""Command line entry point for the document fetcher.

Run from the backend/ directory, which is this project's import root:

    python -m ingestion search avantel
    python -m ingestion inventory avantel --years 3
    python -m ingestion fetch avantel --years 3 --types annual_report --dry-run
    python -m ingestion fetch avantel --years 3 --types annual_report

A company is named however is convenient -- ticker, registered name, ISIN or
BSE scrip code -- and resolved against BSE's list of active scrips.

BSE is the primary source. Where a requested document type is absent from BSE,
the company's own website is consulted as a fallback; its address comes from
BSE's company information, so this works without any per-company setup. That is
what --source auto means, and it is the default.

Exit codes: 0 success, 1 some documents failed, 2 configuration problem,
3 a source could not be reached, 4 a local filesystem problem, 130 interrupted.
"""

import argparse
import datetime
import sys

from . import collect, config, downloader, taxonomy
from .errors import ConfigurationError, IngestionError, SourceUnavailable, StorageError
from .http import HttpClient
from .sources import company_site, scrip_master

EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_CONFIGURATION = 2
EXIT_SOURCE_UNAVAILABLE = 3
EXIT_STORAGE = 4
EXIT_INTERRUPTED = 130

_STATUS_MARKERS = {
    "downloaded": "  ok  ",
    "would_download": " plan ",
    "skipped_existing": " have ",
    "skipped_budget": " cap  ",
    "failed": " FAIL ",
}


def _human_bytes(count):
    if not count:
        return "0 B"
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _parse_date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {text!r}")


def _add_company_argument(parser):
    parser.add_argument(
        "company",
        help="ticker, registered name, ISIN or BSE scrip code, for example "
        "AVANTEL, 'Avantel Ltd' or 532406",
    )
    parser.add_argument(
        "--refresh-scrips",
        action="store_true",
        help="refetch BSE's scrip list instead of using the weekly cache",
    )


def _add_common_arguments(parser):
    _add_company_argument(parser)
    parser.add_argument("--from", dest="from_date", type=_parse_date, help="start date, YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", type=_parse_date, help="end date, YYYY-MM-DD")
    parser.add_argument(
        "--years",
        type=int,
        default=config.DEFAULT_LOOKBACK_YEARS,
        help="lookback in years when --from is not given (default: %(default)s)",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "bse", "site"),
        default="auto",
        help="auto consults the company website only for types BSE lacks "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=config.REQUEST_DELAY_SECONDS,
        help="seconds between requests to a given host (default: %(default)s)",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="skip the robots.txt check when reading a company website",
    )


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m ingestion",
        description="Download corporate document PDFs from BSE, with company websites as a fallback.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser(
        "search", help="find a company's scrip code by ticker, name or ISIN"
    )
    _add_company_argument(search_parser)

    inventory_parser = subparsers.add_parser(
        "inventory", help="count available documents by type and source, downloading nothing"
    )
    _add_common_arguments(inventory_parser)

    fetch_parser = subparsers.add_parser("fetch", help="download document PDFs")
    _add_common_arguments(fetch_parser)
    fetch_parser.add_argument(
        "--types",
        nargs="+",
        metavar="TYPE",
        default=list(config.DEFAULT_DOCUMENT_TYPES),
        choices=tuple(taxonomy.DOCUMENT_TYPES) + ("all",),
        help="document types to download (default: %(default)s). Pass 'all' for "
        "every report type. Choices: " + ", ".join(taxonomy.DOCUMENT_TYPES) + ", all",
    )
    fetch_parser.add_argument(
        "--latest",
        type=int,
        metavar="N",
        default=config.DEFAULT_LATEST_PER_TYPE,
        help="keep only the N most recent documents of each type "
        "(default: %(default)s). Use 0 for every one in the window",
    )
    fetch_parser.add_argument(
        "--include-unclassified",
        action="store_true",
        help="also download filings that match no document type -- ESOP allotments, "
        "lost share certificates, routine disclosures. Off by default: for a large "
        "company these outnumber the reports four to one",
    )
    fetch_parser.add_argument(
        "--yes",
        action="store_true",
        help="proceed without confirmation when the download exceeds "
        f"{config.CONFIRM_ABOVE_BYTES // (1024 * 1024)} MB",
    )
    fetch_parser.add_argument(
        "--out", default=config.DEFAULT_OUTPUT_DIR, help="output directory (default: %(default)s)"
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be downloaded, and the byte total, without fetching",
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="re-download files that already exist"
    )
    fetch_parser.add_argument(
        "--max-mb", type=float, help="stop once this many megabytes have been accounted for"
    )
    fetch_parser.add_argument(
        "--skip-cover-letters",
        action="store_true",
        help="drop documents whose title reads as a covering letter",
    )
    return parser


# --- collection ---

def _collect(client, args, wanted_types=None):
    """Resolves the company, then gathers its documents via ingestion.collect."""
    from_date, to_date = collect.resolve_window(
        years=args.years, from_date=args.from_date, to_date=args.to_date
    )
    scrip = scrip_master.resolve(client, args.company, refresh=args.refresh_scrips)
    return collect.collect(
        client,
        scrip,
        from_date,
        to_date,
        wanted_types=wanted_types,
        source=args.source,
        respect_robots=not args.ignore_robots,
    )


def _print_header(collected):
    scrip = collected["scrip"]
    label = collected["company"] or "(name unavailable)"
    ticker = f" ({scrip['ticker']})" if scrip["ticker"] else ""
    from_date, to_date = collected["window"]
    print(f"Company : {label}{ticker} [{scrip['scrip_code']}]")
    print(f"Window  : {from_date} to {to_date}")
    print(
        f"Found   : {len(collected['bse'])} from BSE, "
        f"{len(collected['site'])} from the company website"
    )
    for warning in collected["warnings"]:
        print(f"  note: {warning}")


# --- commands ---

def _run_search(client, args):
    entries = scrip_master.load(client, refresh=args.refresh_scrips)
    matches = scrip_master.search(entries, args.company)
    if not matches:
        print(f"No BSE-listed company matches {args.company!r}.", file=sys.stderr)
        return EXIT_CONFIGURATION

    print(f"{len(matches)} match(es) for {args.company!r}:\n")
    print(f"  {'code':<8} {'ticker':<12} {'group':<6} name")
    for entry in matches[:25]:
        print(
            f"  {entry['scrip_code']:<8} {entry['ticker']:<12} "
            f"{entry['group']:<6} {entry['name']}"
        )
    if len(matches) > 25:
        print(f"  ... and {len(matches) - 25} more")
    return EXIT_OK


def _run_inventory(client, args):
    collected = _collect(client, args)
    _print_header(collected)

    bse_counts = taxonomy.inventory(collected["bse"])
    site_counts = taxonomy.inventory(collected["site"])
    width = max(len(name) for name in bse_counts)

    print("\nDocuments by type (one document may match several types):")
    print(f"  {'type'.ljust(width)}   BSE   site")
    for name in bse_counts:
        print(f"  {name.ljust(width)}  {bse_counts[name]:>4}  {site_counts[name]:>5}")

    gaps = [name for name in taxonomy.DOCUMENT_TYPES if not bse_counts[name] and site_counts[name]]
    if gaps:
        print(f"\nOnly on the company website: {', '.join(gaps)}")
    return EXIT_OK


def _progress(result):
    marker = _STATUS_MARKERS.get(result["status"], "  ?   ")
    size = _human_bytes(result["bytes"]) if result["bytes"] else "-"
    source = (result["source"] or "")[:4]
    print(
        f"[{marker}] {source:<4} {result['filed_on'] or '----------':<10} "
        f"{size:>9}  {(result['title'] or '')[:62]}"
    )
    if result["error"]:
        print(f"             {result['error'][:150]}")


def _print_summary(summary, dry_run):
    print("\nSummary")
    for status in ("downloaded", "would_download", "skipped_existing", "skipped_budget", "failed"):
        if summary.get(status):
            print(f"  {status.ljust(16)} {summary[status]}")
    print(f"  {'bytes'.ljust(16)} {_human_bytes(summary['total_bytes'])}")

    if summary.get("manifest_warning"):
        print(f"\nThe files downloaded, but the manifest did not: {summary['manifest_warning']}")

    duplicates = [result for result in summary["results"] if result.get("duplicate_of")]
    if duplicates:
        print(
            f"\n{len(duplicates)} file(s) are byte-identical to a document already in the "
            "manifest. Nothing was deleted; compare them in manifest.json."
        )
    if dry_run:
        print("\nDry run: nothing was written. Re-run without --dry-run to download.")


def _resolve_types(types):
    """None means every report type; "all" is how the command line says that."""
    if not types or "all" in types:
        return None
    return list(types)


def _run_fetch(client, args):
    wanted_types = _resolve_types(args.types)
    collected = _collect(client, args, wanted_types=wanted_types)
    _print_header(collected)

    selected = downloader.select(
        collected["all"],
        wanted_types=wanted_types,
        skip_cover_letters=args.skip_cover_letters,
        include_unclassified=args.include_unclassified,
    )
    matched = len(selected)
    found = downloader.availability(selected, wanted_types)
    if args.latest:
        selected = downloader.keep_latest(selected, args.latest, wanted_types=wanted_types)

    estimate = downloader.estimate_bytes(selected)
    scope = ", ".join(wanted_types) if wanted_types else "all report types"
    from_site = sum(1 for document in selected if document["source"] == company_site.SOURCE)
    print(f"Selected: {len(selected)} PDFs ({scope}), {from_site} from the company website")
    if args.latest and matched > len(selected):
        print(f"          latest {args.latest} of each type, from {matched} matching")
    if wanted_types:
        for doc_type, count in found.items():
            state = f"{count} available" if count else "none found on BSE or the company website"
            print(f"          {doc_type:<18} {state}")
    if not args.include_unclassified and not args.types:
        unclassified = sum(
            1 for document in collected["all"] if not document.get("doc_types")
        )
        if unclassified:
            print(
                f"          {unclassified} filing(s) matched no report type and were "
                "skipped; --include-unclassified to keep them"
            )
    # The announcement feed reports each attachment's size; the annual report
    # archive and company websites do not. Saying so keeps the number honest,
    # because an unsized annual report is usually one of the largest files.
    unsized = sum(1 for document in selected if not document.get("size_bytes"))
    print(
        f"Estimate: {_human_bytes(estimate)}"
        + (f"  (a floor: {unsized} of {len(selected)} report no size)" if unsized else "")
    )

    if not selected:
        print("\nNothing to download.")
        return EXIT_OK

    if not args.dry_run:
        if estimate > config.CONFIRM_ABOVE_BYTES and not args.yes and not args.max_mb:
            # A one-line command should not be able to pull hundreds of
            # megabytes by accident. Narrowing the request is almost always the
            # right answer, so the message suggests that before --yes.
            raise ConfigurationError(
                f"this would download {_human_bytes(estimate)}, above the "
                f"{_human_bytes(config.CONFIRM_ABOVE_BYTES)} threshold.\n"
                "  Narrow it with --types and --latest, cap it with --max-mb, "
                "or confirm with --yes."
            )
        downloader.check_free_space(args.out, estimate)

    max_total_bytes = int(args.max_mb * 1024 * 1024) if args.max_mb else None
    print(f"Output  : {args.out}\n")

    try:
        summary = downloader.download(
            client,
            selected,
            args.out,
            dry_run=args.dry_run,
            force=args.force,
            max_total_bytes=max_total_bytes,
            progress=_progress,
        )
    except IngestionError as exc:
        # download() attaches whatever it completed before giving up, so a long
        # run that dies near the end still reports what it achieved.
        done = len(getattr(exc, "results", []) or [])
        print(f"\nRun stopped after {done} document(s): {exc}", file=sys.stderr)
        raise

    _print_summary(summary, args.dry_run)
    return EXIT_SOME_FAILED if summary.get("failed") else EXIT_OK


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        # The search subcommand has no --delay of its own.
        delay = getattr(args, "delay", config.REQUEST_DELAY_SECONDS)
        with HttpClient(delay_seconds=delay) as client:
            if args.command == "search":
                return _run_search(client, args)
            if args.command == "inventory":
                return _run_inventory(client, args)
            return _run_fetch(client, args)
    except ConfigurationError as exc:
        print(f"Configuration problem: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION
    except StorageError as exc:
        print(f"Local filesystem problem: {exc}", file=sys.stderr)
        return EXIT_STORAGE
    except SourceUnavailable as exc:
        print(f"Source unavailable: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    except KeyboardInterrupt:
        print("\nInterrupted. Partial files were removed; rerun to continue.", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
