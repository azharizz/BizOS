"""Payment deadlines on the Calendar: an .ics with alarms, handed to the Calendar app (no permission prompt needed)."""
import asyncio

from bizos import actions, flows, mac

EVENTS = [{"title": "Pay PO #1, Kestrel; saves $12", "start": "2026-11-08T17:00", "minutes": 15, "notes": "line1\nline2", "alarm_minutes": 120},
          {"title": "Chase invoice #84", "start": "2026-11-10T09:00"}]


def test_ics_has_one_event_with_an_alarm_each_and_escapes_text():
    ics = mac.build_ics(EVENTS)
    assert ics.count("BEGIN:VEVENT") == 2 and ics.count("BEGIN:VALARM") == 2
    assert "SUMMARY:Pay PO #1\\, Kestrel\\; saves $12" in ics and "DESCRIPTION:line1\\nline2" in ics
    assert "DTSTART:20261108T170000" in ics and "DTEND:20261108T171500" in ics and "TRIGGER:-PT120M" in ics and "TRIGGER:-PT60M" in ics


def test_schedule_opens_calendar_with_the_ics_file(monkeypatch):
    calls = []
    monkeypatch.setattr(mac.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(mac.sys, "platform", "darwin")
    out = mac.schedule(EVENTS)
    assert out["status"] == "SCHEDULED" and out["reference"].startswith("2 events")
    assert calls[0][:3] == ["open", "-a", "Calendar"] and calls[0][3].endswith(".ics")
    assert len(calls) == 1


def test_calendar_action_goes_through_the_same_approval_and_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(mac.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(mac.sys, "platform", "darwin")
    engine = actions.ActionEngine(None, tmp_path / "audit.jsonl")
    spec = {"id": "calendar-deadlines", "kind": "calendar", "label": "x", "amount": 0, "currency": "USD", "recipient": "Calendar", "events": EVENTS}
    prev = engine.preview("w", spec)
    assert prev["mode"] == "local"
    res = asyncio.run(engine.execute("w", spec, prev["idempotency_key"], "me"))
    assert res["status"] == "SCHEDULED" and engine.log()[-1]["outcome"] == "executed"


def test_procurement_proposes_dated_deadlines_with_alarms():
    f = flows.make_flow("procurement").run({})
    cal = next(a for a in f.actions if a["kind"] == "calendar")
    assert 1 <= len(cal["events"]) <= 5 and all("start" in e and e["alarm_minutes"] for e in cal["events"])
    assert cal["events"] == sorted(cal["events"], key=lambda e: e["start"])
