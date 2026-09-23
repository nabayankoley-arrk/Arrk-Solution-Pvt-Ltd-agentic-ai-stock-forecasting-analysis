"""Write selected documents to disk as PDFs, whatever source found them.

Four properties matter more than speed here, and each costs very little:

* Downloads are atomic. Bytes land in a .part file and are renamed only once
  the whole document has arrived, so an interrupted run never leaves a
  truncated PDF that a later run mistakes for a finished one.
* Every response is checked for the %PDF magic bytes. Both BSE and company
  sites answer some requests with an HTML error page under a 200 status, and
  without the check those get saved with a .pdf extension and fail much later.
* Failures are separated by kind. One document that will not download is
  recorded and stepped over; a full disk or a source that has stopped
  answering aborts the run rather than producing hundreds of identical errors.
* A manifest.json sidecar records what was fetched. It is what makes reruns
  idempotent and what lets someone trace a local file back to its source --
  deliberately a plain file, not a database, because storage is out of scope.
"""

import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil

import requests

from . import config, taxonomy
from .errors import DocumentUnavailable, NotADocument, SourceUnavailable, StorageError

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")

# How many documents may fail in a row with a source-level error before the run
# gives up. A source that has stopped answering will fail every remaining
# document identically, and each failure costs a full retry cycle.
MAX_CONSECUTIVE_SOURCE_FAILURES = 5


def _slug(text, limit=60):
    slug = _SLUG_UNSAFE.sub("-", (text or "").lower()).strip("-")
    return slug[:limit].strip("-") or "document"


def primary_type(document):
    """The type a document is filed under on disk when it matched several."""
    types = document.get("doc_types") or taxonomy.classify(document)
    return types[0] if types else "other"


def target_path(document, out_dir):
    """Deterministic destination, so a rerun computes the same path.

    The doc_id suffix keeps several documents of the same type and date from
    colliding, which is common around results season. The name is shortened if
    the whole path would exceed what Windows accepts without long paths
    enabled -- an OSError raised deep inside a download is hard to read.
    """
    folder = pathlib.Path(out_dir) / primary_type(document)
    scrip = document.get("scrip_code") or "unknown"
    date = document.get("filed_on") or "undated"
    doc_id = (document.get("doc_id") or "")[:8]
    title = document.get("title") or document.get("subject")

    limit = 60
    while True:
        path = folder / f"{scrip}_{date}_{_slug(title, limit)}_{doc_id}.pdf"
        if len(str(path.resolve())) <= config.MAX_PATH_CHARS or limit <= 8:
            return path
        limit -= 12


def select(documents, wanted_types=None, skip_cover_letters=False, include_unclassified=False):
    """The documents that are both wanted and downloadable as a PDF.

    With no wanted_types, this returns every document that matched *some*
    document type, not every document that exists. The difference is large and
    was a defect once: a year of Infosys filings is 219 documents, of which 177
    are ESOP allotments, lost share certificates and routine disclosures. Those
    are filings, but they are not reports, and downloading 572 MB of them to
    find three annual reports is not what anybody asked for. Pass
    include_unclassified to get the raw firehose.

    Entries with no URL, or whose only URL is not a PDF, are dropped here:
    this package downloads PDFs only.
    """
    chosen = documents
    if wanted_types:
        chosen = taxonomy.filter_by_type(chosen, wanted_types)
    elif not include_unclassified:
        chosen = [document for document in chosen if document.get("doc_types")]
    if skip_cover_letters:
        chosen = [document for document in chosen if not taxonomy.is_cover_letter(document)]
    return [
        document
        for document in chosen
        if any(url.split("?")[0].lower().endswith(".pdf") for url in document.get("urls") or [])
    ]


def keep_latest(documents, per_type, wanted_types=None):
    """The `per_type` most recent documents of each requested type.

    Counted per type rather than overall, so asking for the latest annual
    report and the latest results returns one of each instead of two annual
    reports. A document matching several types is kept if it is recent enough
    for any of them, and is only returned once.

    Undated documents sort last. They come from company websites, where the
    date has to be read out of a filename, and treating an unknown date as
    recent would let a 2009 report displace this year's.

    Ordering uses the full filing timestamp where a source provides one, not
    just the date. That decides real cases: Infosys filed its FY2025-26 annual
    report on 29 May 2026 and a revised version on 30 May, and two filings can
    land on the same day, so "latest" has to be finer-grained than a day.
    """
    if not per_type or per_type < 1:
        return documents

    types = list(wanted_types) if wanted_types else list(taxonomy.DOCUMENT_TYPES)

    def recency(document):
        stamp = document.get("filed_at") or document.get("filed_on") or ""
        return (bool(document.get("filed_on")), stamp)

    ordered = sorted(documents, key=recency, reverse=True)

    kept_ids = set()
    for doc_type in types:
        taken = 0
        for document in ordered:
            if taken >= per_type:
                break
            if doc_type in (document.get("doc_types") or []):
                kept_ids.add(document["doc_id"])
                taken += 1

    return [document for document in ordered if document["doc_id"] in kept_ids]


def availability(documents, wanted_types):
    """How many of each requested type are present, in the order requested.

    The caller asks for a set of types and takes whichever exist: a company
    with an annual report but no transcript is an ordinary outcome, not a
    failure. This makes that outcome explicit rather than leaving it to be
    inferred from a shorter-than-expected file list.
    """
    types = list(wanted_types) if wanted_types else list(taxonomy.DOCUMENT_TYPES)
    counts = {doc_type: 0 for doc_type in types}
    for document in documents:
        for doc_type in document.get("doc_types") or []:
            if doc_type in counts:
                counts[doc_type] += 1
    return counts


def estimate_bytes(documents):
    """Total size the sources report, without downloading anything.

    Company websites report nothing, so a plan built only from website
    documents totals zero. That is honest rather than useful: treat a zero
    estimate as "unknown", not as "small".
    """
    return sum(document.get("size_bytes") or 0 for document in documents)


# --- manifest ---

def manifest_path(out_dir):
    return pathlib.Path(out_dir) / config.MANIFEST_FILENAME


def load_manifest(out_dir):
    path = manifest_path(out_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (ValueError, OSError):
        # A corrupt or unreadable manifest must not stop a download. The files
        # on disk are the real record, and the manifest is rebuilt as they are
        # re-seen.
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_manifest(out_dir, manifest):
    """Writes the manifest atomically. Returns an error string, or None.

    A manifest that cannot be written is reported rather than raised: the PDFs
    are already safely on disk by this point, and losing the sidecar is a far
    smaller problem than discarding a completed download.
    """
    path = manifest_path(out_dir)
    partial = path.with_name(path.name + config.PARTIAL_SUFFIX)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
        os.replace(partial, path)
    except OSError as exc:
        try:
            os.unlink(partial)
        except OSError:
            pass
        return f"could not write {path}: {exc}"
    return None


# --- pre-flight ---

def check_free_space(out_dir, needed_bytes):
    """Raises StorageError if the download plainly will not fit.

    Skipped when needed_bytes is zero, which is what a website-only plan
    reports, since a check against an unknown size is meaningless.
    """
    if not needed_bytes:
        return
    probe = pathlib.Path(out_dir).resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise StorageError(f"could not check free space on {probe}: {exc}") from exc
    if free < needed_bytes + config.FREE_SPACE_MARGIN_BYTES:
        raise StorageError(
            f"not enough free space on {probe}: {free // (1024 * 1024)} MB available, "
            f"{needed_bytes // (1024 * 1024)} MB needed"
        )


# --- transfer ---

def _stream_to_file(response, destination):
    """Streams the body to destination, returning (bytes, sha256).

    Never leaves a partial file behind, whatever goes wrong.
    """
    digest = hashlib.sha256()
    total = 0
    header = b""
    partial = destination.with_name(destination.name + config.PARTIAL_SUFFIX)

    try:
        try:
            handle = open(partial, "wb")
        except OSError as exc:
            raise StorageError(f"cannot write {partial}: {exc}") from exc
        with handle:
            try:
                chunks = response.iter_content(config.CHUNK_BYTES)
                for chunk in chunks:
                    if not chunk:
                        continue
                    if len(header) < len(config.PDF_MAGIC):
                        header += chunk[: len(config.PDF_MAGIC) - len(header)]
                        if len(header) == len(config.PDF_MAGIC) and header != config.PDF_MAGIC:
                            content_type = response.headers.get("Content-Type", "unknown")
                            raise NotADocument(f"not a PDF (Content-Type: {content_type})")
                    handle.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
            except requests.RequestException as exc:
                # A connection dropped or timed out part way through the body.
                raise DocumentUnavailable(
                    f"transfer interrupted after {total} bytes: {type(exc).__name__}: {exc}"
                ) from exc
            except OSError as exc:
                raise StorageError(f"cannot write {partial}: {exc}") from exc

        if total == 0:
            raise DocumentUnavailable("empty response body")

        try:
            os.replace(partial, destination)
        except OSError as exc:
            raise StorageError(f"cannot finalise {destination}: {exc}") from exc
    except BaseException:
        # Covers every error above and interrupts alike: a .part file must
        # never survive a failed transfer.
        try:
            os.unlink(partial)
        except OSError:
            pass
        raise

    return total, digest.hexdigest()


def _fetch_document(client, document, destination):
    """Tries each candidate URL, returning (url, bytes, sha256).

    Raises DocumentUnavailable when none of them yields a PDF, and StorageError
    on a local filesystem problem, which is not this document's fault and
    should abort the run.

    When no candidate URL could be reached at all, SourceUnavailable is raised
    instead. The distinction matters: a 404 says this one document is gone,
    whereas a host that will not answer says the next document will fail the
    same way, and the caller uses that to stop early.
    """
    urls = document.get("urls") or []
    problems = []
    unreachable = 0
    referer = document.get("referer")

    for url in urls:
        for attempt in range(config.MAX_TRANSFER_ATTEMPTS):
            try:
                response = client.open_stream(url, referer=referer)
            except SourceUnavailable as exc:
                unreachable += 1
                problems.append(str(exc))
                break
            try:
                if response.status_code != 200:
                    problems.append(f"{url}: HTTP {response.status_code}")
                    break
                size, checksum = _stream_to_file(response, destination)
            except NotADocument as exc:
                # Retrying the same URL cannot turn an error page into a PDF.
                problems.append(f"{url}: {exc}")
                break
            except DocumentUnavailable as exc:
                problems.append(f"{url}: {exc}")
                if attempt + 1 >= config.MAX_TRANSFER_ATTEMPTS:
                    break
                continue
            finally:
                response.close()
            return url, size, checksum

    if urls and unreachable == len(urls):
        raise SourceUnavailable("; ".join(problems))
    raise DocumentUnavailable("; ".join(problems) or "no URL to try")


def _result(document, status, path=None, size=0, error=None, duplicate_of=None):
    return {
        "doc_id": document.get("doc_id"),
        "source": document.get("source"),
        "filed_on": document.get("filed_on"),
        "title": document.get("title"),
        "doc_types": document.get("doc_types") or [],
        "status": status,
        "path": str(path) if path else None,
        "bytes": size,
        "error": error,
        "duplicate_of": duplicate_of,
    }


def download(
    client,
    documents,
    out_dir,
    dry_run=False,
    force=False,
    max_total_bytes=None,
    progress=None,
):
    """Downloads the documents into out_dir and returns a per-document report.

    max_total_bytes is checked against the size a source reports before a
    document is requested, so the cap holds on a dry run too. Nothing is ever
    deleted: a document whose bytes duplicate one already in the manifest is
    still saved, and merely flagged in its result.

    Raises StorageError if the local filesystem refuses a write, and
    SourceUnavailable if a source stops answering entirely; both abort the run,
    and the results gathered so far are attached to the exception as .results.
    """
    out_dir = pathlib.Path(out_dir)
    manifest = load_manifest(out_dir)
    checksums = {
        entry.get("sha256"): doc_id
        for doc_id, entry in manifest.items()
        if isinstance(entry, dict) and entry.get("sha256")
    }

    results = []
    total_bytes = 0
    manifest_changed = False
    consecutive_source_failures = 0
    manifest_warning = None

    def finish():
        warning = save_manifest(out_dir, manifest) if manifest_changed else None
        summary = {
            "total_bytes": total_bytes,
            "results": results,
            "manifest_warning": warning or manifest_warning,
        }
        for result in results:
            summary[result["status"]] = summary.get(result["status"], 0) + 1
        return summary

    for document in documents:
        destination = target_path(document, out_dir)

        if not force and destination.exists():
            results.append(_result(document, "skipped_existing", path=destination))
            if progress:
                progress(results[-1])
            continue

        reported_bytes = document.get("size_bytes") or 0
        if max_total_bytes is not None and total_bytes + reported_bytes > max_total_bytes:
            results.append(_result(document, "skipped_budget", size=reported_bytes))
            if progress:
                progress(results[-1])
            continue

        if dry_run:
            total_bytes += reported_bytes
            results.append(
                _result(document, "would_download", path=destination, size=reported_bytes)
            )
            if progress:
                progress(results[-1])
            continue

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            error = StorageError(f"cannot create {destination.parent}: {exc}")
            error.results = results
            raise error from exc

        try:
            url, size, checksum = _fetch_document(client, document, destination)
        except StorageError as exc:
            exc.results = results
            raise
        except SourceUnavailable as exc:
            consecutive_source_failures += 1
            results.append(_result(document, "failed", error=str(exc)))
            if progress:
                progress(results[-1])
            if consecutive_source_failures >= MAX_CONSECUTIVE_SOURCE_FAILURES:
                giving_up = SourceUnavailable(
                    f"stopped after {consecutive_source_failures} consecutive source "
                    f"failures; last was: {exc}"
                )
                giving_up.results = results
                manifest_warning = save_manifest(out_dir, manifest) if manifest_changed else None
                raise giving_up from exc
            continue
        except DocumentUnavailable as exc:
            consecutive_source_failures = 0
            results.append(_result(document, "failed", error=str(exc)))
            if progress:
                progress(results[-1])
            continue

        consecutive_source_failures = 0
        total_bytes += size
        duplicate_of = checksums.get(checksum)
        checksums.setdefault(checksum, document["doc_id"])

        manifest[document["doc_id"]] = {
            "doc_id": document.get("doc_id"),
            "source": document.get("source"),
            "scrip_code": document.get("scrip_code"),
            "company": document.get("company"),
            "filed_on": document.get("filed_on"),
            "title": document.get("title"),
            "category": document.get("category"),
            "subcategory": document.get("subcategory"),
            "doc_types": document.get("doc_types") or [],
            "source_url": url,
            "path": str(destination.relative_to(out_dir)).replace("\\", "/"),
            "bytes": size,
            "sha256": checksum,
            "downloaded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        manifest_changed = True

        results.append(
            _result(document, "downloaded", path=destination, size=size, duplicate_of=duplicate_of)
        )
        if progress:
            progress(results[-1])

    return finish()
