"""The failure modes this package distinguishes.

Downloading documents from public websites fails in several genuinely
different ways, and collapsing them into one exception makes a run report
useless. The distinction that matters most to a caller is whether a failure
was fatal to the whole run (a source is unreachable, the disk is full) or
local to a single document (one attachment 404s), because the second kind
should be recorded and stepped over rather than aborting a long download.
"""


class IngestionError(Exception):
    """Base class, so a caller can catch everything this package raises."""


class ConfigurationError(IngestionError):
    """The request itself is wrong: unknown scrip code, no site configured.

    Fatal, and not worth retrying -- nothing about the network will change
    the outcome.
    """


class SourceUnavailable(IngestionError):
    """A source could not be reached, or answered with something unusable.

    Fatal for that source. When one source fails this way, the run may still
    continue against another.
    """


class DocumentUnavailable(IngestionError):
    """One specific document could not be retrieved.

    Local to that document. The run records it and moves on.
    """


class NotADocument(DocumentUnavailable):
    """The server answered, but with something that is not a PDF.

    Kept separate from a plain transfer failure because it usually means a
    stale link or an error page rather than a transient problem, so retrying
    the same URL is pointless.
    """


class StorageError(IngestionError):
    """The local filesystem refused a write: full disk, permissions, bad path.

    Fatal for the run. Every remaining document would hit the same wall, and
    continuing would produce a long list of identical failures.
    """
