"""Shared pipeline_runs bookend writer for all ingestion jobs."""
import asyncpg
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from dotenv import load_dotenv

def _load_env():
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    load_dotenv(root / ".env", override=False)


def parse_dt(value):
    """Parse an ISO 8601 string (or None) to a timezone-aware datetime."""
    if not value:
        return None
    from datetime import datetime, timezone
    s = value.rstrip("Z")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

async def get_conn() -> asyncpg.Connection:
    _load_env()
    return await asyncpg.connect(
        os.environ["DATABASE_URL"],
        ssl="require",
        statement_cache_size=0,
    )

logger = logging.getLogger(__name__)


@asynccontextmanager
async def pipeline_run(conn: asyncpg.Connection, source: str, worker_id: str = None):
    run_id = await conn.fetchval(
        "INSERT INTO pipeline_runs (source_name, worker_id, started_at, status) "
        "VALUES ($1, $2, NOW(), 'running') RETURNING id",
        source, worker_id,
    )
    try:
        yield run_id
        await conn.execute(
            "UPDATE pipeline_runs SET status='success', completed_at=NOW() WHERE id=$1",
            run_id,
        )
    except Exception as e:
        logger.exception(f"Pipeline {source} failed: {e}")
        await conn.execute(
            "UPDATE pipeline_runs SET status='failure', completed_at=NOW(), "
            "error_message=$1, retry_count=retry_count+1 WHERE id=$2",
            str(e)[:1000], run_id,
        )
        raise
