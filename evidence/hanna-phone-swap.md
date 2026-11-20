# Hanna Plumbing & Heating: humans and AI assistants see different phone numbers

Checked 2026-11-20 ~13:22 PST, read-only.

- Raw HTML (what an assistant that does not run JavaScript reads), `curl -sL -A "Mozilla/5.0" https://hannaplumbingheating.com`:
  only `(319) 377-2809` / `3193772809` (27 occurrences).
- Real browser (Playwright, JavaScript on), all `tel:` links on the homepage: `tel:+13193260380` / `(319) 326-0380` (8 links).
- Landfall's scanner run (runs/hanna-plumbing/scan.json, nojs_content check) saw a third number after JavaScript: `(319) 326-0388`.

The number shown after JavaScript changes between visits, which matches a call-tracking number pool (inference, not confirmed with
the business). Consequence: calls that come from AI assistants reading the raw page use 377-2809 and skip the tracking numbers,
so the owner cannot see how many customers AI assistants send.
