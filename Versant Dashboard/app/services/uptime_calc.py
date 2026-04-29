"""SLA uptime and penalty calculation."""
from app import db
from app.cache import cached


@cached("uptime:")
async def get_uptime(worker_id: str, from_dt, to_dt) -> dict:
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    """
    Calculate SLA uptime % and penalty exposure for the given period.
    Downtime = sum of runtime error durations (critical only) + platform incidents.
    """
    # Total window in minutes
    total_minutes = max((to_dt - from_dt).total_seconds() / 60, 1)

    # Critical error count (proxy for downtime events)
    critical_errors = await db.fetchval("""
        SELECT COUNT(*) FROM runtime_errors
        WHERE worker_id = $1
          AND severity = 'critical'
          AND created_at BETWEEN $2::timestamptz AND $3::timestamptz
    """, worker_id, from_dt, to_dt)

    # Platform incidents overlapping the window
    incident_minutes = await db.fetchval("""
        SELECT COALESCE(SUM(
            EXTRACT(EPOCH FROM (
                LEAST(incident_end, $2::timestamptz) -
                GREATEST(incident_start, $1::timestamptz)
            )) / 60
        ), 0)
        FROM platform_incidents
        WHERE incident_start <= $2::timestamptz
          AND (incident_end IS NULL OR incident_end >= $1::timestamptz)
    """, from_dt, to_dt)

    downtime_minutes = float(incident_minutes or 0)
    uptime_pct = max(0.0, (total_minutes - downtime_minutes) / total_minutes * 100)

    # Get SLA target and penalty
    sla_row = await db.fetchrow("""
        SELECT sla_target_pct, penalty_per_hour
        FROM sla_config
        WHERE worker_id = $1
          AND effective_from <= CURRENT_DATE
          AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
        ORDER BY effective_from DESC
        LIMIT 1
    """, worker_id)

    sla_target = float(sla_row["sla_target_pct"]) if sla_row else 99.5
    penalty_per_hour = float(sla_row["penalty_per_hour"]) if sla_row else 0.0

    breach = uptime_pct < sla_target
    penalty_exposure = (downtime_minutes / 60 * penalty_per_hour) if breach else 0.0

    return {
        "uptime_pct":       round(uptime_pct, 3),
        "sla_target_pct":   sla_target,
        "downtime_minutes": round(downtime_minutes, 1),
        "breach":           breach,
        "penalty_exposure": round(penalty_exposure, 2),
        "critical_errors":  int(critical_errors or 0),
    }
