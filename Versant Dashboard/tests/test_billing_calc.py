import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.billing_calc import calculate_bill

TIERS = [
    {"tier_name": "Base",   "min_minutes": 0,     "max_minutes": 40000, "rate_per_minute": 0.0045, "overage_rate": 0.006},
    {"tier_name": "Growth", "min_minutes": 40001,  "max_minutes": 80000, "rate_per_minute": 0.0038, "overage_rate": 0.0052},
    {"tier_name": "Scale",  "min_minutes": 80001,  "max_minutes": None,  "rate_per_minute": 0.003,  "overage_rate": 0.0045},
]

def test_base_tier_no_overage():
    r = calculate_bill(30000, TIERS, echo_surcharge=0)
    assert r["base_cost"] == pytest.approx(135.0)
    assert r["overage_minutes"] == 0
    assert r["tier_name"] == "Base"

def test_base_tier_with_overage():
    r = calculate_bill(45000, TIERS, echo_surcharge=0)
    # 40000 * 0.0045 + 5000 * 0.006
    assert r["base_cost"] == pytest.approx(210.0)
    assert r["overage_minutes"] == 5000

def test_echo_surcharge():
    r = calculate_bill(30000, TIERS, echo_surcharge=1820.0)
    assert r["echo_surcharge"] == 1820.0
    assert r["total"] == pytest.approx(135.0 + 1820.0)

def test_zero_minutes():
    r = calculate_bill(0, TIERS, echo_surcharge=0)
    assert r["total"] == 0

def test_growth_tier():
    r = calculate_bill(60000, TIERS, echo_surcharge=0)
    assert r["tier_name"] == "Growth"
    assert r["base_cost"] == pytest.approx(60000 * 0.0038)
