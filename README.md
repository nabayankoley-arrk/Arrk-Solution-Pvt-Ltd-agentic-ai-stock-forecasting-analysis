# Arrk-Solution-Pvt-Ltd-agentic-ai-stock-forecasting-analysis
AI-powered stock forecasting and analysis platform leveraging Large Language Models (LLMs), agentic AI workflows, market data, technical indicators, news sentiment, and fundamental analysis to generate explainable investment insights and support data-driven financial decision-making.

## Database Setup

PostgreSQL, accessed with raw `psycopg2` — no ORM, no migration tool. Three
schemas: `public`, `"Technical"`, `"Memory"` (the last two are mixed-case and
must be double-quoted in every query).

### 1. Start Postgres and load the schema

```bash
docker run -d --name stock-analysis-pg -e POSTGRES_PASSWORD=<choose one> -e POSTGRES_DB=stock_analysis -p 5432:5432 postgres:16
```

```bash
docker cp backend/db/schema.sql stock-analysis-pg:/tmp/schema.sql && docker exec stock-analysis-pg psql -U postgres -d stock_analysis -f /tmp/schema.sql
```

Needs no `psql` on your PATH. Against a server you already have, run
`psql "$DATABASE_URL" -f backend/db/schema.sql` instead.

### 2. Configure `backend/.env`

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

### 3. Install dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. On a network that inspects TLS

Skip unless outbound calls fail with `self-signed certificate in certificate
chain`. `bootstrap.py` installs the OS trust store for Python's `ssl` (covering
`requests`), but yfinance fetches via `curl_cffi`, which uses its own bundled
CA store — that one needs an exported PEM. From `backend/`, in PowerShell:

```powershell
$o="certs\win-ca.pem"; ni -Force (Split-Path $o) -ItemType Directory | Out-Null; $sb=New-Object Text.StringBuilder; 'Cert:\LocalMachine\Root','Cert:\CurrentUser\Root','Cert:\LocalMachine\CA' | % { gci $_ -EA SilentlyContinue | % { [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----'); [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks')); [void]$sb.AppendLine('-----END CERTIFICATE-----') } }; sc $o $sb.ToString() -Encoding ascii
```

`bootstrap.py` picks `backend/certs/win-ca.pem` up automatically. It is
machine-specific and gitignored — regenerate it per machine.

## Frontend Setup

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

`npm run dev` (plain Next dev server on port 3000) also works for fast UI
iteration, but its `/api/chat` calls will 404 since nothing serves the
backend on that same origin in dev mode — use it for layout/markup work,
and `npm run build` + the FastAPI-served page for anything that needs a
real API response.

## Seeding data

### Fundamentals

`seed_fundamentals.py` only seeds tickers **already in `universe`**, and nothing
in the repo populates that table. Insert your tickers first:

```sql
INSERT INTO universe (ticker, company_name, exchange, sector)
VALUES ('TCS.NS', 'Tata Consultancy Services', 'NSE', 'Information Technology')
ON CONFLICT (ticker) DO NOTHING;
```

Then, from `backend/`:

```bash
python -m db.seed_fundamentals
```

Run it as a module — `python db/seed_fundamentals.py` fails with
`attempted relative import with no known parent package`.

It writes `financial_statements` and `analyst_price_targets` from yfinance.
`analyst_rating_changes` is intentionally not seeded (yfinance returned no data
for the tickers tested). Yahoo rate-limits aggressively from shared office IPs;
`Too Many Requests` is transient, so just retry.

### Price history

From `backend/`, after the tickers are in `universe`:

```bash
python -m db.seed_price_history TCS.NS
```

Omit the ticker to seed every ticker in `universe`. Tickers not in `universe`
are skipped with a message rather than failing on the foreign key.

Fetches 3 years of daily OHLCV into `"Technical".price_history` — more than the
250 trading days `technical_analysis/config.py` asks for, because the
Orchestrator's `long_term` horizon requests `lookback_days=500`. Re-running
upserts on `(ticker, trade_date)`, so it is safe to repeat daily.

Seed this **before** running any analysis: two separate things read the table.
The technical pillar computes every indicator from it and treats fewer than
`MIN_PRICE_HISTORY_ROWS` (20) rows as an outright fetch failure, and the
Orchestrator takes the latest close as Fundamental Analysis's `current_price` —
without which `relative_valuation` and `analyst_consensus` both report
"insufficient data" however complete the filings are.
