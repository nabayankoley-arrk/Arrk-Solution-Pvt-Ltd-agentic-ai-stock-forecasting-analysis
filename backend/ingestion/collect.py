"""Gather a company's documents from every source, in one call.

This is the seam between "find the documents" and "do something with them".
It exists because the command line and the HTTP API need identical behaviour:
the same two BSE feeds, the same de-duplication, the same rule about when a
company website is worth consulting. Duplicating that in two callers would
guarantee they drift apart.

Nothing here downloads anything. It returns records; ingestion/downloader.py
turns records into files.
"""

import datetime

from . import taxonomy
from .errors import ConfigurationError, SourceUnavailable
from .sources import bse, company_site

SOURCES = ("auto", "bse", "site")


def resolve_window(years=1, from_date=None, to_date=None):
    """A (from, to) pair of dates from either an explicit range or a lookback."""
    to_date = to_date or datetime.date.today()
    if from_date is None:
        try:
            from_date = to_date.replace(year=to_date.year - years)
        except ValueError:
            # 29 February has no equivalent in a non-leap year.
            from_date = to_date.replace(month=2, day=28, year=to_date.year - years)
    if from_date > to_date:
        raise ConfigurationError(f"start date {from_date} is after end date {to_date}")
    return from_date, to_date


def _within_window(found, from_date, to_date):
    """Applies the date window to website documents.

    A website document's date is read out of its title or filename and is often
    missing altogether. Undated documents are kept rather than discarded: the
    fallback exists to find things BSE does not have, and silently dropping a
    transcript because nobody put a date in its name would defeat that.
    """
    first, last = from_date.isoformat(), to_date.isoformat()
    return [
        document
        for document in found
        if not document["filed_on"] or first <= document["filed_on"] <= last
    ]


def _from_site(client, scrip_code, warnings, respect_robots=True):
    """Website documents, or [] with a warning recorded on any problem."""
    base_url = bse.fetch_company_website(client, scrip_code)
    configured = company_site.site_config(scrip_code) is not None

    if not base_url and not configured:
        warnings.append(
            f"BSE lists no website for scrip code {scrip_code}; add an entry to "
            "ingestion/companies.json to point the fallback at one"
        )
        return []

    try:
        return company_site.fetch_documents(
            client, scrip_code, base_url=base_url, respect_robots=respect_robots
        )
    except ConfigurationError as exc:
        warnings.append(f"company website skipped: {exc}")
    except SourceUnavailable as exc:
        warnings.append(
            f"could not read {base_url or 'the company website'}: {exc}. "
            "If this site needs special handling, add an entry to ingestion/companies.json."
        )
    return []


def _from_bse(client, scrip_code, from_date, to_date, company, wanted_types):
    """Both BSE feeds, merged and de-duplicated.

    The announcement feed carries an annual report only as it was filed, so a
    one-year window finds one or two; the archive holds every year BSE has.
    Both serve from the same corpfiling store, so the same report arrives twice
    and the overlap is dropped by stored filename.

    Where the archive has anything for the window it is treated as the sole
    authority on what an annual report is. It has to be: companies file the AGM
    notice, a covering letter to shareholders and a Regulation 36(1)(b) letter
    under the same "Reg. 34 (1) Annual Report" subcategory, on the same day, and
    those routinely carry a later timestamp than the report itself. Checked
    across eight companies on 2026-09-07, the archive named the right document
    every time while the announcement stream named a notice or a letter for
    Reliance, TCS and Titan.
    """
    found = bse.fetch_documents(client, scrip_code, from_date, to_date, company=company)

    if not wanted_types or "annual_report" in wanted_types:
        archive = bse.fetch_annual_reports(
            client, scrip_code, from_date, to_date, company=company
        )
        if archive:
            found = _merge_archive(found, archive)

    found.sort(key=lambda document: document.get("filed_at") or "", reverse=True)
    return found


def _merge_archive(announced, archive):
    """Lets the archive replace the announcement stream on annual reports.

    Three cases, and getting the first one wrong silently loses the report:

    * The same file in both feeds. The archive copy wins and the announcement
      copy is dropped, so the file is not downloaded twice under two names.
      Any other type the announcement earned -- a combined report-and-AGM-notice
      PDF is both -- is carried across rather than lost.
    * An announcement the archive does not list, but which claimed to be an
      annual report. Demoted, not discarded: an AGM notice keeps agm_egm, and
      only a pure covering letter drops out of the results entirely.
    * Everything else is untouched.
    """
    by_key = {}
    for document in archive:
        by_key.setdefault(bse.attachment_key(document), document)

    kept = []
    for document in announced:
        twin = by_key.get(bse.attachment_key(document))
        if twin is not None:
            merged = set(twin["doc_types"]) | set(document["doc_types"])
            twin["doc_types"] = [
                doc_type for doc_type in taxonomy.DOCUMENT_TYPES if doc_type in merged
            ]
            continue
        if "annual_report" in document["doc_types"]:
            document["doc_types"] = [
                doc_type for doc_type in document["doc_types"] if doc_type != "annual_report"
            ]
        kept.append(document)

    return kept + archive


def collect(
    client,
    scrip,
    from_date,
    to_date,
    wanted_types=None,
    source="auto",
    respect_robots=True,
):
    """Every document available for one company, by source.

    `scrip` is a record from scrip_master.resolve(). `source` is "auto", "bse"
    or "site"; under "auto" the company website is consulted only for the
    document types BSE did not supply, which keeps BSE authoritative and avoids
    fetching the same annual report twice under two different names.

    Returns a dict with the scrip record, the resolved window, the documents
    from each source, their union, and any non-fatal warnings. Raises
    ConfigurationError when BSE does not recognise the company at all.
    """
    if source not in SOURCES:
        raise ConfigurationError(f"unknown source {source!r}; expected one of {', '.join(SOURCES)}")

    scrip_code = scrip["scrip_code"]
    warnings = []
    company = scrip.get("name") or ""
    bse_documents = []
    site_documents = []

    if source in ("auto", "bse"):
        company = company or bse.fetch_company_name(client, scrip_code)
        bse_documents = _from_bse(
            client, scrip_code, from_date, to_date, company, wanted_types
        )
        if not company and not bse_documents:
            # A listed company with a quiet window still returns a name, so
            # this is a code BSE does not carry rather than an empty result.
            raise ConfigurationError(
                f"BSE has nothing for scrip code {scrip_code}; check the company name or code"
            )

    if source == "site":
        site_documents = _within_window(
            _from_site(client, scrip_code, warnings, respect_robots), from_date, to_date
        )
    elif source == "auto":
        covered = {
            doc_type for document in bse_documents for doc_type in document["doc_types"]
        }
        missing = set(wanted_types or taxonomy.DOCUMENT_TYPES) - covered
        if missing:
            harvested = _within_window(
                _from_site(client, scrip_code, warnings, respect_robots), from_date, to_date
            )
            # Only the gap is taken from the site. A site document carrying no
            # recognised type cannot be the answer to a gap, and a site lists
            # hundreds of them.
            site_documents = [
                document for document in harvested if missing & set(document["doc_types"])
            ]

    return {
        "scrip": scrip,
        "company": company or scrip.get("name") or "",
        "window": (from_date, to_date),
        "bse": bse_documents,
        "site": site_documents,
        "all": bse_documents + site_documents,
        "warnings": warnings,
    }
