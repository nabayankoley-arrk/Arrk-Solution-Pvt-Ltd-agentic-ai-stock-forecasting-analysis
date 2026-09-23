"""A company's own website as a fallback document source.

BSE is the primary source and should be preferred: it is one integration, it
is complete for anything a company is legally obliged to file, and it carries
a filing date. A company website is the fallback for what BSE does not have --
most often earnings-call and AGM transcripts, which smaller companies are not
required to file and therefore publish only on their own investor pages.

No per-company setup is needed for the ordinary case. BSE records each listed
company's own website in its company information, so the address is discovered
rather than configured, and the strategy is worked out by looking at what the
site serves:

    html_links  a conventional page whose PDF links are in the HTML
    js_bundle   a JavaScript single-page app whose document list is compiled
                into its script bundle, so nothing useful is in the HTML
    auto        the default: try both and merge, following the site's own
                navigation to a handful of investor pages

Avantel is the worked example of the second kind: avantel.in serves a React
shell with an empty <div id="root">, and its 800-odd documents live as
{name, pdf} pairs inside a content-hashed bundle. Discovery handles it without
help, as it did for 7 of 8 companies sampled on 2026-09-03.

companies.json exists for the cases where discovery fails or gets it wrong, and
an entry there always wins. What it cannot rescue is a site behind a
bot-protection challenge, which needs a browser engine rather than a different
URL. Expect coverage here to stay narrower and less reliable than BSE's; that
is why this is the fallback and not the primary source.
"""

import json
import pathlib
import re
import urllib.parse
import urllib.robotparser

from .. import documents
from ..errors import ConfigurationError, SourceUnavailable

SOURCE = "company_site"

REGISTRY_PATH = pathlib.Path(__file__).resolve().parent.parent / "companies.json"

# Matches the {name:"...",pdf:"..."} pairs a bundler emits for an object
# literal, tolerating whitespace and either quote style.
_BUNDLE_ENTRY = re.compile(
    r"""[{,]\s*name\s*:\s*["']([^"']+)["']\s*,\s*pdf\s*:\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+\.js)["']""", re.IGNORECASE)
_ANCHOR = re.compile(
    r"""<a[^>]+href=["']([^"']+?\.pdf)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_ANY_ANCHOR = re.compile(r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")

# Words that mark a link as leading to a company's filings rather than to its
# products or careers pages.
_INVESTOR_HINT = re.compile(
    r"investor|shareholder|financial|disclosur|annual[-_ ]?report|announcement|"
    r"corporate[-_ ]?governance|filings|results",
    re.IGNORECASE,
)
# Each discovered page costs a paced request, so the crawl stays shallow: one
# landing page plus a handful of the links it offers, never a full site walk.
MAX_DISCOVERED_PAGES = 6

_robots_cache = {}


def load_registry(path=None):
    """The per-company site configuration, keyed by scrip code as a string."""
    path = pathlib.Path(path) if path else REGISTRY_PATH
    if not path.exists():
        raise ConfigurationError(f"site registry not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            registry = json.load(handle)
    except (ValueError, OSError) as exc:
        raise ConfigurationError(f"site registry {path} could not be read: {exc}") from exc
    if not isinstance(registry, dict):
        raise ConfigurationError(f"site registry {path} must contain a JSON object")
    return registry


def site_config(scrip_code, registry=None):
    """The entry for a scrip code, or None when no site is configured.

    Returning None rather than raising is deliberate: most companies will not
    have an entry, and that is an ordinary outcome of a fallback lookup, not an
    error.
    """
    registry = registry if registry is not None else load_registry()
    entry = registry.get(str(scrip_code))
    if entry is None:
        return None
    if not isinstance(entry, dict) or not entry.get("base_url"):
        raise ConfigurationError(
            f"site registry entry for {scrip_code} needs at least a base_url"
        )
    strategy = entry.get("strategy", "html_links")
    if strategy not in STRATEGIES:
        raise ConfigurationError(
            f"site registry entry for {scrip_code} names unknown strategy {strategy!r}; "
            f"known: {', '.join(sorted(STRATEGIES))}"
        )
    return entry


def robots_allows(client, url):
    """Whether the site's robots.txt permits fetching this URL.

    A missing or unreadable robots.txt is treated as permission, which is the
    conventional reading. The result is cached per host so a run costs one
    extra request in total.
    """
    parts = urllib.parse.urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host in _robots_cache:
        return _robots_cache[host].can_fetch("*", url)

    parser = urllib.robotparser.RobotFileParser()
    try:
        body = client.get_text(urllib.parse.urljoin(host, "/robots.txt"))
        parser.parse(body.splitlines())
    except SourceUnavailable:
        parser.parse([])
    _robots_cache[host] = parser
    return parser.can_fetch("*", url)


def _absolute(base_url, path):
    # Document paths on these sites routinely contain spaces and other
    # characters that must be percent-encoded, but some are already encoded.
    # Marking % safe prevents a second round of encoding.
    return urllib.parse.urljoin(base_url, urllib.parse.quote(path, safe="/%:?&=#"))


def _make(entry, scrip_code, title, url):
    title = documents.clean(title)
    return documents.make_document(
        source=SOURCE,
        doc_id=documents.stable_id(SOURCE, url),
        urls=[url],
        title=title,
        scrip_code=scrip_code,
        company=entry.get("company", ""),
        # Company sites almost never publish a filing date as a field, so the
        # date written into the title or filename is the only one available.
        filed_on=documents.date_from_text(title) or documents.date_from_text(url),
        raw={"url": url, "title": title},
    )


def _harvest_js_bundle(client, entry, scrip_code):
    """Reads the document list out of a single-page app's script bundle."""
    base_url = entry["base_url"]
    index = client.get_text(base_url)

    bundles = entry.get("bundles") or [
        src for src in _SCRIPT_SRC.findall(index) if "/static/js/" in src
    ]
    if not bundles:
        raise SourceUnavailable(
            f"no script bundle found at {base_url}; the site layout has probably changed"
        )

    found = {}
    for bundle in bundles:
        script = client.get_text(_absolute(base_url, bundle), referer=base_url)
        for title, path in _BUNDLE_ENTRY.findall(script):
            if not path.lower().endswith(".pdf"):
                continue
            url = _absolute(base_url, path)
            found.setdefault(url, title)

    return [_make(entry, scrip_code, title, url) for url, title in found.items()]


def _harvest_html_links(client, entry, scrip_code):
    """Reads PDF links out of ordinary HTML pages."""
    base_url = entry["base_url"]
    pages = entry.get("pages") or [base_url]

    found = {}
    problems = []
    for page in pages:
        page_url = _absolute(base_url, page)
        try:
            html = client.get_text(page_url, referer=base_url)
        except SourceUnavailable as exc:
            # One unreachable page must not discard what the others yielded.
            problems.append(str(exc))
            continue
        for href, label in _ANCHOR.findall(html):
            url = _absolute(page_url, href)
            title = documents.clean(_TAGS.sub(" ", label)) or pathlib.Path(href).stem
            found.setdefault(url, title)

    if not found and problems:
        raise SourceUnavailable("; ".join(problems))
    return [_make(entry, scrip_code, title, url) for url, title in found.items()]


def _discover_pages(index_html, limit=MAX_DISCOVERED_PAGES):
    """Links from a landing page that look like investor or filings pages.

    Guessing at paths such as /investors would cost a request each and mostly
    404. Following the site's own navigation is both cheaper and more likely to
    be right, since a company that publishes documents links to them.
    """
    seen = []
    for href, label in _ANY_ANCHOR.findall(index_html):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        haystack = f"{href} {_TAGS.sub(' ', label)}"
        if _INVESTOR_HINT.search(haystack) and href not in seen:
            seen.append(href)
        if len(seen) >= limit:
            break
    return seen


def _harvest_auto(client, entry, scrip_code):
    """Works out how a site publishes documents, then reads it.

    Both strategies are tried and their results merged, because a site can be
    a mixture: a server-rendered investor page listing annual reports, with a
    JavaScript component holding everything else. Neither failing is fatal on
    its own -- only finding nothing at all is worth reporting.
    """
    base_url = entry["base_url"]
    index = client.get_text(base_url)

    pages = [base_url] + _discover_pages(index)
    merged = {}
    problems = []

    try:
        for document in _harvest_html_links(client, {**entry, "pages": pages}, scrip_code):
            merged.setdefault(document["urls"][0], document)
    except SourceUnavailable as exc:
        problems.append(f"html_links: {exc}")

    # Worth trying whenever the page carries script bundles at all; a site that
    # renders its documents server-side simply yields nothing here.
    if _SCRIPT_SRC.search(index):
        try:
            for document in _harvest_js_bundle(client, entry, scrip_code):
                merged.setdefault(document["urls"][0], document)
        except SourceUnavailable as exc:
            problems.append(f"js_bundle: {exc}")

    if not merged and problems:
        raise SourceUnavailable("; ".join(problems))
    return list(merged.values())


STRATEGIES = {
    "auto": _harvest_auto,
    "html_links": _harvest_html_links,
    "js_bundle": _harvest_js_bundle,
}


def fetch_documents(
    client, scrip_code, registry=None, base_url=None, respect_robots=True
):
    """Every PDF the company's site publishes, or [] when there is no site.

    A registry entry wins when one exists, because it encodes something that
    was verified by hand. Otherwise `base_url` is used with automatic strategy
    detection -- that is the ordinary path, since BSE publishes the website for
    every listed company and the registry exists only to correct the cases
    where detection fails.

    Raises ConfigurationError for a malformed registry entry or a site that
    disallows crawling, and SourceUnavailable when the site cannot be read.
    Neither is fatal to a run that already has BSE results; the caller decides.
    """
    entry = site_config(scrip_code, registry)
    if entry is None:
        if not base_url:
            return []
        entry = {"base_url": base_url, "strategy": "auto", "company": ""}

    site_url = entry["base_url"]
    if respect_robots and not robots_allows(client, site_url):
        raise ConfigurationError(
            f"{site_url} disallows automated access in robots.txt; not fetching"
        )

    harvest = STRATEGIES[entry.get("strategy", "auto")]
    found = harvest(client, entry, scrip_code)
    found.sort(
        key=lambda document: (document.get("filed_on") or "", document["title"]), reverse=True
    )
    return found
