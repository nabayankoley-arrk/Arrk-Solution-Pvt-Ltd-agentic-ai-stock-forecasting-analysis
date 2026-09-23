"""Read the text out of a downloaded PDF, with PyMuPDF.

Scale matters here and is easy to underestimate. Measured on real filings:
an Avantel annual report is 261 pages and 640,000 characters; State Bank of
India's is 756 pages and 1.9 million. That is roughly 160,000 to 475,000
tokens -- within Claude's context window, but the difference between a cheap
call and an expensive one, so callers are given the character count before
they commit to a model call rather than after.

Extraction itself is fast: about two seconds for a 756-page report.
"""

import pathlib

import pymupdf

# Blank output from a text-layer extraction means a scanned document: pages of
# images with no embedded text. Those need OCR, which is out of scope, so they
# are reported rather than passed to a model as an empty string.
MIN_USEFUL_CHARS = 200


class NotExtractable(RuntimeError):
    """The file could not be read, or holds no extractable text."""


def extract(path):
    """Returns {"text", "pages", "chars"} for one PDF.

    Raises NotExtractable for a corrupt file, and for a scanned one whose pages
    carry no text layer.
    """
    path = pathlib.Path(path)
    if not path.is_file():
        raise NotExtractable(f"no such file: {path}")

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises several unrelated types
        raise NotExtractable(f"{path.name}: cannot open ({type(exc).__name__}: {exc})") from exc

    try:
        pages = len(document)
        parts = []
        for page in document:
            try:
                parts.append(page.get_text())
            except Exception:
                # One unreadable page should not lose the other 700.
                continue
    finally:
        document.close()

    text = "\n".join(parts).strip()
    if len(text) < MIN_USEFUL_CHARS:
        raise NotExtractable(
            f"{path.name}: {pages} page(s) but only {len(text)} characters of text. "
            "This is almost certainly a scanned document and needs OCR."
        )

    return {"text": text, "pages": pages, "chars": len(text)}


def head(text, limit):
    """The first `limit` characters, cut at a paragraph break where possible.

    Used only when a caller has explicitly asked for a cap. Truncation is never
    applied silently -- the job reports how much of a document was sent.
    """
    if limit is None or len(text) <= limit:
        return text
    window = text[:limit]
    breakpoint_at = window.rfind("\n\n")
    # Only respect a paragraph break in the last fifth, so a document without
    # blank lines is not cut to a fraction of the requested size.
    if breakpoint_at > limit * 0.8:
        return window[:breakpoint_at]
    return window
