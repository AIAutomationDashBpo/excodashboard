from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timedelta, timezone

from app import db
from app.auth import require_auth

router = APIRouter(tags=["insights"])
templates = Jinja2Templates(directory="app/templates")

DISPOSITION_COLORS = {
    "booking_confirmed": "#10B981",
    "cancellation":      "#F59E0B",
    "transfer_to_human": "#3B82F6",
    "no_match":          "#6B7280",
    "dropped":           "#EF4444",
    "information_only":  "#8B5CF6",
    "error":             "#DC2626",
    "unknown":           "#9CA3AF",
}

DISPOSITION_LABELS = {
    "booking_confirmed": "Booking Confirmed",
    "cancellation":      "Cancellation",
    "transfer_to_human": "Transfer to Human",
    "no_match":          "No Match",
    "dropped":           "Dropped",
    "information_only":  "Information Only",
    "error":             "Error",
    "unknown":           "Unknown",
}


def _default_range():
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=60)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(
    request: Request,
    worker_id: Optional[str] = Query(None),
    env: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1),
    user: dict = Depends(require_auth),
):
    workers = await db.fetch("""
        SELECT w.worker_id, w.name FROM workers w
        LEFT JOIN (
            SELECT worker_id, MAX(start_time) AS last_activity
            FROM call_logs GROUP BY worker_id
        ) cl ON cl.worker_id = w.worker_id
        WHERE w.is_active=TRUE
        ORDER BY cl.last_activity DESC NULLS LAST, w.name
    """)
    if not worker_id and workers:
        worker_id = workers[0]["worker_id"]

    _from, _to = from_date or _default_range()[0], to_date or _default_range()[1]
    context = await _build_insights_context(worker_id, env, _from, _to, page)

    return templates.TemplateResponse("insights.html", {
        "request": request,
        "user": user,
        "workers": [dict(w) for w in workers],
        "active_tab": "insights",
        "worker_id": worker_id,
        "env": env or "all",
        "from_date": _from,
        "to_date": _to,
        "page": page,
        **context,
    })


@router.get("/api/insights/disposition", response_class=HTMLResponse)
async def disposition_chart(
    request: Request,
    worker_id: str = Query(...),
    env: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = from_date or _default_range()[0], to_date or _default_range()[1]
    dispositions = await _get_dispositions(worker_id, env, _from, _to)
    return templates.TemplateResponse("partials/disposition_chart.html", {
        "request": request, "dispositions": dispositions,
    })


@router.get("/api/insights/call-feed", response_class=HTMLResponse)
async def call_feed(
    request: Request,
    worker_id: str = Query(...),
    env: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1),
    phone: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    _from, _to = from_date or _default_range()[0], to_date or _default_range()[1]
    calls, total = await _get_call_feed(worker_id, env, _from, _to, page, phone)
    return templates.TemplateResponse("partials/call_feed.html", {
        "request": request,
        "calls": calls,
        "page": page,
        "total": total,
        "has_next": page * 20 < total,
        "worker_id": worker_id,
        "env": env,
        "from_date": _from,
        "to_date": _to,
        "phone": phone or "",
    })


@router.get("/api/insights/call/{log_id}", response_class=HTMLResponse)
async def call_detail(
    request: Request,
    log_id: str,
    worker_id: str = Query(...),
    user: dict = Depends(require_auth),
):
    call = await db.fetchrow(
        "SELECT * FROM call_logs WHERE log_id = $1 AND worker_id = $2", log_id, worker_id
    )
    return templates.TemplateResponse("partials/call_detail.html", {
        "request": request,
        "call": dict(call) if call else None,
        "disposition_label": DISPOSITION_LABELS.get(call["disposition"] if call else "", "Unknown"),
    })


async def _get_dispositions(worker_id: str, env: str, from_dt: str, to_dt: str) -> list:
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    if not worker_id:
        return []

    if env and env != "all":
        rows = await db.fetch("""
            SELECT
                COALESCE(cl.disposition, 'unknown') AS disposition,
                COUNT(*) AS call_count
            FROM call_logs cl
            JOIN deployments d ON d.deployment_id = cl.deployment_id
            WHERE cl.worker_id = $1
              AND cl.start_time >= $2::timestamptz
              AND cl.start_time <= $3::timestamptz
              AND d.environment = $4
            GROUP BY 1 ORDER BY 2 DESC
        """, worker_id, from_dt, to_dt, env)
    else:
        rows = await db.fetch("""
            SELECT
                COALESCE(disposition, 'unknown') AS disposition,
                COUNT(*) AS call_count
            FROM call_logs
            WHERE worker_id = $1
              AND start_time >= $2::timestamptz
              AND start_time <= $3::timestamptz
            GROUP BY 1 ORDER BY 2 DESC
        """, worker_id, from_dt, to_dt)

    total = sum(r["call_count"] for r in rows)
    return [
        {
            "disposition": r["disposition"],
            "label": DISPOSITION_LABELS.get(r["disposition"], r["disposition"].replace("_", " ").title()),
            "count": int(r["call_count"]),
            "pct": round(int(r["call_count"]) / total * 100, 1) if total else 0,
            "color": DISPOSITION_COLORS.get(r["disposition"], "#9CA3AF"),
        }
        for r in rows
    ]


async def _get_call_feed(
    worker_id: str, env: str, from_dt: str, to_dt: str, page: int,
    phone: Optional[str] = None,
):
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    if not worker_id:
        return [], 0
    offset = (page - 1) * 20

    args: list = [worker_id, from_dt, to_dt]
    phone_clause = ""
    if phone and phone.strip():
        args.append(f"%{phone.strip()}%")
        n = len(args)
        phone_clause = (
            f" AND (cl.from_number ILIKE ${n}"
            f" OR cl.to_number ILIKE ${n}"
            f" OR cl.confirmation_number ILIKE ${n})"
        )

    rows = await db.fetch(f"""
        SELECT cl.log_id, cl.start_time, cl.from_number, cl.to_number,
               cl.duration_seconds, cl.disposition, cl.confirmation_number,
               cl.status, cl.direction, d.environment
        FROM call_logs cl
        LEFT JOIN deployments d ON d.deployment_id = cl.deployment_id
        WHERE cl.worker_id = $1
          AND cl.start_time >= $2::timestamptz
          AND cl.start_time <= $3::timestamptz
          {phone_clause}
        ORDER BY cl.start_time DESC
        LIMIT 20 OFFSET ${len(args) + 1}
    """, *args, offset)

    total = await db.fetchval(f"""
        SELECT COUNT(*) FROM call_logs cl
        WHERE cl.worker_id = $1
          AND cl.start_time >= $2::timestamptz
          AND cl.start_time <= $3::timestamptz
          {phone_clause}
    """, *args)

    calls = []
    for r in rows:
        d = dict(r)
        d["disposition_label"] = DISPOSITION_LABELS.get(d["disposition"] or "", "Unknown")
        d["disposition_color"] = DISPOSITION_COLORS.get(d["disposition"] or "", "#9CA3AF")
        calls.append(d)
    return calls, int(total or 0)


async def _build_insights_context(worker_id, env, from_dt, to_dt, page):
    dispositions = await _get_dispositions(worker_id, env, from_dt, to_dt)
    calls, total = await _get_call_feed(worker_id, env, from_dt, to_dt, page)
    disposition_trend = await _get_disposition_trend(worker_id, env, from_dt, to_dt)
    return {
        "dispositions": dispositions,
        "calls": calls,
        "total_calls": total,
        "has_next": page * 20 < total,
        "disposition_colors": DISPOSITION_COLORS,
        "disposition_labels": DISPOSITION_LABELS,
        "disposition_trend": disposition_trend,
    }


async def _get_disposition_trend(worker_id: str, env: str, from_dt: str, to_dt: str) -> dict:
    from_dt_p, to_dt_p = db.parse_dt(from_dt), db.parse_dt(to_dt)
    if not worker_id:
        return {"weeks": [], "series": []}

    rows = await db.fetch("""
        SELECT
            TO_CHAR(DATE_TRUNC('week', start_time), 'Mon DD') AS week,
            DATE_TRUNC('week', start_time) AS week_dt,
            COALESCE(disposition, 'unknown') AS disposition,
            COUNT(*)::int AS cnt
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
        GROUP BY 1, 2, 3
        ORDER BY 2, 3
    """, worker_id, from_dt_p, to_dt_p)

    from collections import defaultdict, OrderedDict
    weeks_ordered = OrderedDict()
    week_data: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        weeks_ordered[r["week"]] = True
        week_data[r["disposition"]][r["week"]] = r["cnt"]

    weeks = list(weeks_ordered.keys())
    active_dispositions = [d for d in DISPOSITION_COLORS if any(week_data[d].values())]
    series = [
        {
            "name": DISPOSITION_LABELS.get(d, d),
            "color": DISPOSITION_COLORS.get(d, "#9CA3AF"),
            "data": [week_data[d].get(w, 0) for w in weeks],
        }
        for d in active_dispositions
    ]
    return {"weeks": weeks, "series": series}
