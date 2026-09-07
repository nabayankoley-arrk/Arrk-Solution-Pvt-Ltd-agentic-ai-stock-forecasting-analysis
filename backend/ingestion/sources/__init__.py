"""Document sources. Each exposes fetch_documents() returning the shape in
ingestion/documents.py, so the rest of the package does not know or care which
one found a given PDF."""

from . import bse, company_site

__all__ = ["bse", "company_site"]
