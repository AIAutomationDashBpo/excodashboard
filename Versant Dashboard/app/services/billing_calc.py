"""Billing calculation logic — tier selection, overage, Echo surcharge."""
from decimal import Decimal
from typing import Optional


def calculate_bill(
    minutes: float,
    tiers: list[dict],
    echo_surcharge: float = 0.0,
) -> dict:
    """
    Calculate the monthly bill for a given minute count.

    tiers: list of dicts with keys:
        min_minutes, max_minutes (None = unlimited),
        rate_per_minute, overage_rate (optional)

    Returns dict with: tier_name, included_minutes, used_minutes,
    overage_minutes, base_cost, echo_surcharge, total
    """
    if not tiers or minutes <= 0:
        return {
            "tier_name": "N/A",
            "included_minutes": 0,
            "used_minutes": 0,
            "overage_minutes": 0,
            "base_cost": 0.0,
            "echo_surcharge": echo_surcharge,
            "total": echo_surcharge,
        }

    # Sort tiers by min_minutes ascending; pick the applicable tier
    sorted_tiers = sorted(tiers, key=lambda t: t["min_minutes"])
    active_tier = sorted_tiers[0]
    for tier in sorted_tiers:
        if minutes >= tier["min_minutes"]:
            active_tier = tier

    max_mins = active_tier.get("max_minutes")
    rate = float(active_tier["rate_per_minute"])
    overage_rate = float(active_tier.get("overage_rate") or rate)

    if max_mins is None or minutes <= max_mins:
        base_cost = minutes * rate
        overage_minutes = 0
    else:
        base_cost = max_mins * rate + (minutes - max_mins) * overage_rate
        overage_minutes = minutes - max_mins

    total = base_cost + echo_surcharge

    return {
        "tier_name": active_tier.get("tier_name", "Unknown"),
        "included_minutes": max_mins or minutes,
        "used_minutes": minutes,
        "overage_minutes": overage_minutes,
        "base_cost": round(base_cost, 2),
        "echo_surcharge": round(echo_surcharge, 2),
        "total": round(total, 2),
    }
