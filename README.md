# Arrk-Solution-Pvt-Ltd-agentic-ai-stock-forecasting-analysis
AI-powered stock forecasting and analysis platform leveraging Large Language Models (LLMs), agentic AI workflows, market data, technical indicators, sentiment from annual reports and earnings-call transcripts, and fundamental analysis to generate explainable investment insights and support data-driven financial decision-making.

## Project layout

| Path | What |
| --- | --- |
| `backend/` | FastAPI app (`main.py`), LangGraph agents, Postgres layer, document fetcher, jobs. **Every Python command runs from here.** |
| `backend/agents/` | The chat agent (`chat_intent_routing/`), the orchestrator, and the technical / fundamental / sentiment analysis subgraphs |
| `backend/db/` | Schema, connection, seed scripts |
| `backend/ingestion/` | BSE / company-website PDF fetcher ([Document fetcher](#document-fetcher)) |
| `backend/jobs/` | Manually-run jobs ([Jobs](#jobs)) |
| `frontend/` | Next.js chat UI, built as a static export and served by `backend/main.py` |

## How it works

```
frontend (chat UI) --POST /api/chat/stream--> backend/main.py
                                                  |
   agents/chat_intent_routing  -- LangGraph tool-calling agent, conversation in a Postgres checkpointer
       |- analyze_stock(ticker)        -> agents/orchestrator
       |                                    |- technical_analysis    (rules, "Technical".price_history)
       |                                    |- fundamental_analysis  (rules, financial_statements)
       |                                    |- sentiment_analysis    (document_summaries)
       |                                    `- reconciles the three pillars, optional human review
       `- get_filing_sentiment(ticker) -> agents/sentiment_analysis only
```

The chat agent reads each message in the context of the session, decides
whether to answer directly, ask which company, refuse an off-topic question or
call a tool, and writes the reply from the tool results. `analyze_stock` gives
the overall picture (price, signals, support/resistance, all three pillars);
`get_filing_sentiment` answers questions about what the latest annual report
and call transcript said — management tone, guidance, risks, themes, quotes.

### Where the LLM is used

Technical and fundamental analysis make no LLM calls. Every prompt:

| Prompt | File (under `backend/`) | When it runs |
| --- | --- | --- |
| Chat agent | `agents/chat_intent_routing/nodes/agent.py`, tool descriptions in `nodes/tools.py` | Every chat turn, again after each tool call |
| Sentiment profile | `agents/sentiment_analysis/prompts.py` | Once per stored filing summary (and per `PROMPT_VERSION`); cached afterwards |
| Pillar reconciliation | `agents/orchestrator/llm_client.py` | Each analysis |
| Price-range forecast | `agents/orchestrator/forecast_price_range.py` | Only with `forecast_days` (`/api/stock-analysis`) |
| Filing summaries | `ingestion/summarise.py` | Offline, in `jobs/summarise_reports` |

All use the provider and model from `backend/.env` (`LLM_PROVIDER`,
`OPENROUTER_MODEL`). The chat agent needs a model with tool calling.

## Setup

### Database

PostgreSQL, accessed with raw `psycopg2` — no ORM, no migration tool. Three
schemas: `public`, `"Technical"`, `"Memory"` (the last two are mixed-case and
must be double-quoted in every query).

#### 1. Start Postgres and load the schema

```bash
docker run -d --name stock-analysis-pg -e POSTGRES_PASSWORD=<choose one> -e POSTGRES_DB=stock_analysis -p 5432:5432 postgres:16
```

```bash
docker cp backend/db/schema.sql stock-analysis-pg:/tmp/schema.sql && docker exec stock-analysis-pg psql -U postgres -d stock_analysis -f /tmp/schema.sql
```

Needs no `psql` on your PATH. Against a server you already have, run
`psql "$DATABASE_URL" -f backend/db/schema.sql` instead.

After pulling a change to `schema.sql`, re-apply it from `backend/`. It only
creates or adds what is missing, so it is safe to repeat:

```bash
python -m db.apply_schema
```

The chat's conversation checkpoints live in LangGraph's own tables, which the
API creates on first startup.

#### 2. Configure `backend/.env`

Gitignored, loaded by `backend/bootstrap.py`. An exported shell variable always
wins over the file.

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock_analysis
DB_USER=postgres
DB_PASSWORD=<the password from step 1>

LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=<your key>
OPENROUTER_MODEL=inclusionai/ling-3.0-flash-fin:free
```

Models ending `:free` draw on a separate daily allowance, so they keep working
after a key's spend limit is exhausted.

#### 3. Install dependencies

Python 3.9 or newer. A virtual environment is recommended:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell or cmd
source .venv/bin/activate       # bash
pip install -r backend/requirements.txt
```

Re-run this after pulling any merge that touches `requirements.txt` -- a new
dependency (e.g. `pymupdf`, added for the sentiment/ingestion jobs) otherwise
surfaces later as a `ModuleNotFoundError` deep in an import chain rather than
anything that points back at this file.

#### 4. On a network that inspects TLS

Skip unless outbound calls fail with `self-signed certificate in certificate
chain`. `bootstrap.py` installs the OS trust store for Python's `ssl` (covering
`requests`), but yfinance fetches via `curl_cffi`, which uses its own bundled
CA store — that one needs an exported PEM. From `backend/`, in PowerShell:

```powershell
$o="certs\win-ca.pem"; ni -Force (Split-Path $o) -ItemType Directory | Out-Null; $sb=New-Object Text.StringBuilder; 'Cert:\LocalMachine\Root','Cert:\CurrentUser\Root','Cert:\LocalMachine\CA' | % { gci $_ -EA SilentlyContinue | % { [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----'); [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks')); [void]$sb.AppendLine('-----END CERTIFICATE-----') } }; sc $o $sb.ToString() -Encoding ascii
```

`bootstrap.py` picks `backend/certs/win-ca.pem` up automatically. It is
machine-specific and gitignored — regenerate it per machine.

### Frontend

The chat UI is a Next.js (App Router, TypeScript, Tailwind) app that lives in
`frontend/`, built as a **static export**. `backend/main.py` mounts
`frontend/out` (the build output, gitignored) at `/`, so the API and the UI
are served from the same FastAPI process on the same origin — no CORS
configuration needed.

```bash
cd frontend
npm install
npm run build   # static export -> frontend/out
```

Then start the backend as usual (`uvicorn main:app --reload` from `backend/`)
and open `http://127.0.0.1:8000/`. Re-run `npm run build` after any frontend
change and refresh the page — StaticFiles reads from disk on every request,
so no backend restart is needed.

The chat streams its replies from `POST /api/chat/stream`: a status line while
an analysis runs ("Analysing TCS.NS..."), then the reply word by word.

`npm run dev` (plain Next dev server on port 3000) also works for fast UI
iteration, but its `/api/chat/stream` calls will 404 since nothing serves the
backend on that same origin in dev mode — use it for layout/markup work,
and `npm run build` + the FastAPI-served page for anything that needs a
real API response.

## Seeding data

### Universe

`universe` is the FK parent every other table below needs a row in, and
nothing populated it until `db/seed_universe.py`: it fetches the top 20
BSE-listed companies by market capitalisation (`jobs.top20`, the same source
`jobs/summarise_reports.py` uses) and upserts each in. From `backend/`:

```bash
python -m db.seed_universe
```

`seed_fundamentals.py` and `seed_price_history.py` both call this
automatically at the start of their own `main()`, so running either with no
arguments seeds exactly the current top 20 — a manual `INSERT` is no longer
needed for the default path. BSE's own ticker is unsuffixed (`INFY`); this
appends `.NS` to match the NSE-suffixed form the rest of the codebase assumes
(`fetch_fundamentals_data.py`, `fetch_price_history.py`, both yfinance seed
scripts). `sector` is left NULL — BSE's scrip list carries no sector field.

The list moves with the market: re-running after a big shift can return a
different twentieth name (and safely upserts it in alongside whatever was
seeded before — nothing already in `universe` is removed).

### Fundamentals

From `backend/`:

```bash
python -m db.seed_fundamentals
```

Run it as a module — `python db/seed_fundamentals.py` fails with
`attempted relative import with no known parent package`.

Writes `financial_statements` and `analyst_price_targets` from yfinance for
the top 20 (see Universe above). `analyst_rating_changes` is intentionally
not seeded (yfinance returned no data for the tickers tested).

Yahoo rate-limits aggressively from shared office IPs, and worse across 20
tickers in one run than for a single one — expect some `Too Many Requests`
failures on the first pass. It is safe to just re-run: every insert is an
upsert, so an already-seeded ticker is refreshed, not duplicated, and only
the ones that failed cost anything on the next attempt.

### Price history

From `backend/`:

```bash
python -m db.seed_price_history                # top 20 by market cap
python -m db.seed_price_history TCS.NS INFY.NS # just these
```

Naming tickers still requires them to already be in `universe`; unknown ones
are skipped with a message rather than failing on the foreign key.

Fetches 3 years of daily OHLCV into `"Technical".price_history` — more than the
250 trading days `technical_analysis/config.py` asks for, because the
Orchestrator's `long_term` horizon requests `lookback_days=500`. Re-running
upserts on `(ticker, trade_date)`, so it is safe to repeat daily — and, as with
Fundamentals above, safe to just re-run after a rate-limited batch.

Seed this **before** running any analysis: two separate things read the table.
The technical pillar computes every indicator from it and treats fewer than
`MIN_PRICE_HISTORY_ROWS` (20) rows as an outright fetch failure, and the
Orchestrator takes the latest close as Fundamental Analysis's `current_price` —
without which `relative_valuation` and `analyst_consensus` both report
"insufficient data" however complete the filings are.

### Sentiment

The Sentiment Analysis subgraph reads `document_summaries`, populated by
`backend/jobs/summarise_reports.py` from filings that `backend/ingestion`
downloads. Without it the sentiment pillar returns "unavailable" (no
transcript or annual-report data) and analysis falls back to the technical and
fundamental pillars alone — this is expected on an unseeded database, not a
bug.

From `backend/`:

```bash
python -m jobs.summarise_reports --check   # what would happen, no downloads
python -m jobs.summarise_reports           # the real run, top 20 by market cap
```

Needs the same Postgres connection as everything else above, plus an LLM key
in `backend/.env` (the job reuses `agents/orchestrator/llm_client`) — see
[Jobs](#jobs) for the full prerequisites, table layout, and how it
handles annual reports too large for one model call.

The job addresses companies by **unsuffixed BSE ticker** (`TCS`), while the
rest of the system uses the NSE suffix (`TCS.NS`); `document_summaries` has no
foreign key to `universe` for that reason. It downloads PDFs from BSE and makes
one LLM call per document, so expect it to be slow on a first run, and to hit
the same transient rate limits noted under Fundamentals above.

At request time the sentiment pillar reads the latest stored transcript (up to
6 months old) and annual report (up to 15 months) and gives each summary a
**sentiment profile**: overall label (bullish / neutral / bearish), management
tone (confident / cautious / defensive, or unknown when the summary does not
show it), guidance, per-theme stances (demand, margins, capital allocation,
risks, governance…), positives, concerns and quotes. It takes one LLM call the
first time and is cached on the row after that. The two labels are combined
into one recency-weighted direction.

The prompt is in `backend/agents/sentiment_analysis/prompts.py`. Bump
`PROMPT_VERSION` when you change it: each document's profile is rebuilt on the
next request for it. The profile columns need `python -m db.apply_schema` once.

## Running the API

Start Postgres if it isn't already up (a no-op if it is):

```bash
docker start stock-analysis-pg
```

Then, from `backend/`:

```bash
python -m uvicorn main:app --reload
```

Two things that must hold:

- **Run it from `backend/`.** `main.py` imports `from db.connection import ...`
  and `from agents...`, which resolve relative to that directory. From the repo
  root uvicorn reports `Could not import module "main"`.
- **`python -m uvicorn`, not `uvicorn`** — the `uvicorn.exe` shim is not on PATH
  by default on Windows.

Serves the frontend at <http://127.0.0.1:8000/> and Swagger at `/docs`.

### Endpoints

`POST /api/chat` — free-text chat, answered by a tool-calling LLM agent (see
[How it works](#how-it-works)). Only `message` is required. It reads the
message in the context of the conversation so far and either answers directly
(clarifying questions, off-topic refusals, follow-ups on earlier results) or
calls a tool — `analyze_stock` for the overall picture, `get_filing_sentiment`
for questions about the annual report or call transcript — once per company,
so comparisons work.

- **`session_id`** is the conversation. Omit it on the first message and send
  back the returned one: earlier turns and the company under discussion are
  restored from LangGraph's Postgres checkpointer, so follow-ups like "what
  about its valuation?" or "and Infosys?" work. The checkpoint tables are
  created on first startup. A new session starts with no context.
- **`user_id`** only tags turns in the `"Memory".conversation_history` audit
  log. The frontend sends a per-browser id automatically.

```json
{"user_id": "your-name", "message": "how is TCS looking today?"}
```

`POST /api/chat/stream` takes the same body and runs the same turn, returned as
Server-Sent Events: `status` (`{"ticker", "message"}`, when a tool call starts),
`token` (`{"text"}`, the reply as it is written), then always `done` with the
same JSON `/api/chat` returns. Treat `done.reply` as authoritative.

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream -H "Content-Type: application/json" -d "{\"message\": \"how is TCS looking?\"}"
```

`response_type` is `analysis` (an analysis ran this turn), `reply` or `error`.
Needs the LLM settings from `backend/.env`, and a model that supports tool
calling (OpenRouter lists this per model); if the model can't be reached the
reply says so.

`POST /api/stock-analysis` — structured; `stock_name` is the only required
field. Supply `forecast_days` for an LLM-reasoned price range (a qualitative
estimate over existing pillar signals, not a trained forecasting model — it
carries a disclaimer, and returns `unavailable` rather than inventing a number
when the LLM can't be reached). `/api/chat` never sets `forecast_days`, so chat
replies contain no forecast.

```json
{"stock_name": "TCS.NS", "horizon": "medium_term", "forecast_days": 30}
```

## Document fetcher

Downloads corporate document PDFs to the local filesystem, from BSE first and
from a company's own website where BSE does not carry what was asked for.

Name a company however is convenient — ticker, registered name, ISIN or BSE
scrip code. Nothing needs configuring per company.

### Running it locally

From a terminal at the repository root:

```bash
cd backend
python -m pip install requests                 # all this module needs
python -m ingestion inventory avantel --years 3
```

`requirements.txt` covers the whole backend and also pulls in LangGraph and
psycopg2 for the agent packages. Installing `requests` alone is enough to run
the fetcher, and avoids those heavier dependencies if you only want to try it.

#### The latest reports, which is the usual request

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

#### Naming a company

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

#### Options

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

#### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Finished, but some documents failed |
| 2 | Configuration problem: unknown or ambiguous company, bad date window |
| 3 | A source could not be reached |
| 4 | A local filesystem problem: full disk, permissions, unusable path |
| 130 | Interrupted |

### Sources

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

#### When discovery is not enough

[companies.json](backend/ingestion/companies.json) holds per-company overrides and is normally
empty, which is correct. Add an entry when BSE lists no website or a stale one,
when the documents live on a page the shallow crawl does not reach, or when a
strategy needs pinning. An entry always wins over discovery.

What an override cannot fix is a site behind a bot-protection challenge. Astra
Microwave (`astramwp.com`) answers every request with HTTP 307 and no
`Location` header, which needs a browser engine rather than a different URL.
Such a site is reported as a note and the run continues on BSE.

Expect this source to stay narrower and less reliable than BSE. That is why it
is the fallback and not the primary.

#### Website dates

Company sites rarely publish a document date as a field, so the date is read
out of the title or filename (`AGM Transcript 23.06.2025`). Documents whose
date cannot be read are kept rather than dropped, since the fallback exists to
find things BSE lacks and discarding a transcript for want of a date in its
name would defeat that. Such documents are stored as `undated`.

### Scope

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

### Document types

`annual_report`, `results`, `board_meeting`, `presentation`, `transcript`,
`credit_rating`, `agm_egm`, `pledge`, `management_change`, `order_win`.

Classification is multi-label: an "Outcome of Board Meeting" carrying the
quarterly numbers is both `board_meeting` and `results`. On disk a document is
stored under the first type it matched, in the order above.

#### Reports, not every filing

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

#### Titles

Some companies write nothing useful in the headline — Infosys files almost
everything as "Enclosed", which once produced 150 local files all named
`..._enclosed_....pdf`. Where the headline says nothing, BSE's own subcategory
is used instead, and a very short headline is qualified with it. This affects
filenames, so documents fetched before this change will be re-downloaded under
better names rather than recognised as already present.

BSE's own subcategory label is used wherever it exists, and the mapping in
[taxonomy.py](backend/ingestion/taxonomy.py) was built from the subcategories BSE actually
returned for a small-cap and a large-cap over three years. Documents filed
under BSE's generic "Company Update / General" bucket, and everything harvested
from a website, are matched on their title instead. Those title patterns are
the part most likely to need maintenance, which is why the smoke test covers
them in detail.

### Output layout

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

### Behaviour worth knowing

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

### Failure handling

Failures are separated by kind, because the right response differs. The types
are defined in [errors.py](backend/ingestion/errors.py):

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

### Tests

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

### A caution

These are primary-source documents retrieved from BSE and from company
websites. Observe their terms of use, keep the request pacing conservative, and
leave the robots.txt check enabled unless you have a specific reason not to.
Retrieving a document is not permission to redistribute it.

## Jobs

Manually-run jobs. Each is a module with a `__main__` guard, run from `backend/`.

| Job | Purpose |
| --- | --- |
| `python -m jobs.top20` | Print the current top 20 BSE companies by market capitalisation |
| `python -m jobs.summarise_reports` | Download the latest AR and TR per company, summarise each, store the summaries |

### Before the first run

The job needs the Postgres database and the LLM key from
[Setup](#setup) (steps 1 and 2). Check the schema before the first run:

```bash
python -m db.apply_schema --check    # lists expected tables, marks missing ones
python -m db.apply_schema            # load schema.sql
```

`LLM_PROVIDER=ollama` runs against a local model instead, with no key. This job
never picks a provider of its own -- change the environment, not the code.

### The table

One table, `document_summaries`, defined in [db/schema.sql](backend/db/schema.sql).

| Column | Notes |
| --- | --- |
| `scrip_code`, `ticker`, `company_name` | Who the document belongs to |
| `report_name` | The document's title as filed |
| `report_type` | **`AR`** annual report, **`TR`** transcript report. `CHECK` constrained |
| `filed_on` | Filing date |
| `source`, `source_url`, `local_path` | Where it came from and where it sits |
| `sha256` | Of the PDF bytes. **Unique** — this is what makes reruns safe |
| `page_count`, `char_count` | What was fed to the model |
| `summary`, `model` | The output, and which model produced it |
| `sentiment_profile`, `sentiment_label`, `sentiment_rationale` | Written by the sentiment analysis at request time, not by this job |
| `sentiment_prompt_version`, `sentiment_model`, `sentiment_scored_at` | Which profile prompt and model built them, and when |
| `created_at`, `updated_at` | |

`document_summaries` is the only table this work adds; the others in
`schema.sql` belong to the agents. The reads and writes for
it live in [db/upsert.py](backend/db/upsert.py) alongside the rest
(`save_document_summary`, `existing_document_checksums`,
`latest_document_summary`, `report_type_for`).

It deliberately has no foreign key to `universe(ticker)`. This job addresses
companies by BSE scrip code across the top 20 by market capitalisation, which
is not the same set as `universe`, and uses unsuffixed tickers (`INFY`) where
`universe` holds NSE-suffixed ones (`INFY.NS`).

### Running it

```powershell
# What would happen and how big it is. Downloads and reads, calls no model.
python -m jobs.summarise_reports --check

# Same, but stops before reading sizes too
python -m jobs.summarise_reports --dry-run

# The real run: top 20 by market cap
python -m jobs.summarise_reports

# A pinned set instead of the live top 20
python -m jobs.summarise_reports --symbols INFY TCS RELIANCE
```

**Run `--check` first.** It downloads and reads the PDFs, then reports their
sizes and which will need splitting -- without calling the model or writing a
row.

#### Options

| Option | Default | Effect |
| --- | --- | --- |
| `--symbols` | top 20 | Pin an exact set by ticker, name or scrip code |
| `--count N` | 20 | How many of the top companies |
| `--years N` | 1 | How far back to look for the latest of each |
| `--check` | | Report plan, sizes and which will be split, then stop |
| `--dry-run` | | Download and read only |
| `--force` | | Re-summarise documents already stored |
| `--delay` | 1.0 | Seconds between requests to a given host |

#### Exit codes

`0` success, `1` some documents failed, `2` a prerequisite is missing (no
database, no API key), `3` a source was unreachable.

### What it does

Per company, the latest annual report and the latest call transcript — taking
whichever of the two exists, which is the same rule the fetcher uses:

```
ingestion.collect     find the latest AR and TR (BSE, company site as fallback)
ingestion.downloader  write the PDFs, verify %PDF, record sha256
ingestion.extract     PyMuPDF text layer
ingestion.summarise   the configured LLM, in parts if needed
db.upsert             one row, keyed on sha256
```

Three things make a rerun cheap. A PDF already on disk is not downloaded again;
a document whose `sha256` is already in `document_summaries` is not sent to the
model again; and the write is `ON CONFLICT (sha256) DO UPDATE`, so the same
document refreshes its row rather than duplicating it.

### Long documents, which is the thing to watch

Annual reports are large. Measured on real filings:

| Document | Pages | Characters |
| --- | --- | --- |
| State Bank of India annual report | 756 | 1,906,508 |
| Infosys annual report | 384 | 1,314,631 |
| Avantel annual report | 261 | 643,779 |
| Avantel AGM transcript | 18 | 62,604 |

`inclusionai/ling-3.0-flash-fin:free` holds 262,144 tokens, which is roughly a
million characters of English financial prose. So smaller annual reports fit in
one call and the largest do not -- and since this job targets the top 20 by
market capitalisation, the ones that do not fit are exactly the biggest
companies.

A document over `SUMMARY_MAX_INPUT_CHARS` (800,000 by default, leaving room for
the prompt and the reply) is therefore read in parts: each part is reduced to
notes, and those notes are summarised together. Nothing is truncated silently.
`--check` reports which documents will be split and into how many parts, and
the stored row records the `char_count` it was built from.

Raise `SUMMARY_MAX_INPUT_CHARS` if you move to a model with a larger window;
lower it if you move to a smaller one. The configured model is free, so the
number of calls costs time rather than money.

### Scheduling

This is deliberately a manual job, as asked. Nothing schedules it. When it
should run nightly, the thing to add is a scheduler entry calling the same
module — not a second code path.
