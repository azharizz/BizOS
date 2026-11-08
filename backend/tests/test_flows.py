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


# ---- procurement: the cash-aware pay run
def po(**kw):
    base = {"po_id": 1, "supplier_id": 1, "supplier": "S", "product": "P", "product_id": 1, "amount": 1000.0, "payment_due_on": "2026-12-01",
            "invoice_date": "2026-11-05", "early_pay_days": 10, "early_pay_discount_pct": 2.0, "supplier_terms": "2/10 net 30",
            "on_hand": 100, "forecast_demand": 50, "avg_delay_days": 0.2}
    return {**base, **kw}


TODAY = flows.date(2026, 11, 8)
OVERDUE = [{"invoice_id": n, "customer": f"C{n}", "customer_id": n, "amount": 2000.0 + n, "days_overdue": 10} for n in range(1, 8)]


def test_plan_run_pays_only_what_cash_covers_and_keeps_a_reserve():
    pos = [po(po_id=1, amount=3000), po(po_id=2, amount=3000, early_pay_discount_pct=0), po(po_id=3, amount=3000)]
    r = flows.plan_run(pos, 5000, OVERDUE, TODAY)
    paid = [p for p in r["rows"] if p["when"] == "Today"]
    assert sum(p["net"] for p in paid) == r["today_total"] <= 5000 * (1 - flows.RESERVE_PCT)
    assert len(paid) == 1 and paid[0]["discount_usd"] == 60.0  # a discount beats a plain due date
    assert {p["when"] for p in r["rows"]} - {"Today"} <= {"After collection", "Next cycle"}
    assert r["stages"][0] == {"stage": "Start", "cash_after": 5000.0}


def test_plan_run_holds_slow_suppliers_and_chases_largest_invoices_first():
    pos = [po(po_id=1, avg_delay_days=6.3, on_hand=10), po(po_id=2, amount=4000)]
    r = flows.plan_run(pos, 1000, OVERDUE, TODAY)
    assert next(p for p in r["rows"] if p["po_id"] == 1)["when"] == "On receipt"
    amounts = [a["amount"] for a in r["asks"]]
    assert amounts == sorted(amounts, reverse=True) and 0 < len(r["asks"]) <= flows.MAX_ASKS
    assert r["expected"] == round(sum(a["amount"] for a in r["asks"]) * flows.COLLECT_PCT, 2)


def test_plan_run_loses_a_discount_that_ends_before_collections_land():
    r = flows.plan_run([po(amount=9000, invoice_date="2026-10-29")], 1000, OVERDUE, TODAY)  # discount ends today
    row = r["rows"][0]
    assert row["when"] != "Today" and row["discount_usd"] == 0 and row["net"] == 9000 and r["discount_lost"] == 180.0


def test_plan_run_is_repeatable_and_more_cash_pays_more():
    pos = [po(po_id=n, amount=2000) for n in range(1, 5)]
    low, high = flows.plan_run(pos, 3000, OVERDUE, TODAY), flows.plan_run(pos, 20000, OVERDUE, TODAY)
    assert pos[0]["amount"] == 2000 and "net" not in pos[0]  # the input is untouched
    assert high["today_total"] > low["today_total"] and not high["asks"]
    assert flows.plan_run(pos, 0, OVERDUE, TODAY)["today_total"] == 0


def test_procurement_flow_uses_the_paypal_balance_it_is_given():
    flow = flows.make_flow("procurement")
    ctx = {"context": {}, "balance": {"available": 60000.0, "withheld": 0.0, "source": "PayPal sandbox"}}
    for _, m in flow.steps:
        ctx.update(flow.act(m, ctx))
    f = flow.findings(ctx)
    assert kpi(f, "PayPal cash available") == 60000.0 and not ctx["run"]["asks"]
    assert all(r["when"] in ("Today", "On receipt") for r in f.tables["payment_plan"])
    assert any(a["kind"] == "payout" for a in f.actions) and "PayPal sandbox" in f.risks[1]


def test_procurement_default_plan_links_operations_sales_and_finance():
    f = run("procurement")
    plan = f.tables["payment_plan"]
    assert {r["action"] for r in plan} == {"Pay supplier", "Collect", "Hold"}
    assert f.tables["open_pos"] and f.tables["cash_stages"] and "demo balance" in f.risks[1]
    held = [r for r in plan if r["action"] == "Hold"]
    assert held and all("Harbor Ridge" in r["counterparty"] for r in held)  # supplier 7: slow, paid on receipt
    assert any(a["kind"] == "invoice_reminder" for a in f.actions)


# ---- procurement: quotes read from the Chrome page, ranked by real cost
from bizos import quotes as quote_lib  # noqa: E402


def digest_of_page() -> str:
    """What agent._dom_digest hands the flow for the sample page: header row then one row per quote."""
    rows = [quote_lib.HEADERS] + [quote_lib._cells(x) + ["Select quote"] for x in quote_lib.QUOTES]
    return "headings: Quotes\ntable: " + " / ".join(" ; ".join(r) for r in rows)


def test_parse_quotes_reads_the_page_digest_and_ignores_other_tables():
    parsed = quote_lib.parse_quotes("table: A ; B / 1 ; 2\n" + digest_of_page())
    assert [p["supplier"] for p in parsed] == [q["supplier"] for q in quote_lib.QUOTES]
    pine = next(p for p in parsed if p["supplier"] == "Pinecrest Woodcraft")
    assert pine["unit_price"] == 58.4 and pine["lead_days"] == 16 and pine["deposit_pct"] == 30 and pine["terms"] == "2/10 net 30"
    assert quote_lib.parse_quotes("") == [] and quote_lib.parse_quotes("table: x ; y / 1 ; 2") == []


def test_rendered_page_has_one_labelled_button_per_quote():
    page = quote_lib.render_page()
    for q_ in quote_lib.QUOTES:
        assert f'aria-label="Select quote: {q_["supplier"]}"' in page
    assert 'aria-label="Confirm order"' in page and "Sample marketplace" in page


def test_cheapest_unit_price_is_not_the_cheapest_quote():
    f = run("procurement")
    ranked = f.tables["quotes"]
    assert ranked[0]["supplier"] == "Pinecrest Woodcraft" and ranked[-1]["supplier"] == "Lakeside Ceramics Co."
    assert min(ranked, key=lambda r: r["unit_price"])["supplier"] == "Lakeside Ceramics Co."
    cur = next(r for r in ranked if r["current"])
    assert cur["supplier"] == "Harbor Ridge Trading" and cur["total_cost"] - ranked[0]["total_cost"] > 10000
    assert kpi(f, "Saved by switching supplier") > 10000


def test_quotes_from_chrome_page_drive_the_plan_and_the_deposit_is_paid_first():
    flow = flows.make_flow("procurement")
    ctx = {"context": {"dom": digest_of_page(), "title": "Sourcing Hub"}}
    for _, m in flow.steps:
        ctx.update(flow.act(m, ctx))
    assert ctx["quotes_source"].startswith("Chrome page")
    f = flow.findings(ctx)
    first = f.tables["payment_plan"][0]
    assert first["when"] == "Today" and first["reference"].startswith("New order") and "Chrome quote" in first["source"]
    assert f.actions[0]["id"].startswith("payout-new-") and "deposit" in f.actions[0]["label"]
    assert "Chrome page" in f.diagram and f.diagram.startswith("flowchart")


def test_every_plan_row_names_its_data_source():
    f = run("procurement")
    assert {r["source"] for r in f.tables["payment_plan"]} >= {"SQLite purchase orders", "SQLite invoices"}
    assert "Built-in quotes" in f.diagram and "demo" in f.diagram.lower()


def test_sample_page_buttons_are_plain_buttons_so_only_the_confirm_asks():
    page = quote_lib.render_page()
    assert page.count('<button type="button"') == len(quote_lib.QUOTES) + 1 and "<button class=" not in page


# ---- multi-site research: four supplier sites, four layouts
import re as _re  # noqa: E402


def snap_of(slug: str) -> dict:
    s = next(x for x in quote_lib.SITES if x["slug"] == slug)
    page = _re.sub(r"<script.*?</script>|<style.*?</style>", "", quote_lib.render_supplier(slug), flags=_re.S)
    text = _re.sub(r"[ \t]+", " ", _re.sub(r"<[^>]+>", " ", _re.sub(r"<(/tr|/p|/div|/h1|/td|br)[^>]*>", "\n", page)))
    return {"headings": [s["supplier"]], "text": text, "url": f"http://x/demo/s/{slug}"}


def test_every_supplier_layout_yields_its_own_quote():
    for s in quote_lib.SITES:
        q_ = quote_lib.extract_quote(snap_of(s["slug"]))
        assert q_["supplier"] == s["supplier"] and q_["unit_price"] == s["unit_price"], s["layout"]
        assert (q_["moq"], q_["lead_days"], q_["deposit_pct"], q_["terms"]) == (s["moq"], s["lead_days"], s["deposit_pct"], s["terms"])


def test_market_page_links_every_supplier_with_a_view_quote_button():
    page = quote_lib.render_market()
    for s in quote_lib.SITES:
        assert f'href="/demo/s/{s["slug"]}"' in page and f'aria-label="View quote: {s["supplier"]}"' in page
    assert quote_lib.render_supplier("nope") is None


def run_with_web():
    flow = flows.make_flow("procurement")
    ctx = {"context": {}, "web_quotes": [quote_lib.extract_quote(snap_of(s["slug"])) for s in quote_lib.SITES]}
    for _, m in flow.steps:
        ctx.update(flow.act(m, ctx))
    return flow.findings(ctx), ctx


def test_researched_quotes_rank_against_the_incumbent_and_unpriced_sites_get_a_quote_request():
    f, ctx = run_with_web()
    assert ctx["quotes_source"] == "Chrome research: 4 supplier sites read"
    ranked = [r["supplier"] for r in f.tables["quotes"]]
    assert ranked[0] == "Pinecrest Woodcraft" and "Harbor Ridge Trading" in ranked and "Orchid Ceramics" not in ranked  # no price: not ranked
    assert [r["status"] for r in f.tables["research_log"]].count("quote read") == 3
    rfq = [a for a in f.actions if a["id"].startswith("rfq-")]
    assert len(rfq) == 1 and rfq[0]["kind"] == "draft" and "Orchid" in rfq[0]["label"]
    assert kpi(f, "Supplier sites read") == 4 and any(w["source"] == "research_log" for w in f.widgets)
    assert "4 supplier sites read" in f.diagram


def test_fresh_workspace_ignores_a_planner_that_wants_an_old_one():
    from bizos import agent
    ws = {}
    s = agent.Session(ws)
    s.ws_id = "old"
    ws["old"] = {"id": "old"}
    s._fresh, s.ws_id = True, None
    made = s.use_workspace({"workspace": "old"})
    assert made["id"] != "old" and s.ws_id == made["id"] and s._fresh is False


def test_lineage_names_paypal_as_connected_even_when_the_demo_scale_is_on():
    flow = flows.make_flow("procurement")
    ctx = {"context": {}, "balance": {"available": 4858.0, "withheld": 0.0, "source": "PayPal Sandbox balance $4,396.66 as of 2026-11-08; demo scale 0.1"}}
    for _, m in flow.steps:
        ctx.update(flow.act(m, ctx))
    d = flow.findings(ctx).diagram
    assert "PayPal Sandbox API: $4,858 available" in d and "not connected" not in d
