# Landfall: make any small business agent-ready

Approved in chat by Aakash, 2026-11-20 12:55 PST (Personal Agents Hackathon, tokens&, submit 4:30 PM).

## Problem
Personal agents (Muse, Grok, Claude, ChatGPT) now find, compare and book things for people. Small businesses
outside the Bay and outside tech are invisible or unusable to those agents and do not know it.

## What Landfall does
Input: a business URL and one sentence ("people should be able to order a cake for Saturday pickup").
1. **Read** (static scan, receipts): robots.txt rules for AI agents, llms.txt, schema.org JSON-LD (business, hours,
   menu/offers, address), content present without JavaScript, bot challenges, labeled forms, alt text, sitemap.
2. **Do** (agent task run): a browser agent (Playwright) tries real customer tasks, read-only, stops before any
   payment or submission; pass/fail per task with the step, screenshot and network evidence.
3. **Find** (agent visibility): ask an agent the customer's question ("bakery in Dayton OH with Saturday cake
   pickup"); does the business appear?
4. **Fix**: generate the fix package (JSON-LD, llms.txt, robots.txt patch, labels, an agent card) and apply it to
   a local mirror of the site.
5. **Verify**: rerun read + do on the mirror; before/after score. A check rejects any finding without a receipt.
6. **Report**: plain-English page for the owner.

## Ways in
- Remote MCP server (`make_agent_ready`, `audit`, `report`): works as a custom connector in Claude, Muse, Grok, ChatGPT.
- Email (AgentMail) as the no-agent fallback (later).

## Sponsors
Firedrill (drills that test the shopper agent reports failures honestly), Senso (context layer for the shopper),
Amplitude (agent-run funnel), Cognee (memory across audits), Persona (agent-blocking note), tokens& checks.

## Rules
Read-only on real sites: no purchases, no form submissions, no sign-ups; fixes only on our mirror. Honest limit:
real agents will not re-index by demo time, so visibility "after" is shown on the mirror with a live-reading agent.
Targets: real small businesses outside the Bay Area and outside tech.
