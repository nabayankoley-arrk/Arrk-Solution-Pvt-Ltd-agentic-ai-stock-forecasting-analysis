"""BSE as a document source.

Everything here was checked against the live endpoints on 2026-09-03, and the
field names below mirror that response verbatim. When BSE changes something,
this module is the first place to look.
"""

import collections
import datetime
import re

from .. import documents
from ..errors import SourceUnavailable

SOURCE = "bse"

ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
SCRIP_HEADER_URL = "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"
CORP_INFO_URL = "https://api.bseindia.com/BseIndiaAPI/api/CorpInfo/w"
# BSE's dedicated annual report archive, separate from the announcement feed
# and far deeper: reports back to 1997 with direct PDF links.
ANNUAL_REPORTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w"

# The JSON API returns 403 without a bseindia Referer. The attachment host is
# more permissive, but the same header is sent there for consistency.
API_REFERER = "https://www.bseindia.com/corporates/ann.html"
ATTACHMENT_REFERER = "https://www.bseindia.com/"

# BSE serves attachments from two directories. Recent filings appear in both;
# anything more than roughly a year old exists only under AttachHis. Both are
# offered as candidate URLs rather than choosing between them, because the OLD
# flag on a filing record reads 1 even for filings from the current week and so
# cannot be used to pick one.
ATTACHMENT_URL = "https://www.bseindia.com/xml-data/corpfiling/{directory}/{name}"
ATTACHMENT_DIRECTORIES = ("AttachHis", "AttachLive")

# Page size is fixed server side; it is used only to recognise the last page.
PAGE_SIZE = 50
# A guard against a pagination bug looping forever. 100 pages is 5,000 filings,
# comfortably more than any company files in a decade.
MAX_PAGES = 100

# Announcements are requested a year at a time. A window BSE refuses is halved
# and retried down to MIN_WINDOW_DAYS, below which the problem is taken to be
# something other than window size and is reported rather than retried.
MAX_WINDOW_DAYS = 366
MIN_WINDOW_DAYS = 31
ONE_DAY = datetime.timedelta(days=1)


def _attachment_urls(attachment_name):
    if not attachment_name:
        return []
    return [
        ATTACHMENT_URL.format(directory=directory, name=attachment_name)
        for directory in ATTACHMENT_DIRECTORIES
    ]


# Some companies put nothing useful in the headline. Infosys files almost
# everything as "Enclosed", which produced 150 local files all named
# "..._enclosed_....pdf". Where the headline says nothing, BSE's own
# subcategory does, so it is used to build a title worth reading.
_EMPTY_HEADLINE = re.compile(
    r"^(?:please find (?:enclosed|attached)|enclosed|attached|as enclosed|"
    r"(?:\w+ )?enclosed|n\.?a\.?|nil|-+)$",
    re.IGNORECASE,
)


def _display_title(headline, subcategory):
    headline = documents.clean(headline)
    subcategory = documents.clean(subcategory)
    if not headline or _EMPTY_HEADLINE.match(headline):
        return subcategory or headline or "filing"
    # A short headline is kept but qualified, so "Transcript" becomes
    # "Earnings Call Transcript - Transcript" rather than staying ambiguous
    # among a dozen files with the same name.
    if subcategory and len(headline) < 20 and subcategory.lower() not in headline.lower():
        return f"{subcategory} - {headline}"
    return headline


def _to_document(row, company):
    # NEWS_DT is the filing timestamp and is present on every row observed;
    # DT_TM is kept as a fallback in case an older row lacks it.
    timestamp = row.get("NEWS_DT") or row.get("DT_TM") or ""
    attachment_name = documents.clean(row.get("ATTACHMENTNAME"))

    document = documents.make_document(
        source=SOURCE,
        doc_id=row.get("NEWSID") or documents.stable_id(SOURCE, attachment_name),
        urls=_attachment_urls(attachment_name),
        title=_display_title(row.get("HEADLINE"), row.get("SUBCATNAME")),
        scrip_code=row.get("SCRIP_CD"),
        company=documents.clean(row.get("SLONGNAME")) or company,
        filed_on=timestamp[:10],
        subject=row.get("NEWSSUB"),
        category=row.get("CATEGORYNAME"),
        subcategory=row.get("SUBCATNAME"),
        # BSE reports the attachment size in the listing, which lets a dry run
        # total up a download without touching a single PDF.
        size_bytes=row.get("Fld_Attachsize") or 0,
        raw=row,
    )
    document["referer"] = ATTACHMENT_REFERER
    document["filed_at"] = timestamp
    return document


def fetch_company_name(client, scrip_code):
    """The registered company name, or "" if BSE will not confirm the code.

    Used to label a run and to give the operator a chance to notice a mistyped
    scrip code before anything is downloaded. A failure here is never fatal:
    the name is a convenience, not part of the download path.
    """
    params = {"Debtflag": "", "scripcode": str(scrip_code), "seriesid": ""}
    try:
        payload = client.get_json(SCRIP_HEADER_URL, params=params, referer=API_REFERER)
    except SourceUnavailable:
        return ""
    if not isinstance(payload, dict):
        return ""
    return documents.clean((payload.get("Cmpname") or {}).get("FullN"))


def fetch_company_website(client, scrip_code):
    """The company's own website as BSE records it, or "".

    BSE holds this in the registered-office block of its company information,
    written without a scheme ("www.avantel.in"), so it is normalised here into
    something fetchable. It is what makes the website fallback work for any
    listed company without a hand-written registry entry.
    """
    try:
        payload = client.get_json(
            CORP_INFO_URL, params={"scripcode": str(scrip_code)}, referer=API_REFERER
        )
    except SourceUnavailable:
        return ""
    if not isinstance(payload, dict):
        return ""

    rows = payload.get("Table1") or []
    url = documents.clean(rows[0].get("sURL")) if rows and isinstance(rows[0], dict) else ""
    if not url or "." not in url:
        return ""

    url = url.split(",")[0].strip().strip("/")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url + "/"


def fetch_annual_reports(client, scrip_code, from_date, to_date, company=""):
    """Annual reports from BSE's dedicated archive, which goes back decades.

    Worth a separate request because the announcement feed only carries a
    report as it was filed, so a one-year window finds one or two. This archive
    returns Infosys's 31 reports back to 1997 and Avantel's 27 back to 2000,
    each with a direct PDF link.

    Rows before roughly 2011 carry only a year, with no filing date, so the
    date window is applied against the year for those. Revised reports appear
    as separate rows and are labelled as such rather than replacing the
    original, since both were genuinely filed.
    """
    try:
        payload = client.get_json(
            ANNUAL_REPORTS_URL, params={"scripcode": str(scrip_code)}, referer=API_REFERER
        )
    except SourceUnavailable:
        # The announcement feed still carries recent annual reports, so losing
        # the archive costs depth, not the latest report. Never fatal.
        return []
    if not isinstance(payload, dict):
        return []

    collected = []
    for row in payload.get("Table") or []:
        if not isinstance(row, dict):
            continue
        url = documents.clean(row.get("PDFDownload"))
        if not url.lower().endswith(".pdf"):
            continue

        timestamp = documents.clean(row.get("revised_date_time") or row.get("Fld_AuthoriseDate"))
        year = documents.clean(row.get("Year"))
        if timestamp:
            if not from_date.isoformat() <= timestamp[:10] <= to_date.isoformat():
                continue
        elif year.isdigit():
            if not from_date.year <= int(year) <= to_date.year:
                continue

        revised = documents.clean(row.get("status")).lower() == "revised"
        document = documents.make_document(
            source=SOURCE,
            doc_id=documents.stable_id(SOURCE, url),
            urls=[url],
            title=f"Annual Report {year}" + (" (revised)" if revised else ""),
            scrip_code=documents.clean(row.get("Scripcode")) or scrip_code,
            company=documents.clean(row.get("scrip_name")) or company,
            filed_on=timestamp[:10],
            # BSE's own label for an annual report filing, so this classifies
            # through the same subcategory mapping as the announcement feed.
            subcategory="Reg. 34 (1) Annual Report",
            raw=row,
        )
        document["referer"] = ATTACHMENT_REFERER
        document["filed_at"] = timestamp or year
        collected.append(document)

    collected.sort(key=lambda document: document.get("filed_at") or "", reverse=True)
    return collected


def attachment_key(document):
    """The stored filename an attachment URL points at, for de-duplication.

    The announcement feed and the annual report archive both serve from BSE's
    corpfiling store, so the same report arrives from both under the same
    filename but wrapped in different records.
    """
    for url in document.get("urls") or []:
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
        if name:
            return name
    return ""


def _split_window(from_date, to_date, max_days):
    windows = []
    start = from_date
    while start <= to_date:
        end = min(start + datetime.timedelta(days=max_days - 1), to_date)
        windows.append((start, end))
        start = end + ONE_DAY
    return windows


def _fetch_window(client, scrip_code, from_date, to_date, company, seen_ids, collected):
    """Reads one date window. Returns False if BSE refused to serve it.

    Pages are walked until BSE returns a short page, de-duplicating by NEWSID
    because a filing added while we page can otherwise be seen twice.
    """
    for page in range(1, MAX_PAGES + 1):
        params = {
            "pageno": page,
            "strCat": "-1",
            "strPrevDate": from_date.strftime("%Y%m%d"),
            "strScrip": str(scrip_code),
            "strSearch": "P",
            "strToDate": to_date.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": "-1",
        }
        payload = client.get_json(ANNOUNCEMENTS_URL, params=params, referer=API_REFERER)
        if not isinstance(payload, dict):
            raise SourceUnavailable(
                f"BSE returned {type(payload).__name__} where an object was expected"
            )

        # A query BSE will not serve comes back as {} -- no error, no status,
        # simply an empty envelope. A window that genuinely holds nothing still
        # carries Table and Table1 with ROWCNT 0, so the two are distinguishable
        # and must be: treating {} as "no filings" reports a busy company as
        # silent, which is the worst kind of wrong answer.
        if "Table" not in payload:
            return False

        rows = payload.get("Table") or []
        if not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue
            document = _to_document(row, company)
            if document["doc_id"] in seen_ids:
                continue
            seen_ids.add(document["doc_id"])
            collected.append(document)

        if len(rows) < PAGE_SIZE:
            break

    return True


def fetch_documents(client, scrip_code, from_date, to_date, company=""):
    """Every announcement filed for `scrip_code` between the two dates.

    Both dates are datetime.date and inclusive.

    The request is split into windows of at most a year, and any window BSE
    refuses is halved and retried. The refusal appears to be about how much
    work a single query costs rather than a fixed row count -- Avantel's three
    years and 271 filings are served, while MTAR Technologies' three years are
    not, though its two years and 246 filings are.
    """
    collected = []
    seen_ids = set()
    pending = collections.deque(_split_window(from_date, to_date, MAX_WINDOW_DAYS))

    while pending:
        start, end = pending.popleft()
        if _fetch_window(client, scrip_code, start, end, company, seen_ids, collected):
            continue

        span = (end - start).days + 1
        if span <= MIN_WINDOW_DAYS:
            raise SourceUnavailable(
                f"BSE would not serve announcements for scrip {scrip_code} between "
                f"{start} and {end}, even across only {span} days"
            )
        middle = start + datetime.timedelta(days=span // 2)
        pending.appendleft((middle, end))
        pending.appendleft((start, middle - ONE_DAY))

    collected.sort(key=lambda document: document.get("filed_at") or "", reverse=True)
    return collected

