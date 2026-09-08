"""Classify a filing or published document into the types worth downloading.

BSE labels every filing with a category and subcategory, and that label is
authoritative when present -- SUBCATEGORY_TYPES below was built from the
subcategories BSE actually returned for a small-cap and a large-cap over three
years, not from guesswork. The title patterns are the fallback: they rescue
filings dropped into BSE's generic "Company Update / General" bucket, and they
are the only signal available for documents harvested from a company website,
which carry nothing but a title.

Classification is multi-label on purpose. An "Outcome of Board Meeting" that
attaches the quarterly numbers is genuinely both a board_meeting and a results
filing, and forcing a single label would hide one of them.
"""

import re

# Ordered by how often they are asked for rather than alphabetically. The order
# is also the order used in classify() output, in inventory() tables, and to
# pick the folder a document is stored under.
DOCUMENT_TYPES = (
    "annual_report",
    "results",
    "board_meeting",
    "presentation",
    "transcript",
    "credit_rating",
    "agm_egm",
    "pledge",
    "management_change",
    "order_win",
)

# BSE subcategory (lowercased, exact) -> document type.
SUBCATEGORY_TYPES = {
    "reg. 34 (1) annual report": "annual_report",
    "financial results": "results",
    "integrated filing (financial)": "results",
    "board meeting": "board_meeting",
    "outcome of board meeting": "board_meeting",
    "revision of outcome": "board_meeting",
    "outcome without intimation": "board_meeting",
    "investor presentation": "presentation",
    "analyst / investor meet": "presentation",
    "earnings call transcript": "transcript",
    "credit rating": "credit_rating",
    "agm": "agm_egm",
    "egm": "agm_egm",
    "agm/egm": "agm_egm",
    "postal ballot": "agm_egm",
    "dividend/agm": "agm_egm",
    "disclosures under reg. 29(2) of sebi (sast) regulations, 2011": "pledge",
    "disclosures under reg. 31(1) and 31(2) of sebi (sast) regulations, 2011": "pledge",
    "disclosures under reg. 31(1), 31(2) and 31(4) of sebi (sast) regulations, 2011": "pledge",
    "change in directorate": "management_change",
    "change in management": "management_change",
    "cessation": "management_change",
    "resignation of director": "management_change",
    "appointment of statutory auditor/s": "management_change",
    "award of order / receipt of order": "order_win",
}

# Searched against subcategory + category + title + subject. A document already
# matched by its subcategory is not re-tested, so these only have to rescue the
# ones filed under a generic label or harvested from a website.
TITLE_PATTERNS = {
    "annual_report": r"\bannual report\b",
    "results": (
        r"\b(?:un)?audited (?:standalone |consolidated )?financial results\b"
        r"|\bfinancial results\b|\bquarterly results\b"
    ),
    "board_meeting": r"\bboard meeting\b|\bmeeting of the board of directors\b",
    "presentation": r"\b(?:investor|analyst|corporate|earnings|institutional) presentation\b",
    "transcript": r"\btranscript\b",
    "credit_rating": (
        r"\bcredit rating\b|\brating (?:action|rationale)\b"
        r"|\bicra\b|\bcrisil\b|\bcare ratings\b|\bindia ratings\b|\bbrickwork\b"
    ),
    "agm_egm": (
        r"\b(?:annual|extraordinary|extra-ordinary) general meeting\b"
        r"|\bpostal ballot\b|\bagm\b|\begm\b"
    ),
    "pledge": r"\bpledge[ds]?\b|\bencumbr\w+\b|\binvocation of pledge\b",
    # Two independent requirements -- a change word and a role word -- in
    # either order, which a single alternation cannot express.
    "management_change": (
        r"(?=.*\b(?:resignation|resigns?|resigned|appointment|appointed|cessation|"
        r"ceased|retirement|retires?|re-?appointment)\b)"
        r"(?=.*\b(?:director|directorate|cfo|ceo|chief financial officer|"
        r"chief executive officer|managing director|company secretary|"
        r"key managerial personnel|kmp|auditors?)\b)"
    ),
    "order_win": (
        r"\b(?:award|receipt|bagging|bagged|awarded|securing|secured) of\b.{0,30}\border\b"
        r"|\b(?:work|purchase|supply) order\b|\bletter of intent\b|\bloi\b"
        r"|\breceipt of order\b|\border win\b"
    ),
}

_COMPILED_PATTERNS = {
    doc_type: re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for doc_type, pattern in TITLE_PATTERNS.items()
}

# A type inferred from wording alone can be overruled by wording that says the
# document is really something else. BSE's own subcategory is never overruled.
#
# The case this exists for: companies file the AGM notice and the annual report
# as one submission and describe both in one subject line. Avantel's notice
# reads "Notice Of The 36th Annual General Meeting (AGM) Of The Company And
# Annual Report For FY 2025-26", which mentions an annual report but attaches
# the notice -- the report itself is a separate filing two minutes earlier.
# Without this, "the latest annual report" returns a 2 MB meeting notice
# instead of a 15 MB report.
#
# Restricting the veto to text-inferred types is what keeps it safe. Infosys
# filed a genuine annual report on 2025-06-02 whose subject also mentions the
# AGM notice; BSE labelled it "Reg. 34 (1) Annual Report", so it is kept.
# The second case: companies advertise in the newspapers that the annual report
# has been posted to shareholders, and file the advertisement with BSE. State
# Bank of India filed three things on 27 May 2026 -- the report, the archive
# copy, and "Newspaper Publication regarding notice of dispatch of Annual
# Report" -- and the advertisement, being filed latest that day, won "the
# latest annual report". It is a press clipping, not a report.
TYPE_VETOES = {
    "annual_report": (
        r"\bnotice\b.{0,60}\bannual general meeting\b"
        r"|\bagm notice\b"
        r"|\bnewspaper\s+(?:publication|advertisement|clipping|cutting)"
        r"|\b(?:notice|intimation)\s+of\s+(?:the\s+)?des?patch\b"
        r"|\bdes?patch(?:ed|ing)?\s+of\b.{0,40}\bannual report\b"
    ),
}

_COMPILED_VETOES = {
    doc_type: re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for doc_type, pattern in TYPE_VETOES.items()
}

# Companies routinely file a one-page covering letter alongside the real
# document, under the same subcategory and on the same day. Recognising them is
# offered as an opt-in filter rather than applied automatically, because a
# short filing is not always a throwaway one.
_COVER_LETTER_PATTERN = re.compile(r"\bcover(?:ing)? (?:letter|note)\b", re.IGNORECASE)


def _searchable_text(document):
    parts = (
        document.get("subcategory") or "",
        document.get("category") or "",
        document.get("title") or "",
        document.get("subject") or "",
    )
    # Underscores separate words in BSE's NEWSSUB field and in many website
    # filenames ("Award_of_Order_Receipt_of_Order"), so they must not glue
    # words together and defeat the \b anchors above.
    return " ".join(parts).replace("_", " ")


def classify(document):
    """Every document type this matches, in DOCUMENT_TYPES order."""
    subcategory = (document.get("subcategory") or "").strip().lower()
    matched = set()

    mapped = SUBCATEGORY_TYPES.get(subcategory)
    if mapped:
        matched.add(mapped)

    text = _searchable_text(document)
    for doc_type, pattern in _COMPILED_PATTERNS.items():
        # A type BSE already asserted is left alone, vetoes included.
        if doc_type in matched or not pattern.search(text):
            continue
        veto = _COMPILED_VETOES.get(doc_type)
        if veto and veto.search(text):
            continue
        matched.add(doc_type)

    return [doc_type for doc_type in DOCUMENT_TYPES if doc_type in matched]


def is_cover_letter(document):
    return bool(_COVER_LETTER_PATTERN.search(_searchable_text(document)))


def filter_by_type(documents, wanted):
    """Documents matching any of `wanted`, a type name or an iterable of them."""
    if isinstance(wanted, str):
        wanted = (wanted,)
    wanted = set(wanted)
    unknown = wanted - set(DOCUMENT_TYPES)
    if unknown:
        raise ValueError(f"unknown document type(s): {', '.join(sorted(unknown))}")
    return [
        document
        for document in documents
        if wanted & set(document.get("doc_types") or classify(document))
    ]


def inventory(documents):
    """Counts per document type, plus how many matched nothing.

    Useful before a download to see what a company actually publishes: annual
    reports and results are reliably filed with BSE, transcripts often are not.
    """
    counts = {doc_type: 0 for doc_type in DOCUMENT_TYPES}
    counts["unclassified"] = 0
    for document in documents:
        types = document.get("doc_types") or classify(document)
        if not types:
            counts["unclassified"] += 1
        for doc_type in types:
            counts[doc_type] += 1
    return counts
