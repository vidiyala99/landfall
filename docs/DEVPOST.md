# Landfall: Devpost

## Inspiration
Personal agents now find, compare and book things for people. The businesses they pick from are not all in the Bay Area or in tech: a bakery in Ohio, a plumber in Iowa, a florist in Kentucky. Those owners cannot tell whether an agent can read their site, and nobody tells them. Landfall is "Devin for everyone" in one concrete domain: you state a goal, a factory of agents does the work, and you get a report you can read.

## What it does
Give it a URL and a sentence ("people should be able to order sympathy flowers for same-day delivery"). Landfall scans the site, sends two kinds of agents (a browser agent and a no-JavaScript reader) to do real customer tasks read-only, asks an agent the customer's question to test visibility, mirrors the site, builds fixes (JSON-LD, llms.txt, robots patch, labels, an agent card, owner questions), reruns the same tasks on the fixed copy, and writes a plain-English owner report. It works as a remote MCP server (a custom connector in Claude; Muse and Grok also support custom MCP) or through the report link.

Real runs, 2026-11-20:
- **Floranext florists:** `ChatGPT-User` and `PerplexityBot` get HTTP 403 on all 4 florists we tested, while Chrome and `Claude-User` get through (`evidence/floranext-agent-wall.txt`).
- **Small Town Blooms:** 0/4 tasks on the live site. On the mirror, with the wall lifted, the no-JS reader finished 2 and got partway on 2. The wall is a host setting, so Landfall can only report it.
- **Hanna Plumbing:** raw HTML shows (319) 377-2809; a manual browser check showed a different number, a call-tracking swap. Calls from assistants that read raw HTML skip the tracking numbers.
- **3 C's Bakery:** hours, prices and lead time exist nowhere online. Landfall asked the owner 5 questions instead of inventing answers. Task scores stayed flat (1/4).

## How we built it
Python. Agent37 sandboxes run the lanes and host the public MCP server. Agents are headless Claude Code with Playwright, plus a curl-only reader. The pipeline is scan, find, do, mirror, fix, rescan, do on mirror, report; each stage is its own CLI so lanes stay independent. Firedrill drills Landfall's own customer agent with a pushy "just book it" customer and a prompt injection planted in a page (results: see `firedrill/RESULTS.md`). Amplitude records the agent funnel and Cognee keeps memory across audits.

## Challenges
- Agents overclaim. `honesty_check` refuses any "done" it cannot match to a saved page, and some answers stay flagged "needs a human look".
- The mirror is imperfect: Hanna's Do score fell from 4/4 to 3/4 because the mirror's `/contact` returned 404. We kept the number.

## Accomplishments
- 5 real small businesses audited end to end; Read scores rose on all 5 (Small Town Blooms 68 to 92, Hanna 84 to 96, Kingston 56 to 72, Saam 82 to 92, 3 C's 70 to 78).
- A factory that says "not found" and asks the owner.

## What we learned
Evidence versus inference: the 403s are measured; why they exist is not. Visibility needs real assistants to re-index, which a hackathon cannot show, so "after" is on the mirror only. Bot walls and call-tracking are host and vendor settings that no site-level fix reaches.

## What's next
Email as a way in for owners with no agent. More business categories, with Cognee memory showing which fixes move scores for which types.

## Built with
Python, Playwright, Claude Code, MCP (streamable HTTP), Agent37, Firedrill, Amplitude, Cognee, tokens&, schema.org JSON-LD.
