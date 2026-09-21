"""Offline smoke test for the document fetcher.

Nothing here touches the network. Two things rot silently and are covered in
detail: the classification rules, because BSE renaming a subcategory turns a
download into a quiet "nothing to download"; and the failure paths, because
they are by definition the code least exercised by a working run.

    python -m ingestion.smoke_test   # from the backend/ directory

For a live check, use the inventory command instead:

    python -m ingestion inventory avantel --years 3
"""

import datetime
import json
import pathlib
import tempfile

from . import collect, config, documents, downloader, extract, taxonomy
from .errors import ConfigurationError, SourceUnavailable
from .sources import bse, company_site, scrip_master

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  pass  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}{' -- ' + detail if detail else ''}")


def check_raises(label, exception_type, call):
    try:
        call()
    except exception_type:
        print(f"  pass  {label}")
    except Exception as exc:  # noqa: BLE001 - the point is to report the wrong type
        failures.append(label)
        print(f"  FAIL  {label} -- raised {type(exc).__name__}: {exc}")
    else:
        failures.append(label)
        print(f"  FAIL  {label} -- nothing raised")


# --- fakes ---

class FakeResponse:
    def __init__(self, status_code=200, body=b"", content_type="application/pdf", explode=False):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self._body = body
        self._explode = explode
        self.closed = False

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start:start + size]
        if self._explode:
            import requests
            raise requests.ConnectionError("connection reset mid-body")

    def close(self):
        self.closed = True


class FakeClient:
    """Serves canned responses by URL. Anything unlisted is unreachable."""

    def __init__(self, streams=None, texts=None, payloads=None):
        self.streams = streams or {}
        self.texts = texts or {}
        self.payloads = payloads or {}
        self.opened = []
        self.fetched = []

    def open_stream(self, url, referer=None):
        self.opened.append(url)
        if url not in self.streams:
            raise SourceUnavailable(f"{url} failed after 3 attempts (ConnectionError)")
        return self.streams[url]

    def get_text(self, url, referer=None):
        self.fetched.append(url)
        if url not in self.texts:
            raise SourceUnavailable(f"{url} failed after 3 attempts (ConnectionError)")
        return self.texts[url]

    def get_json(self, url, params=None, referer=None):
        if url not in self.payloads:
            raise SourceUnavailable(f"{url} failed after 3 attempts (ConnectionError)")
        return self.payloads[url]


PDF = b"%PDF-1.4\n" + b"x" * 4000


def a_document(doc_id="d" * 16, urls=("https://example.test/a.pdf",), title="Financial Results"):
    return documents.make_document(
        source="test", doc_id=doc_id, urls=list(urls), title=title, scrip_code=532406,
        company="Test Ltd", filed_on="2026-01-15",
    )


# --- classification ---

SAMPLE_DOCUMENTS = [
    ("annual_report", {"subcategory": "Reg. 34 (1) Annual Report",
                       "title": "Annual Report for the year 2025-26"}),
    ("results", {"subcategory": "Financial Results", "title": "Outcome of Board Meeting"}),
    ("results", {"subcategory": "Integrated Filing (Financial)",
                 "title": "Integrated Filing for the quarter ended June 2026"}),
    ("board_meeting", {"subcategory": "Board Meeting",
                       "title": "Board Meeting Intimation for considering results"}),
    ("presentation", {"subcategory": "Investor Presentation",
                      "title": "Investor Presentation Q1 FY27"}),
    ("transcript", {"subcategory": "Earnings Call Transcript",
                    "title": "Transcript of the earnings conference call"}),
    ("credit_rating", {"subcategory": "Credit Rating", "title": "Intimation of Credit Rating"}),
    ("agm_egm", {"subcategory": "AGM", "title": "Notice of 36th Annual General Meeting"}),
    ("pledge", {"subcategory": "Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011",
                "title": "Disclosure of encumbrance on shares"}),
    ("management_change", {"subcategory": "Change in Directorate",
                           "title": "Resignation of Director"}),
    ("order_win", {"subcategory": "Award of Order / Receipt of Order",
                   "title": "Intimation with regard to Receipt of Purchase Order"}),
    # Filed under a generic subcategory, or harvested from a website, so only
    # the title rules can catch these. This is the bucket that breaks first.
    ("credit_rating", {"subcategory": "General",
                       "title": "Announcement under Reg.30 - CRISIL rating rationale"}),
    ("transcript", {"subcategory": "", "title": "Avantel Limited - AGM Transcript 23.06.2025"}),
    ("management_change", {"subcategory": "General",
                           "title": "Cessation of Chief Financial Officer"}),
    ("order_win", {"subcategory": "General",
                   "title": "Company has bagged a work order from Indian Navy"}),
    ("order_win", {"subcategory": "General", "title": "",
                   "subject": "Announcement_under_Regulation_30_Award_of_Order_Receipt_of_Order"}),
]


def test_classification():
    print("--- classification ---")
    for expected, fields in SAMPLE_DOCUMENTS:
        document = {"subcategory": "", "category": "", "title": "", "subject": ""}
        document.update(fields)
        matched = taxonomy.classify(document)
        shown = (fields.get("title") or fields.get("subject") or "")[:50]
        check(f"{expected:<18} <- {shown}", expected in matched, f"matched {matched}")

    print("\n--- documents that should match no type ---")
    for title in ("Closure of Trading Window", "Newspaper Publication",
                  "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018"):
        document = {"subcategory": title, "category": "", "title": title, "subject": ""}
        matched = taxonomy.classify(document)
        check(f"no match for {title[:45]}", not matched, f"matched {matched}")


def test_type_vetoes():
    print("\n--- an AGM notice is not an annual report ---")
    # Avantel, 30 May 2026: the notice and the report are two filings, and the
    # notice's subject line mentions both.
    notice = {
        "subcategory": "AGM", "category": "AGM/EGM",
        "title": "Notice of 36th Annual General Meeting",
        "subject": "Notice Of The 36Th Annual General Meeting (AGM) Of The Company "
                   "And Annual Report For FY 2025-26.",
    }
    check(
        "the notice is not an annual report",
        taxonomy.classify(notice) == ["agm_egm"],
        str(taxonomy.classify(notice)),
    )

    report = {
        "subcategory": "Reg. 34 (1) Annual Report", "category": "Others",
        "title": "Annual Report for the year 2025-26", "subject": "",
    }
    check("the report still is one", "annual_report" in taxonomy.classify(report))

    # Infosys, 2 June 2025: a genuine annual report whose subject also mentions
    # the AGM notice. BSE labelled it, so the veto must not touch it.
    labelled = {
        "subcategory": "Reg. 34 (1) Annual Report", "category": "Others",
        "title": "Integrated Annual Report for the Financial Year 2024-25",
        "subject": "Notice of the 44th Annual General Meeting and Integrated Annual Report",
    }
    check(
        "BSE's own label is never overruled",
        "annual_report" in taxonomy.classify(labelled),
        str(taxonomy.classify(labelled)),
    )

    # State Bank of India, 27 May 2026: a press advertisement saying the report
    # has been posted to shareholders, filed later that day than the report
    # itself, so it won "the latest annual report" until this veto existed.
    for subcategory, title in (
        ("Newspaper Publication",
         "Newspaper Publication regarding notice of dispatch of Annual Report for FY2025-26"),
        ("Newspaper Publication",
         "Newspaper Advertisement pertaining to dispatch of Annual Report"),
        ("General", "Intimation of despatch of Annual Report to shareholders"),
    ):
        advert = {"subcategory": subcategory, "category": "Company Update",
                  "title": title, "subject": ""}
        check(
            f"press notice is not a report: {title[:44]}",
            "annual_report" not in taxonomy.classify(advert),
            str(taxonomy.classify(advert)),
        )

    # The real SBI filing, same day, same words -- but BSE labelled it.
    real = {"subcategory": "Reg. 34 (1) Annual Report", "category": "Others",
            "title": "Annual Report and BRSR for FY2025-26", "subject": ""}
    check("the report filed the same day survives", "annual_report" in taxonomy.classify(real))


def test_inventory():
    print("\n--- inventory ---")
    counts = taxonomy.inventory([
        {"subcategory": "Credit Rating", "category": "", "title": "", "subject": ""},
        {"subcategory": "Closure of Trading Window", "category": "",
         "title": "Closure of Trading Window", "subject": ""},
    ])
    check("counts a classified document", counts["credit_rating"] == 1)
    check("counts an unclassified document", counts["unclassified"] == 1)
    check("reports every known type", set(taxonomy.DOCUMENT_TYPES).issubset(counts))


# --- document records ---

def test_document_helpers():
    print("\n--- document records ---")
    check("date from dd-mm-yyyy", documents.date_from_text("AGM Transcript 30-05-2022") == "2022-05-30")
    check("date from dd.mm.yyyy", documents.date_from_text("AGM TRANSCRIPT 23.06.2023") == "2023-06-23")
    check("date from yyyy-mm-dd", documents.date_from_text("report 2024-05-08 final") == "2024-05-08")
    check("no date found", documents.date_from_text("36th AGM Transcript") == "")
    check("impossible date rejected", documents.date_from_text("ref 45-99-2024") == "")
    check(
        "ids are stable and distinct",
        documents.stable_id("s", "a") == documents.stable_id("s", "a")
        != documents.stable_id("s", "b"),
    )
    check("classification is applied on construction", a_document()["doc_types"] == ["results"])


# --- selection and paths ---

def test_selection_and_paths():
    print("\n--- selection and paths ---")
    records = [
        a_document("a" * 16, ("https://x.test/ar.pdf",), "Annual Report 2025-26"),
        a_document("b" * 16, ("https://x.test/cl.pdf",), "Covering letter to the Annual Report"),
        a_document("c" * 16, ("https://x.test/data.xlsx",), "Shareholding pattern"),
        a_document("d" * 16, (), "No link at all"),
    ]
    records[0]["size_bytes"] = 16000000
    records[1]["size_bytes"] = 90000

    check("non-PDF link dropped", len(downloader.select(records)) == 2)
    check("document with no link dropped", all(r["urls"] for r in downloader.select(records)))
    check("type filter applied", len(downloader.select(records, ["annual_report"])) == 2)
    check(
        "cover letter filter is opt-in",
        len(downloader.select(records, ["annual_report"], skip_cover_letters=True)) == 1,
    )
    check("byte estimate", downloader.estimate_bytes(downloader.select(records)) == 16090000)

    first = downloader.target_path(records[0], "out")
    check("path is deterministic", first == downloader.target_path(records[0], "out"))
    check("path is typed by folder", first.parent.name == "annual_report")
    check("same-day documents do not collide", first != downloader.target_path(records[1], "out"))
    check(
        "untyped document lands in other/",
        downloader.target_path(records[3], "out").parent.name == "other",
    )

    long_title = a_document("e" * 16, ("https://x.test/a.pdf",), "Results " + "verylongword " * 40)
    long_path = downloader.target_path(long_title, "out")
    check(
        "path is shortened to stay usable on Windows",
        len(str(long_path.resolve())) <= downloader.config.MAX_PATH_CHARS,
        f"{len(str(long_path.resolve()))} chars",
    )


# --- manifest ---

def test_manifest():
    print("\n--- manifest ---")
    with tempfile.TemporaryDirectory() as temp_dir:
        entry = {"doc_id": "aaaa", "sha256": "0" * 64, "path": "results/x.pdf"}
        check("save reports no error", downloader.save_manifest(temp_dir, {"aaaa": entry}) is None)
        check("round trip", downloader.load_manifest(temp_dir) == {"aaaa": entry})

        path = downloader.manifest_path(temp_dir)
        check(
            "saved file is valid JSON",
            json.loads(pathlib.Path(path).read_text(encoding="utf-8")) == {"aaaa": entry},
        )

        path.write_text("{ not json", encoding="utf-8")
        check("corrupt manifest degrades to empty", downloader.load_manifest(temp_dir) == {})
        path.write_text('["a list, not an object"]', encoding="utf-8")
        check("wrong-shaped manifest degrades to empty", downloader.load_manifest(temp_dir) == {})
        check("missing manifest is empty", downloader.load_manifest(temp_dir + "/nope") == {})

        # A file where a directory needs to be: mkdir fails, and the manifest
        # write has nowhere to go.
        blocker = pathlib.Path(temp_dir) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        warning = downloader.save_manifest(blocker / "sub", {"a": entry})
        check("unwritable manifest is reported, not raised", isinstance(warning, str), repr(warning))


# --- downloading ---

def test_download_success():
    print("\n--- downloading: success ---")
    with tempfile.TemporaryDirectory() as temp_dir:
        document = a_document(urls=("https://example.test/a.pdf",))
        client = FakeClient(streams={"https://example.test/a.pdf": FakeResponse(body=PDF)})
        summary = downloader.download(client, [document], temp_dir)

        result = summary["results"][0]
        check("status", result["status"] == "downloaded", result["status"])
        check("byte count", result["bytes"] == len(PDF))
        check("file exists", pathlib.Path(result["path"]).exists())
        check("manifest written", len(downloader.load_manifest(temp_dir)) == 1)

        client.streams["https://example.test/a.pdf"] = FakeResponse(body=PDF)
        again = downloader.download(client, [document], temp_dir)
        check("rerun skips existing", again["results"][0]["status"] == "skipped_existing")

        twin = a_document("f" * 16, ("https://example.test/b.pdf",), "Financial Results copy")
        client.streams["https://example.test/b.pdf"] = FakeResponse(body=PDF)
        third = downloader.download(client, [twin], temp_dir)
        check("identical bytes are flagged", third["results"][0]["duplicate_of"] is not None)
        check("but the file is still kept", pathlib.Path(third["results"][0]["path"]).exists())


def test_download_failures():
    print("\n--- downloading: failures ---")
    with tempfile.TemporaryDirectory() as temp_dir:
        cases = {
            "404": FakeResponse(status_code=404),
            "html": FakeResponse(body=b"<html>error</html>", content_type="text/html"),
            "empty": FakeResponse(body=b""),
            "cut": FakeResponse(body=PDF, explode=True),
        }
        for name, response in cases.items():
            url = f"https://example.test/{name}.pdf"
            document = a_document(name.ljust(16, "0"), (url,))
            client = FakeClient(streams={url: response})
            summary = downloader.download(client, [document], temp_dir)
            result = summary["results"][0]
            check(f"{name} is recorded as failed", result["status"] == "failed", result["status"])

        check(
            "no partial files survive a failure",
            not list(pathlib.Path(temp_dir).rglob("*.part")),
        )
        check(
            "no half-written PDFs survive a failure",
            not list(pathlib.Path(temp_dir).rglob("*.pdf")),
        )

        # A second candidate URL rescues the document when the first is an
        # error page. This is exactly the BSE AttachHis/AttachLive case.
        document = a_document("g" * 16, ("https://example.test/bad.pdf", "https://example.test/good.pdf"))
        client = FakeClient(streams={
            "https://example.test/bad.pdf": FakeResponse(status_code=404),
            "https://example.test/good.pdf": FakeResponse(body=PDF),
        })
        summary = downloader.download(client, [document], temp_dir)
        check("falls back to the second URL", summary["results"][0]["status"] == "downloaded")


def test_download_aborts():
    print("\n--- downloading: aborting a hopeless run ---")
    with tempfile.TemporaryDirectory() as temp_dir:
        many = [
            a_document(f"{index:016d}", ("https://unreachable.test/x.pdf",))
            for index in range(downloader.MAX_CONSECUTIVE_SOURCE_FAILURES + 4)
        ]
        client = FakeClient()

        def run():
            downloader.download(client, many, temp_dir)

        check_raises("unreachable source aborts the run", SourceUnavailable, run)
        try:
            run()
        except SourceUnavailable as exc:
            check(
                "abort happens at the threshold, not at the end",
                len(exc.results) == downloader.MAX_CONSECUTIVE_SOURCE_FAILURES,
                f"{len(exc.results)} results",
            )

        # A budget stops the run before anything is requested.
        document = a_document(urls=("https://example.test/a.pdf",))
        document["size_bytes"] = 5_000_000
        client = FakeClient(streams={"https://example.test/a.pdf": FakeResponse(body=PDF)})
        summary = downloader.download(client, [document], temp_dir, max_total_bytes=1_000_000)
        check("budget cap is honoured", summary["results"][0]["status"] == "skipped_budget")
        check("capped document is never requested", not client.opened)


# --- company website fallback ---

BUNDLE = (
    'var docs=[{name:"Annual Report 2025-26",pdf:"Investors/25. Annual Reports/AR_2025_26.pdf"},'
    '{name:"AGM Transcript 23.06.2025",pdf:"Investors/28. AGM/Transcript_23_06_2025.pdf"},'
    "{name:\"Logo\",pdf:'assets/logo.png'}];"
)
INDEX_HTML = '<html><body><div id="root"></div><script src="/static/js/main.abc123.js"></script></body></html>'
LINKS_HTML = (
    '<html><body><a href="/docs/annual-report-2025.pdf">Annual Report <b>2025-26</b></a>'
    '<a href="https://cdn.test/transcript%2023.06.2025.pdf">AGM Transcript 23.06.2025</a>'
    '<a href="/about.html">About us</a></body></html>'
)


def test_company_site_registry():
    print("\n--- company website: registry ---")
    registry = {
        "532406": {"company": "Avantel Ltd", "base_url": "https://site.test/", "strategy": "js_bundle"},
        "111111": {"strategy": "js_bundle"},
        "222222": {"base_url": "https://site.test/", "strategy": "carrier_pigeon"},
    }
    check("known code resolves", company_site.site_config("532406", registry)["company"] == "Avantel Ltd")
    check("unknown code returns None, not an error", company_site.site_config("999999", registry) is None)
    check_raises(
        "entry without a base_url is rejected",
        ConfigurationError,
        lambda: company_site.site_config("111111", registry),
    )
    check_raises(
        "unknown strategy is rejected",
        ConfigurationError,
        lambda: company_site.site_config("222222", registry),
    )
    check_raises(
        "missing registry file is reported clearly",
        ConfigurationError,
        lambda: company_site.load_registry("no/such/companies.json"),
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        broken = pathlib.Path(temp_dir) / "companies.json"
        broken.write_text("{ not json", encoding="utf-8")
        check_raises(
            "corrupt registry file is reported clearly",
            ConfigurationError,
            lambda: company_site.load_registry(broken),
        )

    shipped = company_site.load_registry()
    check("shipped registry parses", isinstance(shipped, dict))
    check(
        "shipped registry entries are valid",
        all(
            company_site.site_config(code, shipped)
            for code in shipped
            if not code.startswith("_")
        ),
    )


def test_company_site_harvest():
    print("\n--- company website: harvesting ---")
    registry = {"1": {"company": "T", "base_url": "https://site.test/", "strategy": "js_bundle"}}
    client = FakeClient(texts={
        "https://site.test/": INDEX_HTML,
        "https://site.test/static/js/main.abc123.js": BUNDLE,
        "https://site.test/robots.txt": "User-agent: *\nDisallow:\n",
    })
    found = company_site.fetch_documents(client, "1", registry)
    check("bundle entries found", len(found) == 2, f"{len(found)} found")
    check("non-PDF entries dropped", all(d["urls"][0].endswith(".pdf") for d in found))
    check("spaces in paths are encoded", any("%20" in d["urls"][0] for d in found))
    check(
        "dates are read from titles",
        any(d["filed_on"] == "2025-06-23" for d in found),
        str([d["filed_on"] for d in found]),
    )
    check("titles are classified", any("transcript" in d["doc_types"] for d in found))

    registry = {"2": {"company": "T", "base_url": "https://site.test/", "strategy": "html_links",
                      "pages": ["investors.html"]}}
    client = FakeClient(texts={
        "https://site.test/investors.html": LINKS_HTML,
        "https://site.test/robots.txt": "User-agent: *\nDisallow:\n",
    })
    found = company_site.fetch_documents(client, "2", registry)
    check("html links found", len(found) == 2, f"{len(found)} found")
    check("link text becomes the title, tags stripped",
          any(d["title"] == "Annual Report 2025-26" for d in found),
          str([d["title"] for d in found]))
    check("already-encoded paths are not double-encoded",
          not any("%2520" in d["urls"][0] for d in found))

    check("no site configured returns nothing", company_site.fetch_documents(client, "9", {}) == [])


def test_company_site_failures():
    print("\n--- company website: failures ---")
    registry = {"1": {"company": "T", "base_url": "https://site.test/", "strategy": "js_bundle"}}
    # robots.txt answers are cached per host for the life of the process, so
    # each case here starts from a clean cache.
    company_site._robots_cache.clear()

    blocked = FakeClient(texts={"https://site.test/robots.txt": "User-agent: *\nDisallow: /\n"})
    check_raises(
        "robots.txt disallow is honoured",
        ConfigurationError,
        lambda: company_site.fetch_documents(blocked, "1", registry),
    )
    company_site._robots_cache.clear()

    check(
        "robots.txt can be overridden explicitly",
        company_site.fetch_documents(
            FakeClient(texts={
                "https://site.test/": INDEX_HTML,
                "https://site.test/static/js/main.abc123.js": BUNDLE,
            }),
            "1", registry, respect_robots=False,
        ),
    )

    unreachable = FakeClient(texts={"https://site.test/robots.txt": "User-agent: *\nDisallow:\n"})
    check_raises(
        "unreachable site is reported",
        SourceUnavailable,
        lambda: company_site.fetch_documents(unreachable, "1", registry),
    )
    company_site._robots_cache.clear()

    no_bundle = FakeClient(texts={
        "https://site.test/": "<html><body>no scripts here</body></html>",
        "https://site.test/robots.txt": "User-agent: *\nDisallow:\n",
    })
    check_raises(
        "a site whose layout changed is reported",
        SourceUnavailable,
        lambda: company_site.fetch_documents(no_bundle, "1", registry),
    )
    company_site._robots_cache.clear()


# --- naming a company ---

SCRIPS = [
    {"scrip_code": "532406", "ticker": "AVANTEL", "name": "Avantel Ltd",
     "issuer": "Avantel Limited", "isin": "INE005B01027", "group": "A", "industry": ""},
    {"scrip_code": "500325", "ticker": "RELIANCE", "name": "Reliance Industries Ltd",
     "issuer": "Reliance Industries Limited", "isin": "INE002A01018", "group": "A", "industry": ""},
    {"scrip_code": "500111", "ticker": "RELCAPITAL", "name": "Reliance Capital Ltd",
     "issuer": "Reliance Capital Limited", "isin": "INE013A01015", "group": "B", "industry": ""},
    {"scrip_code": "532539", "ticker": "RELINFRA", "name": "Reliance Infrastructure Ltd",
     "issuer": "Reliance Infrastructure Limited", "isin": "INE036A01016", "group": "B",
     "industry": ""},
]


def test_scrip_lookup():
    print("\n--- naming a company ---")
    first = lambda query: scrip_master.search(SCRIPS, query)[0]["scrip_code"]  # noqa: E731

    check("exact ticker wins", first("AVANTEL") == "532406")
    check("ticker is case insensitive", first("avantel") == "532406")
    check("scrip code resolves to itself", first("500325") == "500325")
    check("ISIN resolves", first("INE005B01027") == "532406")
    check("full name resolves", first("Reliance Industries Ltd") == "500325")
    check(
        "an exact ticker beats a name that merely contains the word",
        first("reliance") == "500325",
        str([e["name"] for e in scrip_master.search(SCRIPS, "reliance")]),
    )
    check("partial name matches several", len(scrip_master.search(SCRIPS, "reliance ")) == 3)
    check("no match returns nothing", scrip_master.search(SCRIPS, "zzzz") == [])
    check_raises(
        "an empty query is rejected",
        ConfigurationError,
        lambda: scrip_master.search(SCRIPS, "   "),
    )

    class Stub:
        def get_json(self, *args, **kwargs):
            raise AssertionError("resolve must not refetch when entries are cached")

    original = scrip_master.load
    scrip_master.load = lambda client, cache_dir=None, refresh=False: SCRIPS
    try:
        check("unambiguous query resolves", scrip_master.resolve(Stub(), "avantel")["ticker"] == "AVANTEL")
        check_raises(
            "an ambiguous name lists the options",
            ConfigurationError,
            lambda: scrip_master.resolve(Stub(), "reliance i"),
        )
        check_raises(
            "an unknown name is rejected",
            ConfigurationError,
            lambda: scrip_master.resolve(Stub(), "no such company"),
        )
        check(
            "an unlisted numeric code is passed through",
            scrip_master.resolve(Stub(), "999999")["scrip_code"] == "999999",
        )
    finally:
        scrip_master.load = original


def test_website_discovery():
    print("\n--- discovering a company website ---")
    url = bse.CORP_INFO_URL

    client = FakeClient(payloads={url: {"Table1": [{"sURL": "www.avantel.in"}]}})
    check("scheme is added", bse.fetch_company_website(client, "1") == "https://www.avantel.in/")

    client = FakeClient(payloads={url: {"Table1": [{"sURL": "https://x.test/  "}]}})
    check("an existing scheme is kept", bse.fetch_company_website(client, "1") == "https://x.test/")

    client = FakeClient(payloads={url: {"Table1": [{"sURL": "a.test, b.test"}]}})
    check("only the first of several is used", bse.fetch_company_website(client, "1") == "https://a.test/")

    for label, payload in (
        ("blank", {"Table1": [{"sURL": ""}]}),
        ("not a URL", {"Table1": [{"sURL": "NA"}]}),
        ("no rows", {"Table1": []}),
        ("unexpected shape", {"Table1": "nonsense"}),
    ):
        client = FakeClient(payloads={url: payload})
        check(f"{label} yields no website", bse.fetch_company_website(client, "1") == "")

    check(
        "an unreachable endpoint yields no website, not an error",
        bse.fetch_company_website(FakeClient(), "1") == "",
    )


NAV_HTML = (
    '<html><body>'
    '<a href="/products">Products</a>'
    '<a href="/investor-relations">Investor Relations</a>'
    '<a href="/careers">Careers</a>'
    '<a href="/financials.html">Financial Information</a>'
    '<a href="mailto:x@y.test">Investors email</a>'
    '<script src="/static/js/main.abc123.js"></script>'
    "</body></html>"
)


def test_auto_strategy():
    print("\n--- working out how a site publishes ---")
    pages = company_site._discover_pages(NAV_HTML)
    check("investor pages are followed", "/investor-relations" in pages)
    check("financial pages are followed", "/financials.html" in pages)
    check("unrelated pages are ignored", "/products" not in pages and "/careers" not in pages)
    check("mailto links are ignored", not any(p.startswith("mailto:") for p in pages))
    check("the crawl stays shallow", len(pages) <= company_site.MAX_DISCOVERED_PAGES)

    company_site._robots_cache.clear()
    client = FakeClient(texts={
        "https://site.test/robots.txt": "User-agent: *\nDisallow:\n",
        "https://site.test/": NAV_HTML,
        "https://site.test/investor-relations": LINKS_HTML,
        "https://site.test/financials.html": "<html>nothing here</html>",
        "https://site.test/static/js/main.abc123.js": BUNDLE,
    })
    found = company_site.fetch_documents(client, "1", registry={}, base_url="https://site.test/")
    titles = {document["title"] for document in found}
    check("both strategies contribute", len(found) == 4, f"{len(found)}: {sorted(titles)}")
    check("html links are included", "Annual Report 2025-26" in titles)
    check("bundle entries are included", "AGM Transcript 23.06.2025" in titles)

    company_site._robots_cache.clear()
    check(
        "no website and no entry means no documents",
        company_site.fetch_documents(client, "1", registry={}, base_url="") == [],
    )

    company_site._robots_cache.clear()
    registry = {"1": {"company": "T", "base_url": "https://pinned.test/", "strategy": "html_links",
                      "pages": ["investors.html"]}}
    client = FakeClient(texts={
        "https://pinned.test/robots.txt": "User-agent: *\nDisallow:\n",
        "https://pinned.test/investors.html": LINKS_HTML,
    })
    found = company_site.fetch_documents(
        client, "1", registry=registry, base_url="https://discovered.test/"
    )
    check("a registry entry overrides discovery", len(found) == 2 and all(
        "pinned.test" in document["urls"][0] or "cdn.test" in document["urls"][0]
        for document in found
    ))


def test_report_types_only():
    print("\n--- reports, not every filing ---")
    reports = [
        a_document("a" * 16, ("https://x.test/a.pdf",), "Annual Report 2025-26"),
        a_document("b" * 16, ("https://x.test/b.pdf",), "Financial Results for Q1"),
    ]
    # What a large company actually files most of: real filings, but not
    # reports. Infosys filed 177 of these in a year against 42 reports.
    noise = [
        a_document("c" * 16, ("https://x.test/c.pdf",), "Allotment of equity shares towards ESOPs"),
        a_document("d" * 16, ("https://x.test/d.pdf",), "Loss of share certificates"),
        a_document("e" * 16, ("https://x.test/e.pdf",), "Newspaper Publication"),
    ]
    everything = reports + noise
    check("no types requested means reports only", len(downloader.select(everything)) == 2)
    check(
        "the firehose is available on request",
        len(downloader.select(everything, include_unclassified=True)) == 5,
    )
    check(
        "an explicit type request is unaffected",
        len(downloader.select(everything, ["annual_report"])) == 1,
    )


def test_availability():
    print("\n--- take whichever of the wanted types exists ---")
    wanted = list(config.DEFAULT_DOCUMENT_TYPES)
    check(
        "the default pair is annual report and transcript",
        wanted == ["annual_report", "transcript"],
        str(wanted),
    )

    report = a_document("a" * 16, ("https://x.test/a.pdf",), "Annual Report 2025-26")
    transcript = a_document("b" * 16, ("https://x.test/b.pdf",), "Earnings Call Transcript")

    both = downloader.availability([report, transcript], wanted)
    check("both present are counted", both == {"annual_report": 1, "transcript": 1}, str(both))
    check("nothing is missing", not [k for k, v in both.items() if not v])

    one = downloader.availability([report], wanted)
    check("only one present still reports the other", one == {"annual_report": 1, "transcript": 0}, str(one))
    check("the absent one is identifiable", [k for k, v in one.items() if not v] == ["transcript"])

    neither = downloader.availability([], wanted)
    check("neither present", neither == {"annual_report": 0, "transcript": 0}, str(neither))

    check(
        "counts follow the requested order",
        list(downloader.availability([], ["transcript", "annual_report"]))
        == ["transcript", "annual_report"],
    )

    # A document matching two types counts under each requested one.
    dual = a_document("c" * 16, ("https://x.test/c.pdf",), "AGM Transcript 23.06.2025")
    counts = downloader.availability([dual], ["transcript", "agm_egm"])
    check("a multi-type document counts once per type", counts == {"transcript": 1, "agm_egm": 1}, str(counts))

    check(
        "types outside the request are ignored",
        downloader.availability([dual], ["annual_report"]) == {"annual_report": 0},
    )


def test_keep_latest():
    print("\n--- keeping only the latest ---")

    def dated(doc_id, title, filed_on):
        document = a_document(doc_id, ("https://x.test/" + doc_id + ".pdf",), title)
        document["filed_on"] = filed_on
        return document

    documents_in = [
        dated("ar26" + "0" * 12, "Annual Report 2025-26", "2026-05-30"),
        dated("ar25" + "0" * 12, "Annual Report 2024-25", "2025-05-31"),
        dated("ar24" + "0" * 12, "Annual Report 2023-24", "2024-05-08"),
        dated("re26" + "0" * 12, "Financial Results for Q1", "2026-07-23"),
        dated("re25" + "0" * 12, "Financial Results for Q4", "2026-04-23"),
    ]

    latest = downloader.keep_latest(documents_in, 1)
    titles = {document["title"] for document in latest}
    check("one of each type, not one overall", len(latest) == 2, str(sorted(titles)))
    check("the newest annual report wins", "Annual Report 2025-26" in titles)
    check("the newest results win", "Financial Results for Q1" in titles)

    check("two of each type", len(downloader.keep_latest(documents_in, 2)) == 4)
    check("asking for more than exists is harmless",
          len(downloader.keep_latest(documents_in, 99)) == 5)
    check("no limit passes everything through",
          len(downloader.keep_latest(documents_in, None)) == 5)

    check(
        "a type filter narrows what is counted",
        {document["title"] for document in
         downloader.keep_latest(documents_in, 1, wanted_types=["annual_report"])}
        == {"Annual Report 2025-26"},
    )

    # A document matching two types must not be returned twice.
    both = dated("both" + "0" * 12, "Outcome of Board Meeting: Financial Results", "2026-08-01")
    both["doc_types"] = ["results", "board_meeting"]
    kept = downloader.keep_latest([both], 1)
    check("a multi-type document is returned once", len(kept) == 1)

    undated = a_document("un" + "0" * 14, ("https://x.test/u.pdf",), "Annual Report, undated")
    undated["filed_on"] = ""
    kept = downloader.keep_latest([undated, documents_in[0]], 1)
    check(
        "an undated document does not displace a dated one",
        [document["title"] for document in kept] == ["Annual Report 2025-26"],
        str([document["title"] for document in kept]),
    )
    check("but it is kept when it is all there is",
          len(downloader.keep_latest([undated], 1)) == 1)


def test_display_titles():
    print("\n--- titles worth reading ---")
    title = bse._display_title
    check(
        "an empty headline falls back to the subcategory",
        title("Enclosed", "Earnings Call Transcript") == "Earnings Call Transcript",
    )
    check("so does a blank one", title("", "Credit Rating") == "Credit Rating")
    check("and so do the variants", title("Disclosure enclosed", "Credit Rating") == "Credit Rating")
    check("and placeholders", title("NA", "Board Meeting") == "Board Meeting")
    check(
        "a short headline is qualified, not replaced",
        title("Transcript", "Earnings Call Transcript")
        == "Earnings Call Transcript - Transcript",
    )
    check(
        "a real headline is left alone",
        title("Financial Results for the quarter ended June 30, 2026", "Financial Results")
        == "Financial Results for the quarter ended June 30, 2026",
    )
    check(
        "nothing at all still yields a usable name",
        title("", "") == "filing",
    )
    check(
        "a short headline already naming its subcategory is not doubled",
        title("Credit Rating", "Credit Rating") == "Credit Rating",
    )


ARCHIVE_ROWS = {
    "Table": [
        {"Scripcode": "500209", "scrip_name": "Infosys Ltd", "Year": "2026",
         "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aa.pdf",
         "revised_date_time": "2026-05-30T20:04:09.06", "Fld_AuthoriseDate": None,
         "status": "Revised"},
        {"Scripcode": "500209", "scrip_name": "Infosys Ltd", "Year": "2026",
         "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/bb.pdf",
         "revised_date_time": None, "Fld_AuthoriseDate": "2026-05-29T20:11:20.78",
         "status": "New"},
        {"Scripcode": "500209", "scrip_name": "Infosys Ltd", "Year": "2015",
         "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/cc.pdf",
         "revised_date_time": None, "Fld_AuthoriseDate": "2015-06-02T15:39:26.473",
         "status": "New"},
        # Pre-2011 rows carry a year and no date at all.
        {"Scripcode": "500209", "scrip_name": "Infosys Ltd", "Year": "1998",
         "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/dd.pdf",
         "revised_date_time": None, "Fld_AuthoriseDate": None, "status": "New"},
        {"Scripcode": "500209", "scrip_name": "Infosys Ltd", "Year": "2020",
         "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/notapdf.zip",
         "revised_date_time": None, "Fld_AuthoriseDate": "2020-06-02T15:39:26.473",
         "status": "New"},
    ]
}


def test_annual_report_archive():
    print("\n--- BSE's annual report archive ---")
    client = FakeClient(payloads={bse.ANNUAL_REPORTS_URL: ARCHIVE_ROWS})
    wide = bse.fetch_annual_reports(
        client, "500209", datetime.date(1990, 1, 1), datetime.date(2026, 12, 31)
    )
    titles = [document["title"] for document in wide]
    check("every dated and undated row is read", len(wide) == 4, str(titles))
    check("non-PDF rows are dropped", not any(".zip" in d["urls"][0] for d in wide))
    check("a revised report is labelled", "Annual Report 2026 (revised)" in titles)
    check("an original is not", "Annual Report 2026" in titles)
    check(
        "all classify as annual reports",
        all(document["doc_types"] == ["annual_report"] for document in wide),
        str([d["doc_types"] for d in wide]),
    )
    check("newest first", titles[0] == "Annual Report 2026 (revised)", str(titles))
    check(
        "a revision takes its revision date",
        wide[0]["filed_on"] == "2026-05-30",
        wide[0]["filed_on"],
    )

    narrow = bse.fetch_annual_reports(
        client, "500209", datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
    )
    check("the date window is applied", len(narrow) == 2, str([d["title"] for d in narrow]))

    by_year = bse.fetch_annual_reports(
        client, "500209", datetime.date(1997, 1, 1), datetime.date(1999, 12, 31)
    )
    check(
        "an undated row is filtered on its year",
        [document["title"] for document in by_year] == ["Annual Report 1998"],
        str([d["title"] for d in by_year]),
    )

    check(
        "an unreachable archive is not fatal",
        bse.fetch_annual_reports(
            FakeClient(), "500209", datetime.date(2020, 1, 1), datetime.date(2026, 1, 1)
        ) == [],
    )


def test_archive_wins_on_annual_reports():
    print("\n--- the archive decides what an annual report is ---")

    def announced(key, title, types):
        document = a_document(
            key.ljust(16, "0"),
            (f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{key}.pdf",),
            title,
        )
        document["doc_types"] = list(types)
        return document

    def archived(key, title="Annual Report 2026"):
        document = a_document(
            key.ljust(16, "1"),
            (f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{key}.pdf",),
            title,
        )
        document["doc_types"] = ["annual_report"]
        return document

    # Reliance: the announcement stream offered an AGM notice under the annual
    # report subcategory, filed after the report. It must lose the label but
    # stay an agm_egm.
    notice = announced("aa", "Notice convening the 49th AGM", ["annual_report", "agm_egm"])
    letter = announced("bb", "Letter to shareholders re the Annual Report", ["annual_report"])
    unrelated = announced("cc", "Earnings Call Transcript", ["transcript"])
    report = archived("dd")

    merged = collect._merge_archive([notice, letter, unrelated], [report])
    kinds = {d["title"]: d["doc_types"] for d in merged}
    check("the archive report is present", "annual_report" in kinds["Annual Report 2026"])
    check(
        "an AGM notice is demoted but kept",
        kinds["Notice convening the 49th AGM"] == ["agm_egm"],
        str(kinds.get("Notice convening the 49th AGM")),
    )
    check(
        "a bare covering letter loses every type",
        kinds["Letter to shareholders re the Annual Report"] == [],
    )
    check("unrelated documents are untouched", kinds["Earnings Call Transcript"] == ["transcript"])
    check("nothing is duplicated", len(merged) == 4, f"{len(merged)} documents")

    # TCS: the same file in both feeds. This is the case that silently lost the
    # report when the archive copy was dropped as a duplicate.
    same_in_both = announced("ee", "Integrated Annual Report 2025-26", ["annual_report"])
    merged = collect._merge_archive([same_in_both], [archived("ee")])
    check("the same file survives as one document", len(merged) == 1, f"{len(merged)}")
    check("and it is still an annual report", merged[0]["doc_types"] == ["annual_report"])

    # BDL: one PDF that is both the report and the AGM notice. The extra type
    # must survive the swap to the archive copy.
    combined = announced("ff", "Annual Report and 56th AGM Notice", ["annual_report", "agm_egm"])
    merged = collect._merge_archive([combined], [archived("ff")])
    check(
        "extra types carry across to the archive copy",
        merged[0]["doc_types"] == ["annual_report", "agm_egm"],
        str(merged[0]["doc_types"]),
    )

    check("an empty archive leaves everything alone",
          len(collect._merge_archive([notice, unrelated], [])) == 2)


def test_attachment_key():
    print("\n--- de-duplicating across BSE feeds ---")
    key = bse.attachment_key
    announced = {"urls": [
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/aa-bb.pdf",
        "https://www.bseindia.com/xml-data/corpfiling/AttachLive/aa-bb.pdf",
    ]}
    archived = {"urls": ["https://www.bseindia.com/xml-data/corpfiling/AttachHis/AA-BB.pdf"]}
    check("the stored filename is the key", key(announced) == "aa-bb.pdf")
    check(
        "the same file from either feed collides",
        key(announced) == key(archived),
        f"{key(announced)} vs {key(archived)}",
    )
    check(
        "a different file does not",
        key(announced) != key({"urls": ["https://x.test/cc-dd.pdf"]}),
    )
    check("a query string is ignored", key({"urls": ["https://x.test/e.pdf?v=2"]}) == "e.pdf")
    check("no URL yields no key", key({"urls": []}) == "")


def test_extract_helpers():
    print("\n--- reading PDFs ---")
    check_raises(
        "a missing file is reported, not crashed on",
        extract.NotExtractable,
        lambda: extract.extract("no/such/file.pdf"),
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        bogus = pathlib.Path(temp_dir) / "not-really.pdf"
        bogus.write_bytes(b"this is not a PDF")
        check_raises(
            "a file that is not a PDF is reported",
            extract.NotExtractable,
            lambda: extract.extract(bogus),
        )

    body = "para one\n\n" + ("x" * 500) + "\n\n" + ("y" * 500)
    check("no cap means no truncation", extract.head(body, None) == body)
    check("a cap above the length is a no-op", extract.head(body, 99999) == body)
    capped = extract.head(body, 600)
    check("a cap truncates", len(capped) <= 600)
    check(
        "truncation prefers a paragraph break near the cut",
        capped.endswith("x" * 10),
        repr(capped[-20:]),
    )
    # A document with no blank lines must not be cut back to almost nothing.
    solid = "z" * 1000
    check("a document with no breaks is cut at the cap", len(extract.head(solid, 600)) == 600)


def test_report_type_abbreviations():
    print("\n--- AR / TR abbreviations ---")
    from db import documents as store

    check("an annual report is AR", store.report_type_for(["annual_report"]) == "AR")
    check("a transcript is TR", store.report_type_for(["transcript"]) == "TR")
    check(
        "a document that is both is stored as the annual report",
        store.report_type_for(["transcript", "annual_report"]) == "AR",
    )
    check("anything else is neither", store.report_type_for(["results", "agm_egm"]) is None)
    check("no types at all is neither", store.report_type_for([]) is None)
    check("a combined report and AGM notice is AR",
          store.report_type_for(["annual_report", "agm_egm"]) == "AR")


if __name__ == "__main__":
    test_classification()
    test_type_vetoes()
    test_inventory()
    test_document_helpers()
    test_selection_and_paths()
    test_manifest()
    test_download_success()
    test_download_failures()
    test_download_aborts()
    test_company_site_registry()
    test_company_site_harvest()
    test_company_site_failures()
    test_scrip_lookup()
    test_website_discovery()
    test_auto_strategy()
    test_report_types_only()
    test_availability()
    test_keep_latest()
    test_display_titles()
    test_annual_report_archive()
    test_archive_wins_on_annual_reports()
    test_attachment_key()
    test_extract_helpers()
    test_report_type_abbreviations()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("all checks passed")
