"""KPI actuals calculation from call_logs data."""
from app import db
from app.cache import cached


DISPOSITION_SUCCESS = ("booking_confirmed", "cancellation", "information_only")
DISPOSITION_FAILED  = ("transfer_to_human", "no_match", "dropped", "error")


@cached("kpi:")
async def get_kpi_actuals(worker_id: str, from_dt, to_dt) -> dict:
    from_dt, to_dt = db.parse_dt(from_dt), db.parse_dt(to_dt)
    """Return a dict of kpi_key -> actual value for the given period."""

    # Success rate: calls not transferred/dropped/errored
    success_rate = await db.fetchval("""
        SELECT ROUND(
            COUNT(*) FILTER (WHERE disposition = ANY($4)) * 100.0
            / NULLIF(COUNT(*), 0), 2
        )
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
    """, worker_id, from_dt, to_dt, list(DISPOSITION_SUCCESS))

    # Avg response latency
    avg_latency = await db.fetchval("""
        SELECT ROUND(AVG(response_latency_ms)::numeric, 0)
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
          AND response_latency_ms IS NOT NULL
    """, worker_id, from_dt, to_dt)

    # Booking conversion rate (booking_confirmed / total calls)
    booking_rate = await db.fetchval("""
        SELECT ROUND(
            COUNT(*) FILTER (WHERE disposition = 'booking_confirmed') * 100.0
            / NULLIF(COUNT(*), 0), 2
        )
        FROM call_logs
        WHERE worker_id = $1
          AND start_time >= $2::timestamptz
          AND start_time <= $3::timestamptz
    """, worker_id, from_dt, to_dt)

    return {
        "success_rate":  float(success_rate or 0),
        "response_time": float(avg_latency or 0),
        "booking_rate":  float(booking_rate or 0),
        # no_pii_leaks and accuracy require QA/Echo data — default to None
        "no_pii_leaks":  None,
        "accuracy":      None,
    }


def evaluate_kpi(actual: float | None, goal_operator: str, goal_value: float) -> str:
    """Return 'green', 'amber', or 'red' RAG status."""
    if actual is None:
        return "gray"
    if goal_operator == "gte":
        if actual >= goal_value:
            return "green"
        elif actual >= goal_value * 0.9:
            return "amber"
        return "red"
    elif goal_operator == "lte":
        if actual <= goal_value:
            return "green"
        elif actual <= goal_value * 1.1:
            return "amber"
        return "red"
    elif goal_operator == "eq":
        return "green" if actual == goal_value else "red"
    return "gray"
