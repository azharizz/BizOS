# BizOS AI

A floating overlay that reads what you're looking at (screen + Chrome DOM), lets an agent investigate it against
company data, compiles an AG Studio workspace, and lets a person approve real PayPal Sandbox actions.

```
app/
  backend/              Python · FastAPI · OpenAI Agents SDK
    bizos/
      agent.py          Session: planner agent -> user approves -> analyst agent (tools, streamed brief)
      tools.py          agent tools: verified flow steps, guarded SQL, Chrome DOM, PayPal reads, canvas design
      flows.py          7 department flows (factory + @register), each step verified
      compiler.py       the AG Studio canvas: widget factory, grid placement + compaction, default layout
      actions.py        PayPal client, action factory, @audited @requires_approval @idempotent
      bridge.py         Chrome extension hub (request/response over WebSocket)
      llm.py            model for the SDK + startup capability check + L3 vision
      main.py           /ws /ext /workspaces /actions/* /paypal/payouts/* /extension /audit /health
    tests/              61 tests
  desktop/              Electron · React · Vite (overlay pill + workspace window)
  chrome_extension/     MV3: background.js, content_script.js, popup, options (bridge URL + token)
```

## Run

```bash
cd app/backend && uv sync
cd ../desktop && npm install && npm run dev     # spawns the backend itself
```

Press **⌘⇧Space** (Ctrl+Shift+Space) over any app and ask anything. Drag the dotted grip on the pill to move the overlay. There are no role tabs: the planner works out
whether it's an executive, finance, marketing, engineering, operations, procurement or sales question (seven verified
flows), or something else entirely (`general`: the agent writes its own queries and builds the workspace from them).

- **Workspace:** the agent designs it in AG Studio (KPI tiles, charts picked for the data, a 12-column grid, at most
  one table). Asking again **edits the same workspace** live (the overlay shows "Editing · <title>"); click **New** to
  start another. Your own layout changes in "Edit layout" are saved and kept by later agent edits.
- **Voice:** the mic button uses the OS's own engine: macOS Dictation (enable it in System Settings → Keyboard →
  Dictation), Windows voice typing (Win+H, untested). **Hands-free** (footer switch): say "Hey BizOS" any time,
  even with the overlay closed, and it opens and starts dictating. The wake phrase is detected offline
  (`bizos/wake.py`, Vosk; ~40 MB model downloaded once to `~/.bizos/models`); audio never leaves the machine.
- **Screenshots (L3):** asked every time (No / Yes, once / **Always yes**). Always yes is global; turn it off from the
  mint `L3 auto` badge. Every automatic capture is shown on the plan card.

**Chrome extension:** `chrome://extensions` → Developer mode → Load unpacked → `app/chrome_extension`.
In the overlay footer click **Pair Chrome** (copies the token), paste it in the extension's Settings.
Chrome asks once to allow **local network access**: click Allow (the bridge is 127.0.0.1).

## Test

```bash
cd app/backend && uv run pytest                                    # 61 passed
cd app/desktop && npm test && npm run lint && npm run typecheck    # 22 passed (incl. extension DOM reader)
```

## PayPal Sandbox app: enable these features

At developer.paypal.com → Apps & Credentials → your app → Features:
**Payouts**, **Invoicing**, **Transaction Search**: all three enabled and verified live. Set `PAYPAL_SANDBOX_RECEIVER=<your sandbox personal account email>` in `.env` so
test payouts and invoices land in a real sandbox account (otherwise they stay UNCLAIMED on placeholder emails).
Large payouts can fail for lack of sandbox balance; the workspace polls the real payout status.

## Notes

- Without a model (no key / provider down) the same tools run deterministically.
- Windows adapter is written but **untested**. Workspaces and idempotency results live in memory;
  PayPal also dedupes on `sender_batch_id` / `PayPal-Request-Id`.
