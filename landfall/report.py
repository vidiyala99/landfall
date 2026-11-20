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

FONTS_HARBOR = ("https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700"
                "&family=Big+Shoulders+Display:wght@700;800&family=Ultra&display=swap")
STATIC = "/static/harbor"

SEV_ORDER = {"high": 0, "med": 1, "low": 2}
GROUP_WORD = {"high": "Big problems", "med": "Worth fixing", "low": "Small things"}
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


# ---------- scores ----------

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


def _num(v, cls, unit=""):
    return f'<span class="{cls}">{esc(v)}</span>' + (f'<span class="unit">{esc(unit)}</span>' if unit else "")


ARROW = '<span class="arrow" aria-hidden="true"></span><span class="sr">became</span>'
NOT_RUN = '<span class="na">not run yet</span>'
PENDING = '<span class="pending">re-check after you publish the fixes</span>'

# ---------- the headline: one plain sentence an owner gets in five seconds ----------

# Most-blocking first; a check that keeps assistants out entirely beats a missing label.
HEADLINE_ORDER = ("bot_challenge", "robots_ai", "nojs_content", "jsonld_business", "facts_in_images_or_pdf",
                  "menu_js", "jsonld_hours", "jsonld_offers", "contact_machine_readable", "form_labels", "llms_txt")
HEADLINES = {
    "bot_challenge": ("Some AI assistants are turned away at your door", "Requests that identify as certain assistants get an error page instead of your site."),
    "robots_ai": ("Your website tells AI assistants to stay out", "A setting on your site asks assistants like ChatGPT not to read it."),
    "nojs_content": ("Your website looks blank to AI assistants", "Your key facts only appear after a script runs, and most assistants never run it."),
    "nojs_prices": ("AI assistants can see your products but not your prices", "Your prices only appear after a script runs. Assistants that read the page without running it, like ChatGPT, find no prices."),
    "jsonld_business": ("AI assistants can't be sure who you are", "Your name, address and phone are not labeled in a way assistants can read."),
    "facts_in_images_or_pdf": ("Your menu is locked where AI can't read it", "Your prices sit inside pictures or PDFs that assistants skip."),
    "menu_js": ("AI assistants can't see your menu", "Your menu only appears after a script runs, and most assistants never run it."),
    "jsonld_hours": ("AI assistants can't tell when you're open", "Your hours are not labeled in a way assistants can read, so they guess."),
    "jsonld_offers": ("AI assistants can't see what you sell", "Your products and prices are not labeled in a way assistants can read."),
    "contact_machine_readable": ("AI assistants can't pick up your contact details", "Your phone and address are hard for assistants to find on the page."),
    "form_labels": ("AI assistants can't fill in your forms", "Some boxes on your forms have no name, so assistants don't know what to type."),
    "llms_txt": ("AI assistants have no guide to your website", "A short guide file would tell them what you do and where your facts live."),
}
# Short problem names for the "what's broken" rows (check titles in scan.json describe the passing state).
PROBLEM = {
    "bot_challenge": "A bot wall turns AI assistants away",
    "robots_ai": "Your site tells AI assistants to stay out",
    "nojs_content": "Key facts only appear after a script runs",
    "jsonld_business": "Name, address and phone are not labeled for assistants",
    "jsonld_hours": "Opening hours are not labeled for assistants",
    "jsonld_offers": "Products and prices are not labeled for assistants",
    "facts_in_images_or_pdf": "Menu or prices are stuck in pictures or PDFs",
    "form_labels": "Form boxes have no names",
    "contact_machine_readable": "Phone and address are hard for assistants to pick up",
    "img_alt": "Pictures have no text descriptions",
    "sitemap": "No sitemap for assistants to follow",
    "llms_txt": "No short guide for assistants (llms.txt)",
}


def _failing(scan):
    checks = [c for c in _list(_dict(scan).get("checks")) if isinstance(c, dict)]
    fails = [c for c in checks if c.get("status") in ("fail", "warn")]
    fails.sort(key=lambda c: (SEV_ORDER.get(c.get("severity"), 3), 0 if c.get("status") == "fail" else 1))
    return checks, fails


def _task_sentence(do):
    ds = _do_score(do)
    if not ds:
        return ""
    done, total = ds
    if done == 0:
        return f"An AI assistant tried {total} customer tasks and couldn't finish any."
    if done < total:
        return f"An AI assistant finished {done} of {total} customer tasks."
    return f"An AI assistant still finished all {total} customer tasks."


def headline(scan, do):
    """(title, sub) in plain words, from the worst failed check plus the task results."""
    if not scan:
        return ("Can AI assistants help your customers?",
                "We test what assistants like ChatGPT see on your website, build fixes, and test again.")
    _, fails = _failing(scan)
    tasks = _task_sentence(do)
    if not fails:
        return ("AI assistants can read your website", " ".join(x for x in ("Every check we ran passed.", tasks) if x))
    top_sev = SEV_ORDER.get(fails[0].get("severity"), 3)
    worst = [c for c in fails if SEV_ORDER.get(c.get("severity"), 3) == top_sev]
    worst.sort(key=lambda c: HEADLINE_ORDER.index(c.get("id")) if c.get("id") in HEADLINE_ORDER else 99)
    c = worst[0]
    # Prices that only appear after JavaScript block shopping outright (verified live: ChatGPT found the products
    # but "not a price"), so that finding leads whenever it is present.
    priced = [f for f in fails if f.get("id") == "nojs_content" and "prices" in (f.get("detail") or "").lower()]
    if priced:
        c = {"id": "nojs_prices"}
    if c.get("id") in HEADLINES:
        title, sub = HEADLINES[c["id"]]
    else:
        title = "AI assistants are missing facts about you"
        sub = f"We found {len(fails)} {'thing' if len(fails) == 1 else 'things'} that stop assistants reading your site."
    return title, " ".join(x for x in (sub, tasks) if x)


# ---------- hero ----------

def _flat(before, after) -> str:
    """Only an improvement gets the green 'after' colour; no change stays neutral."""
    return " flat" if isinstance(before, (int, float)) and isinstance(after, (int, float)) and after <= before else ""


def _metric(label, question, value_html) -> str:
    return (f'<div class="metric" role="group" aria-label="{esc(label)}"><div class="m-label">{esc(label)}</div>'
            f'<div class="m-q">{esc(question)}</div><div class="nums">{value_html}</div></div>')


def section_hero(name, url, scan, after_scan, do, after_do, find, after_find) -> str:
    rb, ra = _read_score(scan), _read_score(after_scan)
    if rb is None and ra is None:
        read = NOT_RUN
    else:
        read = (_num(rb, "before") if rb is not None else NOT_RUN) + ARROW + (
            _num(ra, "after" + _flat(rb, ra), "/100") if ra is not None else PENDING)

    db, da = _do_score(do), _do_score(after_do)
    if db is None and da is None:
        doh = NOT_RUN
    else:
        doh = (_num(f"{db[0]}/{db[1]}", "before") if db else NOT_RUN) + ARROW + (
            _num(f"{da[0]}/{da[1]}", "after" + _flat(db[0] if db else None, da[0])) if da else PENDING)

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
            yn(after_find, "after") if after_find else PENDING)

    site = f'<a href="{safe_url(url)}" rel="noopener noreferrer">{esc(_host(url))}</a>' if safe_url(url) else ""
    show_name = esc(name) if not (site and str(name).lower() == _host(url).lower()) else ""
    biz = show_name + (" " if show_name and site else "") + site
    title, sub = headline(scan, do)
    return biz, title, sub, (_metric("Read", "Can assistants read your facts?", read)
                             + _metric("Do", "Can they finish customer tasks?", doh)
                             + _metric("Found", "Do they suggest you?", found))


def _split_sub(sub, do):
    """The hero keeps the problem sentence; the task sentence moves to the tasks section (less text up top)."""
    tasks = _task_sentence(do)
    if tasks and sub.endswith(tasks):
        return sub[:-len(tasks)].strip() or sub, tasks
    return sub, ""


def _host(url):
    m = re.match(r"^https?://([^/]+)", url or "", re.I)
    h = m.group(1) if m else (url or "")
    return h[4:] if h.lower().startswith("www.") else h


def _empty(msg):
    return f'<p class="empty">{msg}</p>'


def _first_sentence(text, limit=140):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r"^(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def _row(cls, summary_html, body_html) -> str:
    return (f'<details class="row {cls}"><summary>{summary_html}<span class="chev" aria-hidden="true"></span></summary>'
            f'<div class="body">{body_html}</div></details>')


# ---------- tasks ----------

CHIP_WORD = {"done": "Done", "partial": "Partly", "failed": "Failed"}


def section_do(do, after_do, lead="", title="What the assistant tried") -> str:
    head = (f'<h2>{esc(title)}</h2><p class="note">{esc(lead + " " if lead else "")}'
            'It only looked: no orders, payments or forms.</p>')
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
        after_src = t if is_after_only else a
        chips = (_chip(None if is_after_only else t.get("outcome"), "Before") + ARROW
                 + _chip(after_src.get("outcome") if after_src else None, "After fixes", pending=not after_src))
        reason_src = (t.get("blocker") if t.get("outcome") != "done" else None) or t.get("answer") or t.get("blocker")
        reason = f'<span class="why">{esc(_first_sentence(reason_src))}</span>' if reason_src and not is_after_only else ""
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
        body = ((f'<dl class="facts">{dl}</dl>' if dl else "")
                + (f'<p class="receipts"><span>Proof:</span> {"".join(links)}</p>' if links else "")) or '<p class="muted">No details saved.</p>'
        summary = (f'<span class="r-title">{esc(t.get("task") or "Untitled task")}</span>'
                   f'<span class="chips">{chips}</span>{reason}')
        items.append(_row("task", summary, body))
    return f'<section class="block wrap" id="tasks">{head}<div class="rows">{"".join(items)}</div></section>'


def _chip(outcome, when, pending=False):
    if outcome in OUTCOME_WORD:
        return (f'<span class="chip {outcome}" title="{esc(when)}: {OUTCOME_WORD[outcome]}">'
                f'<span class="sr">{esc(when)}: </span>{CHIP_WORD[outcome]}</span>')
    word = "re-check after you publish" if pending else "not run"
    return f'<span class="chip na"><span class="sr">{esc(when)}: </span>{word}</span>'


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


# ---------- what's broken ----------

def _status_tag(c, after_status) -> str:
    if c.get("fixable") is False or not c.get("fix_id"):
        # Not something a file can fix (e.g. a bot wall at the host): it needs the owner or the host.
        return ('<span class="tag host">Needs a setting change by you or your website host</span>'
                if after_status.get(c.get("id")) == "pass" or c.get("fixable") is False else "")
    if after_status.get(c.get("id")) == "pass":
        return '<span class="tag fixed">Fixed in our test copy</span>'
    return '<span class="tag">Fix included</span>' if c.get("fix_id") else ""


def section_broken(scan, after_scan, grouped=False, title="What's broken") -> str:
    head = f'<h2>{esc(title)}</h2><p class="note">Biggest first. Open any row for the proof we saved.</p>'
    if not scan:
        return f'<section class="block wrap" id="broken">{head}{_empty("The website check has not run yet.")}</section>'
    checks, fails = _failing(scan)
    after_status = {c.get("id"): c.get("status") for c in _list(_dict(after_scan).get("checks")) if isinstance(c, dict)}
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
            status = _status_tag(c, after_status)
            title = c.get("title") or c.get("id") or "Problem"
            name = PROBLEM.get(c.get("id"), title)
            body_parts = [f'<p>{esc(c.get("detail") or "")}</p>' if c.get("detail") else ""]
            if name != title:
                body_parts.append(f'<p class="muted">What we checked: {esc(title)}</p>')
            if c.get("fixable") is False and after_status.get(c.get("id")) == "pass":
                body_parts.append('<p class="muted">Our test copy has no wall, so the numbers above show what happens after.</p>')
            if excerpt:
                body_parts.append(f'<blockquote class="excerpt">{esc(excerpt)}</blockquote>')
            if link:
                body_parts.append(f'<p class="receipts">{link}</p>')
            summary = (f'<span class="sev"><span class="pip" aria-hidden="true"></span>{SEV_WORD[sev]}</span>'
                       f'<span class="r-title">{esc(name)}</span>{status}')
            rows.append((sev, _row(f"finding sev-{sev}", summary, "".join(body_parts))))
        if grouped:
            parts = []
            for sev in ("high", "med", "low"):
                group = [r for s, r in rows if s == sev]
                if group:
                    parts.append(f'<div class="group g-{sev}"><h3 class="g-head">{GROUP_WORD[sev]}'
                                 f'<span class="g-count">{len(group)}</span></h3><div class="rows">{"".join(group)}</div></div>')
            body = "".join(parts)
        else:
            body = f'<div class="rows">{"".join(r for _, r in rows)}</div>'
    tail = f'<p class="passed">{passed} of {len(checks)} checks passed.</p>' if checks else ""
    return f'<section class="block wrap" id="broken">{head}{body}{tail}</section>'


# ---------- found ----------

def section_find(find, after_find) -> str:
    head = '<h2>When a customer asked an assistant</h2>'
    if not find:
        return f'<section class="block wrap" id="found">{head}{_empty("We have not asked an assistant about you yet.")}</section>'
    agent = esc(find.get("agent") or "An AI assistant")
    visible = find.get("visible")
    verdict = ('<span class="tag fixed">You were suggested</span>' if visible is True else
               '<span class="tag bad">You were not suggested</span>' if visible is False else "")
    recs = [r for r in _list(find.get("recommendations")) if isinstance(r, dict)]
    rec_html = ""
    if recs:
        lis = "".join(f'<li><strong>{_ext_link(r.get("url"), r.get("name") or r.get("url")) if r.get("url") else esc(r.get("name"))}</strong>'
                      + (f' <span class="why-full">{esc(r.get("why"))}</span>' if r.get("why") else "") + "</li>" for r in recs)
        label = "Who it suggested instead" if visible is False else "Who it suggested"
        rec_html = _row("recs", f'<span class="r-title">{label} ({len(recs)})</span>', f'<ol class="recs">{lis}</ol>')
    proof = receipt_href(find.get("receipt"))
    proof_html = f' <a href="{proof}">Its full reply</a>' if proof else ""
    if after_find and isinstance(after_find.get("visible"), bool):
        after = f'After the fixes, on our test copy: {"suggested" if after_find["visible"] else "still not suggested"}.'
    else:
        after = "Assistants take weeks to notice changes. Re-check this after you publish the fixes."
    return (f'<section class="block wrap" id="found">{head}<div class="ask"><p class="asker">{agent} was asked:</p>'
            f'<p class="query">&ldquo;{esc(find.get("query") or "")}&rdquo;</p><p class="verdict">{verdict}{proof_html}</p></div>'
            f'{rec_html}<p class="passed">{after}</p></section>')


# ---------- fixes ----------

FIX_WHAT = {
    "llms_txt": "A short guide that tells assistants what you do",
    "robots_ai": "Lets AI assistants read your site",
    "jsonld_business": "Labels your name, address and phone",
    "jsonld_hours": "Labels your opening hours",
    "jsonld_offers": "Labels what you sell",
    "contact_machine_readable": "Makes your phone and address easy to pick up",
    "form_labels": "Names the boxes on your forms",
    "img_alt": "Adds text descriptions to your pictures",
}

# Where each kind of fix file goes, for files CHANGES.md does not describe.
WHERE_DEFAULT = {
    "llms.txt": "Upload to the root of your website.",
    "robots.txt": "Replace the robots.txt at the root of your website.",
    "agent.json": "Upload to yoursite.com/.well-known/agent.json (optional).",
    "jsonld.html": "Paste inside the <head> of your homepage.",
    "products.jsonld.html": "Paste inside the <head> of your homepage. Redo it when prices change.",
}


def _fix_items(changes: str | None):
    """Parse '### Title (`id`, sev)' blocks with **File:** and **Where to paste:** lines, grouped by file."""
    items = {}
    if not changes:
        return items
    for block in re.split(r"(?m)^###\s+", changes)[1:]:
        first = block.split("\n", 1)[0]
        cid = re.search(r"\(`([^`]+)`", first)
        title = FIX_WHAT.get(cid.group(1) if cid else "", re.sub(r"\s*\(`[^`]*`[^)]*\)\s*$", "", first).strip())
        f = re.search(r"\*\*File:\*\*\s*`?([^`\n]+?)`?\s*$", block, re.M)
        w = re.search(r"\*\*Where to paste:\*\*\s*(.+)$", block, re.M)
        if not f:
            continue
        key = f.group(1).strip().replace("\\", "/")
        key = key[len("fixes/"):] if key.startswith("fixes/") else key
        it = items.setdefault(key, {"what": [], "where": None})
        if title and title not in it["what"]:
            it["what"].append(title)
        if w and not it["where"]:
            it["where"] = w.group(1).strip()
    return items


def section_fixes(run_dir: Path, title="Your fix package") -> str:
    head = (f'<h2>{esc(title)}</h2><p class="note">Hand these files to whoever runs your website. '
            'Each one goes in one place.</p>')
    n_products = _product_count(run_dir)
    changes = _load_text(run_dir / "fixes" / "CHANGES.md")
    owner = _load_text(run_dir / "fixes" / "needs-owner.md")
    files = _fix_files(run_dir)
    if not changes and not files:
        left = _empty("No fixes yet. They appear here after the fix step runs.")
    else:
        parsed = _fix_items(changes)
        rels = {r for r, _ in files}
        # Described fixes first, in CHANGES.md order; skip a .json twin of an .html snippet.
        order = {k: i for i, k in enumerate(parsed)}
        ordered = sorted((f for f in files if not f[0].endswith(".md")
                          and not (f[0].endswith(".json") and f[0][:-5] + ".html" in rels)),
                         key=lambda f: (order.get(f[0], 99), f[0]))
        lis = []
        for rel, href in ordered:
            it = parsed.get(rel, {})
            whats = it.get("what", [])
            if rel.rsplit("/", 1)[-1] == "products.jsonld.html":
                what = _file_purpose(rel, n_products)
            elif not whats:
                what = _file_purpose(rel)
            elif len(whats) == 1:
                what = whats[0]
            elif len(whats) == 2:
                what = whats[0] + " and " + whats[1][:1].lower() + whats[1][1:]
            else:
                what = _file_purpose(rel) + f" (fixes {len(whats)} problems)"
            where = it.get("where") or WHERE_DEFAULT.get(rel.rsplit("/", 1)[-1], "Your web person will know where this goes.")
            lis.append(f'<li><div class="f-what">{esc(what)}</div><div class="f-where">{esc(where)}</div>'
                       f'<a class="file" href="{href}">{esc(rel)}</a></li>')
        notes = [f'<a href="{h}">{esc(r)}</a>' for r, h in files if r.endswith(".md")]
        full = (_row("notes", '<span class="r-title">Full notes on every change</span>',
                     f'<div class="md">{markdown(changes)}</div>') if changes else "")
        left = ((f'<ol class="checklist">{"".join(lis)}</ol>' if lis else "")
                + (f'<p class="receipts"><span>Guides for your web person:</span> {"".join(notes)}</p>' if notes else "")
                + full)
    right = ('<aside class="owner"><h3>Questions only you can answer</h3>'
             + (f'<div class="md">{markdown(tidy_owner(_drop_title(owner)))}</div>' if owner
                else "<p>" + ("None right now." if changes else "These appear after the fix step runs.") + "</p>")
             + "</aside>")
    return f'<section class="block wrap" id="fixes">{head}<div class="cols">{left and f"<div>{left}</div>"}{right}</div></section>'


def _drop_title(md: str) -> str:
    """The aside already has a heading; drop the file's own leading '# ...' line."""
    return re.sub(r"^\s*#[^\n]*\n", "", md, count=1)


def _product_count(run_dir: Path):
    data = _load_json(run_dir / "products.json")
    if not data:
        return None
    n = data.get("count")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    items = data.get("products")
    return len(items) if isinstance(items, list) else None


def tidy_owner(md: str) -> str:
    """Owner questions quote scraped text: drop a span repeated back to back, and space 'Fri9:00' as 'Fri 9:00'."""
    out = []
    for line in md.split("\n"):
        prev = None
        while prev != line:
            prev = line
            line = re.sub(r"(\S.{5,}?)(?:\s*\1)+", r"\1", line)
        line = re.sub(r"(?<=[A-Za-z])(?=\d{1,2}:\d{2})", " ", line)
        out.append(line)
    return "\n".join(out)


def _file_purpose(rel: str, n_products=None) -> str:
    name = rel.rsplit("/", 1)[-1]
    if name == "products.jsonld.html":
        return (f"Your {n_products} products with their prices, readable by assistants" if n_products
                else "Your products with their prices, readable by assistants")
    return {"llms.txt": "A short guide that tells assistants what you do",
            "robots.txt": "Lets AI assistants read your site",
            "agent.json": "A card listing what an assistant can do on your site",
            "jsonld.html": "A hidden label with your business facts",
            "jsonld.json": "The same hidden label, as a plain data file"}.get(name, "Fix file")


def _fix_files(run_dir: Path):
    fixes = run_dir / "fixes"
    try:
        found = sorted(p for p in fixes.rglob("*") if p.is_file() and p.name not in ("CHANGES.md", "needs-owner.md"))
    except OSError:
        return []
    out = []
    for p in found[:40]:
        href = receipt_href(p.relative_to(run_dir).as_posix())
        if href:
            out.append((p.relative_to(fixes).as_posix(), href))
    return out


def section_footer(scan, do, find) -> str:
    when = [esc(x) for x in (_dict(scan).get("fetched_at"), _dict(do).get("ran_at"), _dict(find).get("asked_at")) if x]
    stamp = f" Checked {when[0][:10]}." if when else ""
    return f"""<footer class="wrap"><h3>How this was checked</h3>
<ul><li>Read-only. We never ordered, paid, signed up or sent a form on your website.</li>
<li>Fixes were tried on a private copy of your site, not the live one.</li>
<li>Every problem links to a saved receipt: the page text, a screenshot or the assistant's reply.</li></ul>
<p>Made with Landfall.{stamp}</p></footer>"""


VARIANTS = ("a", "b", "harbor-a", "harbor-b")


def _fix_tally(scan, after_scan):
    """(problems, fixed in the test copy, needs the owner or host) for the step labels and summary."""
    _, fails = _failing(scan)
    after_status = {c.get("id"): c.get("status") for c in _list(_dict(after_scan).get("checks")) if isinstance(c, dict)}
    host = sum(1 for c in fails if c.get("fixable") is False or not c.get("fix_id"))
    fixed = sum(1 for c in fails if c.get("fix_id") and c.get("fixable") is not False
                and after_status.get(c.get("id")) == "pass")
    return len(fails), fixed, host


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _todo_count(run_dir: Path):
    owner = _load_text(run_dir / "fixes" / "needs-owner.md") or ""
    questions = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*+])\s+", owner))
    files = [r for r, _ in _fix_files(run_dir) if not r.endswith(".md")]
    rels = set(files)
    files = [r for r in files if not (r.endswith(".json") and r[:-5] + ".html" in rels)]
    return questions, len(files)


def _layout_a(ctx) -> str:
    """Three-step story: the headline and three numbers on top, then one step on screen at a time.
    Tabs are radio inputs, so it works with no script; print shows every step."""
    problems, fixed, host = ctx["tally"]
    questions, nfiles = ctx["todo"]
    todo = " and ".join(x for x in (_plural(nfiles, "file") if nfiles else "",
                                     _plural(questions, "question") if questions else "") if x)
    steps = [
        ("wrong", "What's wrong", _plural(problems, "problem") if ctx["scan"] else "not checked yet"),
        ("fixed", "What we fixed", f"{fixed} of {problems} fixed" if problems else "customer tasks"),
        ("next", "What you do next", todo or "nothing yet"),
    ]
    inputs = "".join(f'<input class="step-in" type="radio" name="step" id="step-{i}"{" checked" if i == 1 else ""} '
                     f'aria-label="Step {i}: {esc(t)}">' for i, (_, t, _c) in enumerate(steps, 1))
    tabs = "".join(f'<label class="tab" for="step-{i}"><span class="tab-n">{i}</span>'
                   f'<span class="tab-t">{esc(t)}</span><span class="tab-c">{esc(c)}</span></label>'
                   for i, (_, t, c) in enumerate(steps, 1))

    def nxt(i):
        if i >= 3:
            return '<p class="end">That is the whole report. Questions? Reply to the email this came with.</p>'
        return (f'<div class="pager"><label class="next" for="step-{i + 1}">Next: {esc(steps[i][1])}'
                f'<span class="arrow" aria-hidden="true"></span></label></div>')

    fixed_line = ""
    if problems:
        bits = [f"{fixed} of {problems} problems are fixed in our private test copy of your site."]
        if host:
            bits.append(f"{_plural(host, 'problem')} {'needs' if host == 1 else 'need'} a setting change by you or your host.")
        fixed_line = f'<p class="tally">{esc(" ".join(bits))}</p>'
    panels = [ctx["broken"] + ctx["find"], fixed_line + ctx["do"], ctx["fixes"]]
    body = "".join(f'<div class="panel p{i}" id="{steps[i - 1][0]}">{part}{nxt(i)}</div>'
                   for i, part in enumerate(panels, 1))
    return f"""<body class="v-a"><a class="skip" href="#story">Skip to the steps</a>
<header class="hero wrap" id="top">
  <p class="biz">{ctx["biz"]}</p>
  <h1>{esc(ctx["title"])}</h1>
  <p class="sub">{esc(ctx["sub"])}</p>
  <div class="board" aria-label="Before and after our fixes">{ctx["board"]}</div>
  <p class="legend">Today, then after our fixes on a private copy of your site.</p>
</header>
<main class="story wrap" id="story">
{inputs}
<nav class="tabs" aria-label="Report steps">{tabs}</nav>
<div class="panels">{body}</div>
</main>
{ctx["footer"]}
</body>"""


def _layout_b(ctx) -> str:
    """Checklist dashboard: a sticky summary on the left, a compact problem, fix and proof checklist on the
    right grouped by severity, and a final to-do card."""
    problems, fixed, host = ctx["tally"]
    questions, nfiles = ctx["todo"]
    verdict = []
    if problems:
        verdict.append(f'<li><strong>{problems}</strong> problems found</li>')
        verdict.append(f'<li><strong>{fixed}</strong> fixed in our test copy</li>')
        if host:
            verdict.append(f'<li><strong>{host}</strong> need{"s" if host == 1 else ""} you or your host</li>')
    if nfiles or questions:
        verdict.append(f'<li><strong>{nfiles + questions}</strong> things on your to-do</li>')
    jump = ('<nav class="jump" aria-label="On this page"><a href="#broken">Problems</a><a href="#tasks">Tasks</a>'
            '<a href="#found">Found</a><a href="#todo">Your to-do</a></nav>')
    verdict_html = f'<ul class="verdict-list">{"".join(verdict)}</ul>' if verdict else ""
    return f"""<body class="v-b"><a class="skip" href="#broken">Skip to the checklist</a>
<div class="dash wrap">
<aside class="summary hero" id="top">
  <p class="biz">{ctx["biz"]}</p>
  <h1>{esc(ctx["title"])}</h1>
  <p class="sub">{esc(ctx["sub"])}</p>
  <div class="board" aria-label="Before and after our fixes">{ctx["board"]}</div>
  <p class="legend">Today, then after our fixes on a private copy of your site.</p>
  {verdict_html}
  {jump}
</aside>
<main class="list">
{ctx["broken"]}
{ctx["do"]}
{ctx["find"]}
<div class="todo" id="todo">{ctx["fixes"]}</div>
</main>
</div>
{ctx["footer"]}
</body>"""


# ---------- harbor world (variants harbor-a, harbor-b) ----------

def _cargo_tags(scan, after_scan) -> str:
    """Each problem is a manila cargo tag on twine: the front says the problem and how bad it is,
    opening it (a <details>, so no script) turns it over to the receipt and the fix status."""
    if not scan:
        return _empty("The website check has not run yet.")
    _, fails = _failing(scan)
    if not fails:
        return _empty("Nothing broken. Assistants can read everything we checked.")
    after_status = {c.get("id"): c.get("status") for c in _list(_dict(after_scan).get("checks")) if isinstance(c, dict)}
    tags = []
    for c in fails:
        sev = c.get("severity") if c.get("severity") in SEV_WORD else "low"
        r = _dict(c.get("receipt"))
        href = receipt_href(r.get("path"))
        link = f'<a href="{href}">See the proof</a>' if href else ""
        if not link and safe_url(r.get("url")):
            link = _ext_link(r.get("url"), "See the page")
        name = PROBLEM.get(c.get("id"), c.get("title") or c.get("id") or "Problem")
        back = [f'<p>{esc(_first_sentence(c.get("detail"), 150))}</p>' if c.get("detail") else ""]
        if r.get("excerpt"):
            back.append(f'<blockquote class="excerpt">{esc(r.get("excerpt"))}</blockquote>')
        if link:
            back.append(f'<p class="receipts">{link}</p>')
        tags.append(f'<li class="cargo sev-{sev}"><details><summary>'
                    f'<span class="eyelet" aria-hidden="true"></span>'
                    f'<span class="stamp">{SEV_WORD[sev]}</span>'
                    f'<span class="c-name">{esc(name)}</span>{_status_tag(c, after_status)}'
                    f'<span class="c-open">Turn over for proof</span></summary>'
                    f'<div class="c-back">{"".join(back) or "<p>No proof saved.</p>"}</div></details></li>')
    return f'<ol class="cargo-line" aria-label="Problems, biggest first">{"".join(tags)}</ol>'


def _todo_words(ctx) -> str:
    questions, nfiles = ctx["todo"]
    return " and ".join(x for x in (_plural(nfiles, "file") if nfiles else "",
                                     _plural(questions, "question") if questions else "") if x) or "nothing yet"


def _harbor_quarterboard(ctx) -> str:
    return f'<h1 class="qb"><span class="qb-face">{esc(ctx["title"])}</span></h1>'


def _layout_harbor_a(ctx) -> str:
    """The dock board: one projector screen with the quarterboard headline, the slate tally, the enamel to-do
    plate and a line of cargo tags; tasks, the customer question and the fix files sit on the deck below."""
    return f"""<body class="v-harbor v-ha"><a class="skip" href="#deck">Skip to the details</a>
<header class="dock" id="top">
  <div class="dock-in">
    <p class="biz">{ctx["biz"]}</p>
    {_harbor_quarterboard(ctx)}
    <p class="sub">{esc(ctx["sub"])}</p>
    <div class="dock-row">
      <div class="slate board" role="group" aria-label="Before and after our fixes">{ctx["board"]}</div>
      <a class="enamel" href="#todo"><span class="e-k">Your to-do</span><span class="e-v">{esc(_todo_words(ctx))}</span></a>
    </div>
    <section class="cargo-wrap" id="broken" aria-labelledby="cargo-h">
      <h2 id="cargo-h" class="sr">Problems</h2>
      {_cargo_tags(ctx["scan"], ctx["after_scan"])}
    </section>
  </div>
</header>
<main class="deck" id="deck">
{ctx["do"]}
{ctx["find"]}
<div class="todo" id="todo">{ctx["fixes"]}</div>
</main>
{ctx["footer"]}
</body>"""


def _layout_harbor_b(ctx) -> str:
    """The arrival log: a short quayside header, then three paged berths (Arrived, Repaired, Ready to sail),
    each signposted by a carved quarterboard. Berths are radio inputs, so it works with no script."""
    problems, fixed, host = ctx["tally"]
    berths = [
        ("arrived", "Arrived", _plural(problems, "problem") if ctx["scan"] else "not checked yet", "qb-quay-1"),
        ("repaired", "Repaired", f"{fixed} of {problems} fixed" if problems else "customer tasks", "qb-yard-2"),
        ("ready", "Ready to sail", _todo_words(ctx), "qb-sail-1"),
    ]
    inputs = "".join(f'<input class="step-in" type="radio" name="berth" id="berth-{i}"{" checked" if i == 1 else ""} '
                     f'aria-label="{esc(t)}: {esc(c)}">' for i, (_, t, c, _p) in enumerate(berths, 1))
    posts = "".join(f'<label class="post" for="berth-{i}" style="--plate:url({STATIC}/{p}.webp)">'
                    f'<span class="post-t">{esc(t)}</span><span class="post-c">{esc(c)}</span></label>'
                    for i, (_, t, c, p) in enumerate(berths, 1))

    def nxt(i):
        if i >= 3:
            return '<p class="end">That is the whole log. Questions? Reply to the email this came with.</p>'
        return (f'<div class="pager"><label class="next" for="berth-{i + 1}">Next: {esc(berths[i][1])}'
                f'<span class="arrow" aria-hidden="true"></span></label></div>')

    fixed_line = ""
    if problems:
        bits = [f"{fixed} of {problems} problems are fixed in our private test copy of your site."]
        if host:
            bits.append(f"{_plural(host, 'problem')} {'needs' if host == 1 else 'need'} a setting change by you or your host.")
        fixed_line = f'<p class="tally slate-line">{esc(" ".join(bits))}</p>'
    arrived = ('<section class="block" id="broken"><h2>What came ashore</h2>'
               '<p class="note">Biggest first. Turn a tag over for the proof.</p>'
               f'{_cargo_tags(ctx["scan"], ctx["after_scan"])}</section>' + ctx["find"])
    ready = ctx["fixes"]  # its "Your to-do" heading is styled as the yellow enamel plate
    panels = [arrived, fixed_line + ctx["do"], ready]
    body = "".join(f'<div class="panel p{i}" id="{berths[i - 1][0]}">{part}{nxt(i)}</div>'
                   for i, part in enumerate(panels, 1))
    return f"""<body class="v-harbor v-hb"><a class="skip" href="#log">Skip to the log</a>
<header class="quay" id="top">
  <div class="quay-in">
    <p class="biz">{ctx["biz"]}</p>
    {_harbor_quarterboard(ctx)}
    <p class="sub">{esc(ctx["sub"])}</p>
    <div class="slate board" role="group" aria-label="Before and after our fixes">{ctx["board"]}</div>
  </div>
</header>
<main class="log" id="log">
{inputs}
<nav class="posts" aria-label="Report berths">{posts}</nav>
<div class="panels">{body}</div>
</main>
{ctx["footer"]}
</body>"""


def render(run_dir, variant="a") -> str:
    """variant 'a' is the three-step story, 'b' the checklist dashboard, 'harbor-a' the dock board and
    'harbor-b' the arrival log (harbor world); anything else falls back to 'a'."""
    run_dir = Path(run_dir)
    variant = variant if variant in VARIANTS else "a"
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
    harbor = variant.startswith("harbor")
    if harbor:
        css += "\n" + (TEMPLATES / "report-harbor.css").read_text(encoding="utf-8")
    css += "\n" + (TEMPLATES / f"report-{variant}.css").read_text(encoding="utf-8")

    biz, title, sub, board = section_hero(name, url, scan, after_scan, do, after_do, find, after_find)
    sub, task_line = _split_sub(sub, do)
    ctx = {
        "scan": scan, "after_scan": after_scan, "biz": biz, "title": title, "sub": sub, "board": board,
        "tally": _fix_tally(scan, after_scan), "todo": _todo_count(run_dir),
        "broken": section_broken(scan, after_scan, grouped=(variant == "b"),
                                 title="Problems" if variant == "b" else "What's broken"),
        "do": section_do(do, after_do, lead=task_line,
                         title="Customer tasks, before and after" if variant == "a" else "What the assistant tried"),
        "find": section_find(find, after_find),
        "fixes": section_fixes(run_dir, title="Your to-do"),
        "footer": section_footer(scan, do, find),
    }
    layout = {"b": _layout_b, "harbor-a": _layout_harbor_a, "harbor-b": _layout_harbor_b}.get(variant, _layout_a)(ctx)

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(name)}: AI assistant check</title>
<meta name="description" content="Can AI assistants read, use and recommend {esc(name)}? Before and after report.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_HARBOR if harbor else FONTS}">
<style>{css}</style></head>
{layout}</html>"""
    try:
        (run_dir / "report.html").write_text(page, encoding="utf-8")
    except OSError:
        pass
    return page


if __name__ == "__main__":
    out = render(Path(sys.argv[1]), *sys.argv[2:3])
    print(f"wrote {Path(sys.argv[1]) / 'report.html'} ({len(out)} bytes)")
