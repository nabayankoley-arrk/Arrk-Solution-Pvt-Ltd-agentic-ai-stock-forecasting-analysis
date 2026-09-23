"""One paced, retrying HTTP session shared by every source.

Pacing is per host rather than global, so waiting politely on BSE does not
also slow a company website. Every requests-level exception is translated
into this package's own error types here, which is what lets the rest of the
code catch failures by meaning rather than by library detail.
"""

import time
import urllib.parse

import requests

from . import config
from .errors import SourceUnavailable


class HttpClient:
    """A browser-shaped session with per-host pacing and bounded retries.

    Use it as a context manager so the connection pool is closed:

        with HttpClient() as client:
            payload = client.get_json(url, params={...})
    """

    def __init__(
        self,
        delay_seconds=config.REQUEST_DELAY_SECONDS,
        timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
    ):
        self.session = requests.Session()
        self.session.headers.update(config.REQUEST_HEADERS)
        self._delay_seconds = delay_seconds
        self._timeout_seconds = timeout_seconds
        self._last_request_at = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def close(self):
        self.session.close()

    def _wait_turn(self, url):
        host = urllib.parse.urlsplit(url).netloc
        previous = self._last_request_at.get(host)
        if previous is not None:
            elapsed = time.monotonic() - previous
            if elapsed < self._delay_seconds:
                time.sleep(self._delay_seconds - elapsed)
        self._last_request_at[host] = time.monotonic()

    def get(self, url, params=None, stream=False, referer=None):
        """Returns a response, retrying transient failures.

        Raises SourceUnavailable once the retries are exhausted. A non-retryable
        HTTP status (404, 403) is returned to the caller rather than raised,
        because whether it is fatal depends on what was being asked for.
        """
        headers = {"Referer": referer} if referer else None
        last_problem = None

        for attempt in range(config.MAX_RETRIES):
            self._wait_turn(url)
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout_seconds,
                    stream=stream,
                )
            except requests.RequestException as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code not in config.RETRY_STATUS_CODES:
                    return response
                last_problem = f"HTTP {response.status_code}"
                # The body is never useful on a retryable status, and leaving a
                # streamed response open would leak the connection.
                response.close()

            if attempt < config.MAX_RETRIES - 1:
                time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** attempt))

        raise SourceUnavailable(
            f"{url} failed after {config.MAX_RETRIES} attempts ({last_problem})"
        )

    def get_json(self, url, params=None, referer=None):
        """The decoded JSON body, or SourceUnavailable if it is not usable."""
        response = self.get(url, params=params, referer=referer)
        try:
            if response.status_code != 200:
                raise SourceUnavailable(f"{url} returned HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise SourceUnavailable(f"{url} did not return JSON: {exc}") from exc
        finally:
            response.close()

    def get_text(self, url, referer=None):
        """The decoded body as text, or SourceUnavailable if it is not usable."""
        response = self.get(url, referer=referer)
        try:
            if response.status_code != 200:
                raise SourceUnavailable(f"{url} returned HTTP {response.status_code}")
            # Company sites frequently omit a charset. Letting requests guess
            # from the bytes is more reliable than its ISO-8859-1 default.
            if response.encoding is None:
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        finally:
            response.close()

    def open_stream(self, url, referer=None):
        """An open streaming response. The caller must close it."""
        return self.get(url, stream=True, referer=referer)
