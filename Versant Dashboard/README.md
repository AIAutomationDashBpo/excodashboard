# Brainbase Operations Dashboard

Internal ops dashboard for AI voice bots. FastAPI + HTMX + ApexCharts + Tailwind CSS + PostgreSQL.

## Quick Start (Docker — recommended)

```bash
# 1. Copy and fill in your Brainbase API key
cp .env.example .env
# Edit .env — set BRAINBASE_API_KEY=sk_...

# 2. Start PostgreSQL + the app
docker compose up -d

# 3. Run initial ingestion (workers and deployments first)
docker compose exec app python ingestion/pull_workers.py
docker compose exec app python ingestion/pull_deployments.py

# 4. Backfill 90 days of call logs
docker compose exec app python ingestion/backfill_history.py --days 90

# 5. Open the dashboard
open http://localhost:8000
```

## Manual Start (no Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL and BRAINBASE_API_KEY

# Create and migrate the database
createdb brainbase_dashboard
psql brainbase_dashboard < migrations/V1__initial_schema.sql

# Run the app
uvicorn app.main:app --reload --port 8000
```

## After first login — seed your worker IDs

After `pull_workers.py` runs, check which worker IDs were discovered:
```sql
SELECT worker_id, name FROM workers;
```
Then update `migrations/seed.sql` — replace `VERSANT_WORKER_ID` and `BARTACO_WORKER_ID` — and run:
```bash
psql brainbase_dashboard < migrations/seed.sql
```

## Ingestion schedule (run these regularly or deploy as Azure Functions)

| Script | Recommended interval |
|---|---|
| `pull_workers.py` | Every 6 hours |
| `pull_deployments.py` | Every 6 hours |
| `pull_voice_analysis.py` | Every 15 minutes |
| `pull_call_logs.py` | Every 1 hour |
| `pull_runtime_errors.py` | Every 5 minutes |

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Dashboard surfaces

| URL | Surface |
|---|---|
| `/metrics` | KPI headlines, call trends, goals vs actuals |
| `/billing` | Monthly cost, tier, Echo surcharge |
| `/insights` | Disposition breakdown, call feed, transcripts |
| `/uptime` | SLA %, downtime, penalty, incident timeline |
| `/health` | JSON health check |
| `/api/docs` | Swagger UI (development only) |
