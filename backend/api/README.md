# Document fetcher API

A thin HTTP layer over [ingestion/](../ingestion/). It validates input, calls
ingestion, and reports what happened. Every decision about which documents to
take and how to fetch them lives in `ingestion/`, so this and the command line
cannot drift apart — both go through `ingestion.collect.collect()`.

## Running it

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn api.app:app --reload
```

Interactive documentation at http://127.0.0.1:8000/docs.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness, plus the list of document types |
| GET | `/companies?q=` | Resolve a ticker, name, ISIN or scrip code |
| POST | `/documents` | Fetch PDFs for a list of symbols |
| GET | `/inventory/{symbol}` | What a company publishes, by type and source |
| GET | `/files` | Everything already downloaded, with a link to each |
| GET | `/files/{path}` | Serve one downloaded PDF |

## Where the PDFs go

`POST /documents` writes the PDFs to **disk on the server**, under `downloads/`,
and returns JSON describing what it did. It does not stream the PDFs back in
the response -- a fetch can be tens of megabytes across several symbols, and
the caller usually wants a manifest rather than a multipart body.

To get at the bytes, use the `download_url` on each document, or browse
`GET /files`:

```
GET /files
  -> [{"title": "Annual Report for the year 2025-26",
       "download_url": "/files/annual_report/532406_2026-05-30_....pdf",
       "bytes": 16041783, "sha256": "9dfcf84c...", ...}]

GET /files/annual_report/532406_2026-05-30_....pdf
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
curl -X POST http://127.0.0.1:8000/documents \
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
| `symbols` | required | Tickers, names, ISINs or scrip codes |
| `types` | `["annual_report","transcript"]` | Or `["all"]` for every report type; see `/health` for the list |
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
  host, so several symbols take tens of seconds and hold the connection open.
  A watchlist of hundreds needs a job queue and a polling endpoint.
- **There is no authentication and no rate limiting.** The service writes files
  to a server-side directory chosen by the caller (`out_dir`), which is fine on
  localhost and not fine on a shared host. Bind it to localhost, or put auth
  and a fixed output directory in front of it first.
