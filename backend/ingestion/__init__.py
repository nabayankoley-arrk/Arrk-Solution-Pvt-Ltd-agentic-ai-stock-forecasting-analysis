"""Download corporate documents as PDFs from BSE and company websites.

Scope is deliberately narrow: find a company's documents, decide which are
wanted, and write those PDFs to disk. Nothing here parses a PDF or writes to
the database -- see ingestion/README.md for why.
"""

from .downloader import download, select
from .errors import (
    ConfigurationError,
    DocumentUnavailable,
    IngestionError,
    NotADocument,
    SourceUnavailable,
    StorageError,
)
from .http import HttpClient
from .taxonomy import DOCUMENT_TYPES, classify, filter_by_type, inventory

__all__ = [
    "ConfigurationError",
    "DOCUMENT_TYPES",
    "DocumentUnavailable",
    "HttpClient",
    "IngestionError",
    "NotADocument",
    "SourceUnavailable",
    "StorageError",
    "classify",
    "download",
    "filter_by_type",
    "inventory",
    "select",
]
