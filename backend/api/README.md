# Document fetcher API

A thin HTTP layer over [ingestion/](../ingestion/). It validates input, calls
ingestion, and reports what happened. Every decision about which documents to
take and how to fetch them lives in `ingestion/`, so this and the command line
cannot drift apart — both go through `ingestion.collect.collect()`.

## Running it

These endpoints are part of the project's one FastAPI app, `backend/main.py`,
which also serves `/api/stock-analysis`, `/api/chat` and the frontend:

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Interactive documentation at http://127.0.0.1:8000/docs.

This module exposes an `APIRouter`, which `main.py` includes. It also assembles
a standalone app for exercising these endpoints without starting the agents or
serving the frontend -- `uvicorn api.app:app --reload`. Both expose identical
paths, so a request written against one works unchanged against the other.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/document-types` | The document types these endpoints understand |
| GET | `/api/companies?q=` | Resolve a ticker, name, ISIN or scrip code |
| POST | `/api/documents` | Fetch PDFs for a list of symbols |
| GET | `/api/inventory/{symbol}` | What a company publishes, by type and source |
| GET | `/api/documents/files` | Everything already downloaded, with a link to each |
| GET | `/api/documents/files/{path}` | Serve one downloaded PDF |

## Where the PDFs go

`POST /documents` writes the PDFs to **disk on the server**, under `downloads/`,
and returns JSON describing what it did. It does not stream the PDFs back in
the response -- a fetch can be tens of megabytes across several symbols, and
the caller usually wants a manifest rather than a multipart body.

To get at the bytes, use the `download_url` on each document, or browse
`GET /api/documents/files`:

```
GET /api/documents/files
  -> [{"title": "Annual Report for the year 2025-26",
       "download_url": "/api/documents/files/annual_report/532406_2026-05-30_....pdf",
       "bytes": 16041783, "sha256": "9dfcf84c...", ...}]

GET /api/documents/files/annual_report/532406_2026-05-30_....pdf
  -> 200 application/pdf, content-disposition: attachment
```

Opening a `download_url` in a browser downloads the PDF.

`/files` serves only from the configured output directory, which is pinned in
`config.DEFAULT_OUTPUT_DIR` and deliberately not taken from the caller: the
fetch endpoint lets a caller choose `out_dir`, and honouring that here as well
would turn it into a way to read any file on the host. Paths resolving outside
that root are refused with 403.

### Fetch the latest reports for several symbols

Symbols alone are enough. The default is the latest annual report and the
latest earnings-call transcript, taking whichever of the two exists:

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
     -H "Content-Type: application/json" \
     -d '{"symbols": ["INFY", "AVANTEL", "BDL"]}'
```

Each result carries `available` — how many of each requested type were found —
and `missing`, so a partial result is explicit rather than inferred from a
short file list:

```
INFY     available={"annual_report": 3, "transcript": 6}  missing=[]
AVANTEL  available={"annual_report": 1, "transcript": 1}  missing=[]
BDL      available={"annual_report": 1, "transcript": 0}  missing=["transcript"]
```

Response, abbreviated:

```json
{
  "window": {"from": "2025-09-07", "to": "2026-09-07"},
  "total_selected": 4, "total_downloaded": 2, "total_bytes": 16793216,
  "results": [
    {
      "symbol": "AVANTEL", "resolved": true, "company": "Avantel Ltd",
      "scrip_code": "532406", "matched": 3, "selected": 2, "downloaded": 2,
      "warnings": [],
      "documents": [
        {"title": "Annual Report for the year 2025-26",
         "doc_types": ["annual_report"], "source": "bse",
         "filed_on": "2026-05-30", "status": "downloaded", "bytes": 16041783,
         "path": "downloads\\annual_report\\532406_2026-05-30_....pdf",
         "source_url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/735548e6-....pdf",
         "sha256": "9dfcf84ccdcd5eef..."}
      ]
    }
  ]
}
```

`source_url` and `sha256` are the provenance: which exchange URL the bytes came
from, and a checksum to prove the local file is unaltered.

### Request fields

| Field | Default | Notes |
| --- | --- | --- |
| `symbols` | required | Tickers, names, ISINs or scrip codes. **1 to 10 per request.** |
| `types` | `["annual_report","transcript"]` | Or `["all"]` for every report type; see `/api/document-types` for the list |
| `latest` | `1` | N most recent **of each type**; `0` for everything in the window |
| `years` | `1` | Lookback from today, 1–40 |
| `source` | `auto` | `auto`, `bse`, or `site` |
| `dry_run` | `false` | Report only, write nothing |
| `force` | `false` | Re-download existing files |
| `include_unclassified` | `false` | Also take filings matching no report type |
| `max_mb` | none | Cap the download |
| `confirm_large` | `false` | Required above 200 MB |
| `out_dir` | `downloads` | Server-side output directory |

The CLI and the API share these defaults, defined once in
`ingestion/config.py` as `DEFAULT_DOCUMENT_TYPES` and
`DEFAULT_LATEST_PER_TYPE`.

### Errors

Each symbol is independent: one that cannot be resolved, or whose source will
not answer, is reported in its own result with an `error` field while the rest
of the batch proceeds. So a partial success returns 200 with per-symbol detail
rather than failing the whole request.

Request-level failures:

| Status | Cause |
| --- | --- |
| 404 | `/inventory` for a company BSE does not recognise |
| 422 | Unknown document type or source |
| 503 | BSE unreachable while loading the scrip list |
| 507 | Local filesystem problem — every remaining symbol would fail the same way |

## Before this goes anywhere shared

Two things are deliberately not built, and both matter if this becomes more
than a desk tool:

- **A fetch is synchronous** and paced at roughly one request per second per
  host. Measured on 2026-09-11, discovery alone costs about **6 seconds per
  company** before a single PDF is downloaded, so ten companies hold the
  connection open for minutes. That is why `symbols` is capped at ten: beyond
  that a browser or a reverse proxy will time out before the work finishes. A
  real watchlist needs a job queue and a polling endpoint, which is not built.
- **There is no authentication and no rate limiting.** The service writes files
  to a server-side directory chosen by the caller (`out_dir`), which is fine on
  localhost and not fine on a shared host. Bind it to localhost, or put auth
  and a fixed output directory in front of it first.
