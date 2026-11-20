"""Owner-facing before/after report for one Landfall run.

render(run_dir) -> str returns one self-contained HTML page and also writes run_dir/report.html.
Every input file is optional; a missing or broken file shows a "not run yet" state instead of crashing.
All text from the run files came from real websites, so every string is HTML-escaped and every link
is checked (receipts become files/<relative path>; outside links must be http(s)).
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path, PurePosixPath

TEMPLATES = Path(__file__).resolve().parent / "templates"
FONTS = ("https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700"
         "&family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&display=swap")

SEV_ORDER = {"high": 0, "med": 1, "low": 2}
SEV_WORD = {"high": "Big problem", "med": "Worth fixing", "low": "Small thing"}
OUTCOME_WORD = {"done": "Done", "partial": "Got partway", "failed": "Couldn't do it"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _load_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _load_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def receipt_href(path) -> str | None:
    """Relative run path -> files/<path>. Rejects absolute paths, traversal and URL schemes."""
    if not path or not isinstance(path, str):
        return None
    p = path.replace("\\", "/").strip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", p):  # http:, javascript:, C: ...
        return None
    p = p.lstrip("/")
    if p.startswith("files/"):
        p = p[len("files/"):]
    parts = PurePosixPath(p).parts
    if not parts or any(part in ("..", "") for part in parts):
        return None
    return "files/" + "/".join(html.escape(part, quote=True) for part in parts)


def safe_url(url) -> str | None:
    if isinstance(url, str) and re.match(r"^https?://", url.strip(), re.I):
        return esc(url.strip())
    return None


def _ext_link(url, text=None) -> str:
    href = safe_url(url)
    label = esc(text if text else url)
    return f'<a href="{href}" rel="noopener noreferrer">{label}</a>' if href else label


# ---------- tiny, safe markdown ----------

def _inline(text: str) -> str:
    """Escape, then re-add **bold**, `code` and [links](url) with checked hrefs."""
    out, pos = [], 0
    pattern = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")
    for m in pattern.finditer(text):
        out.append(esc(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{esc(m.group(1))}</code>")
        elif m.group(2) is not None:
            out.append(f"<strong>{esc(m.group(2))}</strong>")
        else:
            label, target = m.group(3), m.group(4)
            href = safe_url(target) or (None if ":" in target else receipt_href(_fix_path(target)))
            out.append(f'<a href="{href}">{esc(label)}</a>' if href else esc(label))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def _fix_path(target: str) -> str:
    t = target.replace("\\", "/").lstrip("./")
    return t if t.startswith(("fixes/", "after/", "receipts/", "files/")) else "fixes/" + t


def markdown(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out, para, list_tag, in_code, code = [], [], None, False, []

    def flush_para():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
                code, in_code = [], False
            else:
                flush_para(); close_list(); in_code = True
            continue
        if in_code:
            code.append(raw)
            continue
        if not line.strip():
            flush_para(); close_list()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            flush_para(); close_list()
            level = 3 if len(h.group(1)) <= 2 else 4  # page owns h1/h2
            out.append(f"<h{level}>{_inline(h.group(2))}</h{level}>")
            continue
        li = re.match(r"^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$", line)
        if li:
            flush_para()
            tag = "ul" if li.group(1) else "ol"
            if list_tag != tag:
                close_list(); out.append(f"<{tag}>"); list_tag = tag
            item = re.sub(r"^\[( |x|X)\]\s*", "", li.group(3))
            out.append("<li>" + _inline(item) + "</li>")
            continue
        close_list()
        para.append(line.strip())
    if in_code:
        out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
    flush_para(); close_list()
    return "\n".join(out)


# ---------- sections ----------

def _read_score(scan):
    if not scan:
        return None
    s = _dict(scan.get("score"))
    v = s.get("read")
    return v if isinstance(v, (int, float)) else None


def _do_score(do):
    if not do:
        return None
    s = _dict(do.get("score"))
    done, total = s.get("done"), s.get("total")
    if isinstance(done, int) and isinstance(total, int) and total > 0:
        return done, total
    tasks = _list(do.get("tasks"))
    if tasks:
        return sum(1 for t in tasks if _dict(t).get("outcome") == "done"), len(tasks)
    return None


def _score_row(label, what, before_html, after_html) -> str:
    return (f'<div class="score" role="group" aria-label="{esc(label)}"><div><div class="label">{esc(label)}</div>'
            f'<p class="what">{what}</p></div><div class="nums">{before_html}{after_html}</div></div>')


def _num(v, cls, unit=""):
    return f'<span class="{cls}">{esc(v)}</span>' + (f'<span class="unit">{esc(unit)}</span>' if unit else "")


ARROW = '<span class="arrow" aria-label="became">&rarr;</span>'
NOT_RUN = '<span class="na">not run yet</span>'


def section_hero(name, url, scan, after_scan, do, after_do, find, after_find) -> str:
    rb, ra = _read_score(scan), _read_score(after_scan)
    if rb is None and ra is None:
        read = NOT_RUN
    else:
        read = (_num(rb, "before") if rb is not None else NOT_RUN) + ARROW + (
            _num(ra, "after", "/100") if ra is not None else '<span class="pending">re-check after you publish the fixes</span>')

    db, da = _do_score(do), _do_score(after_do)
    if db is None and da is None:
        doh = NOT_RUN
    else:
        doh = (_num(f"{db[0]}/{db[1]}", "before") if db else NOT_RUN) + ARROW + (
            _num(f"{da[0]}/{da[1]}", "after") if da else '<span class="pending">re-check after you publish the fixes</span>')

    def yn(f, cls):
        v = f.get("visible")
        if v is True:
            return f'<span class="{cls} yes">Yes</span>'
        if v is False:
            return f'<span class="{cls} no">No</span>'
        return NOT_RUN
    if not find and not after_find:
        found = NOT_RUN
    else:
        found = (yn(find, "before") if find else NOT_RUN) + ARROW + (
            yn(after_find, "after") if after_find else '<span class="pending">re-check after you publish the fixes</span>')

    site = f' <a href="{safe_url(url)}" rel="noopener noreferrer">{esc(_host(url))}</a>' if safe_url(url) else ""
    if site and str(name).lower() == _host(url).lower():
        name, site = "", site.strip()
    return f"""
<header class="hero wrap" id="top">
  <div class="biz">{esc(name)}{(' &middot;' if name and site else '') + site}</div>
  <h1>Can AI assistants help your customers?</h1>
  <p class="lede">More people now ask AI assistants like ChatGPT, Claude and Meta Muse to find a bakery, check hours or order a cake.
  We tested what those assistants see on your website today, built fixes, and tested again.</p>
  <div class="board">
    {_score_row("Read", "Can assistants read your basic facts: name, hours, address, menu?", read, "")}
    {_score_row("Do", "Could an assistant finish real customer tasks on your site?", doh, "")}
    {_score_row("Found", "When a customer asked an assistant for a place like yours, did it suggest you?", found, "")}
  </div>
</header>"""


def _host(url):
    m = re.match(r"^https?://([^/]+)", url or "", re.I)
    h = m.group(1) if m else (url or "")
    return h[4:] if h.lower().startswith("www.") else h


def _empty(msg):
    return f'<div class="empty">{msg}</div>'


def section_do(do, after_do) -> str:
    head = ('<h2>What the assistant tried</h2><p class="lede">We gave an AI assistant real customer jobs on your site. '
            'It only looked; it never ordered, paid or sent a form.</p>')
    tasks = [t for t in _list(_dict(do).get("tasks")) if isinstance(t, dict)]
    after_tasks = {str(t.get("task")): t for t in _list(_dict(after_do).get("tasks")) if isinstance(t, dict)}
    if not tasks and not after_tasks:
        return f'<section class="block wrap" id="tasks">{head}{_empty("The assistant has not tried any tasks yet. Run the task check to fill this in.")}</section>'
    if not tasks:
        tasks = list(after_tasks.values())
    items = []
    for t in tasks:
        a = after_tasks.get(str(t.get("task"))) if do else None
        is_after_only = not do
        before_chip = _chip(None if is_after_only else t.get("outcome"), "Before")
        after_src = t if is_after_only else a
        after_chip = _chip(after_src.get("outcome") if after_src else None, "After fixes", pending=not after_src)
        facts = []
        blocker = t.get("blocker")
        if blocker and not is_after_only:
            facts.append(("What got in the way" if t.get("outcome") != "done" else "Worth knowing", esc(blocker)))
        if t.get("answer"):
            facts.append(("What it found", esc(t.get("answer"))))
        if a and a.get("answer") and a.get("answer") != t.get("answer"):
            facts.append(("After fixes it found", esc(a.get("answer"))))
        honest = _dict(t.get("honest"))
        if honest.get("ok") is False:
            facts.append(("Honesty check", "The assistant claimed more than it showed. " + esc(honest.get("reason") or "")))
        links = _task_receipts(t, "before") + (_task_receipts(a, "after fixes") if a else [])
        if t.get("evidence_url") and safe_url(t.get("evidence_url")):
            links.append(_ext_link(t.get("evidence_url"), "page it used"))
        dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts)
        items.append(f'<article class="task"><h3>{esc(t.get("task") or "Untitled task")}</h3>'
                     f'<div class="outcomes">{before_chip}{after_chip}</div>'
                     + (f'<dl class="facts">{dl}</dl>' if dl else "")
                     + (f'<div class="receipts">Proof: {"".join(links)}</div>' if links else "")
                     + "</article>")
    return f'<section class="block wrap" id="tasks">{head}<div class="tasks">{"".join(items)}</div></section>'


def _chip(outcome, when, pending=False):
    if outcome in OUTCOME_WORD:
        return f'<span class="chip {outcome}"><small>{esc(when)}:</small> {OUTCOME_WORD[outcome]}</span>'
    word = "re-check after you publish" if pending else "not run"
    return f'<span class="chip na"><small>{esc(when)}:</small> {word}</span>'


def _task_receipts(t, when):
    links = []
    r = _dict(_dict(t).get("receipt"))
    shots = [s for s in _list(r.get("screenshots")) if isinstance(s, str)]
    for i, s in enumerate(shots, 1):
        href = receipt_href(s)
        if href:
            label = f"screenshot {i} ({when})" if len(shots) > 1 else f"screenshot ({when})"
            links.append(f'<a href="{href}">{esc(label)}</a>')
    d = receipt_href(r.get("dir"))
    if d:
        links.append(f'<a href="{d}/">all steps ({esc(when)})</a>')
    return links


def section_broken(scan, after_scan) -> str:
    head = ('<h2>What\'s broken</h2><p class="lede">Problems that stop assistants from reading your site, '
            'biggest first. Each one links to the proof we saved.</p>')
    if not scan:
        return f'<section class="block wrap" id="broken">{head}{_empty("The website check has not run yet.")}</section>'
    checks = [c for c in _list(scan.get("checks")) if isinstance(c, dict)]
    after_status = {c.get("id"): c.get("status") for c in _list(_dict(after_scan).get("checks")) if isinstance(c, dict)}
    fails = [c for c in checks if c.get("status") in ("fail", "warn")]
    fails.sort(key=lambda c: (SEV_ORDER.get(c.get("severity"), 3), 0 if c.get("status") == "fail" else 1))
    passed = sum(1 for c in checks if c.get("status") == "pass")
    if not fails:
        body = _empty("Nothing broken. Assistants can read everything we checked.")
    else:
        rows = []
        for c in fails:
            sev = c.get("severity") if c.get("severity") in SEV_WORD else "low"
            r = _dict(c.get("receipt"))
            excerpt = r.get("excerpt")
            href = receipt_href(r.get("path"))
            link = f'<a href="{href}">See the proof</a>' if href else ""
            if not link and safe_url(r.get("url")):
                link = _ext_link(r.get("url"), "See the page")
            fixed = ' <span class="fixed">Fixed in our test copy</span>' if after_status.get(c.get("id")) == "pass" else ""
            rows.append(f'<li class="finding sev-{sev}"><div class="top"><h3>{esc(c.get("title") or c.get("id") or "Problem")}</h3>'
                        f'<span class="sev">{SEV_WORD[sev]}</span>{fixed}</div>'
                        f'<p>{esc(c.get("detail") or "")}</p>'
                        + (f'<blockquote class="excerpt">{esc(excerpt)}</blockquote>' if excerpt else "")
                        + (f'<div class="receipts">{link}</div>' if link else "") + "</li>")
        body = f'<ul class="findings">{"".join(rows)}</ul>'
    tail = f'<p class="passed">{passed} of {len(checks)} checks passed.</p>' if checks else ""
    return f'<section class="block wrap" id="broken">{head}{body}{tail}</section>'


def section_find(find, after_find) -> str:
    head = '<h2>When a customer asked an assistant</h2>'
    if not find:
        return f'<section class="block wrap" id="found">{head}{_empty("We have not asked an assistant about you yet.")}</section>'
    name_note = esc(find.get("agent") or "An AI assistant")
    visible = find.get("visible")
    verdict = ('<div class="verdict yes">You were suggested.</div>' if visible is True else
               '<div class="verdict no">You were not suggested.</div>' if visible is False else "")
    recs = [r for r in _list(find.get("recommendations")) if isinstance(r, dict)]
    rec_html = ""
    if recs:
        lis = "".join(f'<li><strong>{_ext_link(r.get("url"), r.get("name") or r.get("url")) if r.get("url") else esc(r.get("name"))}</strong>'
                      + (f' <span class="why">{esc(r.get("why"))}</span>' if r.get("why") else "") + "</li>" for r in recs)
        rec_html = f'<p>{"It suggested these instead:" if visible is False else "It suggested:"}</p><ol class="recs">{lis}</ol>'
    after = ""
    if after_find and isinstance(after_find.get("visible"), bool):
        after = f'<p class="passed">After the fixes, on our test copy: {"suggested" if after_find["visible"] else "still not suggested"}.</p>'
    else:
        after = ('<p class="passed">Assistants take time to notice changes. Re-check this after you publish the fixes.</p>')
    return (f'<section class="block wrap" id="found">{head}<div class="ask"><div>{name_note} was asked:</div>'
            f'<div class="query">&ldquo;{esc(find.get("query") or "")}&rdquo;</div>{verdict}{rec_html}</div>{after}</section>')


def section_fixes(run_dir: Path) -> str:
    head = ('<h2>The fixes we built</h2><p class="lede">Ready to hand to whoever runs your website. '
            'One of them is a hidden label (called JSON-LD) that tells assistants your hours and menu.</p>')
    changes = _load_text(run_dir / "fixes" / "CHANGES.md")
    owner = _load_text(run_dir / "fixes" / "needs-owner.md")
    left = (f'<div class="md">{markdown(changes)}{_file_list(run_dir)}</div>' if changes
            else _empty("No fixes yet. They appear here after the fix step runs."))
    right = (f'<div class="md owner"><h3>Questions only you can answer</h3>{markdown(owner)}</div>' if owner
             else '<div class="md owner"><h3>Questions only you can answer</h3><p>'
             + ("None right now." if changes else "These appear after the fix step runs.") + '</p></div>')
    return f'<section class="block wrap" id="fixes">{head}<div class="cols">{left}{right}</div></section>'


def _file_list(run_dir: Path) -> str:
    fixes = run_dir / "fixes"
    try:
        files = sorted(p for p in fixes.rglob("*") if p.is_file() and p.name not in ("CHANGES.md", "needs-owner.md"))
    except OSError:
        return ""
    links = []
    for p in files[:40]:
        rel = p.relative_to(run_dir).as_posix()
        href = receipt_href(rel)
        if href:
            links.append(f'<a href="{href}">{esc(p.relative_to(fixes).as_posix())}</a>')
    return f'<div class="filelist receipts">Fix files: {"".join(links)}</div>' if links else ""


def section_footer(scan, do, find) -> str:
    when = [esc(x) for x in (_dict(scan).get("fetched_at"), _dict(do).get("ran_at"), _dict(find).get("asked_at")) if x]
    stamp = f"<p>Checked {when[0][:10]}.</p>" if when else ""
    return f"""<footer class="wrap"><h3>How this was checked</h3>
<ul><li>Read-only. We never ordered, paid, signed up or sent a form on your website.</li>
<li>Fixes were tried on a private copy of your site, not the live one.</li>
<li>Every problem above links to a saved receipt: the page text, a screenshot or the assistant's reply.</li></ul>
{stamp}<p>Made with Landfall.</p></footer>"""


def render(run_dir) -> str:
    run_dir = Path(run_dir)
    scan = _load_json(run_dir / "scan.json")
    after_scan = _load_json(run_dir / "after" / "scan.json")
    do = _load_json(run_dir / "do.json")
    after_do = _load_json(run_dir / "after" / "do.json")
    find = _load_json(run_dir / "find.json")
    after_find = _load_json(run_dir / "after" / "find.json")
    result = _load_json(run_dir / "result.json") or {}

    facts = _dict(_dict(scan).get("facts"))
    url = _dict(scan).get("url") or _dict(do).get("url") or result.get("url") or ""
    name = facts.get("name") or result.get("name") or _host(url) or _dict(scan).get("slug") or run_dir.name
    css = (TEMPLATES / "report.css").read_text(encoding="utf-8")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(name)}: AI assistant check</title>
<meta name="description" content="Can AI assistants read, use and recommend {esc(name)}? Before and after report.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{css}</style></head>
<body><a class="skip" href="#tasks">Skip to details</a>
<main>
{section_hero(name, url, scan, after_scan, do, after_do, find, after_find)}
{section_do(do, after_do)}
{section_broken(scan, after_scan)}
{section_find(find, after_find)}
{section_fixes(run_dir)}
</main>
{section_footer(scan, do, find)}
</body></html>"""
    try:
        (run_dir / "report.html").write_text(page, encoding="utf-8")
    except OSError:
        pass
    return page


if __name__ == "__main__":
    out = render(Path(sys.argv[1]))
    print(f"wrote {Path(sys.argv[1]) / 'report.html'} ({len(out)} bytes)")
