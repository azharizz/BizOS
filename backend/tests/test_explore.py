"""Exploring a site through Chrome: which links to follow, search, pagination, limits; and weighing options with evidence."""
import asyncio
import json

import pytest

from bizos import explore, tools
from bizos.bridge import BridgeError


# ---- pure helpers
def el(label, href=None, **kw):
    return {"ref": kw.pop("ref", 0), "tag": kw.pop("tag", "a"), "type": "", "label": label, "risky": False, "blocked": False, **({"href": href} if href else {}), **kw}


def test_links_are_ranked_by_the_goal_and_never_include_login_cart_files_or_other_sites():
    els = [el("Blog", "https://s.com/blog/news"), el("Wholesale pricing", "https://s.com/wholesale"), el("Login", "https://s.com/login"),
           el("Cart", "https://s.com/cart"), el("Spec sheet", "https://s.com/a.pdf"), el("Partner", "https://other.com/x"),
           el("Ceramic dripper", "https://s.com/products/ceramic-dripper"), el("Buy now", "https://s.com/buy", risky=True)]
    got = explore.pick_links(els, "https://s.com/", set(), explore.terms("ceramic pour over wholesale price"))
    urls = [g["url"] for g in got]
    assert urls[0] in ("https://s.com/products/ceramic-dripper", "https://s.com/wholesale")
    assert not any(x in urls for x in ("https://s.com/login", "https://s.com/cart", "https://s.com/a.pdf", "https://other.com/x", "https://s.com/buy"))
    assert urls.index("https://s.com/blog/news") > urls.index("https://s.com/wholesale")


def test_norm_collapses_tracking_fragments_and_slashes_and_site_is_the_registrable_domain():
    assert explore.norm("https://S.com/a/?utm_source=x&id=2#top") == "https://s.com/a?id=2"
    assert explore.same_site("https://shop.s.com/a", "https://www.s.com/b") and not explore.same_site("https://s.com", "https://t.com")


def test_search_box_and_pagination_are_found():
    els = [el("Home", "https://s.com/"), el("Search products", tag="input", ref=7), el("Password", tag="input", blocked=True, ref=8),
           el("Next ›", "https://s.com/p?page=2"), el("2", "https://s.com/p?page=2"), el("Contact", "https://s.com/contact")]
    assert explore.find_search_box(els)["ref"] == 7
    assert explore.pagination(els, "https://s.com/p", set()) == ["https://s.com/p?page=2", "https://s.com/p?page=2"][:2]


def test_facts_come_from_the_page_text():
    snap = {"title": "Ceramic set", "text": "Price: US$ 4.50-6.20 / set. MOQ: 500 pcs. Lead time 25-30 days. FOB Ningbo. T/T 30% deposit. "
                                            "ISO 9001 and SGS tested. Free samples available.", "prices": [{"price": "$4.50"}]}
    f = explore.extract_facts(snap)
    assert f["prices"] == ["$4.50"] and "500" in f["moq"][0] and "25-30" in f["lead_time"][0] and "FOB" in f["incoterm"] and "ISO 9001" in f["certifications"]


# ---- weighing
REQS = [{"name": "Price", "weight": 5, "must_have": False}, {"name": "Lead time", "weight": 4, "must_have": True, "minimum": 5},
        {"name": "Reliability", "weight": 3, "must_have": False}]


def test_weighted_matrix_ranks_and_rules_out_options_that_fail_a_must_have():
    opts = [{"name": "A", "scores": {"Price": 9, "Lead time": 2, "Reliability": 9}, "pros": ["cheap"], "cons": ["slow"]},
            {"name": "B", "scores": {"Price": 6, "Lead time": 8, "Reliability": 7}, "pros": ["fast"], "cons": []},
            {"name": "C", "scores": {"Price": 5, "Lead time": 7, "Reliability": 5}}]
    r = explore.weigh(REQS, opts)
    assert r["best"] == "B" and [m["option"] for m in r["matrix"]] == ["B", "C", "A"]
    assert r["matrix"][-1]["status"].startswith("out") and r["matrix"][-1]["rank"] == "" and r["matrix"][0]["rank"] == 1
    assert 0 <= r["best_score"] <= 100 and r["pros_cons"][2]["cons"] == "slow" and r["requirements"][1]["must_have"] == "yes"
    with pytest.raises(ValueError):
        explore.weigh([], opts)


# ---- the crawler, against a simulated site
class FakeHub:
    """A tiny site: home -> products (page 1, 2) / pricing / blog / login, with a search box on the home page."""
    connected = True

    def __init__(self, slow=0.0):
        self.opened, self.typed, self.here, self.slow = [], [], "", slow
        base = "https://shop.example.com"
        self.pages = {
            f"{base}/": ("Home", "Welcome to Example Ceramics", [el("Products", f"{base}/products"), el("Wholesale pricing", f"{base}/pricing"),
                                                                  el("Blog", f"{base}/blog"), el("Login", f"{base}/login"), el("Search", tag="input", ref=3)]),
            f"{base}/products": ("Products", "Ceramic pour over set MOQ: 200 pcs lead time 20 days", [el("Next ›", f"{base}/products?page=2"), el("Pricing", f"{base}/pricing")]),
            f"{base}/products?page=2": ("Products 2", "Ceramic dripper US$ 3.10 MOQ: 500 pcs", []),
            f"{base}/pricing": ("Pricing", "Wholesale price US$ 4.20 per set. Lead time 18 days. FOB Ningbo", []),
            f"{base}/blog": ("Blog", "News", [el("Post", f"{base}/blog/1")]), f"{base}/blog/1": ("Post", "x", []),
            f"{base}/search?q=ceramic": ("Search results", "Results for ceramic: 12 items price $5.00", []),
        }

    async def request(self, op, args=None, timeout=6):
        args = args or {}
        if self.slow:
            await asyncio.sleep(self.slow)
        if op == "open":
            self.opened.append(args["url"]); self.here = args["url"]
            return self._snap()
        if op == "elements":
            return {"elements": self.pages[self.here][2]}
        if op == "risk":
            return {"risky": False, "blocked": False, "search": True, "label": "Search"}
        if op == "type":
            self.typed.append(args["text"]); self.here = "https://shop.example.com/search?q=ceramic"
            return {"typed": "Search"}
        if op == "snapshot":
            return self._snap()
        raise BridgeError(f"unexpected {op}")

    def _snap(self):
        title, text, _ = self.pages[self.here]
        return {"url": self.here, "title": title, "text": text, "headings": [title], "tables": [], "prices": []}


def run_tool(monkeypatch, hub, **kw):
    monkeypatch.setattr(tools, "hub", hub)
    monkeypatch.setattr(tools.web, "check_url", lambda u: u)
    events = []
    run = tools.Run(goal="g", context={}, emit=events.append)
    out = asyncio.run(tools.explore_site_tool(run, "https://shop.example.com/", **kw))
    return run, events, out


def test_explore_follows_useful_links_and_pagination_reads_facts_and_skips_login_and_blog(monkeypatch):
    hub = FakeHub()
    run, events, out = run_tool(monkeypatch, hub, goal="ceramic pour over wholesale price moq", max_pages=8)
    res = json.loads(out)
    visited = [p["url"] for p in res["pages"]]
    assert "https://shop.example.com/pricing" in visited and "https://shop.example.com/products?page=2" in visited
    assert not any("/login" in u or "/blog/1" in u for u in visited) and len(visited) == len(set(visited))
    pricing = next(p for p in res["pages"] if p["url"].endswith("/pricing"))
    assert "FOB" in pricing["facts"]["incoterm"] and "18" in pricing["facts"]["lead_time"][0]
    assert run.ctx["explored"]["example.com"] and events[-1]["status"] == "verified"


def test_explore_stops_at_the_page_limit_and_says_so(monkeypatch):
    _, _, out = run_tool(monkeypatch, FakeHub(), goal="ceramic", max_pages=2)
    res = json.loads(out)
    assert res["pages_read"] == 2 and "page limit" in res["stopped"] and res["not_visited"]


def test_explore_uses_the_sites_own_search_box(monkeypatch):
    hub = FakeHub()
    _, _, out = run_tool(monkeypatch, hub, goal="ceramic", max_pages=3, search_query="ceramic dripper")
    res = json.loads(out)
    assert hub.typed == ["ceramic dripper"] and any(p.get("searched_for") == "ceramic dripper" for p in res["pages"])


def test_explore_stops_at_the_time_limit(monkeypatch):
    import itertools
    from types import SimpleNamespace
    clock = itertools.chain([0.0, 0.0], itertools.repeat(1000.0))  # start, then far past the budget
    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    res = json.loads(run_tool(monkeypatch, FakeHub(), goal="ceramic", max_pages=20, max_seconds=30)[2])
    assert "time limit" in res["stopped"] and res["pages_read"] >= 1


def test_explore_refuses_private_addresses_and_needs_chrome(monkeypatch):
    class Off(FakeHub):
        connected = False
    monkeypatch.setattr(tools, "hub", Off())
    run = tools.Run(goal="g", context={}, emit=lambda e: None)
    assert "Chrome extension" in asyncio.run(tools.explore_site_tool(run, "https://shop.example.com/"))
    monkeypatch.setattr(tools, "hub", FakeHub())
    assert asyncio.run(tools.explore_site_tool(run, "http://127.0.0.1:8787/x")).startswith("ERROR")  # web.check_url blocks loopback


def test_evaluate_options_pins_requirements_matrix_and_pros_cons(monkeypatch):
    run = tools.Run(goal="g", context={}, emit=lambda e: None)
    out = asyncio.run(tools.evaluate_options_tool(run, "Pour-over suppliers", REQS,
                                                  [{"name": "B", "scores": {"Price": 6, "Lead time": 8, "Reliability": 7}, "pros": ["fast"], "cons": ["pricey"]}], ["MOQ under 300"]))
    assert "best" in out and {"pour_over_suppliers_requirements", "pour_over_suppliers_matrix", "pour_over_suppliers_pros_cons"} <= set(run.pinned)
    assert run.pinned["pour_over_suppliers_matrix"]["rows"][0]["weighted_score"] > 0


def test_unpublished_must_haves_are_unconfirmed_not_failures_and_evidence_is_reported():
    opts = [{"name": "Quote-only", "scores": {"Price": None, "Lead time": None, "Reliability": 8}},
            {"name": "Known-bad", "scores": {"Price": 9, "Lead time": 1, "Reliability": 9}},
            {"name": "Known-good", "scores": {"Price": 6, "Lead time": 7, "Reliability": 6}}]
    r = explore.weigh(REQS, opts)
    by = {m["option"]: m for m in r["matrix"]}
    assert by["Known-good"]["status"] == "in" and by["Known-good"]["evidence_known_pct"] == 100
    assert by["Quote-only"]["status"] == "unconfirmed: Lead time" and by["Quote-only"]["evidence_known_pct"] == 25
    assert by["Known-bad"]["status"].startswith("out") and r["best"] == "Known-good"
    assert [m["option"] for m in r["matrix"]] == ["Known-good", "Quote-only", "Known-bad"]
    only = explore.weigh(REQS, opts[:1])
    assert only["best"] == "Quote-only" and only["best_status"].startswith("unconfirmed")


def test_sites_behind_a_sign_in_are_skipped_with_a_reason(monkeypatch):
    assert explore.login_wall("https://jimocn.en.alibaba.com/product/1") and not explore.login_wall("https://www.made-in-china.com/x")
    monkeypatch.setattr(tools, "hub", FakeHub())
    monkeypatch.setattr(tools.web, "check_url", lambda u: u)
    run = tools.Run(goal="g", context={}, emit=lambda e: None)
    out = asyncio.run(tools.explore_site_tool(run, "https://www.alibaba.com/product-detail/x"))
    assert out.startswith("ERROR") and "sign in" in out
    assert "sign in" in asyncio.run(tools.web_open_tool(run, "https://www.aliexpress.com/item/1"))
