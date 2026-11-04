from bizos import compiler, memory


def make_ws(id_, title, headline="", narrative=""):
    ws = compiler.new_workspace(id_)
    ws.update(title=title, headline=headline, narrative=narrative, complete=True)
    ws["runs"].append({"goal": f"about {title}", "flow": "general"})
    return ws


def test_workspaces_survive_a_restart_and_can_be_searched(tmp_path):
    db = memory.Memory(tmp_path / "m.db")
    db.save_workspace(make_ws("a1", "Top 10 cheapest LLMs", "Claude Haiku 5.5 is the cheapest"))
    db.save_workspace(make_ws("b2", "Overdue invoices", "Acme owes $12K"))
    again = memory.Memory(tmp_path / "m.db")  # a new process
    assert set(again.load_workspaces()) == {"a1", "b2"}
    assert again.load_workspaces()["a1"]["headline"] == "Claude Haiku 5.5 is the cheapest"
    assert [w["id"] for w in again.search("llm")] == ["a1"]
    assert [w["id"] for w in again.search("acme invoices")] == ["b2"]
    assert {w["id"] for w in again.recent()} == {"a1", "b2"}


def test_saving_again_updates_and_delete_removes(tmp_path):
    db = memory.Memory(tmp_path / "m.db")
    db.save_workspace(make_ws("a1", "Old title"))
    db.save_workspace(make_ws("a1", "New title"))
    assert [w["title"] for w in db.recent()] == ["New title"] and db.search("old") == []
    db.delete_workspace("a1")
    assert db.load_workspaces() == {} and db.search("new") == []


def test_facts_are_remembered_recalled_and_forgotten(tmp_path):
    db = memory.Memory(tmp_path / "m.db")
    fid = db.remember("Our fiscal year starts in April")
    db.remember("The user prefers charts over tables")
    assert [f["text"] for f in db.recall("fiscal year")] == ["Our fiscal year starts in April"]
    assert len(db.facts()) == 2
    db.forget(fid)
    assert db.recall("fiscal") == [] and len(db.facts()) == 1


def test_search_tolerates_any_user_text(tmp_path):
    db = memory.Memory(tmp_path / "m.db")
    db.save_workspace(make_ws("a1", "Q3 revenue"))
    for q in ['"', "AND OR NOT", "revenue)", "*", ""]:  # FTS syntax characters must not raise
        db.search(q)
    assert [w["id"] for w in db.search('revenue"')] == ["a1"]


async def test_runs_are_saved_and_a_past_workspace_can_be_reopened(tmp_path, monkeypatch):
    from bizos import agent, flows, tools
    db = memory.Memory(tmp_path / "m.db")
    old = make_ws("old1", "Top 10 cheapest LLMs")
    session = agent.Session({"old1": old}, memory=db)
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), canvas=compiler.Canvas(old))
    session.finish(run, old, "**Haiku is cheapest.**")
    assert "old1" in db.load_workspaces()  # saved when a run finishes
    session.ws_id = None  # a later session, nothing open

    async def fake_plan(ask):
        return {"flow": "general", "subject": "s", "rationale": "r", "steps": [], "needs_screenshot": False, "workspace": "old1"}
    monkeypatch.setattr(session, "plan_with_agent", fake_plan)
    monkeypatch.setattr(agent.llm, "model", lambda: object())
    plan = await session.make_plan({"goal": "continue my LLM pricing workspace", "context": {}})
    assert session.offer(plan)["plan"]["editing"]["title"] == "Top 10 cheapest LLMs"
    assert session.use_workspace(plan) is old and session.ws_id == "old1"


async def test_memory_tools_remember_recall_forget(tmp_path):
    from bizos import flows, tools
    db = memory.Memory(tmp_path / "m.db")
    db.save_workspace(make_ws("w9", "Overdue invoices", "Acme owes $12K"))
    events = []
    run = tools.Run(goal="g", context={}, flow=flows.make_flow("general"), emit=events.append)
    out = await tools.remember_tool(run, db, "Our fiscal year starts in April")
    assert "Remembered" in out and events[-1]["status"] == "verified"
    found = tools.recall_tool(db, "fiscal year invoices")
    assert "fiscal year starts in April" in found and "w9" in found
    fid = db.facts()[0]["id"]
    assert "Forgot" in tools.forget_tool(db, fid) and db.facts() == []


def test_planner_and_analyst_see_what_is_remembered(tmp_path):
    from bizos import agent
    db = memory.Memory(tmp_path / "m.db")
    db.remember("Our fiscal year starts in April")
    db.save_workspace(make_ws("w9", "Overdue invoices"))
    brief = agent.Session({}, memory=db).memory_brief("fiscal year revenue")
    assert "fiscal year starts in April" in brief and "w9" in brief and "Overdue invoices" in brief
    assert agent.Session({}).memory_brief("x") == ""
