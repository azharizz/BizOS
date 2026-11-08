"""Model access for any OpenAI-compatible provider (AGENT_BASE_URL / AGENT_API_KEY / AGENT_MODEL).

`model()` feeds the OpenAI Agents SDK (agentic planner + analyst). `check_capabilities()` and
`read_screenshot()` are single calls: the startup check and L3 vision.
"""
import logging

import httpx
from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from . import config

log = logging.getLogger("bizos.llm")
set_tracing_disabled(True)  # traces would go to OpenAI; this provider isn't OpenAI
caps = {"model": config.AGENT_MODEL, "tools": None, "vision": None, "error": None}
_PIXEL = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQAQMAAAAlPW0iAAAAA1BMVEX/AAAZ4gk3AAAADElEQVQI12NgIA0AAAAwAAHHqoWOAAAAAElFTkSuQmCC"  # 16x16 #ff0000


def model() -> OpenAIChatCompletionsModel | None:
    if not (config.AGENT_API_KEY and config.AGENT_BASE_URL and config.AGENT_MODEL):
        return None
    client = AsyncOpenAI(base_url=config.AGENT_BASE_URL, api_key=config.AGENT_API_KEY, timeout=240)
    return OpenAIChatCompletionsModel(model=config.AGENT_MODEL, openai_client=client)


async def _chat(**body) -> dict:
    async with httpx.AsyncClient(base_url=config.AGENT_BASE_URL, timeout=240,
                                 headers={"Authorization": f"Bearer {config.AGENT_API_KEY}"}) as c:
        r = await c.post("/chat/completions", json={"model": config.AGENT_MODEL, **body})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


async def check_capabilities() -> dict:
    """Startup check: tool calling and image input. Missing vision disables L3 screen reading."""
    tool = {"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}
    try:
        msg = await _chat(messages=[{"role": "user", "content": "Call ping with ok=true."}], tools=[tool])
        caps["tools"] = bool(msg.get("tool_calls"))
    except Exception as e:
        caps["tools"], caps["error"] = False, f"model unreachable: {e}"
    try:  # the image is pure red; a provider that silently drops images can't say so
        msg = await _chat(messages=[{"role": "user", "content": [
            {"type": "text", "text": "What colour is this image? One word."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PIXEL}"}}]}])
        caps["vision"] = "red" in (msg.get("content") or "").lower()
    except Exception:
        caps["vision"] = False
    if not caps["vision"]:
        caps["error"] = caps["error"] or f"{config.AGENT_MODEL} has no image input: L3 screen capture is disabled."
    if caps["error"]:
        log.error("CAPABILITY CHECK: %s", caps["error"])
    return caps


async def read_screenshot(png_b64: str) -> str:
    # No max_tokens anywhere: reasoning models think ~3k tokens before answering, and a cap returns nothing.
    msg = await _chat(messages=[{"role": "user", "content": [
        {"type": "text", "text": "Transcribe the business-relevant text, figures and chart readings in this screenshot. "
                                 "Plain text. Mark any figure you are unsure of with (?)."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}}]}])
    return msg.get("content") or ""
