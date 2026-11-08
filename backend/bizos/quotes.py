"""Sample sourcing marketplace for the procurement demo.

`render_page()` is the page served at /demo/sourcing (the Chrome extension reads it like any website);
`parse_quotes()` turns the extension's page digest back into rows; `QUOTES` is the same data, used when no
Chrome page is connected. One source of truth, so the page and the fallback can never disagree.
"""
import html
import re

PRODUCT = "Product A (ceramic pour-over set)"
QUOTES = [  # supplier, country, unit_price, moq, lead_days, rating, terms, deposit_pct
    {"supplier": "Harbor Ridge Trading", "country": "China", "unit_price": 55.20, "moq": 100, "lead_days": 38, "rating": 3.4,
     "terms": "net 30", "deposit_pct": 0.0},
    {"supplier": "Pinecrest Woodcraft", "country": "Canada", "unit_price": 58.40, "moq": 100, "lead_days": 16, "rating": 4.8,
     "terms": "2/10 net 30", "deposit_pct": 30.0},
    {"supplier": "Northwind Components", "country": "Germany", "unit_price": 56.90, "moq": 150, "lead_days": 21, "rating": 4.7,
     "terms": "2/10 net 30", "deposit_pct": 30.0},
    {"supplier": "Orchid Ceramics", "country": "Vietnam", "unit_price": 52.10, "moq": 200, "lead_days": 35, "rating": 4.2,
     "terms": "2.5/14 net 30", "deposit_pct": 25.0},
    {"supplier": "Lakeside Ceramics Co.", "country": "Vietnam", "unit_price": 49.90, "moq": 250, "lead_days": 45, "rating": 3.9,
     "terms": "net 15", "deposit_pct": 50.0},
]
HEADERS = ["Supplier", "Country", "Unit price", "MOQ", "Lead time (days)", "Rating", "Terms", "Deposit", "Action"]


def _cells(q: dict) -> list[str]:
    return [q["supplier"], q["country"], f"${q['unit_price']:.2f}", str(q["moq"]), str(q["lead_days"]), f"{q['rating']:.1f}",
            q["terms"], f"{q['deposit_pct']:g}%"]


def render_page(qty: int = 188) -> str:
    rows = "\n".join(
        "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in _cells(q)) +
        f'<td><button type="button" class="pick" aria-label="Select quote: {html.escape(q["supplier"])}" '
        f'data-s="{html.escape(q["supplier"])}" data-d="{q["deposit_pct"]:g}" data-p="{q["unit_price"]}">Select quote</button></td></tr>'
        for q in QUOTES)
    head = "".join(f"<th>{h}</th>" for h in HEADERS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Sourcing Hub: {PRODUCT}</title>
<style>
 body {{ font: 15px/1.45 -apple-system, system-ui, sans-serif; margin: 0; background: #f5f6f8; color: #1b1f24; }}
 header {{ background: #0b2a4a; color: #fff; padding: 14px 32px; display: flex; justify-content: space-between; align-items: center; }}
 header b {{ font-size: 18px; }} header span {{ font-size: 12px; opacity: .8; border: 1px solid #ffffff55; padding: 3px 8px; border-radius: 10px; }}
 main {{ max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
 .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 3px #0002; padding: 20px 24px; margin-bottom: 20px; }}
 h1 {{ font-size: 22px; margin: 0 0 4px; }} p.sub {{ margin: 0 0 16px; color: #5b6573; }}
 table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid #e6e9ee; }}
 th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #5b6573; }}
 tr.picked td {{ background: #e8f3ff; }}
 button {{ font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid #0b2a4a; background: #fff; color: #0b2a4a; cursor: pointer; }}
 button.primary {{ background: #0b2a4a; color: #fff; }}
 #draft {{ display: none; }} #draft.on {{ display: block; }} #draft input {{ width: 80px; padding: 5px; }}
 #done {{ margin-top: 10px; color: #0a7a3d; font-weight: 600; }}
</style></head><body>
<header><b>Sourcing Hub</b><span>Sample marketplace (demo data)</span></header>
<main>
 <div class="card"><h1>Quotes for {PRODUCT}</h1>
  <p class="sub">Stock is below forecast demand. {len(QUOTES)} suppliers quoted for about {qty} units.</p>
  <table><caption hidden>Supplier quotes</caption><thead><tr>{head}</tr></thead><tbody>
{rows}
  </tbody></table></div>
 <div class="card" id="draft"><h1>Draft purchase order</h1>
  <p class="sub" id="what"></p>
  <label>Quantity <input id="qty" type="number" value="{qty}" aria-label="Quantity"></label>
  <button type="button" class="primary" id="go" aria-label="Confirm order">Confirm order</button>
  <div id="done"></div></div>
</main>
<script>
 document.querySelectorAll('.pick').forEach(b => b.addEventListener('click', () => {{
   document.querySelectorAll('tr').forEach(r => r.classList.remove('picked')); b.closest('tr').classList.add('picked');
   document.getElementById('what').textContent = 'Selected ' + b.dataset.s + ' at $' + b.dataset.p + ' per unit, ' + b.dataset.d + '% deposit.';
   document.getElementById('draft').classList.add('on'); document.getElementById('done').textContent = '';
 }}));
 document.getElementById('go').addEventListener('click', () => {{
   document.getElementById('done').textContent = 'Draft order saved in this demo. Nothing was sent or paid.';
 }});
</script></body></html>"""


def _num(text: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else 0.0


def parse_quotes(dom: str) -> list[dict]:
    """Quotes from the extension's page digest ("table: cell ; cell / cell ; cell ..."), or [] if no quote table is on the page."""
    for line in (dom or "").splitlines():
        if not line.startswith("table:"):
            continue
        rows = [[c.strip() for c in r.split(" ; ")] for r in line[len("table:"):].strip().split(" / ")]
        head = [h.lower() for h in rows[0]]
        if "supplier" not in head or not any(h.startswith("unit price") for h in head):
            continue
        col = lambda name: next(i for i, h in enumerate(head) if h.startswith(name))
        out = []
        for r in rows[1:]:
            if len(r) < len(head):
                continue
            out.append({"supplier": r[col("supplier")], "country": r[col("country")] if "country" in head else "",
                        "unit_price": _num(r[col("unit price")]), "moq": int(_num(r[col("moq")])) if "moq" in head else 1,
                        "lead_days": int(_num(r[col("lead")])), "rating": _num(r[col("rating")]) if "rating" in head else 0.0,
                        "terms": r[col("terms")] if "terms" in head else "", "deposit_pct": _num(r[col("deposit")]) if "deposit" in head else 0.0})
        if out:
            return out
    return []


# ---------------------------------------------------------------- multi-site marketplace (research demo)
SITES = [  # four supplier sites, each laid out differently, so a page's quote has to be read, not looked up
    {"slug": "pinecrest", "supplier": "Pinecrest Woodcraft", "country": "Canada", "layout": "table", "unit_price": 58.40, "moq": 100,
     "lead_days": 16, "rating": 4.8, "terms": "2/10 net 30", "deposit_pct": 30.0, "blurb": "Family-run studio, ships from Vancouver"},
    {"slug": "northwind", "supplier": "Northwind Components", "country": "Germany", "layout": "cards", "unit_price": 56.90, "moq": 150,
     "lead_days": 21, "rating": 4.7, "terms": "2/10 net 30", "deposit_pct": 30.0, "blurb": "Precision ceramics from Saxony"},
    {"slug": "lakeside", "supplier": "Lakeside Ceramics Co.", "country": "Vietnam", "layout": "prose", "unit_price": 49.90, "moq": 250,
     "lead_days": 45, "rating": 3.9, "terms": "net 15", "deposit_pct": 50.0, "blurb": "New factory, volume pricing"},
    {"slug": "orchid", "supplier": "Orchid Ceramics", "country": "Vietnam", "layout": "request", "unit_price": None, "moq": 200,
     "lead_days": 35, "rating": 4.2, "terms": "2.5/14 net 30", "deposit_pct": 25.0, "blurb": "Hand-finished, price on request"},
]
_CSS = """body{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#f5f6f8;color:#1b1f24}
header{background:#0b2a4a;color:#fff;padding:14px 32px;display:flex;justify-content:space-between;align-items:center}
header b{font-size:18px}header span{font-size:12px;opacity:.8;border:1px solid #ffffff55;padding:3px 8px;border-radius:10px}
main{max-width:1000px;margin:24px auto;padding:0 24px}.card{background:#fff;border-radius:10px;box-shadow:0 1px 3px #0002;padding:20px 24px;margin-bottom:18px}
h1{font-size:24px;margin:0 0 4px}p.sub{margin:0 0 14px;color:#5b6573}a.btn,button{font:inherit;padding:7px 14px;border-radius:6px;border:1px solid #0b2a4a;background:#fff;color:#0b2a4a;cursor:pointer;text-decoration:none;display:inline-block}
button.primary{background:#0b2a4a;color:#fff}table{border-collapse:collapse;width:100%}td{padding:9px 6px;border-bottom:1px solid #e6e9ee}td:first-child{color:#5b6573;width:38%}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.k{background:#f2f5f9;border-radius:8px;padding:12px}.k small{display:block;color:#5b6573}.k div{font-size:20px;font-weight:600}
.row{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e6e9ee;padding:14px 0}.row:last-child{border:0}#draft{display:none}#draft.on{display:block}#done{margin-top:10px;color:#0a7a3d;font-weight:600}"""


def _shell(title: str, body: str, script: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
            f'<header><b>Sourcing Hub</b><span>Sample marketplace (demo data)</span></header><main>{body}</main><script>{script}</script></body></html>')


def render_market() -> str:
    rows = "".join(
        f'<div class="row"><div><b>{html.escape(s["supplier"])}</b> <span style="color:#5b6573">· {s["country"]}</span>'
        f'<div style="color:#5b6573">{html.escape(s["blurb"])}</div></div>'
        f'<a class="btn" href="/demo/s/{s["slug"]}" aria-label="View quote: {html.escape(s["supplier"])}">View quote</a></div>' for s in SITES)
    return _shell("Sourcing Hub: ceramic pour-over sets", f'<div class="card"><h1>Ceramic pour-over sets, bulk</h1>'
                  f'<p class="sub">{len(SITES)} suppliers match. Each publishes its quote on its own page.</p>{rows}</div>')


_PICK = """document.querySelectorAll('.pick').forEach(b=>b.addEventListener('click',()=>{
 document.getElementById('what').textContent='Selected '+b.dataset.s+' at $'+b.dataset.p+' per unit, '+b.dataset.d+'% deposit.';
 document.getElementById('draft').classList.add('on');document.getElementById('done').textContent=''}));
 var g=document.getElementById('go');if(g)g.addEventListener('click',()=>{document.getElementById('done').textContent='Draft order saved in this demo. Nothing was sent or paid.'});"""


def render_supplier(slug: str, qty: int = 188) -> str | None:
    s = next((x for x in SITES if x["slug"] == slug), None)
    if not s:
        return None
    price, lead = s["unit_price"], s["lead_days"]
    weeks = round(lead / 7)
    facts = [("Ships from", s["country"]), ("Unit price", f"${price:.2f}" if price else "Quote on request"), ("Minimum order", f"{s['moq']} units"),
             ("Lead time", f"{lead} days"), ("Payment terms", s["terms"]), ("Deposit", f"{s['deposit_pct']:g}%"), ("Rating", f"{s['rating']:.1f} / 5")]
    if s["layout"] == "table":
        body = "<table>" + "".join(f"<tr><td>{k}</td><td>{html.escape(v)}</td></tr>" for k, v in facts) + "</table>"
    elif s["layout"] == "cards":
        cards = [("Price per unit", f"${price:.2f}"), ("Minimum order", f"{s['moq']} units"), ("Lead time", f"{weeks} weeks ({lead} days)"),
                 ("Terms", s["terms"]), ("Deposit", f"{s['deposit_pct']:g}% deposit"), ("Rating", f"{s['rating']:.1f} / 5")]
        body = f'<p class="sub">Ships from {s["country"]}</p><div class="grid">' + "".join(f'<div class="k"><small>{k}</small><div>{v}</div></div>' for k, v in cards) + "</div>"
    elif s["layout"] == "prose":
        body = (f"<p>We quote by volume. Orders of {s['moq']}+ units are <b>${price:.2f} per piece</b>; smaller runs on request. "
                f"After a {s['deposit_pct']:g}% deposit, production plus sea freight takes about {weeks} weeks ({lead} days). "
                f"Payment terms: {s['terms']}. Ships from {s['country']}. Rated {s['rating']:.1f} / 5 by 212 buyers.</p>")
    else:
        body = (f"<p><b>Quote on request.</b> Send us your quantity and we reply within two days. Minimum order {s['moq']} units. "
                f"Lead time {weeks} weeks ({lead} days). Terms {s['terms']}, {s['deposit_pct']:g}% deposit. Ships from {s['country']}. Rating {s['rating']:.1f} / 5.</p>")
    act = (f'<button type="button" class="pick" aria-label="Select quote: {html.escape(s["supplier"])}" data-s="{html.escape(s["supplier"])}" '
           f'data-d="{s["deposit_pct"]:g}" data-p="{price}">Select quote</button>' if price else
           f'<button type="button" aria-label="Request a quote: {html.escape(s["supplier"])}">Request a quote</button>')
    draft = (f'<div class="card" id="draft"><h1>Draft purchase order</h1><p class="sub" id="what"></p><label>Quantity '
             f'<input id="qty" type="number" value="{qty}" aria-label="Quantity"></label> <button type="button" class="primary" id="go" '
             f'aria-label="Confirm order">Confirm order</button><div id="done"></div></div>')
    page = (f'<div class="card"><p class="sub"><a href="/demo/market" style="color:#0b2a4a">← All suppliers</a></p>'
            f'<h1>{html.escape(s["supplier"])}</h1><p class="sub">{PRODUCT}</p>{body}<p style="margin-top:16px">{act}</p></div>{draft}')
    return _shell(f"{s['supplier']}: quote", page, _PICK)


def extract_quote(snap: dict) -> dict | None:
    """One quote from a supplier page the extension read (headings + text), whatever the layout: table, cards or prose."""
    text = " ".join(str(snap.get(k) or "") for k in ("text",)) or ""
    head = next((h for h in snap.get("headings", []) if h and "purchase order" not in h.lower()), "")
    if not head or not text:
        return None
    find = lambda pat: (m := re.search(pat, text, re.I)) and m
    price = find(r"price[^$\d]{0,30}\$\s?(\d+(?:\.\d+)?)") or find(r"\$\s?(\d+(?:\.\d+)?)\s*(?:per|each|/)")
    days = find(r"\((\d+)\s*days?\)") or find(r"lead time[^\d]{0,30}(\d+)\s*days") or find(r"(\d+)\s*days")
    weeks = None if days else find(r"(\d+(?:\.\d+)?)\s*weeks?")
    moq = find(r"(?:moq|minimum order(?: quantity)?)[^\d]{0,20}(\d+)") or find(r"(\d+)\+\s*units")
    dep = find(r"(\d+(?:\.\d+)?)\s*%\s*deposit") or find(r"deposit[^\d]{0,15}(\d+(?:\.\d+)?)\s*%")
    terms = find(r"(\d+(?:\.\d+)?/\d+\s*net\s*\d+|net\s*\d+)")
    rating = find(r"(\d\.\d)\s*/\s*5")
    country = find(r"ships from[:\s]+([A-Z][A-Za-z]+)")
    if not (days or weeks):
        return None
    return {"supplier": head.strip(), "country": country.group(1) if country else "", "unit_price": float(price.group(1)) if price else None,
            "moq": int(moq.group(1)) if moq else 1, "lead_days": int(days.group(1)) if days else int(float(weeks.group(1)) * 7),
            "rating": float(rating.group(1)) if rating else 0.0, "terms": re.sub(r"\s+", " ", terms.group(1)).strip() if terms else "",
            "deposit_pct": float(dep.group(1)) if dep else 0.0, "url": snap.get("url", "")}
