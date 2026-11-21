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


def toggle(slug: str, inside: bool | None) -> str:
    """inside=None marks Home as the current page."""
    s = html.escape(slug or "small-town-blooms")
    cur = ' aria-current="page"'
    home_cur = cur if inside is None else ""
    out_cur = cur if inside is False else ""
    in_cur = cur if inside is True else ""
    return (f'<style>{TOGGLE_CSS}</style><div class="fswitch"><nav aria-label="View">'
            f'<a href="/"{home_cur}>Home</a>'
            f'<a href="/reports/{s}"{out_cur}>Outside the factory</a>'
            f'<a href="/crew?slug={s}"{in_cur}>Inside the factory</a></nav></div>')


# Where each sailor's ship sits in the harbor scene: (ship plate, quarterboard plate, ship box, board box) as fractions
# of the 2736x1536 stage, taken from the Shipyard portal scene spec (.impeccable/build/spec.json regions).
BERTHS = [
    ("ship-yard-1", "qb-yard-1", (0.004, 0.1484, 0.246, 0.2552), (0.0435, 0.168, 0.1436, 0.0625)),
    ("ship-yard-2", "qb-yard-3", (0.004, 0.3477, 0.3048, 0.3385), (0.0431, 0.418, 0.1673, 0.0625)),
    ("ship-yard-3", "qb-yard-3", (0.004, 0.6263, 0.3074, 0.3685), (0.0365, 0.6836, 0.1882, 0.0625)),
    ("ship-sail-1", "qb-sail-3", (0.3257, 0.0605, 0.1382, 0.2734), (0.3143, 0.2715, 0.1490, 0.0495)),
    ("ship-sail-2", "qb-sail-3", (0.3999, 0.209, 0.1743, 0.3828), (0.4054, 0.5047, 0.1448, 0.0495)),
    ("ship-sail-3", "qb-sail-3", (0.4064, 0.5221, 0.1758, 0.3828), (0.4262, 0.8203, 0.1374, 0.0495)),
    ("ship-quay", "qb-drift", (0.5376, 0.0605, 0.2668, 0.401), (0.5858, 0.3561, 0.1622, 0.0495)),
    ("ship-drift", "qb-drift", (0.6184, 0.4824, 0.1941, 0.3874), (0.6584, 0.8125, 0.1512, 0.0495)),
]
STATIC = "/static/harbor"


def _pct(box):
    x, y, w, h = box
    return f"left:{x * 100:.2f}%;top:{y * 100:.2f}%;width:{w * 100:.2f}%;height:{h * 100:.2f}%"


def render(slug: str = "small-town-blooms") -> str:
    """The inside of the factory as the illustrated harbor: one ship per sailor, its name on a carved quarterboard,
    its sponsor tools as cargo tags; focus or hover a ship to read its job and how it uses each tool. CSS only."""
    esc = html.escape
    stages, problems, audits = _counts()
    ships = []
    for i, ((name, role, job, st, uses), (ship, qb, sbox, bbox)) in enumerate(zip(CREW, BERTHS)):
        n = sum(stages[s] for s in st)
        short = name[4:] if name.startswith("The ") else name
        tags = "".join(f'<span class="ctag" style="--d:{j}"><b>{esc(t)}</b></span>' for j, (t, _h) in enumerate(uses))
        uses_html = "".join(f'<li><b class="stamp s-{esc(t.lower())}">{esc(t)}</b> {esc(how)}</li>' for t, how in uses)
        count = f'<p class="runs">{n} runs logged to Amplitude</p>' if st and n else ""
        side = " card-left" if sbox[0] > 0.5 else ""
        ships.append(
            f'<div class="ship" tabindex="0" style="{_pct(sbox)};--i:{i}" aria-labelledby="sn{i}">'
            f'<img src="{STATIC}/{ship}.webp" alt="" decoding="async">'
            f'</div>'
            f'<div class="berth" style="{_pct(bbox)}">'
            f'<span class="qb" style="--plate:url({STATIC}/{qb}.webp)" id="sn{i}">{esc(short)}</span>'
            f'<span class="ctags">{tags}</span></div>'
            f'<div class="card{side}" style="--x:{(sbox[0] + sbox[2] / 2) * 100:.1f}%;--y:{(bbox[1] + bbox[3]) * 100:.1f}%" role="note">'
            f'<h2>{esc(name)}</h2><p class="role">{esc(role)}</p><p class="job">{esc(job)}</p><ul>{uses_html}</ul>{count}</div>')
    total = sum(stages.values())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Landfall crew</title><link rel="stylesheet" href="{FONTS_HARBOR}">
<style>
:root{{--night:#0d1c27;--gilt:#efc566;--gilt-deep:#b8893a;--manila:#ead3a2;--ink:#2a1d12;--chalk:#f1ece0;
  --ease-out:cubic-bezier(0.23,1,0.32,1);color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--night);color:var(--chalk);font:17px/1.45 "Atkinson Hyperlegible",system-ui,sans-serif}}
::selection{{background:var(--gilt);color:#2b160a}}
:focus-visible{{outline:3px solid #f3b928;outline-offset:3px}}
.fswitch{{margin:0;position:absolute;top:1.1vw;left:0;right:0}}
.stage{{position:relative;width:min(100%,calc(100dvh * 2736 / 1536));aspect-ratio:2736/1536;margin:0 auto;container-type:inline-size;
  background:url({STATIC}/harbor-ground.webp) center/cover no-repeat,#1b4a55;overflow:hidden}}
.topbar{{position:absolute;left:0;top:0;width:100%;height:6.05%;background:url({STATIC}/topbar.webp) center/100% 100% no-repeat;
  display:flex;align-items:center;padding-left:2.2cqw;z-index:3}}
.wordmark{{font:400 2.6cqw/1 Ultra,serif;color:var(--gilt);margin:0;text-shadow:0 -1px 0 rgb(50 24 6/.95),0 2px 5px rgb(0 0 0/.5)}}
.ship{{position:absolute;z-index:1;cursor:pointer;border-radius:2cqw}}
.ship img{{width:100%;height:100%;object-fit:contain;display:block;filter:drop-shadow(0 .6cqw .8cqw rgb(0 0 0/.4));transition:transform 220ms var(--ease-out),filter 220ms ease}}
.ctag b{{position:absolute;right:6.5%;top:50%;width:29%;transform:translateY(-58%);text-align:center;font:inherit;color:#2a1608}}
.berth{{position:absolute;z-index:2;pointer-events:none}}
.qb{{display:grid;place-items:center;width:100%;height:100%;padding:0 18%;background:var(--plate) center/100% 100% no-repeat;
  font:400 1.25cqw/1 Ultra,serif;color:var(--gilt);white-space:nowrap;text-shadow:0 -1px 0 rgb(50 24 6/.95),0 1px 3px rgb(0 0 0/.55)}}
.ctags{{display:flex;flex-direction:column;align-items:center;gap:.15cqw;margin-top:.1cqw}}
.ctag{{position:relative;display:block;flex:none;width:9.6cqw;aspect-ratio:972/284;background:url({STATIC}/tag-2.webp) center/100% 100% no-repeat;
  font:800 max(11px,.78cqw)/1 "Big Shoulders Display",sans-serif;color:#2a1608;transform:rotate(calc(-2deg + var(--d) * 3deg));transform-origin:12% 50%;
  filter:drop-shadow(0 .2cqw .25cqw rgb(0 0 0/.45))}}
.board{{position:absolute;left:79.9%;top:5.66%;width:20.1%;height:43.42%;z-index:2;background:url({STATIC}/needs-board.webp) center/100% 100% no-repeat;
  padding:1.9cqw 1.9cqw 1.4cqw;display:flex;flex-direction:column;gap:.55cqw}}
.board h1{{margin:0;font:400 1.4cqw/1.05 Ultra,serif;color:var(--gilt);text-shadow:0 2px 4px rgb(0 0 0/.55)}}
.board p{{margin:0;font-size:max(11px,.82cqw);line-height:1.3;color:var(--chalk)}}
.board b.big{{display:block;font:800 1.6cqw/1 "Big Shoulders Display",sans-serif;color:#bdf2c8}}
.board .tool{{font:800 1.05cqw/1 "Big Shoulders Display",sans-serif;color:var(--gilt);letter-spacing:.02em}}
.hint{{position:absolute;left:81%;top:52%;width:17%;z-index:2;font:700 1cqw/1.3 "Atkinson Hyperlegible",sans-serif;color:var(--chalk);
  background:rgb(13 28 39/.72);padding:.8cqw 1cqw;border-radius:.6cqw}}
.card{{position:absolute;z-index:5;left:var(--x);top:var(--y);width:21cqw;transform:translate(-50%,.4cqw) scale(.97);opacity:0;visibility:hidden;
  background:linear-gradient(180deg,#f0dcae,var(--manila) 40%,#dcc08a);color:var(--ink);padding:1.2cqw 1.3cqw 1cqw;border-radius:.4cqw;
  box-shadow:0 1.2cqw 2cqw -.6cqw rgb(0 0 0/.65);transition:opacity 180ms ease,transform 220ms var(--ease-out),visibility 0s 220ms;pointer-events:none}}
.card.card-left{{transform:translate(-62%,.4cqw) scale(.97)}}
.card h2{{margin:0;font:400 1.35cqw/1.1 Ultra,serif;color:#5a3220}}
.card .role{{margin:.2cqw 0 .5cqw;font:.8cqw/1.2 ui-monospace,Consolas,monospace;color:#5a4128}}
.card .job{{margin:0 0 .6cqw;font-size:1cqw}}
.card ul{{list-style:none;margin:0;padding:0;display:grid;gap:.45cqw;font-size:.92cqw}}
.stamp{{display:inline-block;font:800 .82cqw/1.15 "Big Shoulders Display",sans-serif;letter-spacing:.02em;padding:.05cqw .45cqw;border:2px solid currentColor;border-radius:.25cqw;margin-right:.3cqw;transform:rotate(-2deg)}}
.s-firedrill{{color:#9c3418}}.s-cognee{{color:#2f4a8a}}.s-amplitude{{color:#2f5f2a}}
.runs{{margin:.6cqw 0 0;font:800 .9cqw/1 "Big Shoulders Display",sans-serif;color:#5a4128}}
.ship:focus-visible{{outline-offset:-.6cqw}}
.ship:is(:hover,:focus-visible,:focus) img{{transform:translateY(-.4cqw);filter:drop-shadow(0 1.1cqw 1.2cqw rgb(0 0 0/.5)) brightness(1.06)}}
.ship:is(:hover,:focus) + .berth + .card{{opacity:1;visibility:visible;transform:translate(-50%,0) scale(1);transition:opacity 180ms ease,transform 220ms var(--ease-out),visibility 0s}}
.ship:is(:hover,:focus) + .berth + .card.card-left{{transform:translate(-62%,0) scale(1)}}
@media (prefers-reduced-motion:no-preference){{
  .ship img{{animation:bob 6.5s ease-in-out infinite alternate;animation-delay:calc(var(--i) * -.8s)}}
  .ship:is(:hover,:focus) img{{animation-play-state:paused}}
}}
@keyframes bob{{from{{translate:0 0}}to{{translate:0 .35cqw}}}}
@media (prefers-reduced-motion:reduce){{.ship img,.card{{transition:none}}}}
.foot{{max-width:1100px;margin:0 auto;padding:18px 16px 40px;font-size:14px;color:#cbbfa3}}
/* Phones: the scene becomes a stacked list, every job visible */
@media (max-width:760px){{
  .fswitch{{position:sticky;top:8px;margin:8px 0;order:-3}}
  .stage{{width:auto;aspect-ratio:auto;container-type:normal;background:linear-gradient(rgb(13 28 39/.78),rgb(13 28 39/.9)),url({STATIC}/harbor-ground.webp) center/cover;
    display:flex;flex-direction:column;gap:14px;padding:0 16px 24px;overflow:visible}}
  .topbar{{position:relative;height:64px;padding-left:16px;margin:0 -16px;width:auto;order:-2;background-size:cover}}
  .wordmark{{font-size:32px}}
  .board{{position:relative;left:auto;top:auto;width:auto;height:auto;padding:28px 26px 22px;gap:10px;order:-1}}
  .board h1{{font-size:26px}}.board p{{font-size:15px}}.board b.big{{font-size:30px}}.board .tool{{font-size:17px}}
  .hint{{display:none}}
  .ship{{position:relative;left:auto!important;top:auto!important;width:100%!important;height:auto!important;aspect-ratio:16/9}}
  .ship img{{animation:none}}
  .berth{{position:relative;left:auto!important;top:auto!important;width:min(100%,320px)!important;height:auto!important;margin:-6px auto 0}}
  .qb{{height:62px;font-size:20px}}
  .ctag{{width:170px;font-size:13px}}
  .card{{position:relative;left:auto;top:auto;width:auto;opacity:1;visibility:visible;transform:none!important;padding:16px 18px;margin-bottom:18px}}
  .card h2{{font-size:22px}}.card .role{{font-size:13px}}.card .job,.card ul{{font-size:16px}}.stamp{{font-size:14px}}.runs{{font-size:15px}}
}}
</style></head><body>
<main class="stage">
{toggle(slug, inside=True)}
<header class="topbar"><p class="wordmark">Landfall</p></header>
<aside class="board" aria-labelledby="sod"><h1 id="sod">Sponsors on deck</h1>
<p><span class="tool">Amplitude</span><b class="big">{total}</b>agent stages logged, plus {problems} problems sent to the funnel</p>
<p><span class="tool">Cognee</span><b class="big">{audits}</b>shops remembered in the audit memory</p>
<p><span class="tool">Firedrill</span><b class="big">89 then 91.5</b>out of 100, drilling the customer agent</p></aside>
<p class="hint">Every ship is an agent. Hover or tap a ship to see its job and how it uses each tool.</p>
{''.join(ships)}
</main>
<p class="foot">Counts are from this server's own logs (runs/events.jsonl mirrors every Amplitude event; runs/*/result.json are the audits
sent to Cognee). Firedrill results: firedrill/RESULTS.md. Agents run in parallel on Agent37 sandboxes.</p>
</body></html>"""


HOME_CSS = """
*{box-sizing:border-box}body{margin:0;color:#f3ead6;font:18px/1.55 "Atkinson Hyperlegible",system-ui,sans-serif;
background:#0f2230 url(/static/harbor/harbor-ground.webp) center/cover fixed}
main{min-height:100vh;background:linear-gradient(rgb(12 28 40/.55),rgb(12 28 40/.88) 55%,rgb(12 28 40/.96));padding:18px 24px 64px}
.in{max-width:1320px;margin:0 auto}
.qb{margin:26px 0 0;padding:26px 34px;background:url(/static/harbor/wood.webp) center/cover;border:3px solid #c9a24c;border-radius:12px;box-shadow:0 18px 40px -18px #000}
.qb h1{margin:0;font:400 clamp(40px,6vw,86px)/1 Ultra,serif;color:#f2c75c;text-shadow:0 2px 0 #3b2412}
.qb p{margin:12px 0 0;font:600 clamp(18px,2vw,24px)/1.35 "Big Shoulders Display",sans-serif;letter-spacing:.02em;color:#f7e7c0}
.lede{max-width:62ch;font-size:20px;margin:22px 0 0}
.doors{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:30px}
.door{display:block;text-decoration:none;color:#1d1a16;background:#efd9a6;border-radius:10px;padding:20px 22px;box-shadow:0 12px 28px -14px #000;transition:transform .16s cubic-bezier(.23,1,.32,1)}
.door:active{transform:scale(.98)}@media (hover:hover){.door:hover{transform:translateY(-3px)}}
.door h2{margin:0 0 6px;font:400 26px Ultra,serif}.door p{margin:0;font-size:16px}.door.y{background:#f2c75c}
h3{font:400 32px Ultra,serif;color:#f2c75c;margin:42px 0 6px}.note{margin:0 0 14px;color:#d9ccb0}
.rope{border-top:4px dashed #c9a24c}
.shops{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:20px 16px;padding-top:16px}
.shop{position:relative;display:flex;flex-direction:column;gap:4px;text-decoration:none;color:#1d1a16;background:#efd9a6;padding:30px 16px 16px;
clip-path:polygon(14% 0,86% 0,100% 9%,100% 100%,0 100%,0 9%);box-shadow:0 10px 24px -10px #000;transition:transform .16s cubic-bezier(.23,1,.32,1)}
@media (hover:hover){.shop:hover{transform:translateY(-3px) rotate(-.6deg)}}.shop:active{transform:scale(.98)}
.hole{position:absolute;top:10px;left:50%;width:14px;height:14px;margin-left:-7px;border-radius:50%;background:#7a3b22;box-shadow:inset 0 0 0 3px #b8935a}
.shop b{font:400 20px Ultra,serif}.shop small{color:#6b5a3e}.find{font-weight:700;margin-top:6px}
.go{margin-top:auto;padding-top:8px;font:700 14px "Big Shoulders Display",sans-serif;letter-spacing:.05em;text-transform:uppercase;color:#7a3b22}
.plug{background:url(/static/harbor/slate.webp) center/cover;border-radius:12px;padding:20px 22px;margin-top:8px}
.plug code{display:block;white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.5 ui-monospace,Consolas,monospace;background:rgb(0 0 0/.35);padding:14px;border-radius:8px;margin-top:10px}
.stats{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:22px;font:600 18px "Big Shoulders Display",sans-serif;letter-spacing:.03em}
.stats b{color:#9fe3b8;font-size:28px;margin-right:6px}
@media (max-width:800px){.doors{grid-template-columns:1fr}main{padding:14px 16px 48px}}
@media (prefers-reduced-motion:reduce){.door,.shop{transition:none}}
"""


def render_home(connector_url: str) -> str:
    """The factory's front door: what it does, the shops it audited, the crew, and how to plug it in."""
    esc = html.escape
    try:
        import tomllib
        sites = {x["slug"]: x for x in tomllib.loads((ROOT / "sites" / "targets.toml").read_text(encoding="utf-8")).get("site", [])}
    except Exception:  # noqa: BLE001
        sites = {}
    from landfall import report as _report
    shops = []
    for rp in sorted(RUNS.glob("*/result.json")):
        slug = rp.parent.name
        try:
            scan = json.loads((rp.parent / "scan.json").read_text(encoding="utf-8"))
            dop = rp.parent / "do.json"
            do = json.loads(dop.read_text(encoding="utf-8")) if dop.exists() else None
            title = _report.headline(scan, do)[0]
        except Exception:  # noqa: BLE001
            continue
        meta = sites.get(slug, {})
        where = ", ".join(x for x in (meta.get("city"), meta.get("state")) if x)
        cat = (meta.get("category") or "").title()
        sep = " · " if cat and where else ""
        shops.append(f'<a class="shop" href="/reports/{esc(slug)}"><span class="hole" aria-hidden="true"></span>'
                     f'<b>{esc(meta.get("name") or slug)}</b><small>{esc(cat)}{sep}{esc(where)}</small>'
                     f'<span class="find">{esc(title)}</span><span class="go">Open the report</span></a>')
    prompt = (f"Add a custom connector for me. Name: Landfall. MCP server URL: {connector_url}/mcp. "
              "Transport: Streamable HTTP. Authentication: none.")
    stages, problems, audits = _counts()
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Landfall: make your shop visible to every AI assistant</title>'
        f'<link rel="stylesheet" href="{FONTS_HARBOR}"><style>{HOME_CSS}</style></head><body><main><div class="in">'
        + toggle("small-town-blooms", None)
        + '<header class="qb"><h1>Landfall</h1><p>The factory that makes your shop visible, readable and shoppable '
          'to every AI assistant.</p></header>'
          '<p class="lede">Your customers now ask ChatGPT, Muse, Claude and Perplexity to find and buy things. '
          "Landfall's crew of agents tries your website the way each assistant does, shows what breaks with receipts, "
          'builds the fixes, and proves them on a copy of your site.</p>'
          '<nav class="doors" aria-label="Start here">'
          '<a class="door" href="#shops"><h2>Outside the factory</h2><p>Reports for the shops we audited: what '
          'assistants see, what we fixed, your to-do.</p></a>'
          '<a class="door" href="/crew?slug=small-town-blooms"><h2>Inside the factory</h2><p>Meet the crew: every '
          'sailor is an agent, and how each uses Firedrill, Cognee and Amplitude.</p></a>'
          '<a class="door y" href="#plug"><h2>Plug it into your assistant</h2><p>One prompt connects Landfall to '
          'Muse, Claude, Grok or ChatGPT.</p></a></nav>'
        + f'<div class="stats"><span><b>{audits}</b>shops audited</span><span><b>{problems}</b>problems found with '
          f'receipts</span><span><b>{sum(stages.values())}</b>agent stages logged</span><span><b>2</b>Firedrill drills</span></div>'
        + '<h3 id="shops">Shops that came ashore</h3><p class="note">Real small businesses outside the Bay. Read-only: '
          'we never order, pay or send a form.</p><div class="rope"></div><section class="shops">'
        + "".join(shops)
        + '</section><h3 id="plug">Plug it into your assistant</h3><div class="plug"><p>Paste this into Muse (or add '
          'the URL as a custom connector in Claude, Grok or ChatGPT), then ask: "Can my customers\' AI assistants shop '
          f'on my website?"</p><code>{esc(prompt)}</code></div></div></main></body></html>'
    )

