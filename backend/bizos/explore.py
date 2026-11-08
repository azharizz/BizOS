"""Pure helpers for exploring a website through the user's Chrome, and for weighing what was found.

The crawler itself (tools.explore_site) drives the extension; everything that can be decided without a browser lives here
so it can be tested: which links are worth following, where the search box is, what a page says about price, minimum order,
lead time and trust, and how options score against requirements.
"""
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

SKIP = re.compile(r"log.?in|sign.?in|sign.?up|register|cart|checkout|my.?account|password|privacy|terms|cookie|logout|wishlist|"
                  r"^javascript:|^mailto:|^tel:|\.(pdf|jpe?g|png|gif|svg|zip|mp4)(\?|$)", re.I)
WEIGHTS = {"price": 3, "pricing": 3, "wholesale": 3, "bulk": 3, "moq": 3, "minimum": 2, "quote": 2, "catalog": 2, "catalogue": 2,
           "product": 2, "products": 2, "shop": 1, "collection": 1, "shipping": 2, "delivery": 2, "lead": 2, "sample": 2, "factory": 2,
           "certificat": 2, "about": 1, "faq": 1, "contact": 1, "oem": 2, "custom": 1, "payment": 1, "terms-of-sale": 2}
DOWN = re.compile(r"blog|news|career|jobs|press|investor|forum|login|facebook|twitter|instagram|linkedin|youtube|privacy|cookie", re.I)
NEXT = re.compile(r"^\s*(next|older|more|load more|show more|›|»|>|→)\b|^\s*page\s*\d+\s*$|^\s*\d{1,2}\s*$", re.I)


LOGIN_WALL = ("alibaba.com", "aliexpress.com", "1688.com", "amazon.com", "faire.com")  # prices behind a sign-in; they pop up account choosers


def login_wall(url: str) -> bool:
    return site_of(url) in LOGIN_WALL


def terms(goal: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", goal.lower()) if w not in {"the", "and", "for", "with", "find", "best", "from", "that", "this", "all"}}


def norm(url: str) -> str:
    """One page, one key: no fragment, no tracking parameters, no trailing slash."""
    u = urlparse(url)
    q = urlencode([(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "spm", "ref"))])
    return urlunparse((u.scheme, u.netloc.lower(), u.path.rstrip("/") or "/", "", q, ""))


def site_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return ".".join(host.split(".")[-2:]) if host.count(".") >= 1 else host


def same_site(a: str, b: str) -> bool:
    return site_of(a) == site_of(b)


def score_link(label: str, href: str, goal_terms: set[str]) -> int:
    text = f"{label} {urlparse(href).path}".lower()
    s = sum(3 for t in goal_terms if t in text) + sum(w for k, w in WEIGHTS.items() if k in text)
    return s - (4 if DOWN.search(text) else 0)


def pick_links(elements: list[dict], base: str, visited: set[str], goal_terms: set[str], limit: int = 6) -> list[dict]:
    """Same-site links worth opening next, best first. Never login, cart, account or file links."""
    seen, out = set(), []
    for e in elements:
        href = e.get("href")
        if not href or e.get("blocked") or e.get("risky"):
            continue
        href = urljoin(base, href)
        key = norm(href)
        if not href.startswith(("http://", "https://")) or not same_site(href, base) or key in visited or key in seen:
            continue
        if SKIP.search(href) or SKIP.search(e.get("label", "")):
            continue
        seen.add(key)
        out.append({"url": href, "label": e.get("label", "")[:60], "score": score_link(e.get("label", ""), href, goal_terms)})
    return sorted(out, key=lambda x: -x["score"])[:limit]


def pagination(elements: list[dict], base: str, visited: set[str]) -> list[str]:
    out = []
    for e in elements:
        href = e.get("href")
        if href and NEXT.search(e.get("label", "")) and same_site(urljoin(base, href), base) and norm(urljoin(base, href)) not in visited:
            out.append(urljoin(base, href))
    return out[:2]


def find_search_box(elements: list[dict]) -> dict | None:
    for e in elements:
        blob = f"{e.get('type', '')} {e.get('label', '')}".lower()
        if e.get("tag") in ("input", "textarea") and not e.get("blocked") and ("search" in blob or "find" in blob or "keyword" in blob):
            return e
    return None


MONEY = re.compile(r"(?:US\s?\$|USD\s?|\$|€|£)\s?\d[\d,]*(?:\.\d+)?(?:\s?[-–~]\s?(?:US\s?\$|USD\s?|\$|€|£)?\s?\d[\d,]*(?:\.\d+)?)?", re.I)
PATTERNS = {
    "moq": re.compile(r"(?:moq|min(?:imum)?\.?\s*order(?:\s*quantity)?|min\.? order)[^\d]{0,25}(\d[\d,]*)\s*(pcs|pieces|units|sets|pairs|cartons)?", re.I),
    "lead_time": re.compile(r"(?:lead\s*time|delivery(?:\s*time)?|production(?:\s*time)?|ships? (?:in|within))[^\d]{0,25}(\d{1,3}(?:\s*[-–]\s*\d{1,3})?)\s*(days?|weeks?)", re.I),
    "incoterm": re.compile(r"\b(FOB|EXW|CIF|DDP|DAP|FCA)\b"),
    "payment": re.compile(r"\b(T/T|L/C|PayPal|Western Union|net\s?\d{2}|\d{1,3}% deposit|Alibaba Trade Assurance)\b", re.I),
    "certifications": re.compile(r"\b(ISO\s?\d{4,5}|CE|FDA|SGS|BSCI|LFGB|REACH|RoHS|GOTS|FSC|Sedex)\b"),
    "sample": re.compile(r"\b(free samples?|samples? (?:available|cost|fee|policy)|sample order)\b", re.I),
}


def extract_facts(snap: dict) -> dict:
    """What a page says that matters for choosing a supplier: prices, minimum order, lead time, terms, certifications."""
    text = " ".join(str(snap.get(k) or "") for k in ("title", "text"))
    facts: dict = {}
    prices = [p.get("price") for p in snap.get("prices", []) if p.get("price")] or MONEY.findall(text)
    if prices:
        facts["prices"] = list(dict.fromkeys(re.sub(r"\s+", " ", p).strip() for p in prices))[:8]
    for name, pat in PATTERNS.items():
        hits = [m.group(0) if name in ("incoterm", "payment", "certifications", "sample") else " ".join(g for g in m.groups() if g)
                for m in pat.finditer(text)]
        if hits:
            facts[name] = list(dict.fromkeys(re.sub(r"\s+", " ", h).strip() for h in hits))[:5]
    return facts


def summarize_page(snap: dict, depth: int = 0) -> dict:
    tables = [{"caption": t.get("caption", ""), "rows": [r for r in t.get("rows", [])[:6]]} for t in snap.get("tables", [])[:2]]
    return {"url": snap.get("url", ""), "title": (snap.get("title") or "")[:90], "headings": [h for h in snap.get("headings", [])[:6]],
            "facts": extract_facts(snap), "tables": tables, "excerpt": re.sub(r"\s+", " ", str(snap.get("text") or ""))[:600], "depth": depth}


# ---------------------------------------------------------------- weighing options
def weigh(requirements: list[dict], options: list[dict]) -> dict:
    """Weighted decision matrix with honest gaps. requirements: [{name, weight 1-5, must_have, minimum}]; options: [{name, scores{req: 0-10
    or null when no page states it}, pros, cons}]. A known score below a must-have's `minimum` rules the option out; a must-have nobody
    published is "unconfirmed" (ask before buying), not a failure. Unknowns count as 0 in the score, and `evidence` says how much is known."""
    reqs = [{"name": str(r["name"])[:40], "weight": max(1, min(5, int(r.get("weight", 3)))), "must_have": bool(r.get("must_have")),
             "minimum": float(r.get("minimum", 4))} for r in requirements if r.get("name")]
    if not reqs or not options:
        raise ValueError("need at least one requirement and one option")
    total_w = sum(r["weight"] for r in reqs)
    rows = []
    for o in options:
        raw = o.get("scores") or {}
        known = {r["name"]: (float(raw[r["name"]]) if isinstance(raw.get(r["name"]), (int, float)) and not isinstance(raw.get(r["name"]), bool) else None)
                 for r in reqs}
        sc = {k: (max(0.0, min(10.0, v)) if v is not None else None) for k, v in known.items()}
        fails = [r["name"] for r in reqs if r["must_have"] and sc[r["name"]] is not None and sc[r["name"]] < r["minimum"]]
        unknown = [r["name"] for r in reqs if r["must_have"] and sc[r["name"]] is None]
        weighted = round(100 * sum((sc[r["name"]] or 0) * r["weight"] for r in reqs) / (10 * total_w), 1)
        coverage = round(100 * sum(r["weight"] for r in reqs if sc[r["name"]] is not None) / total_w)
        status = f"out: fails {', '.join(fails)}" if fails else f"unconfirmed: {', '.join(unknown)}" if unknown else "in"
        rows.append({"option": str(o.get("name", "?"))[:50], "weighted_score": weighted, "evidence_known_pct": coverage, "status": status,
                     **{r["name"]: sc[r["name"]] for r in reqs}, "_tier": 2 if fails else 1 if unknown else 0, "_o": o})
    rows.sort(key=lambda r: (r["_tier"], -r["weighted_score"]))
    for n, r in enumerate(rows, 1):
        r["rank"] = n if r["_tier"] < 2 else None
    matrix = [{k: ("" if v is None else v) for k, v in r.items() if not k.startswith("_")} for r in rows]
    pros_cons = [{"option": r["option"], "pros": "; ".join(map(str, (r["_o"].get("pros") or [])[:5])),
                  "cons": "; ".join(map(str, (r["_o"].get("cons") or [])[:5])), "evidence": str(r["_o"].get("evidence", ""))[:200],
                  "url": str(r["_o"].get("url", ""))[:200]} for r in rows]
    requirements_table = [{"requirement": r["name"], "weight": r["weight"], "must_have": "yes" if r["must_have"] else "no",
                           "minimum_score": r["minimum"] if r["must_have"] else ""} for r in reqs]
    best = next((r for r in rows if r["_tier"] < 2), None)
    return {"matrix": matrix, "pros_cons": pros_cons, "requirements": requirements_table, "best": best["option"] if best else None,
            "best_score": best["weighted_score"] if best else None, "best_status": best["status"] if best else None}
