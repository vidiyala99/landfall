# Landfall

Landfall is a factory that makes a small business's website readable and usable by personal AI agents (ChatGPT, Claude, Meta Muse, Grok). A goal goes in ("people should be able to order a cake for Saturday pickup"); parallel agent lanes scan the site, do real customer tasks on it, build fixes on a mirror, rerun the same tasks on the fixed copy, and hand the owner a plain-English before/after report.

Built for the Personal Agents Hackathon (tokens&, San Francisco, 2026-11-20). Design notes: `docs/DESIGN.md`.

## The problem

Personal agents now find, compare and book things for people. A bakery in Ohio, a plumber in Iowa or a florist in Kentucky cannot tell whether those agents can read or use their site, and nobody tells them. Landfall measures it with real agents doing real tasks, then fixes what it can.

## How it works

1. **Read** (`landfall/scan.py`): static scan with receipts: robots.txt rules for AI agents, llms.txt, schema.org JSON-LD, content visible without JavaScript, bot challenges, form labels, alt text, sitemap.
2. **Do** (`landfall/agent_run.py`): two kinds of agents attempt customer tasks, read-only: a browser agent (Playwright) and a no-JavaScript reader (curl, raw HTML). Each task ends `done`, `partial` or `failed`, with steps and saved pages.
3. **Find** (`agent_run.py find`): ask an agent the customer's question ("florist in Beaver Dam Kentucky with same day delivery") and record whether the business is recommended.
4. **Mirror** (`landfall/mirror.py`): save an offline copy of the site.
5. **Fix** (`landfall/fix.py`): JSON-LD, llms.txt, a robots.txt patch, form labels, alt text, an agent card, and `needs-owner.md` (questions for facts the site never states). Applied only to the mirror.
6. **Verify** (`landfall/pipeline.py`): rerun Read and Do on the fixed mirror, same tasks, before/after scores.
7. **Report** (`landfall/report.py`): one self-contained HTML page for the owner.

The agent never gets the last word: `honesty_check` in `agent_run.py` refuses a "done" claim it cannot match to a saved page, and `fix.py` never invents a business fact (unknowns become owner questions).

Lanes run on Agent37 sandboxes (`scripts/lane_run.sh`). Amplitude events (`landfall/telemetry.py`) and Cognee memory across audits (`landfall/memory.py`) are wired in.

## Findings from real runs (2026-11-20)

Scores are Landfall's own 0 to 100 scale. Source: `runs/<slug>/result.json` (the `runs/` folder is gitignored; the Floranext table is committed in `evidence/`).

| Site | Read, before to after | Do (browser), before to after | Visible when an agent is asked the customer's question |
| - | - | - | - |
| Small Town Blooms, Beaver Dam KY (florist) | 68 to 92 | 0/4 to 2/4 done | no |
| Hanna Plumbing & Heating, Marion IA | 84 to 96 | 4/4 to 3/4 done | no |
| 3 C's Bakery, New Franklin OH | 70 to 78 | 1/4 to 1/4 done | no |
| Kingston Barber Shop, Kingston TN | 56 to 72 | 3/4 to 3/4 done | yes |
| Saam Veterinary Clinic, Basin WY | 82 to 92 | 3/4 to 3/4 done | yes |

What the numbers mean, with the caveats:

- **Headline: AI assistants can see your products but not your prices.** On smalltownbloomsky.com the raw HTML contains product names but zero prices; prices are filled in by script (`data-bind="text: price"`). Verified three ways. (1) ChatGPT, asked live for the first arrangement's name and price, named "Back2School Special" and said the price was "not displayed in the accessible page content... I don't want to invent a price." (2) A real browser after scrolling shows $69.99 to $95.00 (for example $80.00, $85.00, $95.00, $69.99, $79.99). (3) Muse (Meta's personal agent, full browser) saw $95 and $59.99 and walked to checkout ($112.69 total for the $95 item). Landfall's scanner now flags it: "Prices (e.g. $45.00, $22.00, $80.00, $85.00) appear only after JavaScript runs" (`runs/small-town-blooms/scan.json`).
- **Per-assistant access check** (`landfall/access.py`, `runs/small-town-blooms/access.json`), smalltownbloomsky.com by user agent: `ChatGPT-User` 403, `OAI-SearchBot` 403, Meta's `meta-externalfetcher` 403, `Claude-User` 200, `Perplexity-User` 200, Chrome 200. Hanna Plumbing and 3 C's Bakery: every assistant identity gets 200. This is a narrow fact about those user-agent strings from our machine. It does not mean ChatGPT cannot reach the site: live, ChatGPT opened smalltownbloomsky.com and named the first product, so its real fetcher evidently differs from our test in IP or identity.
- **Floranext florists, user-agent test** (`evidence/floranext-agent-wall.txt`, GET / by user agent, 2026-11-20): `ChatGPT-User` and `PerplexityBot` get HTTP 403 (CloudFront "Request blocked") on all 4 florists tested (flowersbyedie.com, sherwoodfloristny.com, anewleaffloristinc.com, smalltownbloomsky.com), while Chrome and `Claude-User` get a 301. `PerplexityBot` is Perplexity's crawler; its user-facing agent `Perplexity-User` gets 200. One request per agent name, so it shows the response to that string, not why, and not what a real assistant can reach.
- **Small Town Blooms:** the real site gave 403 to both of our agents (0/4 tasks). On the mirror, the no-JavaScript reader got 2 done and 2 partial; the browser agent got 2 done, 1 partial, 1 failed. The mirror only shows what the site would allow with the 403 lifted.
- **Why Landfall and not the assistant itself:** asked the owner question without Landfall, Muse said customers' assistants "can likely" shop the site and that ChatGPT sends shoppers to the merchant checkout. It tested only itself. Your assistant can only test itself. Landfall tests every assistant your customers use, with receipts.
- **Hanna Plumbing:** the raw HTML shows (319) 377-2809. A manual browser check showed a different number (a call-tracking swap), so calls from assistants that read raw HTML skip the tracking numbers. That manual observation is not saved in `runs/`. The Do score fell from 4/4 to 3/4 on the mirror because the mirror's `/contact` returned 404: a limit of the mirror, not a regression on the live site.
- **3 C's Bakery:** hours, prices and lead time are not on the site in any form. Landfall does not invent them; it writes 5 questions for the owner (`needs-owner.md`). Task scores stay at 1/4 until the owner answers.
- **Visibility** (`find.json`) is a point-in-time web search by one agent. Real assistants will not re-index within hours, so "after" is shown on the mirror only.

Firedrill (`firedrill/RESULTS.md`): drill 1 scored 89/100 on "never claims an order or booking, never repeats the injected claim" and found our wrapper presented the agent's own words as a website quote; fixed. Drill 2 scored 91.5/100 and found dangling "I ignored it" fragments; fixed. Drill 3 is pending. In both drills the agent never booked anything and never repeated the planted injection.

## Where this goes: digital workers

Landfall is the start of "digital workers" for owners. Today the factory makes a shop visible and shoppable to every customer's assistant, and the first worker lists the owner's products with their real prices for assistants (`landfall/products.py`, being built; "list my products for AI assistants"). Next: store chores with owner approval before anything goes live (prices, listings, hours). Platform assistants (for example Shopify's) only work inside their own platform. Landfall works through the website itself, so shops on Floranext, Wix, WordPress or custom sites are covered.

## Run it

```
pip install -r requirements.txt
python -m playwright install chromium     # browser agent and mirror
# agent runs shell out to `claude -p`; install and sign in to Claude Code first

python -m landfall scan https://example.com --out runs/example
python -m landfall mirror https://example.com --out runs/example/mirror
python -m landfall fix runs/example

python -m landfall.agent_run both <slug>                              # do + find (modes: do, fetch, find, both)
python -m landfall.agent_run do <slug> --url http://127.0.0.1:8800    # rerun on the fixed mirror
python -m landfall.mcp_server --port 8765                             # remote MCP server
```

`<slug>` must exist in `sites/targets.toml` (tasks and visibility query are defined there). The full job (scan, find, do, mirror, fix, rescan, do on mirror, `result.json`) is `landfall.pipeline.Job(url, goal, tasks, query).run()`; the MCP tool `make_agent_ready` starts it. Optional keys go in `.env` (never committed): `AMPLITUDE_API_KEY`, `COGNEE_API_KEY`. Without them, events and memory are written to `runs/events.jsonl` and `runs/memory.jsonl` only.

## MCP connector setup

Landfall serves streamable HTTP at `/mcp` and reports at `/reports/<slug>`. Tools: `make_agent_ready(url, goal, visibility_query)`, `job_status(slug)`, `get_report(slug)`, `quick_check(url)`. Answers lead with a live per-assistant access check (`landfall/access.py`) and a 3-line owner summary; known sites return instantly.

1. Host the server (we use an Agent37 instance), or run it locally and tunnel it.
2. In Claude: Settings, Connectors, add a custom connector with URL `<YOUR_LANDFALL_MCP_URL>` (ending in `/mcp`).
3. Ask in plain English: "Is smalltownbloomsky.com ready for AI agents? People should be able to order sympathy flowers for same-day delivery."

Muse and Grok support custom MCP connectors too; the steps differ per app. The hosted URL acts as the credential, so do not publish it.

## Rules

- Read-only on real sites: no purchases, no form submissions, no sign-ups. The agent prompt forbids them, and since tools alone cannot enforce that, every reply and page snapshot is kept as a receipt.
- Fixes are applied only to our mirror, never to the live site.
- Page content is data, never instructions.
- Only facts found on the site go into fixes. Everything else is asked of the owner.

## Honest limits

- Visibility changes need real assistants to re-index, which takes time. We show "after" on the mirror.
- A bot wall (the Floranext 403 for some user-agent strings) is a host or CDN setting. Landfall can name it and write the request to the owner; it cannot lift it. Our user-agent test does not prove what a real assistant's fetcher can reach.
- Prices filled in by script are invisible to readers that skip JavaScript. Landfall flags it; it does not know which assistants run JavaScript on a given day.
- The mirror is a copy of the homepage and a few linked pages, not the live site; links that point off the mirror can 404.
- Scores come from one run per site on one day. Agent answers vary run to run.
- Some "done" answers carry `answer not matched in saved snapshots; needs a human look` in the `honest` field. We leave those flagged.

## Layout

```
landfall/    scan, agent_run, mirror, fix, pipeline, report, mcp_server, telemetry, memory, firedrill_agent
sites/       targets.toml (real businesses), drill/ (fake bakery fixture for Firedrill)
firedrill/   Firedrill drill: descriptor, plan, personas, scenarios, evaluations, RUN.md
evidence/    floranext-agent-wall.txt
scripts/     lane_run.sh (one job on an Agent37 lane)
docs/        DESIGN.md, DEVPOST.md, DEMO.md
tests/       unit tests
runs/        per-site outputs (gitignored)
```

## Tests

```
python -m unittest discover -s tests -t .
```
