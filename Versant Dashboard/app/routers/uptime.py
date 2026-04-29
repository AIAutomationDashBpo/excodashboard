from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timedelta, timezone

from app import db
from app.auth import require_auth
from app.services.uptime_calc import get_uptime

router = APIRouter(tags=["uptime"])
templates = Jinja2Templates(directory="app/templates")


def _default_range():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-01"), now.strftime("%Y-%m-%d")


@router.get("/uptime", response_class=HTMLResponse)
async def uptime_page(
    request: Request,
    worker_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    workers = await db.fetch("""
        SELECT w.worker_id, w.name FROM workers w
        LEFT JOIN (
            SELECT worker_id, MAX(period_start) AS last_activity
            FROM voice_analysis_snapshots GROUP BY worker_id
        ) v ON v.worker_id = w.worker_id
        WHERE w.is_active=TRUE
        ORDER BY v.last_activity DESC NULLS LAST, w.name
    """)
    if not worker_id and workers:
        worker_id = workers[0]["worker_id"]

    _from, _to = from_date or _default_range()[0], to_date or _default_range()[1]
    context = await _build_uptime_context(worker_id, _from, _to)

    return templates.TemplateResponse("uptime.html", {
        "request": request,
        "user": user,
        "workers": [dict(w) for w in workers],
        "active_tab": "uptime",
        "worker_id": worker_id,
        "from_date": _from,
        "to_date": _to,
        **context,
    })


@router.get("/api/uptime/panel", response_class=HTMLResponse)
async def uptime_panel(
    request: Request,
    worker_id: str = Query(...),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = from_date or _default_range()[0], to_date or _default_range()[1]
    context = await _build_uptime_context(worker_id, _from, _to)
    return templates.TemplateResponse("partials/uptime_panel.html", {
        "request": request, **context,
    })


async def _build_uptime_context(worker_id: str, from_dt: str, to_dt: str) -> dict:
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    if not worker_id:
        return {"uptime": {}, "incidents": [], "error_counts": {}, "uptime_series": []}

    uptime = await get_uptime(worker_id, from_dt, to_dt)

    # Error counts by severity
    error_rows = await db.fetch("""
        SELECT severity, COUNT(*) AS cnt
        FROM runtime_errors
        WHERE worker_id = $1
          AND created_at BETWEEN $2::timestamptz AND $3::timestamptz
        GROUP BY severity
    """, worker_id, from_dt, to_dt)
    error_counts = {r["severity"]: int(r["cnt"]) for r in error_rows}

    # Incident timeline (errors + platform incidents merged)
    incidents = await db.fetch("""
        SELECT
            created_at         AS start_time,
            created_at         AS end_time,
            CONCAT(COALESCE(error_type,'unknown'), ' (', COALESCE(service,'?'), ')') AS description,
            severity,
            'runtime_error'    AS source
        FROM runtime_errors
        WHERE worker_id = $1
          AND created_at BETWEEN $2::timestamptz AND $3::timestamptz
        UNION ALL
        SELECT
            incident_start, incident_end, description, severity, 'platform'
        FROM platform_incidents
        WHERE incident_start BETWEEN $2::timestamptz AND $3::timestamptz
        ORDER BY start_time DESC
        LIMIT 50
    """, worker_id, from_dt, to_dt)

    # Daily uptime series for the line chart
    outage_rows = await db.fetch("""
        SELECT
            incident_start::date AS day,
            SUM(
                EXTRACT(EPOCH FROM COALESCE(incident_end, NOW()) - incident_start) / 60.0
            ) AS outage_minutes
        FROM platform_incidents
        WHERE incident_start >= $1::timestamptz
          AND incident_start <= $2::timestamptz
        GROUP BY 1
        ORDER BY 1
    """, from_dt, to_dt)
    outage_by_day = {str(r["day"]): float(r["outage_minutes"] or 0) for r in outage_rows}

    from datetime import timedelta, date as date_type
    start_date = from_dt.date() if hasattr(from_dt, 'date') else from_dt
    end_date   = to_dt.date()   if hasattr(to_dt,   'date') else to_dt
    uptime_series = []
    current = start_date
    while current <= end_date:
        outage = outage_by_day.get(str(current), 0)
        uptime_pct = round(max(0.0, 100.0 - outage / 1440.0 * 100), 3)
        uptime_series.append({"date": str(current), "uptime_pct": uptime_pct})
        current += timedelta(days=1)

    return {
        "uptime": uptime,
        "incidents": [dict(i) for i in incidents],
        "error_counts": error_counts,
        "uptime_series": uptime_series,
    }
