"""Slack and PagerDuty notification dispatch."""
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)


async def send_slack(message: str) -> None:
    if not settings.slack_webhook_url:
        logger.info(f"[Slack not configured] {message}")
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.slack_webhook_url, json={"text": message})
    except Exception as e:
        logger.error(f"Slack alert failed: {e}")


async def send_pagerduty(summary: str, severity: str = "critical") -> None:
    if not settings.pagerduty_routing_key:
        logger.info(f"[PagerDuty not configured] {summary}")
        return
    payload = {
        "routing_key": settings.pagerduty_routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": summary,
            "severity": severity,
            "source": "brainbase-dashboard",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post("https://events.pagerduty.com/v2/enqueue", json=payload)
    except Exception as e:
        logger.error(f"PagerDuty alert failed: {e}")


async def alert_sla_breach(worker_name: str, actual_pct: float, target_pct: float) -> None:
    msg = (
        f":rotating_light: *SLA Breach Detected*\n"
        f"Worker: *{worker_name}*\n"
        f"Uptime: {actual_pct:.3f}% (target: {target_pct:.1f}%)\n"
        f"Review runtime errors and platform incidents."
    )
    await send_slack(msg)
    await send_pagerduty(f"SLA breach: {worker_name} at {actual_pct:.3f}%")


async def alert_pipeline_failure(source: str, error: str, retry_count: int) -> None:
    if retry_count < 3:
        return
    msg = (
        f":warning: *Pipeline Failure* — {source}\n"
        f"Failed {retry_count} consecutive times.\n"
        f"Error: `{error}`"
    )
    await send_slack(msg)


async def alert_critical_error(worker_name: str, error_type: str, service: str) -> None:
    msg = (
        f":red_circle: *Critical Bot Error*\n"
        f"Worker: *{worker_name}* | Service: {service}\n"
        f"Type: `{error_type}`"
    )
    await send_slack(msg)
