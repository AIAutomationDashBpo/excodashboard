"""
Azure Function — Timer trigger every 6 hours.
Pulls all voice Deployments for every active Worker.
"""
import asyncio, asyncpg, os, httpx, logging, re
from ingestion.shared.pipeline import pipeline_run, get_conn, _load_env, parse_dt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_load_env()
API_KEY  = os.environ["BRAINBASE_API_KEY"]
API_BASE = os.environ.get("BRAINBASE_BASE_URL", "https://api.usebrainbase.com")
HEADERS  = {"x-api-key": API_KEY, "Accept": "application/json"}


def infer_env(name: str) -> str:
    """Infer environment from deployment name convention (e.g. versant-prod)."""
    name_lower = name.lower()
    if re.search(r'prod', name_lower):   return 'prod'
    if re.search(r'test|staging', name_lower): return 'test'
    return 'dev'


async def main():
    conn = await get_conn()
    try:
        workers = await conn.fetch("SELECT worker_id FROM workers WHERE is_active=TRUE")
        total = 0
        async with pipeline_run(conn, "deployments"):
            async with httpx.AsyncClient(timeout=30) as client:
                for w in workers:
                    wid = w["worker_id"]
                    r = await client.get(
                        f"{API_BASE}/api/workers/{wid}/deployments/voice", headers=HEADERS)
                    if r.status_code == 404:
                        continue
                    r.raise_for_status()
                    for d in r.json():
                        env = infer_env(d["name"])
                        await conn.execute("""
                            INSERT INTO deployments
                                (deployment_id, worker_id, name, environment, is_active, created_at, updated_at, pulled_at)
                            VALUES ($1,$2,$3,$4,TRUE,$5::timestamptz,$6::timestamptz,NOW())
                            ON CONFLICT (deployment_id) DO UPDATE SET
                                name=EXCLUDED.name, environment=EXCLUDED.environment,
                                updated_at=EXCLUDED.updated_at, pulled_at=NOW()
                        """, d["id"], wid, d["name"], env,
                            parse_dt(d.get("createdAt")), parse_dt(d.get("updatedAt")))
                        total += 1
            logger.info(f"pull_deployments: upserted {total} deployments")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
