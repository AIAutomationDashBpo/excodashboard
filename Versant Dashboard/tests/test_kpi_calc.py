import pytest
from app.services.kpi_calc import evaluate_kpi

def test_gte_pass():      assert evaluate_kpi(92.0, "gte", 85.0) == "green"
def test_gte_amber():     assert evaluate_kpi(77.0, "gte", 85.0) == "amber"
def test_gte_fail():      assert evaluate_kpi(70.0, "gte", 85.0) == "red"
def test_lte_pass():      assert evaluate_kpi(1800, "lte", 2000) == "green"
def test_lte_amber():     assert evaluate_kpi(2100, "lte", 2000) == "amber"
def test_lte_fail():      assert evaluate_kpi(3000, "lte", 2000) == "red"
def test_none_actual():   assert evaluate_kpi(None, "gte", 85.0) == "gray"
