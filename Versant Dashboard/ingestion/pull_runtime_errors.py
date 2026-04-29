"""
Azure Function — Timer trigger every 5 minutes.
Full pull of runtime errors, deduplicating by error_id.
Fires Slack alert on new critical errors.
"""
import asyncio, asyncpg, os, httpx, logging, json
from ingestion.shared.pipeline import pipeline_run, get_conn, _load_env, parse_dt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_load_env()
API_KEY           = os.environ["BRAINBASE_API_KEY"]
API_BASE          = os.environ.get("BRAINBASE_BASE_URL", "https://api.usebrainbase.com")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
HEADERS           = {"x-api-key": API_KEY, "Accept": "application/json"}


async def maybe_alert_slack(worker_name: str, error_type: str, service: str):
    if not SLACK_WEBHOOK_URL:
        return
    msg = f":red_circle: *Critical Bot Error*\nWorker: *{worker_name}* | Service: {service}\nType: `{error_type}`"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(SLACK_WEBHOOK_URL, json={"text": msg})
    except Exception as e:
        logger.warning(f"Slack alert failed: {e}")


async def main():
    conn = await get_conn()
    try:
        workers = await conn.fetch(
            "SELECT w.worker_id, w.name FROM workers w WHERE w.is_active=TRUE"
        )
        total, new_criticals = 0, 0

        async with pipeline_run(conn, "runtime_errors"):
            async with httpx.AsyncClient(timeout=30) as client:
                for w in workers:
                    wid, wname = w["worker_id"], w["name"]
                    offset = 0
                    while True:
                        r = await client.get(
                            f"{API_BASE}/api/workers/{wid}/runtime-errors",
                            headers=HEADERS,
                            params={"limit": 50, "offset": offset},
                        )
                        r.raise_for_status()
                        body = r.json()
                        errors = body.get("errors", body) if isinstance(body, dict) else body
                        if not errors:
                            break
                        for e in errors:
                            existing = await conn.fetchval(
                                "SELECT error_id FROM runtime_errors WHERE error_id=$1", e["id"]
                            )
                            await conn.execute("""
                                INSERT INTO runtime_errors
                                    (error_id, worker_id, error_type, service, severity,
                                     message, created_at, raw_data, pulled_at)
                                VALUES ($1,$2,$3,$4,$5,$6,$7::timestamptz,$8::jsonb,NOW())
                                ON CONFLICT (error_id) DO NOTHING
                            """,
                                e["id"], wid,
                                e.get("type"), e.get("service"), e.get("severity"),
                                e.get("message"), parse_dt(e.get("createdAt")),
                                json.dumps(e),
                            )
                            if not existing and e.get("severity") == "critical":
                                new_criticals += 1
                                await maybe_alert_slack(wname, e.get("type","?"), e.get("service","?"))
                            total += 1
                        if len(errors) < 50 or not body.get("hasMore"):
                            break
                        offset += 50

        logger.info(f"pull_runtime_errors: {total} errors, {new_criticals} new criticals")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
