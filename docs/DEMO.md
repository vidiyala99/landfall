# Landfall: 2-minute live demo

Before going on stage: Claude open with the Landfall connector (`<YOUR_LANDFALL_MCP_URL>`) added; reports for small-town-blooms and hanna-plumbing already generated; `evidence/floranext-agent-wall.txt`, the Hanna phone check and the `firedrill/` results open in tabs.

| Time | Do | Say |
| - | - | - |
| 0:00 | Open Claude with the Landfall connector. | "ChatGPT, Claude, Muse and Grok now find and book things for people. Can they use a small-town florist's site? Let's ask." |
| 0:10 | Type: "Make smalltownbloomsky.com ready for AI agents. People should be able to order sympathy flowers for same-day delivery." Landfall calls `make_agent_ready`. | "One sentence. Landfall is a factory: it starts parallel lanes on Agent37 sandboxes." |
| 0:25 | Call `job_status`; show the stages (scan, find, do, mirror, fix, rescan). | "A browser agent and a no-JavaScript reader try real customer tasks, read-only. Nothing is submitted or bought." |
| 0:40 | Open the report link. Show before/after: Read 68 to 92; tasks 0/4 to 2 done on the copy. | "On the live site both agents got a 403 and finished 0 of 4 tasks. On our mirror, with the wall lifted, the no-JS reader finished 2 and got partway on 2. The wall is a host setting, so the report says so instead of claiming a fix." |
| 1:00 | Show `evidence/floranext-agent-wall.txt`. | "Four Floranext florists. ChatGPT-User and PerplexityBot get 403. Chrome and Claude-User get through. The owners cannot see this." |
| 1:20 | Show Hanna Plumbing: raw HTML number (319) 377-2809 beside the number a browser shows. | "The raw HTML and the browser show different phone numbers, a call-tracking swap. Calls from assistants that read raw HTML skip the tracking numbers." (Check the browser number live first; it is not saved in `runs/`.) |
| 1:35 | Show the Firedrill drill: a pushy "just book it" customer and a planted prompt injection against Landfall's own customer agent. | "We drilled our own agent." Read the actual result line from `firedrill/RESULTS.md`; do not improvise it. |
| 1:50 | Show 3 C's Bakery `needs-owner.md` for two seconds. | "Where facts do not exist, Landfall asks the owner five questions. It does not invent hours." |
| 1:55 | Close. | "Devin for everyone, starting with the florists an AI agent cannot get into: a goal in, a fixed copy and a report out, and the agent never gets the last word." |

## Fallback if live calls are slow
- If `make_agent_ready` has not finished by 0:40, say "this takes minutes; here is one already run" and open the pre-run `/reports/small-town-blooms` link. Keep the script from 0:40.
- If the connector fails, open `runs/small-town-blooms/report.html` locally, and use `quick_check` (static scan only, about 30 s per its tool description) for a live touch.
- If the Hanna browser number will not reproduce, show only the raw HTML number and say the swap was a manual check.
- If Firedrill results are not in, show `firedrill/plan.json` and `firedrill/scenarios/pushy-book-it.json` and say results are pending.
