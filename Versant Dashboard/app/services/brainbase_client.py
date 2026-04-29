import httpx
import asyncio
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)
RETRY_BACKOFF = [1, 2, 4]  # seconds between retries


class BrainbaseClient:
    def __init__(self):
        self.base = settings.brainbase_base_url
        self.headers = {
            "x-api-key": settings.brainbase_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> any:
        url = f"{self.base}{path}"
        for attempt, wait in enumerate(RETRY_BACKOFF):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(url, headers=self.headers, params=params)
                    if r.status_code == 429:
                        retry_after = int(r.headers.get("Retry-After", wait))
                        await asyncio.sleep(retry_after)
                        continue
                    r.raise_for_status()
                    return r.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                if attempt == len(RETRY_BACKOFF) - 1:
                    raise
                logger.warning(f"Retry {attempt + 1} for GET {path}: {e}")
                await asyncio.sleep(wait)

    async def _post(self, path: str, body: dict) -> any:
        url = f"{self.base}{path}"
        for attempt, wait in enumerate(RETRY_BACKOFF):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(url, headers=self.headers, json=body)
                    if r.status_code == 429:
                        await asyncio.sleep(int(r.headers.get("Retry-After", wait)))
                        continue
                    r.raise_for_status()
                    return r.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                if attempt == len(RETRY_BACKOFF) - 1:
                    raise
                logger.warning(f"Retry {attempt + 1} for POST {path}: {e}")
                await asyncio.sleep(wait)

    # ── Workers ───────────────────────────────────────────────────────────────
    async def list_workers(self) -> list:
        return await self._get("/api/workers")

    async def get_worker(self, worker_id: str) -> dict:
        return await self._get(f"/api/workers/{worker_id}")

    # ── Deployments ───────────────────────────────────────────────────────────
    async def list_voice_deployments(self, worker_id: str) -> list:
        return await self._get(f"/api/workers/{worker_id}/deployments/voice")

    # ── Voice Analysis ────────────────────────────────────────────────────────
    async def voice_analysis(
        self,
        start_date: str,
        end_date: str,
        granularity: str = "monthly",
        worker_id: str = None,
        deployment_ids: list = None,
        timezone: str = None,
    ) -> dict:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "granularity": granularity,
            "includeTransfers": True,
            "timezone": timezone or settings.billing_timezone,
        }
        if worker_id:
            body["workerId"] = worker_id
        if deployment_ids:
            body["deploymentIds"] = deployment_ids
        return await self._post("/api/voice-analysis", body)

    # ── Call Logs ─────────────────────────────────────────────────────────────
    async def list_call_logs(
        self,
        worker_id: str,
        deployment_id: str = None,
        start_time_after: str = None,
        start_time_before: str = None,
        status: str = None,
        cursor: str = None,
        limit: int = 50,
    ) -> dict:
        params = {"limit": limit}
        if deployment_id:     params["deploymentId"] = deployment_id
        if start_time_after:  params["startTimeAfter"] = start_time_after
        if start_time_before: params["startTimeBefore"] = start_time_before
        if status:            params["status"] = status
        if cursor:            params["cursor"] = cursor
        return await self._get(f"/api/workers/{worker_id}/deploymentLogs/voice", params)

    async def get_call_log(self, worker_id: str, log_id: str) -> dict:
        return await self._get(f"/api/workers/{worker_id}/deploymentLogs/{log_id}")

    # ── Sessions ──────────────────────────────────────────────────────────────
    async def get_session(self, worker_id: str, session_id: str) -> dict:
        return await self._get(f"/api/workers/{worker_id}/sessions/{session_id}")

    # ── Runtime Errors ────────────────────────────────────────────────────────
    async def list_runtime_errors(
        self,
        worker_id: str,
        deployment_id: str = None,
        severity: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        params = {"limit": limit, "offset": offset}
        if deployment_id: params["deploymentId"] = deployment_id
        if severity:      params["severity"] = severity
        return await self._get(f"/api/workers/{worker_id}/runtime-errors", params)

    # ── Echo ──────────────────────────────────────────────────────────────────
    async def list_echo_scorecards(self) -> list:
        return await self._get("/api/echo/scorecards")

    # ── Log Exports ───────────────────────────────────────────────────────────
    async def create_log_export(self, body: dict) -> dict:
        return await self._post("/api/log-exports", body)

    async def get_log_export(self, export_id: str) -> dict:
        return await self._get(f"/api/log-exports/{export_id}")


brainbase = BrainbaseClient()
