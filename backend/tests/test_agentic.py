"""Agentic layer without a live model: tool guards, ordered verified steps, plan validation, Chrome bridge."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from bizos import bridge, data, flows, main, tools


# ---------------- read-only SQL the agent writes
def test_safe_query_allows_select_and_limits_rows():
    rows = data.safe_query("SELECT customer_id, name FROM customers ORDER BY customer_id", limit=5)
    assert len(rows) == 5 and rows[0]["customer_id"] == 1


@pytest.mark.parametrize("sql", [
    "DELETE FROM customers", "UPDATE customers SET name='x'", "DROP TABLE customers",
    "SELECT 1; DROP TABLE customers", "ATTACH DATABASE '/tmp/x.db' AS x", "PRAGMA writable_schema=1",
    "WITH x AS (SELECT 1) INSERT INTO departments VALUES (99,'x',1)",
])
def test_safe_query_blocks_writes(sql):
    with pytest.raises(Exception):
        data.safe_query(sql)


def test_schema_lists_tables_for_the_agent():
    s = data.schema()
    assert "payments(payment_id, invoice_id" in s and s.count("\n") == 17


# ---------------- step tools
def make_run(flow="ceo", plan=None):
    events = []
    f = flows.make_flow(flow)
    run = tools.Run(goal="g", context={}, flow=f, plan=plan or tools.validate_plan(flow, []), emit=events.append)
    return run, events


async def test_step_tool_runs_prerequisites_in_order_and_verifies():
    run, events = make_run()
    out = await tools.run_step(run, "simulate")  # model jumped ahead: earlier steps run first
    assert list(run.done) == ["research", "compare", "exposure", "simulate"]
    statuses = [(e["index"], e["status"]) for e in events]
    assert statuses == [(0, "running"), (0, "verified"), (1, "running"), (1, "verified"),
                        (2, "running"), (2, "verified"), (3, "running"), (3, "verified")]
    assert "Hold price" in out
    events.clear()
    await tools.run_step(run, "compare")  # repeat calls are free and silent
    assert events == []


async def test_failed_verification_stops_the_run(monkeypatch):
    run, events = make_run()
    monkeypatch.setattr(flows.Ceo, "compare", lambda self, ctx: {"price_gaps": []})
    out = await tools.run_step(run, "exposure")
    assert out.startswith("VERIFY FAILED") and run.failed
    assert events[-1]["status"] == "failed" and "exposure" not in run.done
    assert (await tools.run_step(run, "simulate")).startswith("STOPPED")


async def test_extra_tools_take_planned_slots_then_append():
    plan = tools.validate_plan("ceo", [tools.PlanStep(tool="run_sql", why="Check order trend")])
    run, events = make_run(plan=plan)
    await tools.run_sql_tool(run, "SELECT COUNT(*) n FROM orders", "Order count", pin=True)
    await tools.run_sql_tool(run, "SELECT 1 AS one", "Second query", pin=False)
    assert [e["index"] for e in events if e["status"] == "verified"] == [4, 6]  # 5 is "Design the workspace"
    assert run.pinned["order_count"]["rows"] == [{"n": 2500}]


def test_validate_plan_keeps_core_steps_drops_unknown_tools():
    steps = [tools.PlanStep(tool="step_compare", why="Price gap per SKU"), tools.PlanStep(tool="wire_money", why="x"),
             tools.PlanStep(tool="browser_snapshot", why="Read the product page")]
    plan = tools.validate_plan("ceo", steps)
    assert [p["tool"] for p in plan] == ["browser_snapshot", "step_research", "step_compare", "step_exposure", "step_simulate", "canvas"]
    assert plan[2]["label"] == "Price gap per SKU"


# ---------------- Chrome bridge
class FakeSocket:
    def __init__(self, hub):
        self.hub, self.sent = hub, []

    async def send_json(self, msg):
        self.sent.append(msg)
        asyncio.get_running_loop().call_soon(self.hub.resolve, {"id": msg["id"], "ok": True, "result": {"title": "Lumen"}})


async def test_hub_round_trip_and_disconnected_error():
    hub = bridge.Hub()
    with pytest.raises(bridge.BridgeError):
        await hub.request("snapshot")
    hub.attach(FakeSocket(hub), {})
    assert await hub.request("snapshot") == {"title": "Lumen"}


def test_extension_socket_requires_pairing_token(monkeypatch):
    monkeypatch.setattr(main.bridge, "extension_token", lambda: "pair-me")
    with TestClient(main.app) as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/ext?token=wrong") as ws:
                ws.receive_json()
        with c.websocket_connect("/ext?token=pair-me") as ws:
            ws.send_json({"type": "hello", "version": "test"})
            assert ws.receive_json() == {"type": "welcome"}
            assert c.get("/extension").json()["connected"] is True


# ---------------- general mode: any business question, no fixed department steps
def test_general_flow_is_separate_from_the_seven_departments():
    assert "general" not in flows.FLOWS and flows.make_flow("general").steps == ()
    plan = tools.validate_plan("general", [])
    assert plan == [{"tool": "run_sql", "label": "Query company data"}, tools.DESIGN]


async def test_general_workspace_is_built_from_pinned_evidence():
    from bizos import agent, compiler
    session = agent.Session({})
    ws = compiler.new_workspace("g1")
    run = tools.Run(goal="Which departments overspend?", context={}, flow=flows.make_flow("general"), canvas=compiler.Canvas(ws))
    run.ctx["title"] = "Department spend"
    await tools.run_sql_tool(run, "SELECT name, monthly_budget FROM departments ORDER BY monthly_budget DESC", "Budget by department", pin=True)
    session.finish(run, ws, "**Engineering has the biggest budget.** More detail.")
    kinds = [w["type"] for w in ws["state"]["pages"][0]["widgets"].values()]
    assert kinds == ["column-chart-grouped"]  # a chart, not yet another table
    assert ws["title"] == "Department spend" and ws["headline"] == "Engineering has the biggest budget."
    assert ws["actions"] == [] and ws["complete"]


async def test_new_topic_or_remove_leaves_the_current_workspace(monkeypatch):
    from bizos import agent, compiler
    old = compiler.new_workspace("old")
    old["title"] = "Top 10 cheapest LLMs"
    session = agent.Session({"old": old})
    session.ws_id = "old"
    for decision, kept in (("keep", True), ("new", True), ("remove", False)):
        session.ws_id = "old"
        session.workspaces["old"] = old

        async def fake_plan(ask, d=decision):
            return {"flow": "general", "subject": "coding", "rationale": "r", "steps": [], "needs_screenshot": False, "workspace": d}
        monkeypatch.setattr(session, "plan_with_agent", fake_plan)
        monkeypatch.setattr(agent.llm, "model", lambda: object())
        plan = await session.make_plan({"goal": "remove our workspace, I want to talk about coding", "context": {}})
        offer = session.offer(plan)
        ws = session.use_workspace(plan)
        if decision == "keep":
            assert offer["plan"]["editing"]["title"] == "Top 10 cheapest LLMs" and ws is old
        else:
            assert offer["plan"]["editing"] is None and ws is not old and session.ws_id == ws["id"]
        assert ("old" in session.workspaces) == kept


async def test_agent_designs_the_canvas_with_tools():
    from bizos import compiler
    ws = compiler.new_workspace("d1")
    events = []
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("ceo"), canvas=compiler.Canvas(ws),
                    plan=tools.validate_plan("ceo", []), emit=events.append)
    await tools.run_step(run, "simulate")
    compiler.register(run.canvas, run.flow.findings(run.ctx), {})
    view, add_kpi, add_widget, remove_widget = tools.canvas_tools(run)
    from agents.tool_context import ToolContext
    async def call(tool, **args):
        import json as _j
        ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id="t", tool_arguments=_j.dumps(args))
        return await tool.on_invoke_tool(ctx, _j.dumps(args))
    assert "added" in await call(add_kpi, label="Products undercut", value=12, tone="bad")
    assert "added" in await call(add_widget, kind="donut", source="scenarios", title="GP by response", x="scenario", y=["gross_profit_90d"], width="third")
    assert "ERROR" in await call(add_widget, kind="line", source="nope", title="x", x="a", y=["b"])
    assert run.designed == 2 and events[-1]["label"] == "Design the workspace" and events[-1]["note"] == "2 widgets"


def test_sandbox_receiver_overrides_placeholder_emails(monkeypatch):
    monkeypatch.setattr(flows.config, "PAYPAL_SANDBOX_RECEIVER", "sb-buyer@personal.example.com")
    assert flows.email("supplier", 3) == "sb-buyer@personal.example.com"


def test_plan_accepts_step_names_without_prefix():
    plan = tools.validate_plan("engineering", [tools.PlanStep(tool="spike", why="When did spend jump")])
    assert plan[0] == {"tool": "step_spike", "label": "When did spend jump"}


async def test_agent_that_only_adds_kpis_still_gets_charts_and_edits_keep_the_headline():
    from bizos import agent, compiler
    ws = compiler.new_workspace("k1")
    ws["headline"] = "Paid Social ROAS fell 45%."
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), canvas=compiler.Canvas(ws))
    await tools.run_sql_tool(run, "SELECT channel, SUM(budget) b FROM marketing_campaigns GROUP BY channel", "Budget by channel", pin=True)
    run.canvas.add_kpi("Channels", 6)
    run.designed = 1
    agent.Session({}).finish(run, ws, "**The workspace now has a donut.**")
    assert compiler.has_chart(run.canvas) and ws["headline"] == "Paid Social ROAS fell 45%."


# ---------------- one-click Chrome pairing
def test_pairing_link_is_single_use_and_carries_the_token(monkeypatch):
    monkeypatch.setattr(main.bridge, "extension_token", lambda: "pair-me")
    monkeypatch.setattr(main, "TOKEN", "app-secret")
    with TestClient(main.app) as c:
        assert c.post("/extension/pair").status_code == 401, "only the overlay (app token) can mint a link"
        url = c.post("/extension/pair", headers={"x-bizos-token": "app-secret"}).json()["url"]
        page = c.get(url.replace("http://127.0.0.1:8787", ""))
        assert page.status_code == 200 and 'content="pair-me"' in page.text and "ws://127.0.0.1:8787/ext" in page.text
        again = c.get(url.replace("http://127.0.0.1:8787", ""))
        assert again.status_code == 403 and "pair-me" not in again.text
        assert c.get("/pair?code=guess").status_code == 403
