"""Acting beyond company data: web search/open (Chrome or server fallback), desktop apps, pinning web findings."""
import asyncio

import httpx
import pytest

from bizos import agent, compiler, flows, tools, web

DDG = """<html><body>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fllm-prices&rut=x">LLM price list Oct 2026</a>
<a class="result__snippet">Cheapest new models compared.</a></div>
<div class="result"><a class="result__a" href="https://models.example.org/new">New models this month</a>
<a class="result__snippet">Release tracker.</a></div></body></html>"""


def test_parses_search_results_and_unwraps_redirects():
    rows = web.parse_results(DDG)
    assert rows[0] == {"title": "LLM price list Oct 2026", "url": "https://example.com/llm-prices", "snippet": "Cheapest new models compared."}
    assert rows[1]["url"] == "https://models.example.org/new"


def test_page_text_strips_scripts_and_tags():
    text = web.page_text("<html><head><title>T</title><script>evil()</script></head><body><h1>Prices</h1><p>GPT $1</p></body></html>")
    assert text["title"] == "T" and "Prices" in text["text"] and "evil" not in text["text"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:8787/pair", "http://localhost/x", "http://10.0.0.5/admin",
                                 "http://192.168.1.1", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://x.org"])
def test_server_fetch_refuses_internal_and_non_web_urls(url):
    with pytest.raises(ValueError):
        web.check_url(url)


async def test_fetch_goes_through_the_guard(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="<title>Ok</title><p>hello</p>")
    monkeypatch.setattr(web, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(web, "check_url", lambda u: u)
    page = await web.fetch("https://example.com")
    assert page["title"] == "Ok" and page["url"] == "https://example.com"


async def test_web_filter_block_pages_are_reported_not_read(monkeypatch):
    monkeypatch.setattr(web, "check_url", lambda u: u)
    monkeypatch.setattr(web, "_transport", httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html><title>Forbidden Website</title></html>")))
    with pytest.raises(ValueError, match="web filter"):
        await web.fetch("https://blocked.example")


def run_with_client(responses: dict):
    events, calls = [], []

    async def client(op, args):
        calls.append((op, args))
        return responses[op]
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), emit=events.append,
                    canvas=compiler.Canvas(compiler.new_workspace("w")), client=client)
    return run, events, calls


async def test_open_app_asks_the_desktop_and_reports_a_step():
    run, events, calls = run_with_client({"open_app": {"app": "Numbers", "title": "Budget.numbers"}})
    out = await tools.open_app_tool(run, "Numbers")
    assert calls == [("open_app", {"name": "Numbers"})] and "Budget.numbers" in out
    assert events[-1]["status"] == "verified" and "Numbers" in events[-1]["label"]


async def test_write_note_puts_text_in_a_new_local_document():
    run, events, calls = run_with_client({"write_note": {"app": "TextEdit", "written": 11}})
    out = await tools.write_note_tool(run, "Summary\n- a", "notepad")
    assert calls == [("write_note", {"app": "notepad", "text": "Summary\n- a"})] and "TextEdit" in out
    assert events[-1]["status"] == "verified"
    assert "write_note" in tools.EXTRAS


async def test_close_app_only_runs_when_the_user_approved_it_in_the_plan():
    run, events, calls = run_with_client({"close_app": {"app": "TextEdit", "closed": True, "discarded": True}})
    out = await tools.close_app_tool(run, "notepad", discard=True)
    assert "not in the approved plan" in out and calls == []  # the agent can't add it on its own
    run.plan = [{"tool": "close_app", "label": "Close Notepad without saving"}]
    out = await tools.close_app_tool(run, "notepad", discard=True)
    assert calls == [("close_app", {"name": "notepad", "discard": "yes"})] and "TextEdit" in out
    assert events[-1]["status"] == "verified"


def test_plans_that_close_apps_are_never_auto_run():
    from bizos import agent
    s = agent.Session({})
    plan = {"flow": "general", "team": "t", "title": "t", "subject": "s", "rationale": "r", "sensed": [], "agentic": True,
            "items": tools.validate_plan("general", [tools.PlanStep(tool="close_app", why="Close Notepad without saving")])}
    assert s.offer(plan)["plan"]["confirm"] == "Close Notepad without saving"  # spoken back when asking to confirm
    plan["items"] = tools.validate_plan("general", [tools.PlanStep(tool="web_search", why="Find prices")])
    assert s.offer(plan)["plan"]["confirm"] is None


async def test_web_search_without_chrome_opens_default_browser_and_reads_on_server(monkeypatch):
    run, events, calls = run_with_client({"open_url": {"opened": True}})

    async def fake_search(q):
        return [{"title": "A", "url": "https://a.example", "snippet": "s"}]
    monkeypatch.setattr(web, "search", fake_search)
    out = await tools.web_search_tool(run, "cheap new llm models october 2026")
    assert calls[0][0] == "open_url" and "duckduckgo" in calls[0][1]["url"]
    assert "a.example" in out and events[-1]["status"] == "verified"


async def test_pin_table_turns_web_findings_into_workspace_evidence():
    run, _, _ = run_with_client({})
    rows = [{"model": f"M{i}", "price_per_mtok": i * 0.1, "released": "2026-10"} for i in range(1, 11)]
    assert "pinned" in await tools.pin_table_tool(run, "Cheapest new LLMs", rows)
    assert run.pinned["cheapest_new_llms"]["rows"][0]["model"] == "M1"
    assert "ERROR" in await tools.pin_table_tool(run, "bad", [{"x": {"nested": 1}}])


async def test_session_client_round_trip():
    sent = []

    async def send(msg):
        sent.append(msg)
    s = agent.Session({}, send=send)
    task = asyncio.create_task(s.client("read_screen", {}))
    await asyncio.sleep(0)
    s.resolve({"type": "client_result", "id": sent[0]["id"], "ok": True, "result": {"app": "Excel"}})
    assert await task == {"app": "Excel"} and sent[0]["type"] == "client_call"
    with pytest.raises(RuntimeError):
        await agent.Session({}).client("read_screen", {})


async def test_web_tools_fall_back_when_chrome_cannot_do_it(monkeypatch):
    """An old or broken extension ("unknown op search") must not sink the run."""
    from bizos import bridge

    class OldExtension:
        connected = True

        async def request(self, op, args=None, timeout=6):
            raise bridge.BridgeError(f"unknown op {op}")
    monkeypatch.setattr(tools, "hub", OldExtension())
    run, events, calls = run_with_client({"open_url": {"opened": True}})

    async def fake_search(q):
        return [{"title": "A", "url": "https://a.example", "snippet": "s"}]

    async def fake_fetch(url):
        return {"url": url, "title": "Prices", "text": "Haiku $0.10"}
    monkeypatch.setattr(web, "search", fake_search)
    monkeypatch.setattr(web, "fetch", fake_fetch)
    assert "a.example" in await tools.web_search_tool(run, "llm prices")
    assert "Haiku" in await tools.web_open_tool(run, "https://a.example")
    assert [e["status"] for e in events if e["status"] != "running"] == ["verified", "verified"]


async def test_pinned_findings_are_chartable_immediately_during_the_run():
    run, _, _ = run_with_client({})
    rows = [{"model": f"M{i}", "input_usd": i * 0.01} for i in range(1, 11)]
    await tools.pin_table_tool(run, "Cheapest new LLMs", rows)
    await tools.run_sql_tool(run, "SELECT name, monthly_budget FROM departments", "Budgets", pin=True)
    wid = run.canvas.add({"kind": "bar", "source": "cheapest_new_llms", "x": "model", "y": ["input_usd"], "title": "Price"})
    assert wid and run.canvas.source("budgets")


def fake_page(monkeypatch, elements):
    from bizos import bridge
    calls = []

    async def request(op, args=None, timeout=6):
        calls.append((op, args))
        if op == "risk":
            e = elements[args["ref"]]
            return {"label": e["label"], "risky": e.get("risky", False), "blocked": e.get("blocked", False)}
        return {"ok": True, "url": "https://shop.example/cart", "title": "Cart"}
    monkeypatch.setattr(bridge.hub, "socket", object())
    monkeypatch.setattr(tools.hub, "request", request)
    return calls


async def test_page_click_runs_plain_clicks_but_asks_before_risky_ones(monkeypatch):
    calls = fake_page(monkeypatch, {1: {"label": "Show more"}, 2: {"label": "Place order", "risky": True}})
    asked = []

    async def confirm(question):
        asked.append(question)
        return False  # the user says no
    run, events, _ = run_with_client({})
    run.confirm = confirm
    await tools.page_click_tool(run, 1)
    assert ("click", {"ref": 1}) in calls and asked == []
    out = await tools.page_click_tool(run, 2)
    assert "declined" in out and ("click", {"ref": 2}) not in calls
    assert "Place order" in asked[0]


async def test_risky_actions_are_refused_when_nobody_can_confirm(monkeypatch):
    calls = fake_page(monkeypatch, {2: {"label": "Send", "risky": True}})
    run, _, _ = run_with_client({})  # no confirm channel
    out = await tools.page_click_tool(run, 2)
    assert "declined" in out and ("click", {"ref": 2}) not in calls


async def test_page_type_never_touches_blocked_fields_and_confirms_submit(monkeypatch):
    calls = fake_page(monkeypatch, {3: {"label": "Password", "blocked": True}, 4: {"label": "Search"}})
    run, _, _ = run_with_client({})
    assert "never" in (await tools.page_type_tool(run, 3, "hunter2")) and not any(c[0] == "type" for c in calls)
    await tools.page_type_tool(run, 4, "cold brew")
    assert ("type", {"ref": 4, "text": "cold brew", "submit": False}) in calls

    async def yes(question):
        return True
    run.confirm = yes
    await tools.page_type_tool(run, 4, "tea", submit=True)
    assert ("type", {"ref": 4, "text": "tea", "submit": True}) in calls


async def test_mac_control_asks_before_risky_steps():
    run, events, calls = run_with_client({op: {"ok": True} for op in
                                          ("ui_click", "ui_menu", "press_key", "type_text", "run_shortcut", "clipboard_read")})
    asked = []

    async def no(question):
        asked.append(question)
        return False
    run.confirm = no
    await tools.mac_tool(run, "ui_click", app="Notes", name="New Note")         # plain: no question
    await tools.mac_tool(run, "type_text", app="Notes", text="hello")
    assert [c[0] for c in calls] == ["ui_click", "type_text"] and asked == []
    for op, args in [("ui_click", {"app": "Mail", "name": "Send"}), ("ui_menu", {"app": "Finder", "menu": "File", "item": "Move to Trash"}),
                     ("press_key", {"app": "Slack", "key": "return"}), ("press_key", {"app": "Notes", "key": "delete", "modifiers": "cmd"}),
                     ("run_shortcut", {"name": "Morning routine"}), ("clipboard_read", {})]:
        out = await tools.mac_tool(run, op, **args)
        assert "declined" in out, op
    assert len(asked) == 6 and [c[0] for c in calls] == ["ui_click", "type_text"]  # none of the risky ones ran


async def test_return_in_a_non_messaging_app_is_not_risky():
    run, _, calls = run_with_client({"press_key": {"ok": True}})
    await tools.mac_tool(run, "press_key", app="Numbers", key="return")
    assert calls == [("press_key", {"app": "Numbers", "key": "return"})]


async def test_delete_in_finder_or_explorer_asks_first():
    run, _, calls = run_with_client({"press_key": {"ok": True}})
    for app in ("Finder", "File Explorer"):
        assert "declined" in await tools.mac_tool(run, "press_key", app=app, key="delete")
    assert calls == []
