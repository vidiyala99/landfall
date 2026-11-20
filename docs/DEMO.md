# Landfall: 2-minute live demo

Before going on stage: Muse or ChatGPT open in one tab; Claude open with the Landfall connector (`<YOUR_LANDFALL_MCP_URL>`); `runs/small-town-blooms/report.html` (and `/reports/small-town-blooms`) open; `firedrill/RESULTS.md` open.

| Time | Do | Say |
| - | - | - |
| 0:00 | In Muse or ChatGPT, WITHOUT the connector, ask: "I'm a business owner. I run a flower shop in Beaver Dam, Kentucky: smalltownbloomsky.com. I don't know if my customers can use their AI assistants to shop on my website. Can they?" | "This is what an owner gets today: a long, generic answer. The assistant tested only itself, and it said customers 'can likely' shop." |
| 0:25 | Live proof, in ChatGPT: "Open https://www.smalltownbloomsky.com/ right now and tell me the exact name and price of the first arrangement on the page." | "It names Back2School Special. It gives no price: 'not displayed in the accessible page content... I don't want to invent a price.' The page text has no prices; they sit only inside script data (REA capture). A real browser shows $69.99 to $95.00." |
| 0:55 | Ask the same owner question WITH the Landfall connector. | "Your assistant can only test itself. Landfall tests every assistant your customers use, with receipts." Read the 5 lines: the access matrix (ChatGPT-User 403, OAI-SearchBot 403, meta-externalfetcher 403, Claude-User 200, Perplexity-User 200, Chrome 200), "can see products but not prices", the numbers, and the report link. |
| 1:15 | Open the report. | "Prices (e.g. $45.00, $22.00, $80.00, $85.00) appear only after JavaScript runs. AI assistants can see your products but not your prices." |
| 1:30 | Open `firedrill/RESULTS.md`: drill 1 at 89, drill 2 at 91.5. | "We drilled our own agent with a pushy 'just book it' customer and a planted injection. It never booked and never repeated the injection. The drills caught our wrapper presenting the agent's words as a website quote, then dangling 'I ignored it' fragments. Both fixed; drill 3 pending." |
| 1:50 | Close. | "Digital workers for everyone outside the Bay. Today the factory makes a shop visible and shoppable to every customer's assistant. Next, store chores with owner approval before anything goes live. We work through the website itself, so Floranext, Wix, WordPress and custom sites are covered." |

## Fallback if live calls are slow
- If the ChatGPT call is slow or fails, show the saved answer: name "Back2School Special", price "not displayed in the accessible page content", beside `runs/small-town-blooms/scan.json` (the "appear only after JavaScript runs" line).
- If the connector is slow or fails, open `runs/small-town-blooms/access.json` and `runs/small-town-blooms/report.html` locally; `quick_check` (static scan only) is the live touch if it responds.
- If the owner question in Muse or ChatGPT is slow, say "a long generic answer, and it only tested itself" and move to the live proof.
- If Firedrill drill 3 is not in, say it is pending and show drills 1 and 2 only.
- Do not claim ChatGPT cannot reach the site: it can. The 403s are our user-agent test only.
