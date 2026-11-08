# Demo footage guide (raw clips, edited later)

Story: *Product A is running low, my supplier is late, I am short on cash. Find the best supplier on this marketplace, and tell me who to pay first.*
Start page: `http://127.0.0.1:8787/demo/market` (four supplier sites with four different layouts; BizOS opens each one in Chrome, reads its quote, and flags the one with no published price).
Everything on screen is sample data except PayPal, which is the live Sandbox (balance, payout, payment request).

## Before recording (once)
1. System Settings > Privacy & Security: **Screen Recording** and **Accessibility** on for the terminal app that runs the scripts.
2. Turn on **Do Not Disturb**. Quit mail/chat apps. In Chrome press **Cmd+Shift+B** to hide the bookmarks bar, and use a window with only the demo tab.
3. Start the app: `cd desktop && npm run dev` (needs `uv` on PATH). Check the overlay pill is visible.
4. Chrome must be paired (clip 1 shows how). Check: the overlay footer says **Chrome connected**.
5. Check the Sandbox balance (PayPal developer dashboard). Each approved payout lowers it; approve only on the final take.
6. `demo/prepare.sh` puts Chrome and the workspace window inside the recorded 16:9 band.

## Commands
```
demo/record.sh start 03-ask-and-plan     # one file per clip, 1920x1080 30 fps, cursor + clicks shown
demo/record.sh stop                      # always stop: the file is only valid after this
demo/record.sh list                      # clips so far
```
Files: `~/Movies/bizos-demo-raw/`, with `clips.log` (start/stop times) for the editor.

## Two acts (one video)
Act 1: Chrome on Google, ask BizOS to explore three real supplier sites (needs no setup). Act 2: Chrome on `http://127.0.0.1:8787/demo/market`, press **New** if a workspace is open, ask the payment question.
Before recording: clear old workspaces from History (the planner reattaches to a past workspace on the same topic), hide your terminal, keep Sandbox cash for the payouts (`PAYPAL_DEMO_SCALE`).

## Clips
| # | Clip | What to do |
|---|---|---|
| 1 | connect-chrome | Overlay footer **Connect Chrome**. A page opens in Chrome and says "Connected". If Chrome asks about the local network, click Allow. Manual install: `chrome://extensions` > Developer mode > Load unpacked > `chrome_extension/`. |
| 2 | marketplace | `http://127.0.0.1:8787/demo/market`: four suppliers, each with its own quote page. |
| 3 | ask-and-plan | With that tab in front press Cmd+Shift+Space, ask the question. The plan graph appears. Approve. |
| 4 | reads-chrome | Steps verify live. BizOS selects the winning quote on the page; the **Confirm order** click asks you first. |
| 5 | workspace | AG Studio opens. Quote cost chart, pay-and-collect plan grid, scorecard, plan graph, **Where the data came from** diagram. |
| 6 | grid-and-edit | Sort, filter, group; Edit layout (drag, resize, change chart type); data sources panel shows where each field comes from. |
| 7 | approve | Press-and-hold the deposit payout and the payment request. Then open the PayPal result in Chrome. |
| 8 | follow-up | Ask a follow-up in the same workspace (it edits it). |
| 9 | audit | Audit log, then stop with Esc. |

Use **New** in the workspace window for a fresh workspace before each full take.
