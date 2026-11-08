"""Seven department flows on one engine.

Each flow is a short list of steps (query -> verify) and a findings builder. Flows register themselves
with `@register` and are created with `make_flow(name)` (factory). The agent runs the steps one at a
time so it can verify each before moving on; `Flow.run` does the same in one go.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config, quotes as quote_lib
from .data import q, q1

FLOWS: dict[str, type["Flow"]] = {}


def register(cls):
    FLOWS[cls.name] = cls
    return cls


def make_flow(name: str) -> "Flow":
    return General() if name == General.name else FLOWS[name]()


def route(text: str) -> str | None:
    """Keyword fallback when the model can't (or shouldn't) pick a flow."""
    text = text.lower()
    scores = {n: sum(k in text for k in cls.keywords) for n, cls in FLOWS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


class VerifyError(Exception):
    pass


def verify(label: str, result: dict) -> dict:
    """A step passes when it returned data and every number in it is finite."""
    if not result or any(v in (None, [], {}) for v in result.values()):
        raise VerifyError(f"{label}: step returned no data")
    for v in result.values():
        for row in v if isinstance(v, list) else [v] if isinstance(v, dict) else []:
            bad = [k for k, x in row.items() if isinstance(x, float) and not math.isfinite(x)]
            if bad:
                raise VerifyError(f"{label}: non-numeric values in {bad}")
    return result


@dataclass
class Findings:
    flow: str
    title: str
    headline: str
    kpis: list[dict]
    tables: dict[str, list[dict]]
    widgets: list[dict]
    actions: list[dict]
    risks: list[str] = field(default_factory=list)
    diagram: str = ""  # Mermaid flowchart: where the data came from


class Flow:
    name = team = goal = ""
    keywords: tuple[str, ...] = ()
    steps: tuple[tuple[str, str], ...] = ()  # (label shown in the plan, method name)

    def act(self, method: str, ctx: dict) -> dict:
        label = next(lbl for lbl, m in self.steps if m == method)
        return verify(label, getattr(self, method)(ctx))

    def run(self, context: dict) -> Findings:
        ctx = {"context": context}
        for _, method in self.steps:
            ctx.update(self.act(method, ctx))
        return self.findings(ctx)

    def findings(self, ctx: dict) -> Findings:
        raise NotImplementedError


def kpi(label, value, unit="", tone="neutral"):
    return {"label": label, "value": round(float(value), 2), "unit": unit, "tone": tone}


def pct(a, b):
    return round(100.0 * (a - b) / b, 1) if b else 0.0


def email(kind: str, n) -> str:
    # ponytail: mock records have no contact emails; sandbox gets one receiver account or deterministic placeholders
    return config.PAYPAL_SANDBOX_RECEIVER or f"{kind}{n}@bizos-sandbox.example.com"


class General(Flow):
    """Any business question, any team: no fixed steps. The agent queries company data itself and the
    workspace is compiled from the evidence it pins. Not in FLOWS: the keyword router never picks it."""
    name, team, goal = "general", "Analysis", "Answer a business question from company data"

    def findings(self, ctx):
        return Findings(self.name, ctx.get("title") or "Investigation", ctx.get("headline", ""), [], {}, [], [])


# ---------------------------------------------------------------- CEO
@register
class Ceo(Flow):
    name, team, goal = "ceo", "Executive", "Is this competitor undercutting us?"
    keywords = ("competitor", "pricing", "price", "product page", "www.competitor", "undercut", "shop")
    steps = (("Identify the competitor on screen", "research"),
             ("Compare their prices to our list price and cost", "compare"),
             ("Estimate revenue and margin exposure", "exposure"),
             ("Simulate price responses", "simulate"))
    LOSS_IF_HOLD, LOSS_IF_HALF = .18, .06  # assumed volume loss on undercut products

    def research(self, ctx):
        c = ctx["context"]
        seen = f"{c.get('url', '')} {c.get('title', '')} {c.get('selection', '')}".lower()
        snap = q1("SELECT MAX(captured_on) FROM competitor_prices")
        comps = q("SELECT competitor_id, name, website FROM competitors")
        hit = next((x for x in comps if x["website"] in seen or x["name"].lower() in seen), None)
        hit = hit or q("""SELECT c.competitor_id, c.name, c.website, COUNT(*) n FROM competitor_prices cp
                          JOIN products p USING(product_id) JOIN competitors c USING(competitor_id)
                          WHERE cp.captured_on=? AND cp.price<=p.list_price*0.9
                          GROUP BY c.competitor_id ORDER BY n DESC LIMIT 1""", snap)[0]
        return {"competitor": hit, "snap": {"date": snap}}

    def compare(self, ctx):
        rows = q("""SELECT p.product_id, p.sku, p.name AS product, p.supplier_id, p.list_price, cp.price AS competitor_price,
                    ROUND(100.0*(cp.price-p.list_price)/p.list_price,1) AS gap_pct,
                    ROUND(pc.purchase_cost+pc.manufacturing_cost+pc.storage_cost,2) AS unit_cost
                    FROM competitor_prices cp JOIN products p USING(product_id)
                    JOIN product_costs pc ON pc.product_id=p.product_id AND pc.month=(SELECT MAX(month) FROM product_costs)
                    WHERE cp.competitor_id=? AND cp.captured_on=? ORDER BY gap_pct""",
                 ctx["competitor"]["competitor_id"], ctx["snap"]["date"])
        for r in rows:
            r["margin_pct"] = round(100 * (r["list_price"] - r["unit_cost"]) / r["list_price"], 1)
            r["margin_if_matched_pct"] = round(100 * (r["competitor_price"] - r["unit_cost"]) / r["competitor_price"], 1)
        return {"price_gaps": rows}

    def exposure(self, ctx):
        sold = {r["product_id"]: r for r in q("""SELECT oi.product_id, SUM(oi.quantity) qty, SUM(oi.quantity*oi.unit_price) revenue
                    FROM order_items oi JOIN orders o USING(order_id) WHERE o.status!='cancelled'
                    AND o.order_date > date((SELECT MAX(order_date) FROM orders), '-90 day') GROUP BY oi.product_id""")}
        for r in ctx["price_gaps"]:
            s = sold.get(r["product_id"], {"qty": 0, "revenue": 0})
            r["qty_90d"], r["revenue_90d"] = s["qty"], round(s["revenue"], 2)
        return {"undercut": [r for r in ctx["price_gaps"] if r["gap_pct"] <= -10]}

    def simulate(self, ctx):
        u = ctx["undercut"]
        rev = lambda price, loss: sum(price(r) * r["qty_90d"] * (1 - loss) for r in u)
        gp = lambda price, loss: sum((price(r) - r["unit_cost"]) * r["qty_90d"] * (1 - loss) for r in u)
        half = lambda r: (r["list_price"] + r["competitor_price"]) / 2
        options = [("Hold price", lambda r: r["list_price"], self.LOSS_IF_HOLD),
                   ("Meet halfway", half, self.LOSS_IF_HALF),
                   ("Match price", lambda r: r["competitor_price"], 0.0)]
        return {"scenarios": [{"scenario": n, "assumed_volume_loss_pct": loss * 100, "revenue_90d": round(rev(p, loss), 2),
                               "gross_profit_90d": round(gp(p, loss), 2)} for n, p, loss in options]}

    def findings(self, ctx):
        c, u, sc = ctx["competitor"], ctx["undercut"], ctx["scenarios"]
        best = max(sc, key=lambda s: s["gross_profit_90d"])
        exposed = sum(r["revenue_90d"] for r in u)
        po = q("""SELECT po.po_id, po.supplier_id, s.name, ROUND(po.quantity*po.unit_cost,2) amount FROM purchase_orders po
                  JOIN suppliers s USING(supplier_id) WHERE po.status='in_transit' AND po.product_id IN (%s)
                  ORDER BY amount LIMIT 1""" % (",".join(str(r["product_id"]) for r in u) or "0"))
        actions = [{"id": "price-draft", "kind": "draft", "label": f"Draft price response: {best['scenario']}",
                    "amount": 0, "currency": "USD", "recipient": "Pricing committee", "source": f"{len(u)} undercut SKUs",
                    "why": f"Best 90-day gross profit of the three scenarios (${best['gross_profit_90d']:,.0f})."}]
        if po:
            p = po[0]
            actions.append({"id": f"payout-po{p['po_id']}", "kind": "payout", "label": f"Pay PO #{p['po_id']} to secure stock",
                            "amount": p["amount"], "currency": "USD", "recipient": p["name"], "email": email("supplier", p["supplier_id"]),
                            "source": f"Purchase order #{p['po_id']}", "why": "Undercut SKUs need stock in hand before any price move."})
        return Findings(
            self.name, f"{c['name']} vs. our catalogue",
            f"{c['name']} is {abs(sum(r['gap_pct'] for r in u) / max(len(u), 1)):.0f}% cheaper on {len(u)} products, "
            f"exposing ${exposed:,.0f} of 90-day revenue. Best response: {best['scenario']}.",
            [kpi("Products undercut", len(u), tone="bad"),
             kpi("Average gap", sum(r["gap_pct"] for r in u) / max(len(u), 1), "%", "bad"),
             kpi("Revenue exposed (90d)", exposed, "$"),
             kpi("Best scenario gross profit", best["gross_profit_90d"], "$", "good")],
            {"price_gaps": ctx["price_gaps"], "undercut": u, "scenarios": sc},
            [{"type": "bar", "source": "undercut", "title": "Price gap vs. competitor (%)", "x": "product", "y": ["gap_pct"]},
             {"type": "column", "source": "scenarios", "title": "Price response scenarios (90d)", "x": "scenario", "y": ["revenue_90d", "gross_profit_90d"]},
             {"type": "grid", "source": "price_gaps", "title": "Price gaps by product",
              "cols": ["sku", "product", "list_price", "competitor_price", "gap_pct", "unit_cost", "margin_pct", "margin_if_matched_pct", "revenue_90d"]}],
            actions,
            [f"Volume loss assumptions ({self.LOSS_IF_HOLD:.0%} hold, {self.LOSS_IF_HALF:.0%} halfway) are estimates, not measured.",
             "Competitor prices are a snapshot; confirm on the live page before acting."])


# ---------------------------------------------------------------- Finance
@register
class Finance(Flow):
    name, team, goal = "finance", "Finance", "Do invoices and payments reconcile?"
    keywords = ("invoice", "payment", "paypal", "reconcil", "refund", "receivable", "transaction", "cash")
    steps = (("Match invoices to payments", "match"),
             ("Flag short, duplicate and failed payments", "failures"),
             ("Model cash flow from open and overdue invoices", "cashflow"))

    def match(self, ctx):
        rows = q("""SELECT i.invoice_id, c.customer_id, c.name AS customer, i.issued_on, i.due_on, i.amount, i.status,
                    ROUND(COALESCE(SUM(CASE WHEN p.status='COMPLETED' THEN p.amount END),0),2) AS paid,
                    COALESCE(SUM(p.status='COMPLETED'),0) AS completed, COALESCE(SUM(p.status='FAILED'),0) AS failed
                    FROM invoices i JOIN customers c USING(customer_id) LEFT JOIN payments p USING(invoice_id)
                    GROUP BY i.invoice_id ORDER BY i.invoice_id""")
        for r in rows:
            r["match"] = ("duplicate" if r["completed"] > 1 else "short" if r["completed"] == 1 and r["paid"] < r["amount"] - .01
                          else "overdue" if r["status"] == "overdue" else "unpaid" if r["status"] == "open" else "matched")
            r["difference"] = round(r["paid"] - r["amount"], 2)
        return {"reconciliation": rows}

    def failures(self, ctx):
        cut = "date((SELECT MAX(paid_at) FROM payments), '-20 day')"
        rate = lambda op: q1(f"SELECT 100.0*SUM(status='FAILED')/COUNT(*) FROM payments WHERE paid_at {op} {cut}")
        daily = q(f"""SELECT paid_at AS date, COUNT(*) attempts, SUM(status='FAILED') failed,
                      ROUND(100.0*SUM(status='FAILED')/COUNT(*),1) fail_rate_pct FROM payments
                      WHERE paid_at >= date((SELECT MAX(paid_at) FROM payments), '-59 day') GROUP BY paid_at ORDER BY paid_at""")
        reasons = q(f"""SELECT failure_reason AS reason, COUNT(*) failures FROM payments WHERE status='FAILED'
                        AND paid_at >= {cut} GROUP BY failure_reason ORDER BY failures DESC""")
        return {"rates": {"before": rate("<"), "recent": rate(">=")}, "daily_failures": daily, "reasons": reasons}

    def cashflow(self, ctx):
        rec = ctx["reconciliation"]
        due = lambda s: round(sum(r["amount"] for r in rec if r["match"] == s), 2)
        open_, overdue = due("unpaid"), due("overdue")
        return {"cash_scenarios": [{"scenario": f"Collect {p}% of overdue", "inflow_30d": round(open_ + overdue * p / 100, 2)}
                                   for p in (100, 70, 40)], "due": {"open": open_, "overdue": overdue}}

    def findings(self, ctx):
        rec, rates = ctx["reconciliation"], ctx["rates"]
        n = lambda s: sum(r["match"] == s for r in rec)
        issues = [r for r in rec if r["match"] != "matched"]
        overdue = max((r for r in rec if r["match"] == "overdue"), key=lambda r: r["amount"])
        dup = max((r for r in rec if r["match"] == "duplicate"), key=lambda r: r["difference"])
        short = min((r for r in rec if r["match"] == "short"), key=lambda r: r["difference"])
        return Findings(
            self.name, "Invoice & payment reconciliation",
            f"{n('short')} short and {n('duplicate')} duplicate payments, {n('unpaid') + n('overdue')} unpaid invoices. "
            f"Payment failures jumped from {rates['before']:.0f}% to {rates['recent']:.0f}% in the last 21 days.",
            [kpi("Short payments", n("short"), tone="bad"), kpi("Duplicate payments", n("duplicate"), tone="bad"),
             kpi("Unpaid invoices", n("unpaid") + n("overdue")), kpi("Overdue amount", ctx["due"]["overdue"], "$", "bad"),
             kpi("Failure rate, before", rates["before"], "%"), kpi("Failure rate, last 21d", rates["recent"], "%", "bad")],
            {"reconciliation": issues, "daily_failures": ctx["daily_failures"], "reasons": ctx["reasons"],
             "cash_scenarios": ctx["cash_scenarios"]},
            [{"type": "line", "source": "daily_failures", "title": "Daily payment failure rate (%)", "x": "date", "y": ["fail_rate_pct"]},
             {"type": "column", "source": "reasons", "title": "Failure reasons, last 21 days", "x": "reason", "y": ["failures"]},
             {"type": "grid", "source": "reconciliation", "title": "Unreconciled invoices",
              "cols": ["invoice_id", "customer", "issued_on", "due_on", "amount", "paid", "difference", "match", "failed"]},
             {"type": "column", "source": "cash_scenarios", "title": "30-day cash inflow scenarios", "x": "scenario", "y": ["inflow_30d"]}],
            [{"id": f"remind-{overdue['invoice_id']}", "kind": "invoice_reminder", "label": f"Send reminder for invoice #{overdue['invoice_id']}",
              "amount": overdue["amount"], "currency": "USD", "recipient": overdue["customer"], "email": email("ap.customer", overdue["customer_id"]),
              "source": f"Invoice #{overdue['invoice_id']} (overdue since {overdue['due_on']})", "why": "Largest overdue invoice."},
             {"id": f"refund-{dup['invoice_id']}", "kind": "payout", "label": f"Refund duplicate on invoice #{dup['invoice_id']}",
              "amount": dup["difference"], "currency": "USD", "recipient": dup["customer"], "email": email("ap.customer", dup["customer_id"]),
              "source": f"Invoice #{dup['invoice_id']}: paid ${dup['paid']:,.2f} of ${dup['amount']:,.2f}", "why": "Customer paid twice."},
             {"id": f"short-{short['invoice_id']}", "kind": "draft", "label": f"Draft correction for short payment #{short['invoice_id']}",
              "amount": -short["difference"], "currency": "USD", "recipient": short["customer"],
              "source": f"Invoice #{short['invoice_id']}", "why": "Largest short payment."}],
            ["Failure spike may be a processor issue; check PayPal status before contacting customers."])


# ---------------------------------------------------------------- Marketing
@register
class Marketing(Flow):
    name, team, goal = "marketing", "Marketing", "Which channels are losing return on spend?"
    keywords = ("ads", "campaign", "roas", "marketing", "facebook", "instagram", "tiktok", "ad library", "social")
    steps = (("Compare return on ad spend by channel", "roas"),
             ("Trace the daily trend", "trend"),
             ("Model a budget reallocation", "reallocate"))
    SHIFT = .30

    def roas(self, ctx):
        cut = "date((SELECT MAX(date) FROM marketing_daily_metrics), '-19 day')"
        rows = q(f"""SELECT c.channel,
                     ROUND(SUM(CASE WHEN m.date<{cut} THEN m.revenue END)/SUM(CASE WHEN m.date<{cut} THEN m.spend END),2) roas_before,
                     ROUND(SUM(CASE WHEN m.date>={cut} THEN m.revenue END)/SUM(CASE WHEN m.date>={cut} THEN m.spend END),2) roas_last_20d,
                     ROUND(SUM(CASE WHEN m.date>={cut} THEN m.spend END),2) spend_last_20d
                     FROM marketing_daily_metrics m JOIN marketing_campaigns c USING(campaign_id) GROUP BY c.channel""")
        for r in rows:
            r["change_pct"] = pct(r["roas_last_20d"], r["roas_before"])
        return {"channel_roas": sorted(rows, key=lambda r: r["change_pct"])}

    def trend(self, ctx):
        return {"daily_roas": q("""SELECT m.date, c.channel, ROUND(SUM(m.revenue)/SUM(m.spend),2) roas
                    FROM marketing_daily_metrics m JOIN marketing_campaigns c USING(campaign_id)
                    WHERE m.date >= date((SELECT MAX(date) FROM marketing_daily_metrics), '-44 day')
                    GROUP BY m.date, c.channel ORDER BY m.date""")}

    def reallocate(self, ctx):
        rows = ctx["channel_roas"]
        worst, best = rows[0], max(rows, key=lambda r: r["roas_last_20d"])
        moved = worst["spend_last_20d"] * self.SHIFT
        return {"budget_scenarios": [
            {"scenario": "Keep current mix", "spend_moved": 0.0, "extra_revenue_20d": 0.0},
            {"scenario": f"Move {self.SHIFT:.0%} {worst['channel']} -> {best['channel']}", "spend_moved": round(moved, 2),
             "extra_revenue_20d": round(moved * (best["roas_last_20d"] - worst["roas_last_20d"]), 2)}],
            "shift": {"from": worst["channel"], "to": best["channel"], "amount": round(moved, 2)}}

    def findings(self, ctx):
        w = ctx["channel_roas"][0]
        s = ctx["shift"]
        gain = ctx["budget_scenarios"][1]["extra_revenue_20d"]
        return Findings(
            self.name, "Channel return on ad spend",
            f"{w['channel']} ROAS fell from {w['roas_before']:.1f} to {w['roas_last_20d']:.1f} in 20 days. "
            f"Moving {self.SHIFT:.0%} of its budget to {s['to']} adds about ${gain:,.0f} per 20 days.",
            [kpi(f"{w['channel']} ROAS before", w["roas_before"], "x"), kpi(f"{w['channel']} ROAS, last 20d", w["roas_last_20d"], "x", "bad"),
             kpi("Change", w["change_pct"], "%", "bad"), kpi("Revenue from reallocation (20d)", gain, "$", "good")],
            {k: ctx[k] for k in ("channel_roas", "daily_roas", "budget_scenarios")},
            [{"type": "line", "source": "daily_roas", "title": "Daily ROAS by channel", "x": "date", "y": ["roas"], "series": "channel"},
             {"type": "column", "source": "channel_roas", "title": "ROAS before vs. last 20 days", "x": "channel", "y": ["roas_before", "roas_last_20d"]},
             {"type": "grid", "source": "channel_roas", "title": "Channels", "cols": ["channel", "roas_before", "roas_last_20d", "change_pct", "spend_last_20d"]}],
            [{"id": "budget-draft", "kind": "draft", "label": f"Draft budget shift: {s['from']} -> {s['to']}", "amount": s["amount"],
              "currency": "USD", "recipient": "Growth team", "source": "channel_roas", "why": "No ad-platform integration yet; drafted for review."}],
            ["ROAS of the receiving channel may fall as spend scales."])


# ---------------------------------------------------------------- Engineering
@register
class Engineering(Flow):
    name, team, goal = "engineering", "Engineering", "Why did cloud spend jump?"
    keywords = ("cloud", "aws", "gcp", "azure", "billing", "github", "compute", "ec2", "infra", "kubernetes")
    steps = (("Detect the spend spike", "spike"), ("Break cost down by service", "trend"),
             ("Simulate cheaper alternatives", "simulate"))
    OPTIONS = (("Reserved instances (1y)", .30, "low"), ("Rightsize nodes", .20, "medium"), ("Spot capacity", .45, "high"))

    def spike(self, ctx):
        cut = "date((SELECT MAX(date) FROM cloud_costs), '-13 day')"
        rows = q(f"""SELECT service, ROUND(SUM(CASE WHEN date<{cut} AND date>=date({cut},'-14 day') THEN cost_usd END),2) prev_14d,
                     ROUND(SUM(CASE WHEN date>={cut} THEN cost_usd END),2) last_14d FROM cloud_costs GROUP BY service""")
        for r in rows:
            r["change_pct"] = pct(r["last_14d"], r["prev_14d"])
            r["extra_usd"] = round(r["last_14d"] - r["prev_14d"], 2)
        return {"service_costs": sorted(rows, key=lambda r: -r["change_pct"])}

    def trend(self, ctx):
        return {"daily_costs": q("""SELECT date, service, cost_usd FROM cloud_costs
                    WHERE date >= date((SELECT MAX(date) FROM cloud_costs), '-44 day') ORDER BY date""")}

    def simulate(self, ctx):
        top = ctx["service_costs"][0]
        monthly = top["last_14d"] / 14 * 30
        return {"options": [{"option": n, "service": top["service"], "monthly_cost": round(monthly * (1 - cut), 2),
                             "monthly_saving": round(monthly * cut, 2), "reliability_risk": risk} for n, cut, risk in self.OPTIONS]}

    def findings(self, ctx):
        t = ctx["service_costs"][0]
        best = max((o for o in ctx["options"] if o["reliability_risk"] != "high"), key=lambda o: o["monthly_saving"])
        return Findings(
            self.name, "Cloud cost investigation",
            f"{t['service']} cost is up {t['change_pct']:.0f}% over the last 14 days (+${t['extra_usd']:,.0f}). "
            f"{best['option']} saves about ${best['monthly_saving']:,.0f}/month at {best['reliability_risk']} risk.",
            [kpi(f"{t['service']} change, 14d", t["change_pct"], "%", "bad"), kpi("Extra spend, 14d", t["extra_usd"], "$", "bad"),
             kpi("Total spend, 14d", sum(r["last_14d"] for r in ctx["service_costs"]), "$"),
             kpi("Best safe saving / month", best["monthly_saving"], "$", "good")],
            {k: ctx[k] for k in ("service_costs", "daily_costs", "options")},
            [{"type": "line", "source": "daily_costs", "title": "Daily cost by service", "x": "date", "y": ["cost_usd"], "series": "service"},
             {"type": "column", "source": "options", "title": f"{t['service']} options: monthly cost", "x": "option", "y": ["monthly_cost", "monthly_saving"]},
             {"type": "grid", "source": "service_costs", "title": "Cost by service", "cols": ["service", "prev_14d", "last_14d", "change_pct", "extra_usd"]}],
            [{"id": "ticket-draft", "kind": "draft", "label": f"Draft ticket: {best['option']} for {t['service']}", "amount": best["monthly_saving"],
              "currency": "USD", "recipient": "Platform team", "source": "service_costs", "why": "No ticketing integration yet."}],
            ["Spot capacity can be reclaimed at short notice; keep it off stateful workloads."])


# ---------------------------------------------------------------- Operations
@register
class Operations(Flow):
    name, team, goal = "operations", "Operations", "Which products will stock out?"
    keywords = ("inventory", "warehouse", "stock", "sku", "reorder", "fulfil", "wms")
    steps = (("Find products below forecast demand", "below"), ("Estimate lost revenue from stock-outs", "lost"),
             ("Suggest reorder quantities", "reorder"))

    def below(self, ctx):
        return {"stock_risk": q("""SELECT p.product_id, p.sku, p.name AS product, s.name AS supplier, s.lead_time_days, p.list_price,
                    i.on_hand, i.forecast_demand, i.reorder_point FROM inventory_snapshots i JOIN products p USING(product_id)
                    JOIN suppliers s ON s.supplier_id=p.supplier_id
                    WHERE i.month=(SELECT MAX(month) FROM inventory_snapshots) AND i.on_hand<i.forecast_demand
                    ORDER BY 1.0*i.on_hand/i.forecast_demand""")}

    def lost(self, ctx):
        for r in ctx["stock_risk"]:
            r["shortfall"] = r["forecast_demand"] - r["on_hand"]
            r["lost_revenue"] = round(r["shortfall"] * r["list_price"], 2)
        return {"stock_risk": ctx["stock_risk"]}

    def reorder(self, ctx):
        for r in ctx["stock_risk"]:
            r["reorder_qty"] = r["forecast_demand"] + r["reorder_point"] - r["on_hand"]
        return {"stock_risk": ctx["stock_risk"]}

    def findings(self, ctx):
        s = ctx["stock_risk"]
        lost = sum(r["lost_revenue"] for r in s)
        return Findings(
            self.name, "Inventory & reorder plan",
            f"{len(s)} products end the month below forecast demand, risking ${lost:,.0f} in lost sales.",
            [kpi("Products below forecast", len(s), tone="bad"), kpi("Revenue at risk", lost, "$", "bad"),
             kpi("Units to reorder", sum(r["reorder_qty"] for r in s)), kpi("Longest lead time", max(r["lead_time_days"] for r in s), "d")],
            {"stock_risk": s},
            [{"type": "column", "source": "stock_risk", "title": "On hand vs. forecast demand", "x": "product", "y": ["on_hand", "forecast_demand"]},
             {"type": "bar", "source": "stock_risk", "title": "Revenue at risk by product", "x": "product", "y": ["lost_revenue"]},
             {"type": "grid", "source": "stock_risk", "title": "Reorder plan",
              "cols": ["sku", "product", "supplier", "on_hand", "forecast_demand", "shortfall", "lost_revenue", "reorder_qty", "lead_time_days"]}],
            [{"id": "po-draft", "kind": "draft", "label": f"Draft {len(s)} purchase orders", "amount": 0, "currency": "USD",
              "recipient": "Purchasing", "source": "stock_risk", "why": "No ordering system yet; drafted for review."}],
            ["Forecasts are monthly; a mid-month spike can stock out sooner."])


# ---------------------------------------------------------------- Procurement
SLOW_DELAY_DAYS = 3.0  # a supplier later than this on average is paid on receipt, not in advance
RESERVE_PCT = .10      # cash left untouched when scheduling payments
COLLECT_PCT = .70      # share of an overdue invoice we assume a reminder brings in
COLLECT_DELAY_DAYS = 3  # how long a collection takes to land; discounts ending sooner are lost
MAX_ASKS = 4           # first wave of invoices to chase, largest first


def ends(days: int) -> str:
    return "ends today" if days == 0 else f"ends in {days}d"


def plan_run(pos: list[dict], cash: float, receivables: list[dict], today: date,
             reserve_pct: float = RESERVE_PCT, collect_pct: float = COLLECT_PCT) -> dict:
    """Schedule supplier payments against the cash actually on hand.

    Priority: early-pay discount still open, then stock-out risk, then due date. Slow suppliers are held until delivery.
    A payment that cash cannot cover waits for collections: overdue invoices are chased largest first until the
    expected inflow (collect_pct of each) covers what is waiting. Pure function: easy to test and to re-run what-if.
    """
    pos = [dict(p) for p in pos]  # never mutate the caller's rows: what-if re-runs reuse them
    spendable = max(cash * (1 - reserve_pct), 0.0)
    rows = []
    for po in pos:
        invoiced = date.fromisoformat(po["invoice_date"])
        pct = po["early_pay_discount_pct"] or 0
        window = po["early_pay_days"] or 0
        left = (invoiced + timedelta(days=window) - today).days
        po["discount_days_left"] = left if pct and left >= 0 else None
        po["discount_usd"] = round(po["amount"] * pct / 100, 2) if po["discount_days_left"] is not None else 0.0
        po["net"] = round(po["amount"] - po["discount_usd"], 2)
        po["at_risk"] = bool(po["on_hand"] is not None and po["on_hand"] < po["forecast_demand"])
        po["slow"] = (po["avg_delay_days"] or 0) > SLOW_DELAY_DAYS
        po["tier"] = (0 if po["discount_usd"] and po["at_risk"] else 1 if po["discount_usd"] else 2 if po["at_risk"] else 3)
    queue = sorted(pos, key=lambda p: (not p.get("urgent"), p["slow"], p["tier"], -p["discount_usd"], p["payment_due_on"]))
    left_cash, waiting, lost = spendable, [], 0.0
    for po in queue:
        if po["slow"]:
            po["when"], po["why"] = "On receipt", (f"{po['supplier']} averages {po['avg_delay_days']:.1f} days late"
                                                    f"{' and this product is below forecast demand' if po['at_risk'] else ''}: "
                                                    f"pay on delivery, and line up a backup supplier")
        elif po["net"] <= left_cash:
            left_cash -= po["net"]
            po["when"] = "Today"
            po["why"] = po.get("note") or (f"{po['supplier_terms']} early-pay discount saves ${po['discount_usd']:,.0f}, {ends(po['discount_days_left'])}"
                         if po["discount_usd"] else "Stock is below forecast demand" if po["at_risk"] else f"Due {po['payment_due_on']}")
            if po["discount_usd"] and po["at_risk"]:
                po["why"] += "; stock is below forecast demand"
        else:
            po["when"], po["why"] = "After collection", "Cash cannot cover it today"
            if po["discount_usd"] and po["discount_days_left"] < COLLECT_DELAY_DAYS:  # gone before the cash arrives
                po["why"] += f"; the ${po['discount_usd']:,.0f} discount {ends(po['discount_days_left'])}, before collections land"
                lost += po["discount_usd"]
                po["discount_usd"], po["net"] = 0.0, po["amount"]
            waiting.append(po)
        rows.append(po)
    # chase overdue invoices (largest first) until the expected inflow covers what is waiting
    need = sum(p["net"] for p in waiting if p["tier"] < 3)
    asks, expected = [], 0.0
    for inv in sorted(receivables, key=lambda r: -r["amount"]):
        if expected >= need or len(asks) >= MAX_ASKS:
            break
        asks.append({**inv, "expected": round(inv["amount"] * collect_pct, 2)})
        expected += asks[-1]["expected"]
    expected = round(expected, 2)
    cover = spendable - sum(p["net"] for p in rows if p["when"] == "Today") + expected
    for po in waiting:
        if po["net"] <= cover:
            cover -= po["net"]
        else:
            po["when"], po["why"] = "Next cycle", "Still short after expected collections"
    today_total = round(sum(p["net"] for p in rows if p["when"] == "Today"), 2)
    after_collect = round(sum(p["net"] for p in rows if p["when"] == "After collection"), 2)
    stages = [("Start", round(cash, 2)), ("After today's payments", round(cash - today_total, 2)),
              ("After collections land", round(cash - today_total + expected, 2)),
              ("After remaining payments", round(cash - today_total + expected - after_collect, 2))]
    return {"rows": queue, "asks": asks, "expected": expected, "today_total": today_total, "after_collect": after_collect,
            "stages": [{"stage": n, "cash_after": v} for n, v in stages],
            "discount_captured": round(sum(p["discount_usd"] for p in rows if p["when"] in ("Today", "After collection")), 2),
            "discount_lost": round(lost, 2)}


ASSUMED_NEW_DELAY = 3.0  # days late assumed for a quoted supplier with no delivery history


@register
class Procurement(Flow):
    """Procurement as the hub: a page of quotes (Chrome), Operations (what runs out), Sales (what customers owe)
    and Finance (what PayPal holds) decide who to order from, who to pay now and what to collect first."""
    name, team, goal = "procurement", "Procurement", "Who should we buy from, who do we pay now, and can we afford it?"
    keywords = ("supplier", "vendor", "procure", "purchase order", "lead time", "sourcing", "alibaba", "pay run", "payables",
                "early pay", "quote")
    steps = (("Score suppliers on delay and reliability", "score"), ("Trace margin loss to supplier cost", "margin"),
             ("Compare supplier quotes against stock risk", "quotes"),
             ("Match open purchase orders to stock risk", "open_pos"), ("Check PayPal cash and overdue receivables", "cash"),
             ("Build the pay-and-collect plan", "plan"))
    note = ("When the page on screen lists several suppliers with 'View quote' links, this flow itself opens and reads every "
            "supplier site in Chrome and picks the quote on the page: never plan page-reading or clicking steps for that.")
    DEMO_CASH = 5000.0  # used only when PayPal is not connected
    wants_balance = ("cash",)  # tools.run_step fetches the live PayPal balance before this step

    def score(self, ctx):
        return {"scorecard": q("""SELECT s.supplier_id, s.name AS supplier, s.country, COUNT(*) pos,
                    ROUND(AVG(sh.delay_days),1) avg_delay_days, ROUND(100.0*AVG(sh.delay_days=0),0) on_time_pct,
                    s.reliability_score, ROUND(SUM(po.quantity*po.unit_cost),2) spend
                    FROM purchase_orders po JOIN suppliers s USING(supplier_id) JOIN shipments sh USING(po_id)
                    WHERE sh.delay_days IS NOT NULL GROUP BY s.supplier_id ORDER BY avg_delay_days DESC""")}

    def margin(self, ctx):
        return {"product_a_margin": q("""SELECT pc.month, p.list_price, pc.purchase_cost,
                    ROUND(p.list_price-pc.purchase_cost-pc.manufacturing_cost-pc.storage_cost,2) profit_per_unit
                    FROM product_costs pc JOIN products p USING(product_id) WHERE p.product_id=1 ORDER BY pc.month""")}

    def quotes(self, ctx):
        """Rank the quotes on the Chrome page by what they really cost: price plus the sales lost while stock is out."""
        c = ctx["context"]
        web = ctx.get("web_quotes") or []  # quotes read from several supplier sites in Chrome (tools._research_suppliers)
        page = [] if web else quote_lib.parse_quotes(c.get("dom", ""))
        source = (f"Chrome research: {len(web)} supplier sites read" if web else
                  f"Chrome page: {c.get('title') or c.get('url')}" if page else "Built-in sample quotes (no Chrome page connected)")
        stock = q("""SELECT i.on_hand, i.forecast_demand, i.reorder_point, p.list_price, p.supplier_id AS current_id
                     FROM inventory_snapshots i JOIN products p USING(product_id)
                     WHERE i.product_id=1 AND i.month=(SELECT MAX(month) FROM inventory_snapshots)""")[0]
        units = stock["forecast_demand"] + stock["reorder_point"] - stock["on_hand"]
        daily = stock["forecast_demand"] / 30
        cover = stock["on_hand"] / daily
        hist = {s["supplier"].lower(): s for s in ctx["scorecard"]}
        ids = {r["name"].lower(): r["supplier_id"] for r in q("SELECT supplier_id, name FROM suppliers")}
        out = []
        raw = web or page or [dict(x) for x in quote_lib.QUOTES]
        unpriced = [r for r in raw if not r.get("unit_price")]  # no published price: ask for a quote, don't guess
        raw = [r for r in raw if r.get("unit_price")]
        if web:  # the supplier we use today is the baseline, from company records
            inc = q("""SELECT s.name, s.country, s.lead_time_days, s.reliability_score, s.payment_terms_days,
                       (SELECT unit_cost FROM purchase_orders WHERE product_id=1 ORDER BY ordered_on DESC LIMIT 1) AS cost
                       FROM suppliers s WHERE s.supplier_id=?""", stock["current_id"])[0]
            if inc["name"].lower() not in {r["supplier"].lower() for r in raw}:
                raw.append({"supplier": inc["name"], "country": inc["country"], "unit_price": inc["cost"], "moq": 1,
                            "lead_days": inc["lead_time_days"], "rating": round(inc["reliability_score"] * 5, 1),
                            "terms": f"net {inc['payment_terms_days']}", "deposit_pct": 0.0, "url": ""})
        for r in raw:
            h = hist.get(r["supplier"].lower())
            delay = h["avg_delay_days"] if h else None
            n = max(units, r["moq"])
            landed = round(r["unit_price"] * n, 2)
            expected = r["lead_days"] + (delay if delay is not None else ASSUMED_NEW_DELAY)
            gap = max(0.0, expected - cover)
            lost = round(gap * daily * max(stock["list_price"] - r["unit_price"], 0), 2)
            sid = ids.get(r["supplier"].lower())
            out.append({**r, "supplier_id": sid, "current": "yes" if sid == stock["current_id"] else "",
                        "history": f"{delay:.1f}d late on average, {h['on_time_pct']:.0f}% on time" if h else f"no history, assume {ASSUMED_NEW_DELAY:g}d late",
                        "avg_delay_days": delay, "units": n, "expected_lead_days": round(expected, 1), "stockout_days": round(gap, 1),
                        "landed_cost": landed, "lost_margin": lost, "total_cost": round(landed + lost, 2),
                        "deposit": round(landed * r["deposit_pct"] / 100, 2)})
        out.sort(key=lambda r: r["total_cost"])
        for n, r in enumerate(out, 1):
            r["rank"] = n
        cur = next((r for r in out if r["current"]), None)
        res = {"quotes": out, "chosen": out[0], "quotes_source": source, "current_quote": cur or out[-1],
               "stock": {**stock, "units": units, "daily": round(daily, 2), "cover_days": round(cover, 1)}}
        if unpriced:
            res["unpriced"] = unpriced
        if web:
            res["research_log"] = [{"site": r["supplier"], "country": r["country"], "unit_price": r["unit_price"], "moq": r["moq"],
                                    "lead_days": r["lead_days"], "terms": r["terms"],
                                    "status": "quote read" if r.get("unit_price") else "no published price: request a quote",
                                    "url": r.get("url", "")} for r in web]
        return res

    def open_pos(self, ctx):
        delay = {s["supplier_id"]: s["avg_delay_days"] for s in ctx["scorecard"]}
        rows = q("""SELECT po.po_id, po.supplier_id, s.name AS supplier, p.name AS product, po.product_id,
                    ROUND(po.quantity*po.unit_cost,2) amount, po.payment_due_on, sh.shipped_on AS invoice_date,
                    s.payment_terms_days, s.early_pay_days, s.early_pay_discount_pct, s.reliability_score,
                    i.on_hand, i.forecast_demand
                    FROM purchase_orders po JOIN suppliers s USING(supplier_id) JOIN products p USING(product_id)
                    JOIN shipments sh USING(po_id)
                    LEFT JOIN inventory_snapshots i ON i.product_id=po.product_id AND i.month=(SELECT MAX(month) FROM inventory_snapshots)
                    WHERE po.paid_on IS NULL ORDER BY po.payment_due_on""")
        for r in rows:
            r["avg_delay_days"] = delay.get(r["supplier_id"], 0.0)
            pct_ = r["early_pay_discount_pct"]
            r["supplier_terms"] = f"{pct_:g}/{r['early_pay_days']} net {r['payment_terms_days']}" if pct_ else f"net {r['payment_terms_days']}"
        return {"open_pos": rows}

    def cash(self, ctx):
        bal = ctx.get("balance") or {"available": self.DEMO_CASH, "withheld": 0.0, "source": "demo balance (PayPal not connected)"}
        recv = q("""SELECT i.invoice_id, c.customer_id, c.name AS customer, c.segment, i.due_on, i.amount,
                    CAST(julianday((SELECT MAX(order_date) FROM orders)) - julianday(i.due_on) AS INTEGER) AS days_overdue
                    FROM invoices i JOIN customers c USING(customer_id) WHERE i.status='overdue' ORDER BY i.amount DESC""")
        return {"balance": bal, "receivables": recv}

    def plan(self, ctx):
        today = date.fromisoformat(q1("SELECT MAX(order_date) FROM orders")) + timedelta(days=1)
        ch, cur, st = ctx["chosen"], ctx["current_quote"], ctx["stock"]
        pos = list(ctx["open_pos"])
        if ch["deposit"] > 0:  # the quote we picked becomes an order that is paid first
            pos.insert(0, {"po_id": "NEW", "supplier_id": ch["supplier_id"] or 0, "supplier": ch["supplier"],
                           "product": "Product A (new order)", "product_id": 1, "amount": ch["deposit"],
                           "payment_due_on": today.isoformat(), "invoice_date": today.isoformat(), "early_pay_days": 0,
                           "early_pay_discount_pct": 0, "supplier_terms": f"{ch['deposit_pct']:g}% deposit",
                           "on_hand": st["on_hand"], "forecast_demand": st["forecast_demand"], "avg_delay_days": ch["avg_delay_days"] or 0.0,
                           "urgent": True, "note": f"Starts the Product A order: {ch['units']} units arrive in about {ch['expected_lead_days']:g}d "
                                                   f"(current supplier: {cur['expected_lead_days']:g}d); stock lasts {st['cover_days']:g}d"})
        run = plan_run(pos, ctx["balance"]["available"], ctx["receivables"], today)
        grid = []
        for n, po in enumerate(run["rows"], 1):
            new = po["po_id"] == "NEW"
            grid.append({"step": n, "when": po["when"], "action": "Hold" if po["slow"] else "Pay supplier",
                         "counterparty": po["supplier"], "reference": "New order: Product A (deposit)" if new else f"PO #{po['po_id']} - {po['product']}",
                         "amount": po["amount"], "discount_usd": po["discount_usd"], "cash_effect": -po["net"], "why": po["why"],
                         "source": "Chrome quote + SQLite stock" if new and ctx["quotes_source"].startswith("Chrome") else
                                   "Quote + SQLite stock" if new else "SQLite purchase orders"})
        for inv in run["asks"]:
            grid.append({"step": len(grid) + 1, "when": "Today", "action": "Collect", "counterparty": inv["customer"],
                         "reference": f"Invoice #{inv['invoice_id']} - {inv['days_overdue']}d overdue", "amount": inv["amount"],
                         "discount_usd": 0.0, "cash_effect": inv["expected"], "why": f"Largest overdue; assume {COLLECT_PCT:.0%} comes in",
                         "source": "SQLite invoices"})
        order = {"Today": 0, "After collection": 1, "On receipt": 2, "Next cycle": 3}
        grid.sort(key=lambda r: (order[r["when"]], r["action"] == "Collect", -r["amount"]))
        for n, r in enumerate(grid, 1):
            r["step"] = n
        return {"run": run, "payment_plan": grid, "cash_stages": run["stages"]}

    def lineage(self, ctx) -> str:
        """Mermaid flowchart of where every number came from (shown in the workspace)."""
        n_q, n_po, n_inv = len(ctx["quotes"]), len(ctx["open_pos"]), len(ctx["receivables"])
        chrome = ctx["quotes_source"].startswith("Chrome")
        web = ctx["quotes_source"].startswith("Chrome research")
        bal = ctx["balance"]
        pp = ("Demo balance (PayPal not connected)" if bal["source"].startswith("demo balance")
              else f"PayPal Sandbox API: ${bal['available']:,.0f} available")
        return "\n".join([
            "flowchart LR",
            f'  C["{"Chrome: " + str(len(ctx["research_log"])) + " supplier sites read" if web else "Chrome page" if chrome else "Built-in quotes"}: {n_q} priced quotes"]',
            f'  D[("Company data SQLite: {n_po} open POs, {n_inv} overdue invoices, stock, delivery history")]',
            f'  P["{pp}"]',
            '  Q["Quote comparison: price plus lost sales"]',
            '  G["Pay-and-collect plan: AG Grid"]',
            '  A["Pay supplier: PayPal Payouts"]',
            '  B["Request payment: PayPal Invoicing"]',
            '  H{"Person approves: press and hold"}',
            "  C --> Q", "  D --> Q", "  Q --> G", "  D --> G", "  P --> G",
            "  G --> H", "  H --> A", "  H --> B"])

    def deadlines(self, ctx, now, later, run) -> list[dict]:
        """Dates worth an alarm: a discount that ends, a payment waiting on cash, an overdue invoice to chase."""
        today = date.fromisoformat(q1("SELECT MAX(order_date) FROM orders")) + timedelta(days=1)
        at = lambda day, hh, mm=0: datetime(day.year, day.month, day.day, hh, mm).isoformat(timespec="minutes")
        out = []
        for p in now:  # paid today: the alarm is the last moment the early-pay discount is still on
            if p["po_id"] != "NEW" and p["discount_usd"] and p["discount_days_left"] is not None:
                out.append({"title": f"Early-pay discount ends: PO #{p['po_id']} {p['supplier']} (saves ${p['discount_usd']:,.0f})",
                            "start": at(today + timedelta(days=p["discount_days_left"]), 17), "minutes": 15, "alarm_minutes": 120,
                            "notes": f"Pay ${p['net']:,.2f} to {p['supplier']} ({p['supplier_terms']})."})
        for a in run["asks"][:2]:
            out.append({"title": f"Chase overdue invoice #{a['invoice_id']}: {a['customer']} (${a['amount']:,.0f})",
                        "start": at(today + timedelta(days=COLLECT_DELAY_DAYS - 1), 9), "minutes": 20, "alarm_minutes": 30,
                        "notes": f"{a['days_overdue']} days overdue. A PayPal payment request was sent."})
        for p in later[:2]:
            out.append({"title": f"Pay after collections land: PO #{p['po_id']} {p['supplier']} (${p['net']:,.0f})",
                        "start": at(today + timedelta(days=COLLECT_DELAY_DAYS + 1), 10), "minutes": 20, "alarm_minutes": 60,
                        "notes": f"Cash should be in by then; due {p['payment_due_on']}."})
        slow = [p for p in run["rows"] if p["slow"]]
        if slow:
            p = slow[0]
            out.append({"title": f"Check delivery before paying {p['supplier']} (PO #{p['po_id']})",
                        "start": at(today + timedelta(days=int(p["avg_delay_days"]) + 7), 9), "minutes": 15, "alarm_minutes": 60,
                        "notes": f"Paid on receipt: this supplier averages {p['avg_delay_days']:.1f} days late."})
        return sorted(out, key=lambda e: e["start"])[:5]

    def findings(self, ctx):
        sc, m, run, bal = ctx["scorecard"], ctx["product_a_margin"], ctx["run"], ctx["balance"]
        rows, grid, ch, cur = run["rows"], ctx["payment_plan"], ctx["chosen"], ctx["current_quote"]
        slow, rest = sc[0], sc[1:]
        rest_delay = sum(r["avg_delay_days"] * r["pos"] for r in rest) / sum(r["pos"] for r in rest)
        now = [p for p in rows if p["when"] == "Today"]
        later = [p for p in rows if p["when"] == "After collection"]
        slow_pos = [p for p in rows if p["slow"]]
        overdue = sum(r["amount"] for r in ctx["receivables"])
        saving = max(cur["total_cost"] - ch["total_cost"], 0.0)
        headline = ((f"Best quote for Product A: {ch['supplier']}, ${saving:,.0f} cheaper all-in than {cur['supplier']} once lost sales are counted. "
                     if ch is not cur else f"{cur['supplier']} is already the best quote for Product A. ")
                    + f"{len(now)} payments (${run['today_total']:,.0f}) fit the ${bal['available']:,.0f} in PayPal and capture "
                    f"${run['discount_captured']:,.0f} in early-pay discounts. "
                    + (f"{len(later)} more (${run['after_collect']:,.0f}) wait for ${run['expected']:,.0f} of expected collections. " if later else "")
                    + (f"Chase {len(run['asks'])} overdue invoices first. " if run["asks"] and later else "")
                    + f"{slow['supplier']} is {slow['avg_delay_days']:.1f} days late on average: its {len(slow_pos)} open PO"
                    f"{'s are' if len(slow_pos) != 1 else ' is'} held until delivery.")
        actions = []
        for p in now[:2]:
            new = p["po_id"] == "NEW"
            actions.append({"id": f"payout-new-{p['supplier_id']}" if new else f"payout-po{p['po_id']}", "kind": "payout",
                            "label": f"Pay {ch['deposit_pct']:g}% deposit to {p['supplier']} (new Product A order)" if new else f"Pay PO #{p['po_id']} ({p['supplier']})",
                            "amount": p["net"], "currency": "USD", "recipient": p["supplier"], "email": email("supplier", p["supplier_id"]),
                            "source": f"New order: {ch['units']} units at ${ch['unit_price']:.2f}" if new else f"Purchase order #{p['po_id']} - {p['product']}",
                            "why": p["why"] + (f" Sandbox demo scale {config.PAYPAL_DEMO_SCALE:g}: PayPal sends ${p['net'] * config.PAYPAL_DEMO_SCALE:,.2f}."
                                               if config.PAYPAL_DEMO_SCALE != 1 else "")})
        if run["asks"]:
            a = run["asks"][0]
            actions.append({"id": f"collect-{a['invoice_id']}", "kind": "invoice_reminder", "label": f"Request payment from {a['customer']}",
                            "amount": a["amount"], "currency": "USD", "recipient": a["customer"], "email": email("ap.customer", a["customer_id"]),
                            "source": f"Invoice #{a['invoice_id']} ({a['days_overdue']}d overdue)",
                            "why": "Largest overdue invoice; its cash funds the payments waiting on collection."})
        actions.append({"id": "switch-draft", "kind": "draft", "label": f"Draft: move Product A volume from {slow['supplier']} to {ch['supplier']}",
                        "amount": 0, "currency": "USD", "recipient": "Procurement lead", "source": "quote comparison",
                        "why": "Stock is below forecast demand and the current supplier is the slowest."})
        f = Findings(
            self.name, "Cash-aware procurement", headline,
            [kpi("PayPal cash available", bal["available"], "$"), kpi("Open supplier POs", sum(p["amount"] for p in rows if p["po_id"] != "NEW"), "$"),
             kpi("Payable today", run["today_total"], "$", "good"), kpi("Early-pay discounts captured", run["discount_captured"], "$", "good"),
             kpi("Saved by switching supplier", saving, "$", "good"), kpi("Overdue from customers", overdue, "$", "bad"),
             kpi("Slowest supplier delay", slow["avg_delay_days"], "d", "bad"), kpi("Other suppliers delay", rest_delay, "d")],
            {"payment_plan": grid, "cash_stages": run["stages"], "quotes": ctx["quotes"], "open_pos": rows, "scorecard": sc,
             "product_a_margin": m, "delays": sc[:12]},
            [{"type": "stacked-column", "source": "quotes", "title": "Quote cost: price plus lost sales ($)", "x": "supplier",
              "y": ["landed_cost", "lost_margin"]},
             {"type": "column", "source": "cash_stages", "title": "PayPal cash after each stage ($)", "x": "stage", "y": ["cash_after"]},
             {"type": "bar", "source": "delays", "title": "Average delivery delay (days)", "x": "supplier", "y": ["avg_delay_days"]},
             {"type": "line", "source": "product_a_margin", "title": "Product A: profit per unit", "x": "month", "y": ["profit_per_unit", "purchase_cost"]},
             {"type": "grid", "source": "payment_plan", "title": "Pay-and-collect plan",
              "cols": ["step", "when", "action", "counterparty", "reference", "amount", "discount_usd", "cash_effect", "why", "source"]},
             {"type": "grid", "source": "quotes", "title": "Supplier quotes ranked by real cost",
              "cols": ["rank", "supplier", "current", "unit_price", "lead_days", "history", "stockout_days", "landed_cost", "lost_margin", "total_cost", "deposit"]},
             {"type": "grid", "source": "scorecard", "title": "Supplier scorecard",
              "cols": ["supplier", "country", "pos", "avg_delay_days", "on_time_pct", "reliability_score", "spend"]}],
            actions,
            [f"Quotes came from: {ctx['quotes_source']}. Lost sales = days of stock-out x daily demand x margin; a supplier with no history is assumed {ASSUMED_NEW_DELAY:g} days late.",
             f"Balance source: {bal['source']}. Collections assume {COLLECT_PCT:.0%} of each overdue invoice arrives.",
             f"{RESERVE_PCT:.0%} of cash is kept in reserve. Switching suppliers needs requalification; check capacity before moving volume."],
            self.lineage(ctx))
        deadlines = self.deadlines(ctx, now, later, run)
        if deadlines:
            f.actions.append({"id": "calendar-deadlines", "kind": "calendar", "label": f"Put {len(deadlines)} payment deadlines on your Calendar, with alarms",
                              "amount": 0, "currency": "USD", "recipient": "Calendar", "source": "pay-and-collect plan",
                              "why": "; ".join(d["title"] for d in deadlines[:3]) + ("..." if len(deadlines) > 3 else ""), "events": deadlines})
        if ctx.get("research_log"):  # several sites were read: show what was found, and ask for the quotes that have no price
            f.tables["research_log"] = ctx["research_log"]
            f.widgets.insert(4, {"type": "grid", "source": "research_log", "title": "Supplier sites BizOS read in Chrome",
                                 "cols": ["site", "country", "unit_price", "moq", "lead_days", "terms", "status"]})
            f.kpis.insert(0, kpi("Supplier sites read", len(ctx["research_log"])))
        for u in ctx.get("unpriced", []):
            f.actions.append({"id": "rfq-" + re.sub(r"\W+", "-", u["supplier"].lower()).strip("-"), "kind": "draft",
                              "label": f"Request a quote from {u['supplier']}", "amount": 0, "currency": "USD", "recipient": u["supplier"],
                              "source": u.get("url") or "supplier site",
                              "why": f"{u['supplier']} publishes no price (MOQ {u['moq']}, {u['lead_days']}d lead): ask before ranking it."})
        return f


# ---------------------------------------------------------------- Sales
@register
class Sales(Flow):
    name, team, goal = "sales", "Sales", "Which accounts need attention?"
    keywords = ("customer", "account", "crm", "salesforce", "hubspot", "deal", "overdue", "discount")
    steps = (("Find overdue accounts", "overdue"), ("Measure discount leakage", "leakage"),
             ("Rank top products by segment", "top"))

    def overdue(self, ctx):
        return {"accounts": q("""SELECT c.customer_id, c.name AS customer, c.segment, c.country,
                    SUM(i.status='open') open_invoices, SUM(i.status='overdue') overdue_invoices,
                    ROUND(SUM(CASE WHEN i.status='overdue' THEN i.amount ELSE 0 END),2) overdue_amount,
                    ROUND(SUM(CASE WHEN i.status!='paid' THEN i.amount ELSE 0 END),2) outstanding
                    FROM invoices i JOIN customers c USING(customer_id) GROUP BY c.customer_id
                    HAVING outstanding > 0 ORDER BY overdue_amount DESC, outstanding DESC""")}

    def leakage(self, ctx):
        return {"discounts": q("""SELECT c.segment, ROUND(SUM(oi.quantity*p.list_price*oi.discount_pct/100.0),2) discount_given,
                    ROUND(AVG(oi.discount_pct),1) avg_discount_pct FROM order_items oi JOIN orders o USING(order_id)
                    JOIN customers c USING(customer_id) JOIN products p USING(product_id) GROUP BY c.segment ORDER BY discount_given DESC""")}

    def top(self, ctx):
        return {"top_products": q("""SELECT segment, product, revenue FROM (
                    SELECT c.segment, p.name AS product, ROUND(SUM(oi.quantity*oi.unit_price),2) revenue,
                    ROW_NUMBER() OVER (PARTITION BY c.segment ORDER BY SUM(oi.quantity*oi.unit_price) DESC) rk
                    FROM order_items oi JOIN orders o USING(order_id) JOIN customers c USING(customer_id)
                    JOIN products p USING(product_id) GROUP BY c.segment, p.product_id) WHERE rk<=5""")}

    def findings(self, ctx):
        a, d = ctx["accounts"], ctx["discounts"]
        top = a[0]
        overdue = sum(r["overdue_amount"] for r in a)
        inv = q("""SELECT invoice_id, amount, due_on FROM invoices WHERE customer_id=? AND status='overdue'
                   ORDER BY amount DESC LIMIT 1""", top["customer_id"])[0]
        return Findings(
            self.name, "Account health",
            f"{sum(r['overdue_invoices'] for r in a)} invoices are overdue (${overdue:,.0f}). {top['customer']} owes the most. "
            f"Discounts gave away ${sum(r['discount_given'] for r in d):,.0f}.",
            [kpi("Overdue amount", overdue, "$", "bad"), kpi("Accounts with balance", len(a)),
             kpi("Discount given", sum(r["discount_given"] for r in d), "$", "bad"),
             kpi("Avg discount", sum(r["avg_discount_pct"] for r in d) / len(d), "%")],
            {"accounts": a, "discounts": d, "top_products": ctx["top_products"]},
            [{"type": "column", "source": "discounts", "title": "Discount given by segment", "x": "segment", "y": ["discount_given"]},
             {"type": "bar", "source": "top_products", "title": "Top products by segment", "x": "product", "y": ["revenue"], "series": "segment"},
             {"type": "grid", "source": "accounts", "title": "Accounts with open balances",
              "cols": ["customer", "segment", "country", "open_invoices", "overdue_invoices", "overdue_amount", "outstanding"]}],
            [{"id": f"remind-{inv['invoice_id']}", "kind": "invoice_reminder", "label": f"Send reminder to {top['customer']}",
              "amount": inv["amount"], "currency": "USD", "recipient": top["customer"], "email": email("ap.customer", top["customer_id"]),
              "source": f"Invoice #{inv['invoice_id']} (due {inv['due_on']})", "why": "Largest overdue balance."}],
            ["Enterprise accounts have 45-day terms; confirm before escalating."])
