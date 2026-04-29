"""
One-time run — historical backfill using the same voice-logs API as pull_call_logs.
Usage: python -m ingestion.backfill_history --days 90
"""
import asyncio, os, httpx, logging, argparse, json
from datetime import datetime, timezone, timedelta
from ingestion.shared.pipeline import get_conn, _load_env, parse_dt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_load_env()
API_KEY  = os.environ["BRAINBASE_API_KEY"]
API_BASE = os.environ.get("BRAINBASE_BASE_URL", "https://brainbase-monorepo-api.onrender.com")
HEADERS  = {"x-api-key": API_KEY, "Accept": "application/json"}


def parse_disposition(raw_data: dict) -> str | None:
    if not raw_data:
        return None
    return raw_data.get("disposition")


async def pull_worker_logs(client, conn, worker_id: str, since: str) -> int:
    cursor, count = None, 0
    while True:
        params = {"limit": 100, "startTimeAfter": since}
        if cursor:
            params["cursor"] = cursor
        r = await client.get(
            f"{API_BASE}/api/workers/{worker_id}/deploymentLogs/voice",
            headers=HEADERS, params=params,
        )
        r.raise_for_status()
        body = r.json()
        logs = body.get("data", [])

        for log in logs:
            raw = log.get("data") or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except: raw = {}

            await conn.execute("""
                INSERT INTO call_logs (
                    log_id, worker_id, deployment_id, session_id, external_call_id,
                    direction, from_number, to_number, start_time, end_time,
                    duration_seconds, status, disposition, confirmation_number,
                    caller_verified, response_latency_ms, transcription,
                    transfer_count, raw_data, pulled_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,
                    $9::timestamptz,$10::timestamptz,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19::jsonb,NOW()
                )
                ON CONFLICT (log_id) DO UPDATE SET
                    disposition=EXCLUDED.disposition,
                    transcription=EXCLUDED.transcription,
                    raw_data=EXCLUDED.raw_data,
                    pulled_at=NOW()
            """,
                log.get("id"), worker_id,
                log.get("deploymentId"), log.get("bbEngineSessionId"),
                log.get("externalCallId"), log.get("direction"),
                log.get("fromNumber"), log.get("toNumber"),
                parse_dt(log.get("startTime")), parse_dt(log.get("endTime")),
                int(log.get("duration") or 0) or None,
                log.get("status"),
                parse_disposition(raw),
                raw.get("confirmationNumber"),
                raw.get("callerVerified"),
                raw.get("response_latency_ms"),
                log.get("transcription"),
                len(log.get("transferEvents") or []),
                json.dumps(raw) if raw else None,
            )
            count += 1

        logger.info(f"    page: {len(logs)} logs (total so far: {count})")
        if not body.get("hasMore") or not body.get("nextCursor"):
            break
        cursor = body["nextCursor"]

    return count


async def main(days: int):
    conn = await get_conn()
    try:
        workers = await conn.fetch("SELECT worker_id, name FROM workers WHERE is_active=TRUE")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        logger.info(f"Backfilling {days} days (since {since[:10]}) for {len(workers)} workers")

        total = 0
        async with httpx.AsyncClient(timeout=60) as client:
            for w in workers:
                wid, wname = w["worker_id"], w["name"]
                logger.info(f"Worker: {wname} ({wid})")
                try:
                    n = await pull_worker_logs(client, conn, wid, since)
                    total += n
                    logger.info(f"  -> {n} logs inserted/updated")
                except Exception as e:
                    logger.error(f"  -> failed: {e}")

        logger.info(f"Backfill complete: {total} total logs")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Historical call log backfill")
    parser.add_argument("--days", type=int, default=90, help="Days of history to load (default 90)")
    args = parser.parse_args()
    asyncio.run(main(args.days))
