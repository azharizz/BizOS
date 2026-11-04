"""Long-term memory, local only: one SQLite file (~/.bizos/memory.db).

- Workspaces: every workspace is saved as it changes and reloaded at startup, so nothing is lost on restart and
  old ones can be reopened and continued.
- Facts: short things the agent was told or learned to keep ("our fiscal year starts in April").
Search is SQLite's built-in full-text index (FTS5): no embeddings, no extra model, nothing leaves the machine.
"""
import json
import re
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, title TEXT, headline TEXT, updated REAL, body TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS workspaces_fts USING fts5(id UNINDEXED, title, headline, narrative, goals);
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, text);
"""


def _match(query: str) -> str:
    """User text -> a safe FTS query: plain words, any of them, prefix-matched."""
    words = re.findall(r"\w+", query.lower())[:12]
    return " OR ".join(f'"{w}"*' for w in words)


class Memory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------------- workspaces
    def save_workspace(self, ws: dict):
        goals = " ".join(r.get("goal", "") for r in ws.get("runs", []))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO workspaces VALUES (?,?,?,?,?)",
                            (ws["id"], ws.get("title", ""), ws.get("headline", ""), time.time(), json.dumps(ws)))
            self.db.execute("DELETE FROM workspaces_fts WHERE id = ?", (ws["id"],))
            self.db.execute("INSERT INTO workspaces_fts VALUES (?,?,?,?,?)",
                            (ws["id"], ws.get("title", ""), ws.get("headline", ""), ws.get("narrative", ""), goals))

    def delete_workspace(self, ws_id: str):
        with self.db:
            self.db.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
            self.db.execute("DELETE FROM workspaces_fts WHERE id = ?", (ws_id,))

    def load_workspaces(self) -> dict[str, dict]:
        return {r["id"]: json.loads(r["body"]) for r in self.db.execute("SELECT id, body FROM workspaces")}

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute("SELECT id, title, headline, updated FROM workspaces ORDER BY updated DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not (q := _match(query)):
            return []
        rows = self.db.execute("""SELECT w.id, w.title, w.headline, w.updated FROM workspaces_fts f JOIN workspaces w ON w.id = f.id
                                  WHERE workspaces_fts MATCH ? ORDER BY rank LIMIT ?""", (q, limit))
        return [dict(r) for r in rows]

    # ---------------- facts
    def remember(self, text: str) -> int:
        with self.db:
            fid = self.db.execute("INSERT INTO facts (text, created) VALUES (?, ?)", (text.strip()[:500], time.time())).lastrowid
            self.db.execute("INSERT INTO facts_fts VALUES (?, ?)", (fid, text.strip()[:500]))
        return fid

    def forget(self, fact_id: int):
        with self.db:
            self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self.db.execute("DELETE FROM facts_fts WHERE id = ?", (fact_id,))

    def facts(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT id, text FROM facts ORDER BY created DESC LIMIT ?", (limit,))]

    def recall(self, query: str, limit: int = 8) -> list[dict]:
        if not (q := _match(query)):
            return []
        rows = self.db.execute("""SELECT f.id, f.text FROM facts_fts x JOIN facts f ON f.id = x.id
                                  WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?""", (q, limit))
        return [dict(r) for r in rows]
