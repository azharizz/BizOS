# BizOS AI

A floating overlay that reads what you're looking at (screen + Chrome DOM), lets an agent investigate it against
company data, compiles an AG Studio workspace, and lets a person approve real PayPal Sandbox actions.

```
backend/                Python · FastAPI · OpenAI Agents SDK
  bizos/
    agent.py            Session: planner agent -> user approves -> analyst agent (tools, streamed brief)
    tools.py            agent tools: verified flow steps, guarded SQL, Chrome DOM, PayPal reads, canvas design
    flows.py            7 department flows (factory + @register), each step verified; Procurement is the cash-aware hub
    seed.py             deterministic mock company (data/mock/bizos.db); built on first run if missing
    compiler.py         the AG Studio canvas: widget factory, grid placement + compaction, default layout
    actions.py          PayPal client, action factory, @audited @requires_approval @idempotent
    bridge.py           Chrome extension hub (request/response over WebSocket)
    llm.py              model for the SDK + startup capability check + L3 vision
    main.py             /ws /ext /workspaces /actions/* /paypal/payouts/* /extension /audit /health
  tests/                190 tests
desktop/                Electron · React · Vite (overlay pill + workspace window)
chrome_extension/       MV3: background.js, content_script.js, popup, options (bridge URL + token)
data/mock/bizos.db      the mock company the flows read (regenerate: cd backend && uv run python -m bizos.seed)
```

## Cash-aware procurement (the flagship flow)

With the Chrome extension connected and a marketplace page in front (sample: `http://127.0.0.1:8787/demo/market`), BizOS
opens each supplier's own site in Chrome, reads its quote whatever the layout, and asks for a quote where none is published.
It also reads a single quotes table (sample page at `http://127.0.0.1:8787/demo/sourcing`), ranks them by what they really cost (price plus the sales lost while stock is
out), selects the winner on the page (the final **Confirm order** click always asks first) and puts its deposit at the
front of the pay-and-collect plan. Without Chrome the same quotes come from a built-in copy. Every plan row has a
`source` column, and the workspace draws a **Where the data came from** diagram. Recording guide: `demo/README.md`.


Procurement is where every department's decision turns into a payment, so one flow joins them and lets PayPal be the
cash rail: **collect, hold, pay, confirm**.

| Question | Department data | PayPal |
|---|---|---|
| Which products will stock out, and which open POs feed them? | Operations (stock risk) | |
| Which suppliers are late, and what is their early-pay discount? | Procurement (scorecard, terms) | |
| What can we spend today? | Finance | **Balances** (live, withheld funds included) |
| What do customers owe? | Sales (overdue invoices) | **Invoicing** payment requests |
| Pay a supplier | | **Payouts**, press-and-hold approval |

The plan (an AG Grid, a cash-after-each-stage chart and the supplier scorecard) schedules payments against
the cash on hand with a 10% reserve: early-pay discounts first, then stock-out risk, then due date. A slow supplier
(avg delay over 3 days) is paid **on receipt**, not in advance. What cash cannot cover waits for collections: the
largest overdue invoices are chased first (a PayPal payment request each), assuming 70% arrives. A discount that ends
before collections land is shown as lost. Try: *"Which suppliers should I pay this week, and can I afford it?"* The scheduling
rule is a pure function (`flows.plan_run`), covered by tests; the cash comes from the live Sandbox balance, or a
5,000 USD demo balance when PayPal is not connected (the plan says which).

## Run

```bash
cd backend && uv sync
cd ../desktop && npm install && npm run dev     # spawns the backend itself
```

**Install as a Mac app (local build):** `cd desktop && npm run build && CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac --dir`, then
`codesign --force --deep --sign - dist/mac-arm64/BizOS.app` and copy it to `~/Applications`. It runs from this project folder (it reads the path from
`desktop/build/home.txt`, written at build time, and uses `backend/.venv`), so it is a personal build, not a redistributable one. macOS then lists it
as **BizOS** in Privacy & Security (Microphone for Hands-free).

Press **⌘⇧Space** (Ctrl+Shift+Space) over any app and ask anything. Drag the dotted grip on the pill to move the overlay. There are no role tabs: the planner works out
whether it's an executive, finance, marketing, engineering, operations, procurement or sales question (seven verified
flows), or something else entirely (`general`: the agent writes its own queries and builds the workspace from them).

- **Plan graph:** before anything runs, the overlay draws the plan as a graph (what waits for what, branches, colour
  = risk). × skips an optional step; department steps always run. The workspace keeps a live copy (Plan widget).
- **Workspace:** designed freely in AG Studio: every AG widget (charts, pivot, gauges, scatter/bubble, radar, sunburst,
  date/list/button filters, text, images), any size and position, any format option, several pages (tabs), a theme per
  workspace, plus BizOS widgets: **Plan graph**, **Diagram** (Mermaid: flowchart, gantt, timeline, sequence, mind map,
  ER...), **Ideas map** (click an idea to ask BizOS), **Summary**, **PayPal action**. Asking again **edits the same
  workspace** live; click **New** to start another. Your own changes in "Edit layout" are kept by later agent edits.
- **PayPal (general):** the agent can read anything on an approved list of PayPal endpoints (`actions.CATALOG`:
  balances, transactions, invoices, disputes, payment links, products, subscriptions...) and *propose* any change on it
  (payment link for a product, invoice, reminder, real refund, dispute reply). A proposal is an action card; only a
  person executes it, press-and-hold, audited, once per approval. Its live status (e.g. a payment link ACTIVE) shows
  on the card and the plan graph turns green. Card, vault and identity endpoints are not on the list.
- **Voice:** the mic button uses the OS's own engine: macOS Dictation (enable it in System Settings → Keyboard →
  Dictation), Windows voice typing (Win+H, untested). **Hands-free** (footer switch): say "Hey BizOS" any time,
  even with the overlay closed, and it opens and starts dictating. It's a spoken conversation: after the chime, say
  the request; a 2 s pause sends it, the plan runs without a click, the answer is read aloud (`say`), and it listens
  again for a follow-up (8 s of silence ends it). Steps that can lose work (closing an app without saving) and
  screenshots are asked aloud: say "confirm"/"yes" or "cancel"/"no". PayPal money actions stay press-and-hold. The wake phrase is detected offline
  (`bizos/wake.py`, Vosk; ~40 MB model downloaded once to `~/.bizos/models`); audio never leaves the machine.
- **Screenshots (L3):** asked every time (No / Yes, once / **Always yes**). Always yes is global; turn it off from the
  mint `L3 auto` badge. Every automatic capture is shown on the plan card.

**What the agent can operate** (each step shows live; steps that send, submit, buy or delete always ask first, by
click or by voice):
- **Chrome pages** (extension 0.3): numbered page controls; click, type, choose, scroll. Search boxes submit freely;
  other submits and risky buttons ask. Never types into password or payment fields.
- **Mac apps** (Accessibility permission, once): read an app's controls and on-screen text, click by name, menus,
  type (via paste, any language), keys, your Shortcuts, clipboard. Return in messaging apps, Shortcuts and reading
  the clipboard ask first. Never operates terminals, password managers, System Settings or BizOS itself. Finder works:
  moving to Trash and Delete ask first.
- **Windows** (written, not yet run on a PC): the same app tools through Windows UI Automation + SendKeys; your
  automations live in a `BizOS Shortcuts` folder in your user folder (.lnk, .url, .bat, .cmd, .ps1, always asked);
  the overlay stays unfocusable until you use it. Never operates PowerShell/cmd/Terminal, the registry, Task Manager,
  Settings or the credential store.
- **Stop anytime**: the pill's stop button, Esc, or "Hey BizOS, stop". Finished steps are kept.

**Memory** (`~/.bizos/memory.db`, local only, SQLite full-text search): every workspace is saved and reloaded
after a restart (History menu in the workspace window); the agent remembers facts you tell it ("remember that…")
and can reopen a past workspace ("continue my LLM pricing workspace").

**Chrome extension:** `chrome://extensions` → Developer mode → Load unpacked → `chrome_extension`.
In the overlay footer click **Pair Chrome** (copies the token), paste it in the extension's Settings.
Chrome asks once to allow **local network access**: click Allow (the bridge is 127.0.0.1).

## Exploring, deciding, paying, scheduling

- **`explore_site`**: crawls one real site in your Chrome within limits (up to 25 pages, about 150 s): uses the site's own search, follows the
  links most relevant to the goal and pagination, reads prices, tables, MOQ, lead time, terms and certificates. Navigation only; it never
  clicks buttons that submit, buy or send. Sites that need a sign-in (alibaba.com, aliexpress.com, faire.com...) are skipped.
- **`page_do`**: operates the page you are on by control label, several steps at once (type, choose, click, scroll). Risky controls ask first.
- **`evaluate_options`**: requirements (weights, must-haves) against what pages actually state, as a weighted matrix with pros and cons and an
  "evidence known" share. A must-have nobody published is "unconfirmed", not a failure.
- **Calendar**: the pay-and-collect plan proposes one action that puts its deadlines on your Mac Calendar with alarms. It writes an `.ics`
  and hands it to Calendar, so no macOS permission prompt is needed; Calendar asks which calendar to use.
- **PayPal cash gate**: the balance is PayPal's snapshot minus payouts you sent after it (unsettled payouts hold their money); a payout is
  re-checked before it is sent and a refusal is explained. `PAYPAL_SANDBOX_RECEIVER` should be a Sandbox personal account so test payouts
  settle. If the Sandbox balance is small, `PAYPAL_DEMO_SCALE=0.1` sends 10% of each payout and the plan cash scales up to match (the
  action card says so).

## Test

```bash
cd backend && uv run pytest                                    # 190 passed, 10 skipped (wake word needs macOS + model)
cd desktop && npm test && npm run lint && npm run typecheck    # 62 passed (incl. extension DOM reader)
```

Copy your keys into a repo-root `.env` (`AGENT_API_KEY`, `AGENT_BASE_URL`, `AGENT_MODEL`, `PAYPAL_CLIENT_ID`,
`PAYPAL_CLIENT_SECRET`, `AG_STUDIO_LICENSE_KEY`; `PAYPAL_BASE_URL` defaults to the Sandbox). Node 22.12+ is needed for
`npm install` on recent npm versions.

## PayPal Sandbox app: enable these features

At developer.paypal.com → Apps & Credentials → your app → Features:
**Payouts**, **Invoicing**, **Transaction Search** (enabled and verified live), plus **Payment Links & Buttons** for
payment links (and Disputes / Subscriptions if you want those). `PAYPAL_RETURN_URL` sets where buyers land after paying. Set `PAYPAL_SANDBOX_RECEIVER=<your sandbox personal account email>` in `.env` so
test payouts and invoices land in a real sandbox account (otherwise they stay UNCLAIMED on placeholder emails).
Large payouts can fail for lack of sandbox balance; the workspace polls the real payout status.

## Notes

- Without a model (no key / provider down) the same tools run deterministically.
- Windows adapter is written but **untested**. Workspaces and idempotency results live in memory;
  PayPal also dedupes on `sender_batch_id` / `PayPal-Request-Id`.
