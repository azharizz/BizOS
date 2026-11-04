"""Chrome extension bridge: the extension connects here and answers DOM requests for the active tab.

Page content is untrusted, exactly like screen text: it is data for the agent, never instructions.
"""
import asyncio
import itertools
import secrets
from pathlib import Path

from . import config


def extension_token() -> str:
    """Stable pairing token (env wins), so the extension doesn't need re-pairing on every launch."""
    if config.EXTENSION_TOKEN:
        return config.EXTENSION_TOKEN
    path = Path.home() / ".bizos" / "extension-token"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(24))
        path.chmod(0o600)
    return path.read_text().strip()


class BridgeError(Exception):
    pass


class Hub:
    def __init__(self):
        self.socket = None
        self.info: dict = {}
        self._ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self.socket is not None

    def attach(self, socket, info: dict):
        self.socket, self.info = socket, info  # ponytail: one browser at a time; newest wins

    def detach(self, socket):
        if self.socket is socket:  # an older connection closing never drops the current one
            self.socket = None
            for f in self._waiting.values():
                f.cancel()
            self._waiting.clear()

    def resolve(self, msg: dict):
        f = self._waiting.pop(msg.get("id"), None)
        if f and not f.done():
            f.set_result(msg)

    async def request(self, op: str, args: dict | None = None, timeout: float = 6) -> dict:
        if not self.socket:
            raise BridgeError("Chrome extension is not connected")
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._waiting[rid] = fut
        await self.socket.send_json({"id": rid, "op": op, "args": args or {}})
        try:
            reply = await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._waiting.pop(rid, None)
            raise BridgeError(f"Chrome did not answer {op} in {timeout:.0f}s")
        if not reply.get("ok"):
            raise BridgeError(reply.get("error") or f"{op} failed")
        return reply["result"]


hub = Hub()
