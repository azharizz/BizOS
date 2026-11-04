"""BizOS backend: WebSocket agent loop + REST for workspaces and approved actions.

    uv run uvicorn bizos.main:app --port 8787

If BIZOS_TOKEN is set (the desktop app sets a random one per launch), every request must carry it,
so other local software and web pages can't drive the action endpoints.
"""
import asyncio
import html
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import actions, agent, bridge, config, llm, memory

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("BIZOS_TOKEN", "")
MEMORY = memory.Memory(config.MEMORY_PATH)
WORKSPACES: dict[str, dict] = MEMORY.load_workspaces()  # everything from earlier sessions
paypal = (actions.PayPal(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET, config.PAYPAL_BASE_URL)
          if config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET else None)
engine = actions.ActionEngine(paypal, config.AUDIT_PATH)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(llm.check_capabilities())
    yield
    task.cancel()


app = FastAPI(title="BizOS", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_token(request: Request, call_next):
    public = request.url.path == "/pair"  # guarded by its own single-use code instead
    if TOKEN and not public and request.method != "OPTIONS" and request.headers.get("x-bizos-token") != TOKEN:
        return JSONResponse({"detail": "bad token"}, status_code=401)
    return await call_next(request)


class ActionRef(BaseModel):
    workspace_id: str
    action_id: str


class Approval(ActionRef):
    idempotency_key: str
    approved_by: str


def _action(ref: ActionRef) -> dict:
    ws = WORKSPACES.get(ref.workspace_id) or {}
    spec = next((a for a in ws.get("actions", []) if a["id"] == ref.action_id), None)
    if not spec:
        raise HTTPException(404, "unknown action")
    return spec


@app.get("/health")
def health():
    return {"ok": True, "capabilities": llm.caps, "paypal": "sandbox" if paypal else "preview-only"}


@app.get("/workspaces")
def workspaces(q: str = ""):
    """History: recent workspaces, or the ones matching a search."""
    return MEMORY.search(q, limit=20) if q else MEMORY.recent()


@app.get("/memory/facts")
def facts():
    return MEMORY.facts(100)


@app.delete("/memory/facts/{fact_id}")
def forget(fact_id: int):
    MEMORY.forget(fact_id)
    return {"ok": True}


@app.get("/workspaces/{ws_id}")
def workspace(ws_id: str):
    if ws_id not in WORKSPACES:
        raise HTTPException(404, "unknown workspace")
    return WORKSPACES[ws_id]


@app.get("/workspaces/{ws_id}/meta")
def workspace_meta(ws_id: str):
    """Cheap poll target: the window refetches the full canvas only when agent_version moves."""
    ws = workspace(ws_id)
    return {k: ws[k] for k in ("id", "title", "headline", "narrative", "complete", "actions", "risks", "agent_version", "runs")} | {
        "sources": [s["id"] for s in ws["data"]["sources"]]}


class StateIn(BaseModel):
    state: dict
    base_version: int  # the agent_version the window rendered; older saves would erase newer agent edits


@app.put("/workspaces/{ws_id}/state")
def save_state(ws_id: str, body: StateIn):
    """The user's own layout edits in AG Studio, so the agent's next edit builds on them."""
    ws = workspace(ws_id)
    if body.base_version != ws["agent_version"]:
        raise HTTPException(409, "the agent changed this workspace since; reload")
    pages = body.state.get("pages")
    if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
        raise HTTPException(422, "state needs pages")
    ws["state"] = body.state
    MEMORY.save_workspace(ws)
    return {"ok": True}


@app.post("/actions/preview")
def preview(ref: ActionRef):
    return engine.preview(ref.workspace_id, _action(ref))


@app.post("/actions/execute")
async def execute(body: Approval):
    try:
        return await engine.execute(body.workspace_id, _action(body), body.idempotency_key, body.approved_by)
    except actions.ApprovalRequired as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/paypal/payouts/{batch_id}")
async def payout_status(batch_id: str):
    """Live PayPal status of an approved payout (PENDING -> SUCCESS / UNCLAIMED / FAILED)."""
    if not paypal or not batch_id.isalnum():
        raise HTTPException(404, "unknown payout")
    try:
        return await paypal.payout_status(batch_id)
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/extension")
def extension():
    """Pairing info for the Chrome extension (this endpoint is behind the app token)."""
    version = bridge.hub.info.get("version", "")
    return {"connected": bridge.hub.connected, "token": bridge.extension_token(), "bridge_url": "ws://127.0.0.1:8787/ext",
            "browser": bridge.hub.info.get("ua", ""), "version": version,
            "outdated": bridge.hub.connected and version != EXTENSION_VERSION}


EXTENSION_VERSION = json.loads((config.ROOT / "app" / "chrome_extension" / "manifest.json").read_text())["version"]
PAIR_CODES: dict[str, float] = {}
PAIR_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Connect BizOS</title>
<meta name="bizos-pair" content="{token}" data-bridge="ws://127.0.0.1:8787/ext">
<style>body{{margin:0;height:100vh;display:grid;place-items:center;background:#0e0f0c;color:#ece8df;
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif}}main{{max-width:420px;text-align:center}}
h1{{font-size:22px;letter-spacing:-.02em;margin:18px 0 6px}}p{{color:#8c877b;margin:6px 0}}b{{color:#ece8df}}
#pair-status{{color:#4dffb2;font-weight:600}}code{{color:#ece8df;font-size:12px}}</style></head><body><main>
<svg width="56" height="56" viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="15" fill="#1b1d18"/>
<g fill="#ECE8DF"><rect x="16" y="13" width="7.5" height="38" rx="3.75"/><path fill-rule="evenodd" d="M21.25 38.5a14.25 14.25 0 1 0 28.5 0a14.25 14.25 0 1 0 -28.5 0ZM28.75 38.5a6.75 6.75 0 1 0 13.5 0a6.75 6.75 0 1 0 -13.5 0Z"/></g>
<circle cx="48" cy="16" r="4.75" fill="#4DFFB2"/></svg>
<h1>Connecting Chrome to BizOS</h1><p id="pair-status">Waiting for the BizOS extension…</p>
<p id="pair-help">If nothing happens in a few seconds, install the extension first:<br>
<b>chrome://extensions</b> → Developer mode → <b>Load unpacked</b> → <code>{folder}</code>, then click Connect Chrome again.</p>
<p>If Chrome asks to access devices on your local network, click <b>Allow</b>.</p></main></body></html>"""


@app.post("/extension/pair")
def pair_link():
    """One-click pairing: a single-use link (2 minutes) that the overlay opens in Chrome."""
    now = time.time()
    for code in [c for c, t in PAIR_CODES.items() if t < now]:
        del PAIR_CODES[code]
    code = secrets.token_urlsafe(16)
    PAIR_CODES[code] = now + 120
    return {"url": f"http://127.0.0.1:8787/pair?code={code}"}


@app.get("/pair", response_class=HTMLResponse)
def pair_page(code: str = ""):
    if PAIR_CODES.pop(code, 0) < time.time():
        return HTMLResponse("<p style='font-family:system-ui'>This pairing link has expired. Click <b>Connect Chrome</b> in BizOS again.</p>", 403)
    folder = config.ROOT / "app" / "chrome_extension"
    return PAIR_PAGE.format(token=html.escape(bridge.extension_token()), folder=html.escape(str(folder)))


@app.get("/audit")
def audit():
    return engine.log()


@app.websocket("/ws")
async def ws(socket: WebSocket):
    if TOKEN and socket.query_params.get("token") != TOKEN:
        await socket.close(code=4401)
        return
    await socket.accept()
    lock = asyncio.Lock()

    async def send(event: dict):
        async with lock:  # agent events and desktop calls share one socket
            await socket.send_json(event)

    session = agent.Session(WORKSPACES, paypal, send, MEMORY)
    inbox: asyncio.Queue = asyncio.Queue()

    async def read():  # keeps reading during a run, so desktop replies (client_result) arrive mid-stream
        try:
            while True:
                msg = await socket.receive_json()
                if msg.get("type") == "client_result":
                    session.resolve(msg)
                elif msg.get("type") == "stop":  # handled here, not queued: the run it stops is what the queue waits on
                    session.stop()
                else:
                    inbox.put_nowait(msg)
        except WebSocketDisconnect:
            inbox.put_nowait(None)

    reader = asyncio.create_task(read())
    try:
        while (msg := await inbox.get()) is not None:
            async for event in session.handle(msg):
                await send(event)
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()


@app.websocket("/ext")
async def extension_socket(socket: WebSocket):
    if socket.query_params.get("token") != bridge.extension_token():
        await socket.close(code=4401)
        return
    await socket.accept()
    try:
        while True:
            msg = await socket.receive_json()
            if msg.get("type") == "hello":
                bridge.hub.attach(socket, msg)
                await socket.send_json({"type": "welcome"})
            elif "id" in msg:
                bridge.hub.resolve(msg)
    except WebSocketDisconnect:
        pass
    finally:
        bridge.hub.detach(socket)
