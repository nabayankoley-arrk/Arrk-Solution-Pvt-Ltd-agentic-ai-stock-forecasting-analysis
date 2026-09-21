"""Process-wide runtime setup, imported for its side effects.

Three things every entry point into this backend needs before anything else
reads os.environ, prints, or opens an HTTPS connection:

1. `backend/.env` is loaded into os.environ, which is what db/connection.py's
   own docstring already tells you to use. Each config.py reads its settings
   at *import* time (module-level constants), so this has to run before the
   first `from ..config import ...` anywhere -- which is why this module is
   imported at the top of each module that reads the environment, rather
   than from a single main(). Existing environment variables always win, so
   an explicitly exported value is never silently overridden by the file.

2. The OS certificate store is installed as Python's trust store via
   `truststore`. On a network that does TLS inspection (a corporate proxy
   re-signing HTTPS with its own root CA), certifi's bundle does not contain
   that root and every outbound request fails with "self-signed certificate
   in certificate chain" -- both the LLM calls in
   agents/orchestrator/llm_client.py and yfinance's fetches in
   db/seed_fundamentals.py. That root is already trusted by the OS, so
   deferring to the OS store fixes it without weakening verification: this
   changes *which* trust anchors are used, never whether certificates are
   checked. Note it applies process-wide, not just to this project's calls.

All three steps are idempotent and safe to import repeatedly. Neither raises if
its dependency is missing: a deployment that sets real environment variables
needs no .env, and a network without TLS inspection needs no truststore, so
an ImportError for either is not fatal.
"""

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_BACKEND_DIR, ".env")
_CA_BUNDLE_PATH = os.path.join(_BACKEND_DIR, "certs", "win-ca.pem")

_done = False


def setup():
    """Idempotent. Called once on import; exposed for explicit re-runs."""
    global _done
    if _done:
        return
    _done = True

    try:
        from dotenv import load_dotenv

        # override=False: a variable already exported in the shell wins over
        # the file, so CI/production settings are never clobbered by a
        # developer's local .env that happens to be lying around.
        load_dotenv(_ENV_PATH, override=False)
    except ImportError:
        pass

    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    # 3. stdout/stderr are switched to UTF-8.
    #
    # A Windows console defaults to cp1252, which cannot encode the rupee sign
    # -- so printing anything derived from an Indian filing raises
    # UnicodeEncodeError and kills the process. That is not hypothetical: the
    # debug trace in agents/orchestrator/llm_client.py prints 300 characters of
    # every model reply, and a reply about an Indian company quoting figures in
    # rupees crashes it. So does any summary or chat response echoed to a
    # terminal. errors="replace" rather than "strict" so that a stray character
    # from some other script degrades to "?" instead of taking the run down.
    #
    # Only affects this process's own streams; it changes nothing about how
    # text is stored or sent over the wire.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Not a TextIOWrapper -- redirected to a pipe or captured by a
            # test harness. Those are already byte-oriented or UTF-8.
            pass

    # truststore only patches Python's own `ssl` module, so it covers
    # `requests` but NOT yfinance: yfinance >= 1.x fetches through curl_cffi,
    # which links its own libcurl with its own bundled CA store and never
    # consults Python's ssl module at all. libcurl reads CURL_CA_BUNDLE, so
    # a PEM exported from this machine's OS trust store (which already holds
    # the TLS-inspecting proxy's root) is pointed at here too. Without this,
    # every yfinance call fails with "self signed certificate in certificate
    # chain" even though `requests` calls succeed.
    #
    # The bundle is machine-specific and gitignored; regenerate it per
    # machine (PowerShell, from backend/):
    #
    #   $o="certs\win-ca.pem"; ni -Force (Split-Path $o) -ItemType Directory | Out-Null
    #   $sb=New-Object Text.StringBuilder
    #   'Cert:\LocalMachine\Root','Cert:\CurrentUser\Root','Cert:\LocalMachine\CA' | % {
    #     gci $_ -EA SilentlyContinue | % {
    #       [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----')
    #       [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks'))
    #       [void]$sb.AppendLine('-----END CERTIFICATE-----') } }
    #   sc $o $sb.ToString() -Encoding ascii
    #
    # Set only when unset, so an explicitly exported bundle still wins.
    if os.path.exists(_CA_BUNDLE_PATH):
        for var in ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
            os.environ.setdefault(var, _CA_BUNDLE_PATH)


setup()
