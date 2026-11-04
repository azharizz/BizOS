"""The plan as a graph: steps with dependencies, branches and risk; the user can skip optional steps; the
workspace keeps a live copy (statuses, and PayPal approvals waiting on a person)."""
import json

from agents.tool_context import ToolContext

from bizos import agent, compiler, flows, tools


def test_plan_graph_links_steps_branches_and_risk():
    steps = [tools.PlanStep(tool="run_sql", why="Margin by product"),
             tools.PlanStep(tool="web_search", why="Competitor prices", after=[0]),
             tools.PlanStep(tool="pin_table", why="Keep prices", after=[1]),
             tools.PlanStep(tool="paypal_propose", why="Payment link for the new offer", after=[0], when="if we cut price")]
    items = tools.validate_plan("general", steps)
    nodes = tools.plan_graph(items)
    by = {n["tool"]: n for n in nodes}
    assert [n["tool"] for n in nodes] == ["run_sql", "web_search", "pin_table", "paypal_propose", "canvas"]
    assert by["web_search"]["after"] == [0] and by["pin_table"]["after"] == [1]
    assert by["paypal_propose"]["after"] == [0] and by["paypal_propose"]["when"] == "if we cut price"
    assert by["paypal_propose"]["risk"] == "money" and by["run_sql"]["risk"] == "read" and by["pin_table"]["risk"] == "act"
    assert by["canvas"]["after"] == [2, 3], "the workspace design waits for every open end"
    assert not any(n["core"] for n in nodes)


def test_department_steps_are_core_and_chained():
    nodes = tools.plan_graph(tools.validate_plan("ceo", [tools.PlanStep(tool="browser_snapshot", why="Read the page")]))
    core = [n for n in nodes if n["core"]]
    assert len(core) == 4 and all(n["after"] == [n["index"] - 1] for n in nodes[1:-1])


def test_skipping_drops_optional_steps_only():
    session = agent.Session({})
    items = tools.validate_plan("ceo", [tools.PlanStep(tool="run_sql", why="Order trend")])
    plan = {"items": items}
    agent.apply_skip(plan, [0, 1, 4, 99, "x"])  # 1 = step_research (core), 4 = run_sql, 0 = core too
    assert [p.get("skipped", False) for p in plan["items"]] == [False, False, False, False, True, False]
    assert "run_sql: Order trend" not in agent.analyst_instructions({**plan, "flow": "ceo"})
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("ceo"), plan=plan["items"])
    assert run.slot("run_sql", "Query")[0] == 6, "a skipped slot is never reused"
    assert session.plan is None


async def test_paypal_propose_adds_an_action_linked_to_its_plan_step():
    ws = compiler.new_workspace("pp")
    events = []
    plan = tools.validate_plan("general", [tools.PlanStep(tool="paypal_propose", why="Payment link for Cold Brew")])
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), plan=plan, canvas=compiler.Canvas(ws), emit=events.append)
    read, propose = tools.paypal_tools(run, paypal=object())
    args = {"endpoint": "payment_link_create", "label": "Payment link: Cold Brew 1L", "why": "New product",
            "body_json": json.dumps({"line_items": [{"name": "Cold Brew 1L", "unit_amount": {"currency_code": "USD", "value": "8.40"}}]})}
    out = await propose.on_invoke_tool(ToolContext(context=None, tool_name="paypal_propose", tool_call_id="t", tool_arguments=json.dumps(args)), json.dumps(args))
    action = ws["actions"][0]
    assert "waiting for a person" in out and action["kind"] == "paypal" and action["step"] == 0
    assert events[-1] == {"type": "step", "index": 0, "label": "Payment link for Cold Brew", "status": "verified", "note": "awaiting approval"}
    bad = {"endpoint": "capture_refund", "label": "x", "why": "", "body_json": "[1]"}
    assert "ERROR" in await propose.on_invoke_tool(ToolContext(context=None, tool_name="paypal_propose", tool_call_id="t", tool_arguments=json.dumps(bad)), json.dumps(bad))


def test_workspace_keeps_a_live_plan():
    ws = compiler.new_workspace("lp")
    nodes = tools.plan_graph(tools.validate_plan("ceo", []))
    agent.track_plan(ws, nodes, "Investigate competitor")
    agent.track_plan(ws, None, None, {"type": "step", "index": 0, "label": "Research", "status": "verified", "note": "12 rows"})
    agent.track_plan(ws, None, None, {"type": "step", "index": 9, "label": "Extra query", "status": "running"})
    assert ws["plan"]["subject"] == "Investigate competitor"
    assert ws["plan"]["nodes"][0]["status"] == "verified" and ws["plan"]["nodes"][0]["note"] == "12 rows"
    extra = ws["plan"]["nodes"][-1]
    assert extra["label"] == "Extra query" and extra["after"] == [0]  # follows the step that ran before it


def test_steps_added_along_the_way_follow_the_step_that_ran_before_them():
    ws = compiler.new_workspace("lp2")
    agent.track_plan(ws, tools.plan_graph(tools.validate_plan("general", [tools.PlanStep(tool="run_sql", why="a"), tools.PlanStep(tool="pin_table", why="b")])), "s")
    agent.track_plan(ws, None, None, {"type": "step", "index": 0, "label": "a", "status": "verified"})
    agent.track_plan(ws, None, None, {"type": "step", "index": 2, "label": "Design the workspace", "status": "verified"})
    agent.track_plan(ws, None, None, {"type": "step", "index": 7, "label": "extra", "status": "verified"})
    agent.track_plan(ws, None, None, {"type": "step", "index": 1, "label": "b", "status": "verified"})
    extra = next(n for n in ws["plan"]["nodes"] if n["index"] == 7)
    assert extra["after"] == [0]


async def test_design_has_a_budget_so_the_run_always_finishes():
    # Seen live: the model kept re-designing (24 rounds) and never wrote the brief.
    ws = compiler.new_workspace("cap")
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), canvas=compiler.Canvas(ws))
    note = {t.name: t for t in tools.canvas_tools(run)}["add_widget"]
    args = json.dumps({"kind": "note", "title": "x"})
    ctx = ToolContext(context=None, tool_name="add_widget", tool_call_id="t", tool_arguments=args)
    outs = [await note.on_invoke_tool(ctx, args) for _ in range(tools.MAX_DESIGN + 2)]
    assert all(o.startswith("added") for o in outs[:tools.MAX_DESIGN])
    assert outs[-1].startswith("DONE") and compiler.widget_count(ws) == tools.MAX_DESIGN


def test_closing_the_overlay_connection_stops_its_run(monkeypatch):
    from fastapi.testclient import TestClient
    from bizos import main
    stopped = []
    monkeypatch.setattr(agent.Session, "stop", lambda self: stopped.append(True))
    with TestClient(main.app) as c, c.websocket_connect("/ws"):
        pass
    assert stopped, "a run nobody is listening to must not keep calling the model"
