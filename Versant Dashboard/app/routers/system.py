from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
from app import db
from app.config import settings

router = APIRouter(prefix="/api/system", tags=["system"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/workers")
async def get_workers():
    rows = await db.fetch(
        "SELECT worker_id, name, lob_name FROM workers WHERE is_active = TRUE ORDER BY name"
    )
    return [dict(r) for r in rows]


@router.get("/deployments/{worker_id}")
async def get_deployments(worker_id: str):
    rows = await db.fetch(
        "SELECT deployment_id, name, environment FROM deployments "
        "WHERE worker_id = $1 AND is_active = TRUE ORDER BY environment",
        worker_id,
    )
    return [dict(r) for r in rows]


@router.get("/freshness", response_class=HTMLResponse)
async def get_freshness(request: Request):
    rows = await db.fetch("""
        SELECT DISTINCT ON (source_name)
            source_name, completed_at, status, error_message
        FROM pipeline_runs
        WHERE status IN ('success', 'failure')
        ORDER BY source_name, completed_at DESC
    """)
    thresholds = {
        "voice_analysis":  settings.freshness_voice_analysis,
        "call_logs":       settings.freshness_call_logs,
        "runtime_errors":  settings.freshness_runtime_errors,
        "echo":            settings.freshness_echo,
    }
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        last = row["completed_at"]
        threshold = thresholds.get(row["source_name"], 3600)
        age = (now - last).total_seconds() if last else float("inf")
        age_minutes = round(age / 60, 0) if age != float("inf") else None
        if row["status"] == "failure" or age == float("inf"):
            color = "red"
        elif age > threshold * 3:
            color = "red"
        elif age > threshold * 1.5:
            color = "amber"
        else:
            color = "green"

        if age_minutes is None:
            age_display = "never"
        elif age_minutes < 1:
            age_display = "just now"
        elif age_minutes < 60:
            age_display = f"{int(age_minutes)} min ago"
        elif age_minutes < 1440:
            h = int(age_minutes // 60)
            age_display = f"{h}h ago"
        else:
            age_display = f"{int(age_minutes // 1440)}d ago"

        result.append({
            "source":       row["source_name"],
            "last_updated": last.isoformat() if last else None,
            "age_display":  age_display,
            "color":        color,
            "status":       row["status"],
        })
    return templates.TemplateResponse("partials/freshness_indicator.html", {
        "request": request, "freshness": result,
    })
