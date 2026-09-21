# Jobs

Manually-run jobs. Each is a module with a `__main__` guard, run from `backend/`.

| Job | Purpose |
| --- | --- |
| `python -m jobs.top20` | Print the current top 20 BSE companies by market capitalisation |
| `python -m jobs.summarise_reports` | Download the latest AR and TR per company, summarise each, store the summaries |

## Before the first run

Two things must be provided. Neither is in the repository, and the job checks
both before it downloads anything.

**1. A Postgres database.** The project's `backend/db/` layer defines the
schema and the connection; this job adds one table, `document_summaries`, to
`db/schema.sql`. Connection details come from the environment, via
`db/connection.py`:

```powershell
$env:DB_HOST = "localhost"; $env:DB_PORT = "5432"
$env:DB_NAME = "stock_analysis"
$env:DB_USER = "postgres"; $env:DB_PASSWORD = "..."
```

Or put them in `backend/.env`, which `bootstrap.py` loads. Then:

```powershell
python -m db.apply_schema --check    # what is there now
python -m db.apply_schema            # load schema.sql
```

`--check` lists every table the project expects and marks the missing ones. It
changes nothing. `schema.sql`'s own header gives the `psql` equivalent, which
remains the reference way to load it.

**2. An LLM key.** Summarising reuses the project's own client,
`agents/orchestrator/llm_client.call_llm_chat()`, so provider and model come
from `agents/orchestrator/config.py` and the environment. Put them in
`backend/.env`, which `bootstrap.py` loads and which is gitignored:

```
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=inclusionai/ling-3.0-flash-fin:free
```

`LLM_PROVIDER=ollama` runs against a local model instead, with no key. This job
never picks a provider of its own -- change the environment, not the code.

## The table

One table, `document_summaries`, defined in [db/schema.sql](../db/schema.sql).

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
| `created_at`, `updated_at` | |

`document_summaries` is the only table this work adds; the other twelve in
`schema.sql` belong to the agents and the chat router. The reads and writes for
it live in [db/upsert.py](../db/upsert.py) alongside the rest
(`save_document_summary`, `existing_document_checksums`,
`latest_document_summary`, `report_type_for`).

It deliberately has no foreign key to `universe(ticker)`. This job addresses
companies by BSE scrip code across the top 20 by market capitalisation, which
is not the same set as `universe`, and uses unsuffixed tickers (`INFY`) where
`universe` holds NSE-suffixed ones (`INFY.NS`).

## Running it

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

### Options

| Option | Default | Effect |
| --- | --- | --- |
| `--symbols` | top 20 | Pin an exact set by ticker, name or scrip code |
| `--count N` | 20 | How many of the top companies |
| `--years N` | 1 | How far back to look for the latest of each |
| `--check` | | Report plan, sizes and which will be split, then stop |
| `--dry-run` | | Download and read only |
| `--force` | | Re-summarise documents already stored |
| `--delay` | 1.0 | Seconds between requests to a given host |

### Exit codes

`0` success, `1` some documents failed, `2` a prerequisite is missing (no
database, no API key), `3` a source was unreachable.

## What it does

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

## Long documents, which is the thing to watch

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

## Scheduling

This is deliberately a manual job, as asked. Nothing schedules it. When it
should run nightly, the thing to add is a scheduler entry calling the same
module — not a second code path.
