from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, timezone

from app import db
from app.auth import require_auth
from app.services.billing_calc import calculate_bill

router = APIRouter(tags=["billing"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(
    request: Request,
    worker_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
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

    _month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    billing_data = await _build_billing_context(worker_id, _month)

    # Per-worker costs for the current month
    per_worker_costs = await _build_per_worker_costs(_month, [dict(w) for w in workers])

    return templates.TemplateResponse("billing.html", {
        "request": request,
        "user": user,
        "workers": [dict(w) for w in workers],
        "active_tab": "billing",
        "worker_id": worker_id,
        "month": _month,
        "per_worker_costs": per_worker_costs,
        **billing_data,
    })


@router.get("/api/billing/summary", response_class=HTMLResponse)
async def billing_summary(
    request: Request,
    worker_id: str = Query(...),
    month: str = Query(...),
    user: dict = Depends(require_auth),
):
    data = await _build_billing_context(worker_id, month)
    return templates.TemplateResponse("partials/billing_table.html", {
        "request": request, **data,
    })


async def _build_billing_context(worker_id: str, month: str) -> dict:
    if not worker_id:
        return {"bill": {}, "tiers": [], "monthly_trend": []}

    # Month boundaries
    year, mon = int(month.split("-")[0]), int(month.split("-")[1])
    import calendar
    last_day = calendar.monthrange(year, mon)[1]
    from_dt = db.parse_dt(f"{month}-01")
    to_dt = db.parse_dt(f"{month}-{last_day:02d}")

    # Usage this month (all deployments)
    usage = await db.fetchrow("""
        SELECT
            COALESCE(SUM(total_minutes), 0)::float  AS total_minutes,
            COALESCE(SUM(total_calls), 0)::int      AS total_calls
        FROM voice_analysis_snapshots
        WHERE worker_id = $1
          AND period_start >= $2::timestamptz
          AND period_start <= $3::timestamptz
          AND granularity  = 'monthly'
    """, worker_id, from_dt, to_dt)

    # Billing tiers
    tiers = await db.fetch("""
        SELECT tier_name, min_minutes, max_minutes, rate_per_minute,
               overage_rate, echo_surcharge
        FROM billing_config
        WHERE worker_id = $1
          AND effective_from <= $2::date
          AND (effective_to IS NULL OR effective_to >= $2::date)
        ORDER BY min_minutes
    """, worker_id, from_dt)

    tier_list = [dict(t) for t in tiers]
    echo_surcharge = float(tier_list[0]["echo_surcharge"]) if tier_list else 0.0
    bill = calculate_bill(
        minutes=float(usage["total_minutes"] or 0),
        tiers=tier_list,
        echo_surcharge=echo_surcharge,
    )
    bill["total_calls"] = int(usage["total_calls"] or 0)

    # 6-month trend with estimated cost
    trend = await db.fetch("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', period_start), 'Mon YYYY') AS month,
            COALESCE(SUM(total_minutes), 0)::float AS minutes
        FROM voice_analysis_snapshots
        WHERE worker_id = $1
          AND granularity = 'monthly'
          AND period_start >= (NOW() - INTERVAL '6 months')
        GROUP BY DATE_TRUNC('month', period_start)
        ORDER BY DATE_TRUNC('month', period_start)
    """, worker_id)

    trend_list = []
    for r in trend:
        mins = float(r["minutes"] or 0)
        est = calculate_bill(mins, tier_list, echo_surcharge)
        trend_list.append({"month": r["month"], "minutes": mins, "cost": est["total"]})

    return {
        "bill": bill,
        "tiers": tier_list,
        "monthly_trend": trend_list,
    }


async def _build_per_worker_costs(month: str, workers: list) -> list:
    """Build per-worker cost rows for the billing table."""
    import calendar
    year, mon = int(month.split("-")[0]), int(month.split("-")[1])
    last_day = calendar.monthrange(year, mon)[1]
    from_dt = db.parse_dt(f"{month}-01")
    to_dt   = db.parse_dt(f"{month}-{last_day:02d}")

    rows = []
    for w in workers:
        usage = await db.fetchrow("""
            SELECT COALESCE(SUM(total_minutes), 0)::float AS total_minutes
            FROM voice_analysis_snapshots
            WHERE worker_id = $1
              AND period_start >= $2::timestamptz
              AND period_start <= $3::timestamptz
              AND granularity = 'monthly'
        """, w["worker_id"], from_dt, to_dt)

        tiers = await db.fetch("""
            SELECT tier_name, min_minutes, max_minutes, rate_per_minute, overage_rate, echo_surcharge
            FROM billing_config
            WHERE worker_id = $1
              AND effective_from <= $2::date
              AND (effective_to IS NULL OR effective_to >= $2::date)
            ORDER BY min_minutes
        """, w["worker_id"], from_dt)

        tier_list = [dict(t) for t in tiers]
        if not tier_list:
            continue

        mins = float(usage["total_minutes"] or 0)
        echo = float(tier_list[0]["echo_surcharge"]) if tier_list else 0.0
        bill = calculate_bill(mins, tier_list, echo)
        rows.append({
            "name":           w["name"],
            "minutes":        mins,
            "included":       bill["included_minutes"],
            "overage":        bill["overage_minutes"],
            "echo_surcharge": bill["echo_surcharge"],
            "total":          bill["total"],
        })
    return rows
