"""
Azure Function — Timer trigger every 6 hours.
Pulls all Workers from Brainbase API and upserts into PostgreSQL.
"""
import asyncio, asyncpg, os, httpx, logging
from ingestion.shared.pipeline import pipeline_run, get_conn, _load_env, parse_dt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_load_env()
API_KEY  = os.environ["BRAINBASE_API_KEY"]
API_BASE = os.environ.get("BRAINBASE_BASE_URL", "https://api.usebrainbase.com")
HEADERS  = {"x-api-key": API_KEY, "Accept": "application/json"}


async def main():
    conn = await get_conn()
    try:
        async with pipeline_run(conn, "workers"):
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{API_BASE}/api/workers", headers=HEADERS)
                r.raise_for_status()
                workers = r.json()

            count = 0
            for w in workers:
                await conn.execute("""
                    INSERT INTO workers (worker_id, name, lob_name, is_active, created_at, updated_at, pulled_at)
                    VALUES ($1, $2, $3, TRUE, $4::timestamptz, $5::timestamptz, NOW())
                    ON CONFLICT (worker_id) DO UPDATE SET
                        name=EXCLUDED.name, updated_at=EXCLUDED.updated_at, pulled_at=NOW()
                """, w["id"], w["name"], w.get("name", w["id"]),
                    parse_dt(w.get("createdAt")), parse_dt(w.get("updatedAt")))
                count += 1

            await conn.execute(
                "UPDATE pipeline_runs SET row_count=$1 WHERE id=(SELECT MAX(id) FROM pipeline_runs WHERE source_name='workers')",
                count)
            logger.info(f"pull_workers: upserted {count} workers")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
