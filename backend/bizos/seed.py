"""Deterministic mock company database (read-only at run time).

`python -m bizos.seed [path]` writes it; `data.py` builds it on first use when it is missing. Each department has a
planted story the flows (and tests/test_flows.py) must rediscover: a competitor undercutting 12 products, short and
duplicate payments, a Paid Social ROAS drop, a compute cost spike, 13 products below forecast, one slow supplier
(id 7) squeezing Product A, and 40 overdue invoices. Procurement also carries payment terms (early-pay discounts) and
unpaid purchase orders, so a pay run can be planned against cash.
"""
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

END = date(2026, 11, 7)  # last day of data; every flow reads relative to MAX(date)

SCHEMA = """
CREATE TABLE suppliers(supplier_id INTEGER PRIMARY KEY, name TEXT, country TEXT, lead_time_days INTEGER,
  reliability_score REAL, payment_terms_days INTEGER, early_pay_days INTEGER, early_pay_discount_pct REAL);
CREATE TABLE products(product_id INTEGER PRIMARY KEY, sku TEXT, name TEXT, supplier_id INTEGER, list_price REAL);
CREATE TABLE product_costs(product_id INTEGER, month TEXT, purchase_cost REAL, manufacturing_cost REAL, storage_cost REAL);
CREATE TABLE competitors(competitor_id INTEGER PRIMARY KEY, name TEXT, website TEXT);
CREATE TABLE competitor_prices(competitor_id INTEGER, product_id INTEGER, captured_on TEXT, price REAL);
CREATE TABLE purchase_orders(po_id INTEGER PRIMARY KEY, supplier_id INTEGER, product_id INTEGER, quantity INTEGER,
  unit_cost REAL, status TEXT, ordered_on TEXT, payment_due_on TEXT, paid_on TEXT);
CREATE TABLE shipments(shipment_id INTEGER PRIMARY KEY, po_id INTEGER, shipped_on TEXT, promised_on TEXT,
  delivered_on TEXT, delay_days INTEGER);
CREATE TABLE inventory_snapshots(product_id INTEGER, month TEXT, on_hand INTEGER, forecast_demand INTEGER, reorder_point INTEGER);
CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, name TEXT, segment TEXT, country TEXT);
CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date TEXT, status TEXT);
CREATE TABLE order_items(item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, quantity INTEGER,
  unit_price REAL, discount_pct REAL);
CREATE TABLE invoices(invoice_id INTEGER PRIMARY KEY, customer_id INTEGER, issued_on TEXT, due_on TEXT, amount REAL, status TEXT);
CREATE TABLE payments(payment_id INTEGER PRIMARY KEY, invoice_id INTEGER, amount REAL, status TEXT, failure_reason TEXT, paid_at TEXT);
CREATE TABLE marketing_campaigns(campaign_id INTEGER PRIMARY KEY, name TEXT, channel TEXT, budget REAL);
CREATE TABLE marketing_daily_metrics(metric_id INTEGER PRIMARY KEY, campaign_id INTEGER, date TEXT, spend REAL, revenue REAL, clicks INTEGER);
CREATE TABLE cloud_costs(date TEXT, service TEXT, cost_usd REAL);
CREATE TABLE web_funnel_daily(date TEXT, visits INTEGER, signups INTEGER, orders INTEGER);
CREATE TABLE support_tickets(ticket_id INTEGER PRIMARY KEY, customer_id INTEGER, opened_on TEXT, topic TEXT, status TEXT);
CREATE TABLE returns(return_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, quantity INTEGER, reason TEXT, returned_on TEXT);
CREATE TABLE subscriptions(subscription_id INTEGER PRIMARY KEY, customer_id INTEGER, plan TEXT, started_on TEXT, status TEXT);
CREATE TABLE warehouses(warehouse_id INTEGER PRIMARY KEY, name TEXT, city TEXT);
CREATE TABLE employees(employee_id INTEGER PRIMARY KEY, name TEXT, team TEXT, hired_on TEXT);
CREATE TABLE departments(department_id INTEGER PRIMARY KEY, name TEXT, monthly_budget REAL);
"""

SUPPLIERS = [  # name, country, lead_time, reliability, terms, early_days, early_pct
    ("Northwind Components", "Germany", 21, 0.96, 30, 10, 2.0), ("Kestrel Packaging", "Poland", 14, 0.94, 30, 10, 2.0),
    ("Bluepeak Textiles", "Portugal", 28, 0.92, 45, 10, 3.0), ("Orchid Ceramics", "Vietnam", 35, 0.91, 30, 14, 2.5),
    ("Summit Steelworks", "Turkey", 30, 0.93, 45, 10, 2.0), ("Meridian Plastics", "Mexico", 18, 0.95, 30, 10, 1.5),
    ("Harbor Ridge Trading", "China", 38, 0.71, 30, 0, 0.0),  # id 7: the slow, pricey one
    ("Alder Glassworks", "Czechia", 25, 0.9, 30, 10, 2.0), ("Tidewater Imports", "Indonesia", 33, 0.89, 60, 15, 3.0),
    ("Pinecrest Woodcraft", "Canada", 16, 0.97, 30, 10, 2.0),
]
PRODUCTS = ["Product A", "Ceramic Mug", "Steel Water Bottle", "Linen Tote", "Glass Storage Jar", "Bamboo Cutting Board",
            "Cotton Throw", "Pour-Over Kettle", "Walnut Tray", "Enamel Pot", "Wool Blanket", "Copper Whisk", "Soy Candle",
            "Stoneware Bowl", "Canvas Apron", "Oak Spice Rack", "Cast Iron Pan", "Beeswax Wrap", "Felt Coaster Set",
            "Glass Carafe", "Hemp Rug", "Rattan Basket", "Steel Lunchbox", "Brass Hooks", "Terracotta Planter",
            "Silicone Lid Set", "Paper Notebook", "Linen Napkins", "Salt Cellar", "Teak Spoon Set", "Olive Wood Board",
            "Mesh Strainer", "Wall Shelf", "Ceramic Vase", "Tea Infuser", "Cotton Towels", "Metal Trivet", "Pepper Mill",
            "Bread Bin", "Lantern"]
CHANNELS = ["Paid Search", "Paid Social", "Email", "Affiliate"]
SERVICES = ["compute", "storage", "database", "network", "cdn"]
FIRST = ["Acme", "Birch", "Cobalt", "Delta", "Ember", "Fjord", "Granite", "Harbor", "Iris", "Juniper", "Kite", "Lumen",
         "Maple", "Nova", "Onyx", "Pine", "Quartz", "Raven", "Sable", "Tundra", "Umber", "Vista", "Willow", "Zephyr"]
LAST = ["Foods", "Studios", "Retail", "Labs", "Goods", "Trading", "Works", "Group", "Supply", "Kitchens", "Home", "Market"]


def d(day: date) -> str:
    return day.isoformat()


def build(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    rnd = random.Random(2026)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    many = lambda table, rows: con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows) if rows else None

    # ---- suppliers, products, costs
    many("suppliers", [(i + 1, *s) for i, s in enumerate(SUPPLIERS)])
    products, prices = [], {}
    for pid, name in enumerate(PRODUCTS, 1):
        price = 120.0 if pid == 1 else round(rnd.uniform(14, 95), 2)
        supplier = 7 if pid in (1, 9, 15, 22) else {7: 3, 0: 10}.get(pid % 10, pid % 10)
        products.append((pid, f"SKU-{1000 + pid}", name, supplier, price))
        prices[pid] = price
    many("products", products)
    months = [(date(2025, 12, 1) + timedelta(days=31 * k)).strftime("%Y-%m") for k in range(12)]
    costs = []
    for pid, _, _, _, price in products:
        purchase, make, store = (52.0, 18.0, 11.6) if pid == 1 else (price * .38, price * .17, price * .07)
        for k, m in enumerate(months):
            drift = (6.4 * k / 11) if pid == 1 else rnd.uniform(-.01, .02) * purchase  # Product A: supplier 7 keeps raising its price
            costs.append((pid, m, round(purchase + drift, 2), round(make, 2), round(store, 2)))
    many("product_costs", costs)

    # ---- competitors: Lumen Supply undercuts exactly 12 products by 12-20%
    many("competitors", [(1, "Lumen Supply", "www.competitor1.example"), (2, "Hearth & Co", "www.competitor2.example"),
                         (3, "Northline Goods", "www.competitor3.example")])
    undercut = set(rnd.sample(range(1, 41), 12))
    cp = []
    for snap, drift in ((END - timedelta(days=7), 0.0), (END, 1.0)):
        for pid, price in prices.items():
            g = rnd.uniform(-.20, -.12) * drift if pid in undercut else rnd.uniform(-.05, .08)
            cp.append((1, pid, d(snap), round(price * (1 + g), 2)))
            for cid in (2, 3):
                cp.append((cid, pid, d(snap), round(price * (1 + rnd.uniform(-.04, .1)), 2)))
    many("competitor_prices", cp)

    # ---- inventory: 13 products below forecast this month
    low = set(rnd.sample(range(1, 41), 13))
    inv = []
    for k in range(4, -1, -1):
        month = (date(2026, 11, 1) - timedelta(days=31 * k)).strftime("%Y-%m")
        for pid in range(1, 41):
            forecast = rnd.randint(80, 400)
            rp = int(forecast * .3)
            on_hand = (int(forecast * rnd.uniform(.25, .8)) if pid in low else int(forecast * rnd.uniform(1.1, 2.0))) if k == 0 \
                else int(forecast * rnd.uniform(.9, 1.8))
            inv.append((pid, month, on_hand, forecast, rp))
    many("inventory_snapshots", inv)

    # ---- purchase orders + shipments: supplier 7 averages > 5 days late; everyone else is nearly on time
    pos, ships, po_id = [], [], 0
    supplier_of = {p[0]: p[3] for p in products}
    for _ in range(150):
        po_id += 1
        pid = rnd.randint(1, 40)
        if rnd.random() < .22:
            pid = rnd.choice([1, 9, 15, 22])
        sid = supplier_of[pid]
        ordered = END - timedelta(days=rnd.randint(40, 330))
        lead = SUPPLIERS[sid - 1][2]
        delay = rnd.randint(4, 9) if sid == 7 else rnd.choices([0, 1, 2], [.72, .2, .08])[0]
        promised = ordered + timedelta(days=lead)
        qty = rnd.randint(40, 300)
        cost = round(prices[pid] * (.46 if sid == 7 else .38), 2)
        terms = SUPPLIERS[sid - 1][4]
        delivered = promised + timedelta(days=delay)
        pos.append((po_id, sid, pid, qty, cost, "received", d(ordered), d(delivered + timedelta(days=terms - 14)),
                    d(delivered + timedelta(days=terms - 16))))
        ships.append((po_id, po_id, d(ordered + timedelta(days=3)), d(promised), d(delivered), delay))
    # open POs: still in transit, supplier invoice received (shipped_on = invoice date), payment not sent yet.
    # (product, days since the supplier invoice): early-pay windows are 10-15 days, so some discounts expire in days.
    open_spec = [(1, 4), (9, 6), (2, 9), (4, 3), (5, 7), (6, 8), (7, 2), (8, 11), (10, 5), (11, 9), (12, 12), (13, 6), (14, 1), (3, 8)]
    for pid, age in open_spec:
        po_id += 1
        sid = supplier_of[pid]
        qty = rnd.randint(60, 220)
        cost = round(prices[pid] * (.46 if sid == 7 else .38), 2)
        shipped = END - timedelta(days=age)
        ordered = shipped - timedelta(days=3)
        promised = ordered + timedelta(days=SUPPLIERS[sid - 1][2])
        pos.append((po_id, sid, pid, qty, cost, "in_transit", d(ordered), d(shipped + timedelta(days=SUPPLIERS[sid - 1][4])), None))
        ships.append((po_id, po_id, d(shipped), d(promised), None, None))
    many("purchase_orders", pos)
    many("shipments", ships)

    # ---- customers, orders, items
    segs = ["Enterprise"] * 30 + ["Mid-market"] * 70 + ["SMB"] * 120
    customers = [(i + 1, f"{rnd.choice(FIRST)} {rnd.choice(LAST)} {i + 1}", seg, rnd.choice(["US", "US", "DE", "UK", "CA", "FR"]))
                 for i, seg in enumerate(segs)]
    many("customers", customers)
    orders, items, oid, iid = [], [], 0, 0
    for _ in range(2500):
        oid += 1
        c = rnd.choice(customers)
        orders.append((oid, c[0], d(END - timedelta(days=rnd.randint(0, 179))), "cancelled" if rnd.random() < .04 else "completed"))
        for _ in range(rnd.randint(1, 4)):
            iid += 1
            pid = rnd.randint(1, 40)
            disc = round(rnd.uniform(8, 18) if c[2] == "Enterprise" else rnd.uniform(0, 9), 1)
            items.append((iid, oid, pid, rnd.randint(1, 12), round(prices[pid] * (1 - disc / 100), 2), disc))
    many("orders", orders)
    many("order_items", items)

    # ---- invoices and payments: 60 short, 15 duplicate, 60 open + 40 overdue, 225 matched
    plan = ["short"] * 60 + ["duplicate"] * 15 + ["open"] * 60 + ["overdue"] * 40 + ["matched"] * 225
    rnd.shuffle(plan)
    invoices, payments, pay_id = [], [], 0
    first_pay = END - timedelta(days=119)
    for inv_id, kind in enumerate(plan, 1):
        c = rnd.choice(customers)
        terms = 45 if c[2] == "Enterprise" else 30
        amount = round(rnd.uniform(1800, 4200) if kind == "overdue" and rnd.random() < .5 else rnd.uniform(300, 2400), 2)
        if kind == "open":
            issued = END - timedelta(days=rnd.randint(0, terms - 2))
        elif kind == "overdue":
            issued = END - timedelta(days=terms + rnd.randint(3, 50))
        else:
            issued = END - timedelta(days=rnd.randint(8, 150))
        due = issued + timedelta(days=terms)
        invoices.append((inv_id, c[0], d(issued), d(due), amount, {"open": "open", "overdue": "overdue"}.get(kind, "paid")))
        if kind in ("open", "overdue"):
            continue
        paid_at = min(END, max(first_pay, issued + timedelta(days=rnd.randint(2, terms))))
        paid_amt = round(amount * rnd.uniform(.82, .96), 2) if kind == "short" else amount
        pay_id += 1
        payments.append((pay_id, inv_id, paid_amt, "COMPLETED", None, d(paid_at)))
        if kind == "duplicate":
            pay_id += 1
            payments.append((pay_id, inv_id, amount, "COMPLETED", None, d(min(END, paid_at + timedelta(days=rnd.randint(0, 2))))))
    many("invoices", invoices)
    # A processor issue: exactly 38 completed and 41 failed attempts in the last 21 days (51.9% failed), ~3% failed before.
    cut = END - timedelta(days=20)
    issued_of = {i[0]: date.fromisoformat(i[2]) for i in invoices}
    recent = [k for k, p in enumerate(payments) if date.fromisoformat(p[5]) >= cut]
    older = [k for k, p in enumerate(payments) if date.fromisoformat(p[5]) < cut]
    rnd.shuffle(recent), rnd.shuffle(older)
    movable = [k for k in recent if issued_of[payments[k][1]] < cut - timedelta(days=1)]
    for k in movable[max(0, 38 - (len(recent) - len(movable))):]:  # too many: move to before the window (not before the invoice)
        p = payments[k]
        payments[k] = (*p[:5], d(max(issued_of[p[1]] + timedelta(days=1), cut - timedelta(days=rnd.randint(1, 15)))))
    for k in older:  # too few: pull recent-eligible payments forward
        if sum(date.fromisoformat(p[5]) >= cut for p in payments) >= 38:
            break
        p = payments[k]
        if issued_of[p[1]] <= END - timedelta(days=21):
            payments[k] = (*p[:5], d(cut + timedelta(days=rnd.randint(0, 20))))
    n_recent = sum(date.fromisoformat(p[5]) >= cut for p in payments)
    n_old = len(payments) - n_recent
    assert n_recent == 38, n_recent
    old_fail = round(n_old * .03 / .97)
    for n, window, reasons in ((41, (0, 20), ["PROCESSOR_TIMEOUT"] * 3 + ["BANK_DECLINED", "RISK_REVIEW"]),
                               (old_fail, (21, 118), ["INSUFFICIENT_FUNDS", "CARD_EXPIRED", "BANK_DECLINED"])):
        for _ in range(n):
            pay_id += 1
            payments.append((pay_id, rnd.randint(1, len(plan)), round(rnd.uniform(300, 2000), 2), "FAILED", rnd.choice(reasons),
                             d(END - timedelta(days=rnd.randint(*window)))))
    many("payments", payments)

    # ---- marketing: Paid Social ROAS collapses in the last 20 days
    many("marketing_campaigns", [(i + 1, f"{CHANNELS[i // 2]} {'Always-on' if i % 2 else 'Launch'}", CHANNELS[i // 2],
                                  round(rnd.uniform(8, 20) * 1000, 2)) for i in range(8)])
    base = {"Paid Search": 3.6, "Paid Social": 4.2, "Email": 6.5, "Affiliate": 3.9}
    metrics, mid = [], 0
    for cid in range(1, 9):
        ch = CHANNELS[(cid - 1) // 2]
        for k in range(120):
            day = END - timedelta(days=119 - k)
            roas = base[ch] * (rnd.uniform(.94, 1.06)) * (0.55 if ch == "Paid Social" and day >= END - timedelta(days=19) else 1.0)
            spend = round(rnd.uniform(180, 420), 2)
            mid += 1
            metrics.append((mid, cid, d(day), spend, round(spend * roas, 2), int(spend * rnd.uniform(.8, 1.4))))
    many("marketing_daily_metrics", metrics)

    # ---- engineering: compute +65% over the last 14 days
    cloud = []
    basecost = {"compute": 900, "storage": 260, "database": 520, "network": 180, "cdn": 140}
    for k in range(90):
        day = END - timedelta(days=89 - k)
        for s in SERVICES:
            v = basecost[s] * rnd.uniform(.97, 1.03) * (1.65 if s == "compute" and day >= END - timedelta(days=13) else 1.0)
            cloud.append((d(day), s, round(v, 2)))
    many("cloud_costs", cloud)

    # ---- the rest of the company
    many("web_funnel_daily", [(d(END - timedelta(days=119 - k)), (v := rnd.randint(2200, 3400)), int(v * rnd.uniform(.03, .05)),
                               int(v * rnd.uniform(.012, .02))) for k in range(120)])
    many("support_tickets", [(i, rnd.randint(1, 220), d(END - timedelta(days=rnd.randint(0, 90))),
                              rnd.choice(["billing", "shipping", "defect", "account"]), rnd.choice(["open", "closed", "closed"]))
                             for i in range(1, 301)])
    many("returns", [(i, rnd.randint(1, 2500), rnd.randint(1, 40), rnd.randint(1, 3),
                      rnd.choice(["damaged", "wrong item", "changed mind"]), d(END - timedelta(days=rnd.randint(0, 90))))
                     for i in range(1, 121)])
    many("subscriptions", [(i, rnd.randint(1, 220), rnd.choice(["monthly box", "quarterly box"]),
                            d(END - timedelta(days=rnd.randint(10, 400))), rnd.choice(["active", "active", "cancelled"]))
                           for i in range(1, 151)])
    many("warehouses", [(1, "Main DC", "Rotterdam"), (2, "East Hub", "Newark"), (3, "West Hub", "Reno")])
    many("employees", [(i, f"{rnd.choice(FIRST)} {rnd.choice(LAST)[:-1]}", rnd.choice(["Ops", "Sales", "Marketing", "Finance", "Eng"]),
                        d(date(2020, 1, 1) + timedelta(days=rnd.randint(0, 2200)))) for i in range(1, 41)])
    many("departments", [(i, n, b) for i, (n, b) in enumerate([("Executive", 42000), ("Finance", 38000), ("Marketing", 96000),
                         ("Engineering", 184000), ("Operations", 121000), ("Procurement", 64000), ("Sales", 88000)], 1)])
    con.commit()
    con.close()
    return path


if __name__ == "__main__":
    from . import config
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else config.DB_PATH)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
