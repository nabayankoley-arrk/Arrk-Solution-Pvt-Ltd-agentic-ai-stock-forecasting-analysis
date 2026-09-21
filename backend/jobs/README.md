# Jobs

Manually-run jobs. Each is a module with a `__main__` guard, run from `backend/`.

| Job | Purpose |
| --- | --- |
| `python -m jobs.top20` | Print the current top 20 BSE companies by market capitalisation |
| `python -m jobs.summarise_reports` | Download the latest AR and TR per company, summarise each with Claude, store the summaries |

## Before the first run

Two things must be provided. Neither is in the repository, and the job checks
both before spending anything.

**1. A Postgres database.** There was none: `backend/db/` did not exist, and the
agent packages import a `db` module that was never committed. The schema and
connection layer are now here. Point them at a server and create the table:

```powershell
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/stockdb"
python -m db.apply_schema --check    # what is there now
python -m db.apply_schema            # create what is missing
```

`--check` reports the server, the database and every table it finds, marking
the ones this project owns. It changes nothing.

**2. An Anthropic API key.**

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Or sign in once with `ant auth login`, which stores a profile the SDK reads.

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

`document_summaries` is the only table this work adds. The agent packages under
`backend/agents/` expect tables of their own via
`db.upsert.save_fundamental_analysis_results` and `save_technical_analysis_results`;
those are **not** defined here, because their shape belongs to whoever wrote
those agents. Guessing at them would be worse than leaving the gap visible.

## Running it

```powershell
# What would happen, what it would cost. Downloads and reads, calls no model.
python -m jobs.summarise_reports --check

# Same, but stops before the token count too
python -m jobs.summarise_reports --dry-run

# The real run: top 20 by market cap
python -m jobs.summarise_reports

# A pinned set instead of the live top 20
python -m jobs.summarise_reports --symbols INFY TCS RELIANCE
```

**Run `--check` first.** It prints the exact token count from the API's own
counter and the estimated cost. A run whose estimate exceeds $10 stops and asks
for `--yes`, in the same way the downloader guards a large download.

### Options

| Option | Default | Effect |
| --- | --- | --- |
| `--symbols` | top 20 | Pin an exact set by ticker, name or scrip code |
| `--count N` | 20 | How many of the top companies |
| `--years N` | 1 | How far back to look for the latest of each |
| `--check` | | Report plan, tokens and cost, then stop |
| `--dry-run` | | Download and read only |
| `--force` | | Re-summarise documents already stored |
| `--yes` | | Proceed past the $10 threshold |
| `--effort` | `low` | Model effort: `low` … `max` |
| `--model` | `claude-opus-5` | |

### Exit codes

`0` success, `1` some documents failed, `2` a prerequisite is missing (no
database, no API key, cost above the threshold), `3` a source was unreachable.

## What it does

Per company, the latest annual report and the latest call transcript — taking
whichever of the two exists, which is the same rule the fetcher uses:

```
ingestion.collect     find the latest AR and TR (BSE, company site as fallback)
ingestion.downloader  write the PDFs, verify %PDF, record sha256
ingestion.extract     PyMuPDF text layer
ingestion.summarise   Claude, streamed
db.documents          one row, keyed on sha256
```

Three things make a rerun cheap. A PDF already on disk is not downloaded again;
a document whose `sha256` is already in `document_summaries` is not sent to the
model again; and the write is `ON CONFLICT (sha256) DO UPDATE`, so the same
document refreshes its row rather than duplicating it.

## Cost, which is the thing to watch

Annual reports are large. Measured on real filings:

| Document | Pages | Characters |
| --- | --- | --- |
| State Bank of India annual report | 756 | 1,905,760 |
| Infosys annual report | 384 | 1,314,631 |
| Avantel annual report | 261 | 643,779 |
| Avantel AGM transcript | 18 | 62,604 |

That is roughly 160,000–475,000 input tokens for an annual report, against a
few thousand for a transcript. Twenty companies is therefore dominated entirely
by the annual reports, and at `claude-opus-5` rates ($5 per million input
tokens) a full top-20 run is tens of dollars. `--check` gives you the real
number before you commit.

Nothing is ever truncated silently. If you want to cap what is sent, that is a
deliberate change to `ingestion.extract.head`, and the row records
`char_count` so a summary built on a partial document is identifiable later.

Two levers if the cost is too high: `--effort` is already at `low`, and
`--symbols` narrows the set. Choosing a cheaper model is a decision for you,
not a default I should pick — `--model` takes any model id.

## Scheduling

This is deliberately a manual job, as asked. Nothing schedules it. When it
should run nightly, the thing to add is a scheduler entry calling the same
module — not a second code path.
