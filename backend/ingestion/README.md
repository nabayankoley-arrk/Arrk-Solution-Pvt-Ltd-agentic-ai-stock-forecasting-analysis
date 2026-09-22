# Document fetcher

Downloads corporate document PDFs to the local filesystem, from BSE first and
from a company's own website where BSE does not carry what was asked for.

Name a company however is convenient — ticker, registered name, ISIN or BSE
scrip code. Nothing needs configuring per company.

## Running it locally

Python 3.9 or newer. From a terminal at the repository root:

```bash
cd backend
python -m pip install requests                 # all this module needs
python -m ingestion inventory avantel --years 3
```

`requirements.txt` covers the whole backend and also pulls in LangGraph and
psycopg2 for the agent packages. Installing `requests` alone is enough to run
the fetcher, and avoids those heavier dependencies if you only want to try it.

A virtual environment is recommended but not required:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell or cmd
source .venv/bin/activate       # bash
python -m pip install -r backend/requirements.txt
```

Everything must run from `backend/`, which is this project's import root. From
anywhere else the import fails with `No module named 'ingestion'`.

### The latest reports, which is the usual request

```bash
python -m ingestion fetch INFY --types annual_report results transcript --latest 1
```

Three files: the most recent annual report, the most recent results, the most
recent earnings-call transcript. `--latest N` counts per type, so this returns
one of each rather than three annual reports.

Compare that with `fetch INFY` and no flags, which covers every report type
over a year — for Infosys, 42 documents and 286 MB. Both are legitimate
requests; only one of them is what "get me the latest reports" means.

A typical session:

```bash
# 1. Which company did you mean?
python -m ingestion search "mtar"

# 2. What does it publish, and where does it live?
python -m ingestion inventory mtartech --years 3

# 3. What would a download pull, and how large is it?
python -m ingestion fetch mtartech --years 3 --types transcript --dry-run

# 4. Pull it.
python -m ingestion fetch mtartech --years 3 --types transcript

# 5. Check the offline tests still pass after editing the rules.
python -m ingestion.smoke_test
```

Start with step 2 or 3. Both leave the disk untouched, and the dry run reports
the byte total BSE will serve, taken from the size BSE publishes in its filing
listing. Look at that number first: a single annual report routinely exceeds
15 MB.

### Naming a company

The first argument accepts a ticker (`AVANTEL`), a registered name
(`"Avantel Ltd"`), an ISIN (`INE005B01027`) or a scrip code (`532406`). It is
resolved against BSE's list of all active equity scrips, which is fetched once
and cached for a week under `.ingestion-cache/`.

An exact ticker beats a name that merely contains the same word, so `reliance`
resolves to Reliance Industries rather than to a list. When a query genuinely
matches several companies, the run stops and prints them:

```
'tata motors' matches 2 companies. Name one exactly:
    544569   TMCV         Tata Motors Ltd
    500570   TMPV         Tata Motors Passenger Vehicles Ltd
```

### Options

| Option | Effect |
| --- | --- |
| `--types` | One or more document types, or `all`. Default: `annual_report transcript`. |
| `--latest N` | Keep only the N most recent **of each type**. Default 1; `0` for all. |
| `--include-unclassified` | Also take filings matching no report type (see below). |
| `--yes` | Proceed without confirmation above the 200 MB threshold. |
| `--source` | `auto` (default), `bse`, or `site`. See below. |
| `--from` / `--to` | Explicit `YYYY-MM-DD` window. |
| `--years N` | Lookback from today when `--from` is omitted (default 1). |
| `--out DIR` | Output directory (default `downloads`, already in `.gitignore`). |
| `--dry-run` | Report what would be fetched, write nothing. |
| `--force` | Re-download files that already exist. |
| `--max-mb N` | Stop once N megabytes have been accounted for. |
| `--skip-cover-letters` | Drop documents whose title reads as a covering letter. |
| `--delay SECONDS` | Spacing between requests to a given host (default 1.0). |
| `--ignore-robots` | Skip the robots.txt check when reading a company website. |
| `--refresh-scrips` | Refetch BSE's scrip list instead of using the weekly cache. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Finished, but some documents failed |
| 2 | Configuration problem: unknown or ambiguous company, bad date window |
| 3 | A source could not be reached |
| 4 | A local filesystem problem: full disk, permissions, unusable path |
| 130 | Interrupted |

## Sources

**BSE is primary.** It is one integration, it is complete for anything a
company is legally obliged to file, and every filing carries a date and BSE's
own category label.

Two BSE feeds are read, and both serve PDFs from the same `corpfiling` store:

| Feed | Covers |
| --- | --- |
| Announcements | The Regulation 30 / LODR disclosure stream — results, board meetings, transcripts, credit ratings, AGM notices, order wins, pledge disclosures, management changes. This is the bulk of corporate filings. |
| Annual report archive | Every annual report BSE holds, with a direct PDF link. |

The archive is read separately because the announcement feed carries an annual
report only as it was filed, so a one-year window finds one or two. The archive
returns Infosys's 31 reports back to 1997 and Avantel's 27 back to 2000. The
two feeds overlap on recent years, and the duplicate is dropped by comparing
the stored filename — for Infosys over thirty years, 4 rows overlapped and the
archive added 27.

Not covered, because they are not PDFs: BSE presents the shareholding pattern
and the corporate governance report as structured tables rather than documents,
so they need a different treatment from a PDF downloader. Say so if you want
them and they can be looked at as a separate piece of work.

**A company's website is the fallback.** Some documents are simply not on BSE.
Earnings-call and AGM transcripts are the common case: publishing them is
mandatory only for larger listed entities, so smaller companies put them on
their own investor pages instead. Under `--source auto` the website is
consulted only for the document types BSE did not supply, which keeps BSE
authoritative and avoids fetching the same annual report twice under two names.

The website address is **discovered, not configured**: BSE records each listed
company's own URL in its company information. The fetcher reads it, checks
`robots.txt`, follows the site's own navigation to a handful of investor pages,
and works out how the documents are published:

| Strategy | For |
| --- | --- |
| `auto` | The default: try both of the below and merge the results. |
| `html_links` | An ordinary page whose PDF links are in the HTML. |
| `js_bundle` | A JavaScript app whose document list is compiled into its script bundle, so the HTML contains nothing useful. |

Measured on 2026-09-03 across eight sampled companies, discovery produced
documents for seven with no configuration at all — for example 817 documents
including 33 transcripts for MTAR Technologies, and all 796 of Avantel's,
whose site is a React app serving an empty `<div id="root">` with its documents
buried in a content-hashed bundle.

### When discovery is not enough

[companies.json](companies.json) holds per-company overrides and is normally
empty, which is correct. Add an entry when BSE lists no website or a stale one,
when the documents live on a page the shallow crawl does not reach, or when a
strategy needs pinning. An entry always wins over discovery.

What an override cannot fix is a site behind a bot-protection challenge. Astra
Microwave (`astramwp.com`) answers every request with HTTP 307 and no
`Location` header, which needs a browser engine rather than a different URL.
Such a site is reported as a note and the run continues on BSE.

Expect this source to stay narrower and less reliable than BSE. That is why it
is the fallback and not the primary.

### Website dates

Company sites rarely publish a document date as a field, so the date is read
out of the title or filename (`AGM Transcript 23.06.2025`). Documents whose
date cannot be read are kept rather than dropped, since the fallback exists to
find things BSE lacks and discarding a transcript for want of a date in its
name would defeat that. Such documents are stored as `undated`.

## Scope

This package finds documents, decides which are wanted, and writes those PDFs
to disk. Deliberately **not** in scope, and deliberately not stubbed out:

| Not here | Why |
| --- | --- |
| Database writes | Storage decisions are unresolved. Nothing here imports `db`. |
| PDF text extraction | Downloading is the deliverable; parsing is a separate stage. |
| Financial statement figures | Quarterly and annual numbers come from a different source, not from these documents. |

The one concession to persistence is `manifest.json`, a sidecar described
below, plus the weekly scrip-list cache. Neither is a database nor a substitute
for one.

## Document types

`annual_report`, `results`, `board_meeting`, `presentation`, `transcript`,
`credit_rating`, `agm_egm`, `pledge`, `management_change`, `order_win`.

Classification is multi-label: an "Outcome of Board Meeting" carrying the
quarterly numbers is both `board_meeting` and `results`. On disk a document is
stored under the first type it matched, in the order above.

### Reports, not every filing

Omitting `--types` selects every **report type**, not every filing. Most of
what a large company files is neither a report nor interesting here: ESOP
allotments, lost share certificates, newspaper publications, routine
disclosures. Infosys filed 219 documents in the year to September 2026, of
which 177 matched no report type. Downloading 572 MB to find three annual
reports is not a useful default, so those are skipped and the count is
reported. `--include-unclassified` takes everything.

A download above 200 MB stops and asks for `--types`, `--latest`, `--max-mb`
or `--yes`, so a one-line command cannot pull hundreds of megabytes by
accident.

### Titles

Some companies write nothing useful in the headline — Infosys files almost
everything as "Enclosed", which once produced 150 local files all named
`..._enclosed_....pdf`. Where the headline says nothing, BSE's own subcategory
is used instead, and a very short headline is qualified with it. This affects
filenames, so documents fetched before this change will be re-downloaded under
better names rather than recognised as already present.

BSE's own subcategory label is used wherever it exists, and the mapping in
[taxonomy.py](taxonomy.py) was built from the subcategories BSE actually
returned for a small-cap and a large-cap over three years. Documents filed
under BSE's generic "Company Update / General" bucket, and everything harvested
from a website, are matched on their title instead. Those title patterns are
the part most likely to need maintenance, which is why the smoke test covers
them in detail.

## Output layout

```
downloads/
  manifest.json
  annual_report/
    532406_2026-05-30_annual-report-for-the-year-2025-26_1a2b3c4d.pdf
  transcript/
    532406_2025-06-23_avantel-limited-agm-transcript-23-06-2025_9f2c1e08.pdf
```

Filenames are `<scrip>_<date>_<title slug>_<document id prefix>.pdf`. The id
prefix keeps several documents of the same type and date from colliding, which
is common around results season. Long titles are shortened so the whole path
stays within what Windows accepts without long paths enabled.

`manifest.json` records, per document: source, source URL, document id, date,
title, BSE category and subcategory, classified types, local path, byte count,
SHA-256, and when it was fetched.

## Getting at the files over HTTP

The command line writes PDFs into `downloads/` and prints where they went. The
[HTTP API](../api/README.md) writes to the same place and returns JSON; use its
`GET /files` index and the `download_url` on each document to fetch the bytes.

## Behaviour worth knowing

- **Atomic writes.** Bytes land in a `.part` file and are renamed only once the
  document has fully arrived, so an interrupted run never leaves a truncated
  PDF that a later run mistakes for a finished one.
- **PDF validation.** Every response is checked for the `%PDF` magic bytes.
  Both BSE and company sites answer some requests with an HTML error page under
  a 200 status, and without the check those are saved with a `.pdf` extension
  and fail much later.
- **BSE windows are split and retried.** BSE answers a query it will not serve
  with an empty `{}` rather than an error, and treating that as "no filings"
  reports a busy company as silent. Requests are therefore made a year at a
  time, and any window BSE refuses is halved and retried. MTAR Technologies is
  the worked case: three years returns `{}`, two years returns 246 filings.
- **Two attachment directories on BSE.** Attachments are served from
  `AttachHis` and `AttachLive`; recent filings exist in both, older ones only
  in `AttachHis`. Both are offered as candidates and tried in turn, because the
  `OLD` flag on a filing reads `1` even for filings from the current week and
  cannot be used to choose.
- **Idempotent reruns.** An existing file is skipped unless `--force` is given.
- **Nothing is ever deleted.** A download whose bytes are identical to an
  earlier document is still saved and merely flagged in the summary, since a
  duplicate is more often a re-filing worth keeping than a mistake.
- **Paced requests.** One second between requests to a given host by default,
  with bounded retries on 429 and 5xx responses. Pacing is per host, so waiting
  politely on BSE does not also slow a company website.
- **robots.txt is respected** when reading a company website, overridable with
  `--ignore-robots`.

## Failure handling

Failures are separated by kind, because the right response differs. The types
are defined in [errors.py](errors.py):

| Failure | Response |
| --- | --- |
| One document 404s, or is an HTML error page | Recorded as `failed`, run continues |
| A transfer dies mid-body | Retried once, then recorded as `failed` |
| A source stops answering entirely | Five consecutive failures abort the run |
| A company website is unreachable or blocked | Reported as a note; BSE results stand |
| Disk full, permissions, unusable path | Aborts immediately |
| Manifest cannot be written | Reported as a warning; the PDFs are already safe |
| Corrupt manifest, cache or registry | Reported clearly rather than crashing mid-run |
| Interrupted with Ctrl+C | Partial file removed, rerun continues where it stopped |

A run that aborts still reports everything it completed first.

## Tests

```bash
python -m ingestion.smoke_test   # offline; no network required
```

One hundred and fifty-two checks covering classification, company-name
resolution, website discovery, strategy detection, selection, path
construction, selection defaults, manifest handling and every download failure
path, using canned
responses rather than the network. The classification rules and the failure
paths are the two things that rot silently: if BSE renames a subcategory,
documents stop matching and a run reports "nothing to download" rather than
failing outright.

## A caution

These are primary-source documents retrieved from BSE and from company
websites. Observe their terms of use, keep the request pacing conservative, and
leave the robots.txt check enabled unless you have a specific reason not to.
Retrieving a document is not permission to redistribute it.
