"""Read-only access to the mock company database."""
import re
import sqlite3
import time

from . import config


def _connect() -> sqlite3.Connection:
    if not config.DB_PATH.exists():  # fresh clone: build the deterministic mock company
        from . import seed
        seed.build(config.DB_PATH)
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def q(sql: str, *args) -> list[dict]:
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def q1(sql: str, *args):
    rows = q(sql, *args)
    return next(iter(rows[0].values())) if rows else None


def schema() -> str:
    """Compact `table(col, ...)` list the agent uses to write its own queries."""
    names = [r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return "\n".join(f"{n}({', '.join(c['name'] for c in q(f'PRAGMA table_info({n})'))})" for n in names)


_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def safe_query(sql: str, limit: int = 2000, seconds: float = 10.0) -> list[dict]:
    """Agent-written SQL: one SELECT/WITH statement, read-only by authorizer, row- and time-limited."""
    sql = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", sql) or ";" in sql:
        raise ValueError("only a single SELECT (or WITH ... SELECT) statement is allowed")
    con = _connect()
    deadline = time.monotonic() + seconds
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY)
    con.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        return [dict(r) for r in con.execute(sql).fetchmany(limit)]
    finally:
        con.close()
