"""HTTP API over the document fetcher.

A thin layer: it validates input, calls ingestion, and reports what happened.
Every decision about which documents to take and how to fetch them lives in
ingestion/, so the API and the command line cannot drift apart.

Run it from the backend/ directory:

    uvicorn api.app:app --reload

Then POST a list of symbols:

    curl -X POST http://127.0.0.1:8000/documents \
         -H "Content-Type: application/json" \
         -d '{"symbols": ["INFY", "AVANTEL"],
              "types": ["annual_report", "transcript"],
              "latest": 1}'

Interactive documentation is at /docs.

One caveat worth knowing before this goes anywhere shared: a fetch is
synchronous and paced at roughly one request per second per host, so a request
for several symbols takes tens of seconds and holds the connection open. That
is fine for a handful of symbols from a script or a desk tool. A watchlist of
hundreds needs a job queue instead, which is deliberately not built here.
"""

import pathlib
import urllib.parse
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ingestion import collect as collector
from ingestion import config, downloader, taxonomy
from ingestion.errors import ConfigurationError, SourceUnavailable, StorageError
from ingestion.http import HttpClient
from ingestion.sources import scrip_master

app = FastAPI(
    title="Stock document fetcher",
    version="0.1.0",
    description=(
        "Downloads corporate filing PDFs from BSE, falling back to a company's "
        "own website for document types BSE does not carry."
    ),
)


# --- request and response shapes ---

class FetchRequest(BaseModel):
    symbols: List[str] = Field(
        ...,
        min_length=1,
        description="Tickers, registered names, ISINs or BSE scrip codes.",
        examples=[["INFY", "AVANTEL", "532406"]],
    )
    types: List[str] = Field(
        # A literal default rather than a factory, so /docs shows it. Pydantic
        # copies mutable defaults per instance, so sharing the list is safe.
        default=list(config.DEFAULT_DOCUMENT_TYPES),
        description=(
            "Document types to fetch. Defaults to the latest annual report and "
            "earnings-call transcript; whichever of them exists is taken. Pass "
            "[\"all\"] for every report type. Choices: "
            + ", ".join(taxonomy.DOCUMENT_TYPES) + ", all"
        ),
        examples=[["annual_report", "transcript"]],
    )
    latest: Optional[int] = Field(
        config.DEFAULT_LATEST_PER_TYPE,
        ge=0,
        description=(
            "Keep only the N most recent documents of each type. Defaults to 1. "
            "Use 0 for everything in the window."
        ),
    )
    years: int = Field(1, ge=1, le=40, description="Lookback in years from today.")
    source: str = Field("auto", description="auto, bse or site.")
    dry_run: bool = Field(False, description="Report what would be fetched, write nothing.")
    force: bool = Field(False, description="Re-download files that already exist.")
    include_unclassified: bool = Field(
        False, description="Also take filings matching no report type."
    )
    max_mb: Optional[float] = Field(
        None, gt=0, description="Stop once this many megabytes have been accounted for."
    )
    confirm_large: bool = Field(
        False,
        description=(
            "Required when a symbol's download would exceed "
            f"{config.CONFIRM_ABOVE_BYTES // (1024 * 1024)} MB."
        ),
    )
    out_dir: str = Field(config.DEFAULT_OUTPUT_DIR, description="Server-side output directory.")


class DocumentOut(BaseModel):
    title: str
    doc_types: List[str]
    source: str
    filed_on: str
    status: str
    bytes: int
    path: Optional[str] = None
    download_url: Optional[str] = None
    source_url: Optional[str] = None
    sha256: Optional[str] = None


class SymbolResult(BaseModel):
    symbol: str
    resolved: bool
    company: str = ""
    ticker: str = ""
    scrip_code: str = ""
    matched: int = 0
    selected: int = 0
    downloaded: int = 0
    failed: int = 0
    bytes: int = 0
    available: Dict[str, int] = {}
    missing: List[str] = []
    error: Optional[str] = None
    warnings: List[str] = []
    documents: List[DocumentOut] = []


class FetchResponse(BaseModel):
    window: Dict[str, str]
    total_selected: int
    total_downloaded: int
    total_failed: int
    total_bytes: int
    results: List[SymbolResult]


class CompanyOut(BaseModel):
    scrip_code: str
    ticker: str
    name: str
    isin: str
    group: str


class InventoryResponse(BaseModel):
    company: str
    ticker: str
    scrip_code: str
    window: Dict[str, str]
    counts: Dict[str, Dict[str, int]]
    only_on_website: List[str]
    warnings: List[str]


# --- helpers ---

def _validate_types(types):
    """None means every report type; "all" is how a caller says that."""
    if not types or "all" in types:
        return None
    unknown = sorted(set(types) - set(taxonomy.DOCUMENT_TYPES))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown document type(s): {', '.join(unknown)}. "
                f"Choices: {', '.join(taxonomy.DOCUMENT_TYPES)}"
            ),
        )
    return list(types)


def _fetch_one(client, symbol, request, wanted_types):
    """Runs one symbol end to end, never raising for that symbol's own problems.

    A symbol nobody recognises, or a source that will not answer, is reported
    against that symbol so the rest of the batch still runs. Only a local
    filesystem failure escapes, because it will defeat every remaining symbol.
    """
    result = SymbolResult(symbol=symbol, resolved=False)

    try:
        scrip = scrip_master.resolve(client, symbol)
    except ConfigurationError as exc:
        result.error = str(exc)
        return result

    result.resolved = True
    result.company = scrip.get("name") or ""
    result.ticker = scrip.get("ticker") or ""
    result.scrip_code = scrip.get("scrip_code") or ""

    from_date, to_date = collector.resolve_window(years=request.years)
    try:
        collected = collector.collect(
            client, scrip, from_date, to_date,
            wanted_types=wanted_types, source=request.source,
        )
    except (ConfigurationError, SourceUnavailable) as exc:
        result.error = str(exc)
        return result

    result.company = collected["company"] or result.company
    result.warnings = collected["warnings"]

    selected = downloader.select(
        collected["all"],
        wanted_types=wanted_types,
        include_unclassified=request.include_unclassified,
    )
    result.matched = len(selected)
    result.available = downloader.availability(selected, wanted_types)
    result.missing = [name for name, count in result.available.items() if not count]
    if request.latest:
        selected = downloader.keep_latest(selected, request.latest, wanted_types=wanted_types)
    result.selected = len(selected)

    if not selected:
        return result

    estimate = downloader.estimate_bytes(selected)
    if (
        not request.dry_run
        and not request.confirm_large
        and not request.max_mb
        and estimate > config.CONFIRM_ABOVE_BYTES
    ):
        result.error = (
            f"{symbol} would download {estimate // (1024 * 1024)} MB, above the "
            f"{config.CONFIRM_ABOVE_BYTES // (1024 * 1024)} MB threshold. Narrow it with "
            "types and latest, cap it with max_mb, or set confirm_large."
        )
        return result

    summary = downloader.download(
        client,
        selected,
        request.out_dir,
        dry_run=request.dry_run,
        force=request.force,
        max_total_bytes=int(request.max_mb * 1024 * 1024) if request.max_mb else None,
    )

    # The manifest is where the provenance lives -- source URL and checksum are
    # recorded there as each file lands, not in the per-run report.
    manifest = {} if request.dry_run else downloader.load_manifest(request.out_dir)

    result.downloaded = summary.get("downloaded", 0)
    result.failed = summary.get("failed", 0)
    result.bytes = summary["total_bytes"]
    if summary.get("manifest_warning"):
        result.warnings = result.warnings + [summary["manifest_warning"]]

    for entry in summary["results"]:
        recorded = manifest.get(entry["doc_id"]) or {}
        result.documents.append(
            DocumentOut(
                title=entry["title"] or "",
                doc_types=entry["doc_types"],
                source=entry["source"] or "",
                filed_on=entry["filed_on"] or "",
                status=entry["status"],
                bytes=entry["bytes"],
                path=entry["path"],
                download_url=_download_url(recorded.get("path")),
                source_url=recorded.get("source_url"),
                sha256=recorded.get("sha256"),
            )
        )
    return result


def _download_url(relative_path):
    """A URL the caller can open, or None when the file is not on disk yet."""
    if not relative_path:
        return None
    return "/files/" + urllib.parse.quote(relative_path)


def _served_root():
    """The one directory /files will serve from.

    Pinned to the configured output directory rather than taken from the
    caller. The fetch endpoint lets a caller choose out_dir, and letting the
    same caller then read back an arbitrary path would turn that into a way to
    read any file on the host.
    """
    return pathlib.Path(config.DEFAULT_OUTPUT_DIR).resolve()


# --- routes ---

@app.get("/health")
def health():
    return {"status": "ok", "document_types": list(taxonomy.DOCUMENT_TYPES)}


@app.get("/companies", response_model=List[CompanyOut])
def companies(
    q: str = Query(..., min_length=1, description="Ticker, name, ISIN or scrip code."),
    limit: int = Query(25, ge=1, le=200),
):
    """Resolve a symbol to BSE scrip codes, most specific match first."""
    with HttpClient() as client:
        try:
            entries = scrip_master.load(client)
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [CompanyOut(**entry) for entry in scrip_master.search(entries, q)[:limit]]


@app.post("/documents", response_model=FetchResponse)
def fetch_documents(request: FetchRequest):
    """Fetch PDFs for a list of symbols.

    Each symbol is handled independently: one that cannot be resolved, or whose
    source will not answer, is reported in its own result while the rest of the
    batch proceeds.
    """
    wanted_types = _validate_types(request.types)
    if request.source not in collector.SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown source {request.source!r}; expected one of {', '.join(collector.SOURCES)}",
        )

    from_date, to_date = collector.resolve_window(years=request.years)
    results = []
    try:
        with HttpClient() as client:
            for symbol in request.symbols:
                results.append(_fetch_one(client, symbol, request, wanted_types))
    except StorageError as exc:
        # Every remaining symbol would hit the same wall.
        raise HTTPException(status_code=507, detail=str(exc)) from exc

    return FetchResponse(
        window={"from": from_date.isoformat(), "to": to_date.isoformat()},
        total_selected=sum(result.selected for result in results),
        total_downloaded=sum(result.downloaded for result in results),
        total_failed=sum(result.failed for result in results),
        total_bytes=sum(result.bytes for result in results),
        results=results,
    )


@app.get("/inventory/{symbol}", response_model=InventoryResponse)
def inventory(
    symbol: str,
    years: int = Query(1, ge=1, le=40),
    source: str = Query("auto"),
):
    """What a company publishes, by document type and source. Downloads nothing."""
    with HttpClient() as client:
        try:
            scrip = scrip_master.resolve(client, symbol)
            from_date, to_date = collector.resolve_window(years=years)
            collected = collector.collect(client, scrip, from_date, to_date, source=source)
        except ConfigurationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    from_bse = taxonomy.inventory(collected["bse"])
    from_site = taxonomy.inventory(collected["site"])
    return InventoryResponse(
        company=collected["company"],
        ticker=scrip.get("ticker") or "",
        scrip_code=scrip.get("scrip_code") or "",
        window={"from": from_date.isoformat(), "to": to_date.isoformat()},
        counts={
            name: {"bse": from_bse[name], "site": from_site[name]} for name in from_bse
        },
        only_on_website=[
            name
            for name in taxonomy.DOCUMENT_TYPES
            if not from_bse[name] and from_site[name]
        ],
        warnings=collected["warnings"],
    )


@app.get("/files", response_model=List[DocumentOut])
def list_files():
    """Every document already on disk, from the manifest.

    This is the browsable index: each entry carries a download_url that serves
    the PDF itself.
    """
    manifest = downloader.load_manifest(config.DEFAULT_OUTPUT_DIR)
    return [
        DocumentOut(
            title=entry.get("title") or "",
            doc_types=entry.get("doc_types") or [],
            source=entry.get("source") or "",
            filed_on=entry.get("filed_on") or "",
            status="on_disk",
            bytes=entry.get("bytes") or 0,
            path=entry.get("path"),
            download_url=_download_url(entry.get("path")),
            source_url=entry.get("source_url"),
            sha256=entry.get("sha256"),
        )
        for entry in manifest.values()
        if isinstance(entry, dict)
    ]


@app.get("/files/{path:path}")
def get_file(path: str):
    """Serve one downloaded PDF.

    The resolved path must sit inside the served root; anything else is a
    traversal attempt and is refused rather than clamped.
    """
    root = _served_root()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"bad path: {exc}") from exc

    if target != root and root not in target.parents:
        raise HTTPException(status_code=403, detail="path is outside the download directory")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path}")

    return FileResponse(target, media_type="application/pdf", filename=target.name)
