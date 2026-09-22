"""Tuning constants shared by every document source.

Source-specific endpoints live with their source, in ingestion/sources/.
"""

# Sent to every host. Both BSE and the company sites tested serve a different
# response, or none at all, to a client that does not look like a browser.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- politeness and resilience ---
REQUEST_TIMEOUT_SECONDS = 30
# Applied per host, so pacing BSE does not also slow a company site. Neither
# publishes a documented rate limit, so this is a conservative choice rather
# than a measured one.
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# A transfer that dies mid-body is retried from the start; there is no resume,
# because neither source reliably honours a Range request.
MAX_TRANSFER_ATTEMPTS = 2

# --- downloads ---
CHUNK_BYTES = 65536
# Checked against the first bytes of every download. Both sources answer some
# requests with an HTML error page under a 200 status, and without this check
# those are silently saved as .pdf files.
PDF_MAGIC = b"%PDF"
PARTIAL_SUFFIX = ".part"
MANIFEST_FILENAME = "manifest.json"

# Windows refuses paths beyond 260 characters unless long paths are enabled,
# and the failure surfaces as a confusing OSError deep in a download. Filenames
# are shortened to keep the whole path under this.
MAX_PATH_CHARS = 240

# Refuse to start a download that would leave less than this much free space.
FREE_SPACE_MARGIN_BYTES = 256 * 1024 * 1024

# A download larger than this needs an explicit --yes or --max-mb. A year of
# a large company's filings runs to hundreds of megabytes, and nobody who
# typed a one-line command meant to pull that much without saying so.
CONFIRM_ABOVE_BYTES = 200 * 1024 * 1024

# --- defaults shared with the command line ---
# What this project consumes: the latest annual report and the latest
# earnings-call transcript. Whichever of the two exists is taken; a company
# with only one of them is an ordinary outcome, not an error. Everything
# else BSE carries -- board-meeting intimations, ESOP allotments, AGM
# notices -- is available through --types but is not fetched by default.
DEFAULT_DOCUMENT_TYPES = ("annual_report", "transcript")
# Latest one of each type. 0 means "no limit".
DEFAULT_LATEST_PER_TYPE = 1
# How many companies one API request may ask for. Discovery alone costs about
# six seconds per company because requests to a host are paced a second apart,
# and the PDFs come on top of that, so a request holds its connection open for
# minutes. Ten keeps the worst case near four minutes, inside the timeouts a
# browser or a reverse proxy will usually allow. A real watchlist wants a job
# queue rather than a bigger number here.
MAX_SYMBOLS_PER_REQUEST = 10
DEFAULT_LOOKBACK_YEARS = 1
DEFAULT_OUTPUT_DIR = "downloads"
# Holds the BSE scrip list, which is refetched at most weekly. Separate from
# the output directory so that deleting downloads does not force a refetch.
DEFAULT_CACHE_DIR = ".ingestion-cache"
