"""Every department flow must rediscover its planted story from the mock dataset."""
import math

import pytest

from bizos import flows


def run(name, context=None):
    return flows.make_flow(name).run(context or {})


def kpi(findings, label):
    return next(k["value"] for k in findings.kpis if k["label"] == label)


def test_factory_knows_all_seven_departments():
    assert set(flows.FLOWS) == {"ceo", "finance", "marketing", "engineering", "operations", "procurement", "sales"}
    with pytest.raises(KeyError):
        flows.make_flow("hr")


@pytest.mark.parametrize("name", list(flows.FLOWS))
def test_every_flow_produces_verified_findings(name):
    f = run(name)
    assert f.flow == name and f.title and f.headline
    assert f.kpis and f.widgets and f.actions
    for w in f.widgets:
        assert w["source"] in f.tables and f.tables[w["source"]], w
    for k in f.kpis:
        assert isinstance(k["value"], (int, float)) and math.isfinite(k["value"])


def test_ceo_finds_competitor_undercut_and_reads_context_url():
    f = run("ceo", {"url": "https://www.competitor1.example/products"})
    gaps = f.tables["price_gaps"]
    undercut = [r for r in gaps if r["gap_pct"] <= -10]
    assert len(undercut) == 12
    assert all(-21 <= r["gap_pct"] <= -11 for r in undercut)
    assert "Lumen Supply" in f.title


def test_finance_reconciliation_counts():
    f = run("finance")
    status = [r["match"] for r in f.tables["reconciliation"]]
    assert status.count("short") == 60
    assert status.count("duplicate") == 15
    assert status.count("unpaid") + status.count("overdue") == 100
    assert kpi(f, "Failure rate, last 21d") > 2 * kpi(f, "Failure rate, before")


def test_marketing_paid_social_roas_drop():
    f = run("marketing")
    ps = next(r for r in f.tables["channel_roas"] if r["channel"] == "Paid Social")
    assert ps["roas_before"] > 3.8 and ps["roas_last_20d"] < 2.8


def test_engineering_compute_spike():
    f = run("engineering")
    compute = next(r for r in f.tables["service_costs"] if r["service"] == "compute")
    assert compute["change_pct"] >= 50


def test_operations_low_stock():
    f = run("operations")
    assert len(f.tables["stock_risk"]) == 13
    assert all(r["reorder_qty"] > 0 for r in f.tables["stock_risk"])


def test_procurement_slow_supplier_and_product_a_squeeze():
    f = run("procurement")
    worst = f.tables["scorecard"][0]
    assert worst["supplier_id"] == 7 and worst["avg_delay_days"] > 5
    margins = f.tables["product_a_margin"]
    assert margins[0]["profit_per_unit"] > 36 and margins[-1]["profit_per_unit"] < 33


def test_sales_overdue_accounts():
    f = run("sales")
    assert sum(r["overdue_invoices"] for r in f.tables["accounts"]) == 40


def test_router_picks_flow_from_context():
    assert flows.route("www.competitor1.example pricing") == "ceo"
    assert flows.route("Invoice #4411 payment") == "finance"
    assert flows.route("AWS billing console EC2") == "engineering"
    assert flows.route("nothing relevant") is None
