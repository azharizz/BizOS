"""Put payment deadlines on the user's Calendar, with alarms, without needing any macOS permission prompt.

BizOS writes an .ics file (events with display alarms) and hands it to Calendar, which asks which calendar to add them to;
then it opens Calendar on the first date. macOS only.
"""
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(events: list[dict]) -> str:
    """events: [{title, start: 'YYYY-MM-DDTHH:MM', minutes, notes, alarm_minutes}]. Floating local times."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BizOS//Payment deadlines//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        start = datetime.fromisoformat(e["start"])
        end = start + timedelta(minutes=int(e.get("minutes", 30)))
        lines += ["BEGIN:VEVENT", f"UID:{uuid.uuid4()}@bizos", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
                  f"SUMMARY:{_esc(e['title'])}", f"DESCRIPTION:{_esc(e.get('notes', ''))}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(e['title'])}",
                  f"TRIGGER:-PT{int(e.get('alarm_minutes', 60))}M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def schedule(events: list[dict]) -> dict:
    """Hand the events to Calendar; the user confirms the import in Calendar's own dialog."""
    if not events:
        raise ValueError("no events to schedule")
    ics = build_ics(events)
    if sys.platform != "darwin":
        return {"status": "ICS_ONLY", "reference": f"{len(events)} events", "ics": ics}
    path = Path(tempfile.mkdtemp(prefix="bizos-cal-")) / "BizOS payment deadlines.ics"
    path.write_text(ics)
    subprocess.run(["open", "-a", "Calendar", str(path)], check=True, timeout=15)
    return {"status": "SCHEDULED", "reference": f"{len(events)} events with alarms", "file": str(path)}
