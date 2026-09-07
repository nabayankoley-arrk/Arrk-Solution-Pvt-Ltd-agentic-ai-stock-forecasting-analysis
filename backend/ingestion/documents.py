"""The one record shape every source produces.

BSE returns SHOUTING_SNAKE fields and a filing timestamp; a company website
returns a link and a human-written title and often no date at all. Both are
flattened into the document below, so that classification, selection and
downloading are written once rather than per source.

    doc_id      stable identity, used to key the manifest
    source      "bse" or "company_site"
    scrip_code  BSE numeric code the document was collected for
    company     registered company name, when known
    filed_on    "YYYY-MM-DD", or "" when the source does not say
    title       headline or document name
    subject     BSE's NEWSSUB; "" elsewhere
    category    BSE's category; "" elsewhere
    subcategory BSE's subcategory; "" elsewhere
    urls        candidate URLs, tried in order until one yields a PDF
    size_bytes  size the source reports, or 0 when it does not
    doc_types   result of taxonomy.classify()
    raw         whatever the source returned, for fields not surfaced here
"""

import hashlib
import re

from . import taxonomy

_WHITESPACE = re.compile(r"\s+")

# Dates as companies write them in document titles and filenames:
# 30-05-2022, 23.06.2023, 2023_24, 2023-24.
_DATE_PATTERNS = (
    (re.compile(r"\b(\d{2})[-._](\d{2})[-._](\d{4})\b"), ("day", "month", "year")),
    (re.compile(r"\b(\d{4})[-._](\d{2})[-._](\d{2})\b"), ("year", "month", "day")),
)


def clean(value):
    if not value:
        return ""
    return _WHITESPACE.sub(" ", str(value)).strip()


def date_from_text(text):
    """A "YYYY-MM-DD" date read out of a title or filename, or "".

    Best effort by design. Company websites rarely publish a filing date as a
    field, so the date in the document name is the only one available, and a
    wrong guess is worse than none -- hence the range checks below.
    """
    for pattern, order in _DATE_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        parts = dict(zip(order, match.groups()))
        year, month, day = int(parts["year"]), int(parts["month"]), int(parts["day"])
        if 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def stable_id(source, key):
    """A short deterministic id, so reruns key the manifest identically.

    BSE supplies its own NEWSID and that is used verbatim. A website link has
    no id, so one is derived from the URL: stable across runs, and it changes
    if the company moves the file, which is the behaviour wanted.
    """
    digest = hashlib.sha1(f"{source}:{key}".encode("utf-8")).hexdigest()
    return digest[:16]


def make_document(
    source,
    doc_id,
    urls,
    title,
    scrip_code=None,
    company="",
    filed_on="",
    subject="",
    category="",
    subcategory="",
    size_bytes=0,
    raw=None,
):
    document = {
        "doc_id": doc_id,
        "source": source,
        "scrip_code": scrip_code,
        "company": clean(company),
        "filed_on": filed_on or "",
        "title": clean(title),
        "subject": clean(subject),
        "category": clean(category),
        "subcategory": clean(subcategory),
        "urls": [url for url in urls if url],
        "size_bytes": size_bytes or 0,
        "raw": raw if raw is not None else {},
    }
    document["doc_types"] = taxonomy.classify(document)
    return document
