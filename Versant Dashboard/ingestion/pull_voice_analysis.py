"""
Azure Function — Timer trigger every 15 minutes.
Pulls daily voice analysis snapshots for the current and previous month.
"""
import asyncio, asyncpg, os, httpx, logging
from datetime import datetime, timezone, timedelta
from ingestion.shared.pipeline import pipeline_run, get_conn, _load_env, parse_dt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_load_env()
API_KEY    = os.environ["BRAINBASE_API_KEY"]
API_BASE   = os.environ.get("BRAINBASE_BASE_URL", "https://api.usebrainbase.com")
BILLING_TZ = os.environ.get("BILLING_TIMEZONE", "America/New_York")
HEADERS    = {"x-api-key": API_KEY, "Content-Type": "application/json"}


async def pull_for_worker(client, conn, worker_id: str, start: str, end: str):
    payload = {
        "startDate": start, "endDate": end,
        "granularity": "daily",
        "workerId": worker_id,
        "includeTransfers": True,
        "timezone": BILLING_TZ,
    }
    r = await client.post(f"{API_BASE}/api/voice-analysis", headers=HEADERS, json=payload)
    r.raise_for_status()
    data = r.json()
    summary = data.get("summary", data)  # handle both shapes

    await conn.execute("""
        INSERT INTO voice_analysis_snapshots
            (worker_id, period_start, period_end, granularity,
             total_calls, total_minutes, total_transfers, total_transfer_minutes,
             average_call_duration, pulled_at)
        VALUES ($1,$2::timestamptz,$3::timestamptz,'daily',$4,$5,$6,$7,$8,NOW())
        ON CONFLICT (worker_id, period_start, period_end, granularity, deployment_ids)
            DO UPDATE SET
                total_calls=EXCLUDED.total_calls,
                total_minutes=EXCLUDED.total_minutes,
                total_transfers=EXCLUDED.total_transfers,
                average_call_duration=EXCLUDED.average_call_duration,
                pulled_at=NOW()
    """,
        worker_id, parse_dt(start), parse_dt(end),
        summary.get("totalCalls", 0),
        summary.get("totalMinutes", 0),
        summary.get("totalTransfers", 0),
        summary.get("totalTransferMinutes", 0),
        summary.get("averageCallDuration"),
    )


async def main():
    conn = await get_conn()
    try:
        workers = await conn.fetch("SELECT worker_id FROM workers WHERE is_active=TRUE")
        now = datetime.now(timezone.utc)
        # Pull current month + previous month day-by-day
        periods = []
        for delta in range(0, 60):
            day = now - timedelta(days=delta)
            start = day.strftime("%Y-%m-%dT00:00:00Z")
            end   = day.strftime("%Y-%m-%dT23:59:59Z")
            periods.append((start, end))

        async with pipeline_run(conn, "voice_analysis"):
            async with httpx.AsyncClient(timeout=30) as client:
                for w in workers:
                    for start, end in periods:
                        try:
                            await pull_for_worker(client, conn, w["worker_id"], start, end)
                        except Exception as e:
                            logger.warning(f"voice_analysis skip {w['worker_id']} {start}: {e}")
            logger.info(f"pull_voice_analysis: done for {len(workers)} workers, {len(periods)} days each")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
