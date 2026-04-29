from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timedelta, timezone

from app import db
from app.auth import require_auth
from app.services.kpi_calc import get_kpi_actuals, evaluate_kpi
from app.cache import cached

router = APIRouter(tags=["metrics"])
templates = Jinja2Templates(directory="app/templates")


def _default_dates():
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=60)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(
    request: Request,
    worker_id: Optional[str] = Query(None),
    env: Optional[str] = Query(None),
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

    _from, _to = from_date or _default_dates()[0], to_date or _default_dates()[1]

    context = await _build_metrics_context(worker_id, env, _from, _to)
    return templates.TemplateResponse("metrics.html", {
        "request": request,
        "user": user,
        "workers": [dict(w) for w in workers],
        "active_tab": "metrics",
        "worker_id": worker_id,
        "env": env or "all",
        "from_date": _from,
        "to_date": _to,
        **context,
    })


@router.get("/api/metrics/headline", response_class=HTMLResponse)
async def metrics_headline(
    request: Request,
    worker_id: str = Query(...),
    env: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = from_date or _default_dates()[0], to_date or _default_dates()[1]
    context = await _build_metrics_context(worker_id, env, _from, _to)
    return templates.TemplateResponse("partials/headline_strip.html", {
        "request": request, **context,
        "worker_id": worker_id, "from_date": _from, "to_date": _to,
    })


@router.get("/api/metrics/kpi-table", response_class=HTMLResponse)
async def metrics_kpi_table(
    request: Request,
    worker_id: str = Query(...),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = from_date or _default_dates()[0], to_date or _default_dates()[1]
    goals = await db.fetch("""
        SELECT kpi_key, kpi_name, kpi_description, goal_operator, goal_value, goal_unit
        FROM kpi_goals
        WHERE worker_id = $1
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
        ORDER BY id
    """, worker_id)
    actuals = await get_kpi_actuals(worker_id, _from, _to)
    rows = []
    for g in goals:
        actual = actuals.get(g["kpi_key"])
        rows.append({
            **dict(g),
            "actual": actual,
            "rag": evaluate_kpi(actual, g["goal_operator"], float(g["goal_value"])),
        })
    return templates.TemplateResponse("partials/kpi_table.html", {
        "request": request, "kpi_rows": rows,
    })


@router.get("/api/metrics/trend", response_class=HTMLResponse)
async def metrics_trend(
    request: Request,
    worker_id: str = Query(...),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = db.parse_dt(from_date or _default_dates()[0]), db.parse_dt(to_date or _default_dates()[1])
    rows = await db.fetch("""
        SELECT
            TO_CHAR(DATE_TRUNC('day', period_start), 'YYYY-MM-DD') AS day,
            SUM(total_calls) AS calls,
            ROUND(SUM(total_minutes)::numeric, 1) AS minutes
        FROM voice_analysis_snapshots
        WHERE worker_id = $1
          AND period_start >= $2::timestamptz
          AND period_start <= $3::timestamptz
          AND granularity  = 'daily'
        GROUP BY 1 ORDER BY 1
    """, worker_id, _from, _to)
    return templates.TemplateResponse("partials/trend_chart.html", {
        "request": request,
        "trend_data": [{"day": r["day"], "calls": int(r["calls"] or 0), "minutes": float(r["minutes"] or 0)} for r in rows],
    })


async def _build_metrics_context(worker_id: str, env: str, from_dt: str, to_dt: str) -> dict:
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    if not worker_id:
        return {
            "headline": {
                "total_calls": 0, "total_minutes": 0.0, "total_transfers": 0,
                "avg_duration_sec": 0, "success_rate": 0.0, "calls_change_pct": None,
            },
            "kpi_rows": [],
            "trend_data": [],
            "heatmap_series": [],
            "top_phone_numbers": [],
        }

    # Headline numbers
    headline = await db.fetchrow("""
        SELECT
            COALESCE(SUM(total_calls), 0)::int           AS total_calls,
            COALESCE(SUM(total_minutes), 0)::float       AS total_minutes,
            COALESCE(SUM(total_transfers), 0)::int       AS total_transfers,
            COALESCE(ROUND(AVG(average_call_duration)::numeric, 0), 0)::int AS avg_duration_sec
        FROM voice_analysis_snapshots
        WHERE worker_id = $1
          AND period_start >= $2::timestamptz
          AND period_start <= $3::timestamptz
          AND granularity  = 'daily'
    """, worker_id, from_dt, to_dt)

    # Success rate from call_logs
    success_rate = await db.fetchval("""
        SELECT ROUND(
            COUNT(*) FILTER (WHERE disposition IN ('booking_confirmed','cancellation','information_only'))
            * 100.0 / NULLIF(COUNT(*), 0), 1
        )
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
    """, worker_id, from_dt, to_dt)

    # MoM change (calls vs previous equivalent period)
    period_days = (to_dt - from_dt).days
    prev_from = db.parse_dt((from_dt - timedelta(days=period_days)).strftime("%Y-%m-%d"))
    prev_calls = await db.fetchval("""
        SELECT COALESCE(SUM(total_calls), 0)
        FROM voice_analysis_snapshots
        WHERE worker_id = $1
          AND period_start >= $2::timestamptz
          AND period_start <= $3::timestamptz
          AND granularity  = 'daily'
    """, worker_id, prev_from, from_dt)

    curr_calls = int(headline["total_calls"] or 0)
    prev_calls = int(prev_calls or 0)
    calls_change_pct = (
        round((curr_calls - prev_calls) / prev_calls * 100, 1)
        if prev_calls > 0 else None
    )

    # Top performing hours heatmap (DOW × hour)
    hours_rows = await db.fetch("""
        SELECT
            EXTRACT(DOW FROM start_time)::int AS dow,
            EXTRACT(HOUR FROM start_time)::int AS hour,
            COUNT(*)::int AS calls
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
        GROUP BY 1, 2
    """, worker_id, from_dt, to_dt)

    heatmap = {d: {h: 0 for h in range(6, 22)} for d in range(7)}
    for r in hours_rows:
        h = int(r["hour"])
        if 6 <= h < 22:
            heatmap[int(r["dow"])][h] = int(r["calls"])
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    hour_labels = ["6AM","7AM","8AM","9AM","10AM","11AM","12PM","1PM","2PM","3PM","4PM","5PM","6PM","7PM","8PM","9PM"]
    heatmap_series = [
        {"name": day_names[d], "data": [{"x": hour_labels[h-6], "y": heatmap[d][h]} for h in range(6, 22)]}
        for d in range(7)
    ]

    # Top phone numbers by minutes
    top_rows = await db.fetch("""
        SELECT
            from_number,
            COALESCE(ROUND(SUM(COALESCE(duration_seconds, 0)) / 60.0)::int, 0) AS minutes
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
          AND from_number IS NOT NULL
        GROUP BY from_number
        ORDER BY minutes DESC
        LIMIT 5
    """, worker_id, from_dt, to_dt)
    top_phone_numbers = [{"number": r["from_number"], "minutes": int(r["minutes"] or 0)} for r in top_rows]

    return {
        "headline": {
            "total_calls":      curr_calls,
            "total_minutes":    round(float(headline["total_minutes"] or 0), 1),
            "total_transfers":  int(headline["total_transfers"] or 0),
            "avg_duration_sec": int(headline["avg_duration_sec"] or 0),
            "success_rate":     float(success_rate or 0),
            "calls_change_pct": calls_change_pct,
        },
        "kpi_rows": [],
        "trend_data": [],
        "heatmap_series": heatmap_series,
        "top_phone_numbers": top_phone_numbers,
    }
