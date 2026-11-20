"""The crew board: each Landfall agent ("sailor"), its job, and which sponsor tool it uses and how.

Served at /crew by the MCP server. Facts only: every "uses" line points at code in this repo; counts come from
runs/events.jsonl (the local copy of every event sent to Amplitude) and runs/memory.jsonl (audits sent to Cognee).
"""
from __future__ import annotations

import collections
import html
import json
from pathlib import Path

from landfall.report import FONTS_HARBOR

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

# (sailor, role, job, stages it reports to Amplitude, [(tool, how)])
CREW = [
    ("The Surveyor", "scan.py", "Reads the site like an assistant would: labels, hours, prices, bot walls. Saves receipts.",
     ["scan", "rescan"], [("Amplitude", "Reports each survey and every problem found to the funnel"),
                          ("Cognee", "Its findings become the audit memory")]),
    ("The Gatekeeper", "access.py", "Knocks as ChatGPT, Claude, Perplexity and Meta to see who gets turned away.",
     ["access"], [("Amplitude", "Logs each gate check")]),
    ("The Shopper", "agent_run.py (browser)", "A full-browser agent that tries real customer tasks. Read-only, stops before paying.",
     ["do", "redo"], [("Amplitude", "Logs every task run, before and after the fixes")]),
    ("The Reader", "agent_run.py (no JavaScript)", "Reads pages the way ChatGPT does, without running scripts.",
     ["do_fetch", "redo_fetch"], [("Firedrill", "Drilled as the customer agent: pushy \"just book it\" customer and a planted injection; 89 then 91.5 of 100"),
                                  ("Amplitude", "Logs every task run, before and after")]),
    ("The Lookout", "agent_run.py (find)", "Asks an assistant the customer's question: do you get recommended?",
     ["find"], [("Amplitude", "Logs each visibility check")]),
    ("The Shipwright", "mirror.py + fix.py", "Copies the site, builds the fixes, applies them to the copy for the rerun.",
     ["mirror", "fix"], [("Amplitude", "Logs each repair"), ("Cognee", "Which fixes moved the score is remembered")]),
    ("The Clerk", "products.py", "Digital worker: lists every product with its real price so any assistant can read it.",
     [], [("Cognee", "Product findings feed the audit memory")]),
    ("The Quartermaster", "memory.py + cognee_backend.py", "Keeps the factory's memory across every shop it has audited.",
     [], [("Cognee", "remember after each audit; recall when asked \"which platforms block assistants?\"")]),
]
TOOLS = ("Firedrill", "Cognee", "Amplitude")


def _counts() -> tuple[collections.Counter, int, int]:
    stages: collections.Counter = collections.Counter()
    problems = audits = 0
    p = RUNS / "events.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event_type") == "landfall_stage" and e.get("event_properties", {}).get("status") == "done":
                stages[e["event_properties"].get("stage")] += 1
            elif e.get("event_type") == "landfall_problem_found":
                problems += 1
    # Audits sent to Cognee (scripts/cognee_backfill.py remembers every runs/*/result.json; memory.py adds new ones).
    audits = len(list(RUNS.glob("*/result.json")))
    return stages, problems, audits


TOGGLE_CSS = """.fswitch{position:sticky;top:12px;z-index:50;display:flex;justify-content:center;margin:0 0 18px;pointer-events:none}
.fswitch nav{pointer-events:auto;display:inline-flex;background:#1b120b;border:2px solid #c9a24c;border-radius:999px;padding:4px;box-shadow:0 8px 20px -8px #000}
.fswitch a{font:700 16px "Big Shoulders Display",system-ui,sans-serif;letter-spacing:.05em;text-transform:uppercase;color:#f3ead6;
text-decoration:none;padding:9px 18px;border-radius:999px;transition:background-color .16s ease,transform .12s ease}
.fswitch a:active{transform:scale(.97)}.fswitch a[aria-current=page]{background:#f2c75c;color:#1d1a16}
@media (hover:hover){.fswitch a:not([aria-current]):hover{background:rgb(242 199 92/.18)}}
@media (prefers-reduced-motion:reduce){.fswitch a{transition:none}}"""


def toggle(slug: str, inside: bool) -> str:
    s = html.escape(slug or "small-town-blooms")
    out_cur, in_cur = ('', ' aria-current="page"') if inside else (' aria-current="page"', '')
    return (f'<style>{TOGGLE_CSS}</style><div class="fswitch"><nav aria-label="View">'
            f'<a href="/reports/{s}"{out_cur}>Outside the factory</a>'
            f'<a href="/crew?slug={s}"{in_cur}>Inside the factory</a></nav></div>')


def render(slug: str = "small-town-blooms") -> str:
    esc = html.escape
    stages, problems, audits = _counts()
    tags = []
    for name, role, job, st, uses in CREW:
        n = sum(stages[s] for s in st)
        uses_html = "".join(f'<li><b class="t t-{esc(t.lower())}">{esc(t)}</b> {esc(how)}</li>' for t, how in uses)
        count = f'<p class="n">{n} runs logged</p>' if st and n else ""
        tags.append(f'<article class="tag"><span class="hole" aria-hidden="true"></span><h2>{esc(name)}</h2>'
                    f'<p class="role">{esc(role)}</p><p class="job">{esc(job)}</p><ul>{uses_html}</ul>{count}</article>')
    rows = []
    for name, _r, _j, _s, uses in CREW:
        have = {t: how for t, how in uses}
        cells = "".join(f'<td class="{"y" if t in have else "x"}">{"&#10003;" if t in have else ""}</td>' for t in TOOLS)
        rows.append(f"<tr><th scope=row>{esc(name)}</th>{cells}</tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Landfall crew</title><link rel="stylesheet" href="{FONTS_HARBOR}">
<style>
:root{{--sea:#0f2230;--ink:#1d1a16;--manila:#efd9a6;--gilt:#f2c75c;--wood:#5a3a22}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--sea) url(/static/harbor/harbor-ground.webp) center/cover fixed;color:#f3ead6;font:17px/1.5 "Atkinson Hyperlegible",system-ui,sans-serif}}
.wrap{{max-width:1500px;margin:0 auto;padding:32px 24px 64px;background:linear-gradient(rgb(15 34 48/.82),rgb(15 34 48/.92))}}
h1{{font:400 clamp(36px,5vw,64px)/1.05 Ultra,serif;color:var(--gilt);margin:0;padding:22px 28px;background:url(/static/harbor/wood.webp) center/cover;border:3px solid #c9a24c;border-radius:10px;text-shadow:0 2px 0 #3b2412}}
.sub{{margin:14px 0 26px;font-size:19px;max-width:70ch}}
.stats{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:26px}}.stat{{background:url(/static/harbor/slate.webp) center/cover;border-radius:10px;padding:12px 18px;font:600 18px "Big Shoulders Display",sans-serif;letter-spacing:.02em}}
.stat b{{font-size:34px;color:#9fe3b8;margin-right:6px}}
.rope{{border-top:4px dashed #c9a24c;margin:8px 0 0}}
.tags{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:22px 18px;padding-top:18px}}
.tag{{position:relative;background:var(--manila);color:var(--ink);padding:30px 18px 16px;clip-path:polygon(14% 0,86% 0,100% 9%,100% 100%,0 100%,0 9%);box-shadow:0 10px 24px -10px #000}}
.hole{{position:absolute;top:10px;left:50%;width:14px;height:14px;margin-left:-7px;border-radius:50%;background:#7a3b22;box-shadow:inset 0 0 0 3px #b8935a}}
.tag h2{{font:400 24px Ultra,serif;margin:6px 0 2px}}.role{{font:13px ui-monospace,Consolas,monospace;color:#6b5a3e;margin:0 0 8px}}.job{{margin:0 0 10px}}
.tag ul{{list-style:none;padding:0;margin:0}}.tag li{{margin:6px 0;font-size:15px}}
.t{{display:inline-block;font:700 13px "Big Shoulders Display",sans-serif;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:4px;margin-right:4px;color:#fff}}
.t-firedrill{{background:#b2402a}}.t-cognee{{background:#3b5bb5}}.t-amplitude{{background:#1f6f52}}
.n{{margin:10px 0 0;font:700 14px "Big Shoulders Display",sans-serif;color:#6b5a3e;letter-spacing:.04em}}
h3{{font:400 30px Ultra,serif;color:var(--gilt);margin:40px 0 12px}}
table{{border-collapse:collapse;background:url(/static/harbor/slate.webp) center/cover;border-radius:10px;overflow:hidden;font-size:18px}}
th,td{{padding:10px 18px;border-bottom:1px solid rgb(255 255 255/.12);text-align:left}}thead th{{font:700 18px "Big Shoulders Display",sans-serif;letter-spacing:.04em}}
td.y{{color:#9fe3b8;font-size:22px;text-align:center}}td.x{{text-align:center}}
.foot{{margin-top:22px;font-size:14px;color:#cbbfa3}}
@media (max-width:600px){{.wrap{{padding:20px 16px 48px}}table{{font-size:15px}}th,td{{padding:8px 10px}}}}
@media (prefers-reduced-motion:no-preference){{.tag{{animation:sway 700ms cubic-bezier(.23,1,.32,1) both}}.tag:nth-child(2n){{animation-delay:60ms}}}}
@keyframes sway{{from{{opacity:0;transform:translateY(-10px) rotate(-2deg)}}to{{opacity:1;transform:none}}}}
</style></head><body><main class="wrap">
{toggle(slug, inside=True)}
<h1>The Landfall crew</h1>
<p class="sub">Every sailor is an agent. Here is each one's job, and which sponsor tool it uses and how.</p>
<div class="stats"><span class="stat"><b>{sum(stages.values())}</b>agent stages logged to Amplitude</span>
<span class="stat"><b>{problems}</b>problems sent to the funnel</span><span class="stat"><b>{audits}</b>shops audited into Cognee memory</span>
<span class="stat"><b>2</b>Firedrill drills (89, 91.5)</span></div>
<div class="rope"></div><section class="tags">{''.join(tags)}</section>
<h3>Who uses what</h3>
<table><thead><tr><th>Sailor</th>{''.join(f'<th>{t}</th>' for t in TOOLS)}</tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="foot">Counts are from this server's own logs (runs/events.jsonl mirrors every Amplitude event; runs/memory.jsonl lists audits
sent to Cognee). Firedrill results: firedrill/RESULTS.md. Agents run in parallel on Agent37 sandboxes.</p>
</main></body></html>"""
