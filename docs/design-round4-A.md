# Design round 4: harbor world rollouts (A and B)

Open: `python -m landfall.mcp_server --port 8771`, then
http://127.0.0.1:8771/reports/small-town-blooms?v=harbor-a and `?v=harbor-b`. Variants a and b still work.

## Screenshots (docs/shots/)
- A, 1920x1080 projector, first viewport: r4-harbor-a-1920.png
- A, 1920, bot-wall tag turned over: r4-harbor-a-1920-open.png
- A, 1440: r4-harbor-a-1440.png. A, 390 phone: r4-harbor-a-390.png
- B, 1920 first viewport: r4-harbor-b-1920.png. B, 1920 "Repaired" berth: r4-harbor-b-1920-repaired.png
- B, 1440: r4-harbor-b-1440.png. B, 390 phone: r4-harbor-b-390.png

## A: the dock board
One projector screen. A carved quarterboard carries the headline in gilt Ultra. The slate tally shows Read / Do / Found
before and after in chalk. The yellow enamel plate is "Your to-do" (5 files and 2 questions). Each problem hangs on the
twine as a manila cargo tag with a severity stamp, the plain problem and its fix status. Open a tag to turn it over:
one-sentence detail, the saved excerpt, the proof link. Tasks, the customer question and the fix files sit below the fold.

## B: the arrival log
A shorter quayside header (quarterboard, then the sub and the slate side by side). Below it, three carved quarterboard
posts on a wooden quay (Arrived / Repaired / Ready to sail) page the report one berth at a time. Arrived = cargo tags +
the customer question. Repaired = slate line "3 of 5 fixed" + tasks. Ready to sail = the to-do, with its heading as the
enamel plate. Radio inputs, no script; print shows every berth.

## Skill proof
- impeccable: `context --target landfall/report.py` returned NO_PRODUCT_MD + PRODUCT_INIT_REQUIRED, so I wrote
  PRODUCT.md from docs/DESIGN.md plus the owner's brief, with the assumptions labeled (subagent, no way to ask).
  `concept-seed --scope surface --mode read` dealt structures 6, 2, 5 (lead 6). The world was already fixed and the
  owner named both compositions, so the brief wins. craft-floor applied: no eyebrows, no gradient text, no hard offset
  shadows, themed selection and focus. Critique: `impeccable detect` first pass, A: 5 findings (enamel 2.4:1 read off
  the rivet gradient, tag link 4.3:1, amber stamp 4.47:1, enamel bevel flagged as side-tab, rope stripes); B: 4 findings.
  Fixed: rivets moved to a pseudo-element, link ink #523b24, amber ink #6a4204, bevel softened, quay wash lightened.
  Second pass: A 1 (repeating-stripes = the twine rope, kept on purpose), B 2 (rope + the dusk wash over the harbor
  plate, kept on purpose).
- taste-core: "Reading this as: an owner report for judges on a projector, with a crafted harbor-signage language,
  leaning toward native CSS + Ultra + Atkinson." Dials VARIANCE 7 / MOTION 4 / DENSITY 3. Pre-flight: pass on zero
  em dashes, theme lock, one accent (gilt/enamel), no eyebrows, CTA on one line, reduced motion, hero fits the viewport.
  Failed and fixed: phone overflow (the grid sized to the tag strip, now minmax(0,1fr)), the slate's box showing behind
  the plate art, the to-do duplicated in B.
- taste-redesign: overhaul mode. Kept IA, copy, data and every link. Retired the round-3 grey card board and the
  rows-only list as the first read.
- ui-ux-pro-max: `search.py --domain style` returned vintage-analog-retro-film (grain, light leaks). Rejected: the
  owner wants well kept, not distressed. `--domain typography` returned Abril Fatface + Merriweather. Rejected: Didone,
  not Clarendon. `--domain ux` returned the 4.5:1 contrast rule. Kept and checked with the detector.
- emil-design-eng: one authored moment. Tags swing onto the line (900ms, cubic-bezier(0.23,1,0.32,1), 70ms stagger,
  `backwards` fill so hover and open still work), then the after-numbers land. Press scale 0.97 / 0.985. Hover only
  under (hover:hover) and (pointer:fine). An open tag straightens to 0deg. B berths slide in 14px over 320ms. Reduced
  motion: no swing, no slide, no transitions.
- frontend-design: direction is "the harbor at dusk where the report comes ashore". The bold move is the line of
  hanging cargo tags. Everything around it stays quiet.
- gstack design review: Playwright live at 1920x1080, 1440x900 and 390x844. Clicked a tag open (A) and the Repaired
  and Ready to sail berths (B). Checked scrollWidth at 390: 375 for a 375 viewport, so no sideways scroll.

## Fonts
Ultra (heavy Clarendon slab) and Big Shoulders Display load from Google Fonts. Both are OFL on Google Fonts, but the
copies in Shipyard/portal/fonts have no license file next to them, so no font file ships in this public repo.

## Assets
From the owner's approved FLUX art in Shipyard: the harbor ground plate (no signage, no names), wood, slate and three
blank quarterboards, saved as webp in landfall/static/harbor/ (about 330 KB). The portal home comp was rejected as a
background because it shows Shipyard UI and company names.

## Recommendation
A for the projector: the whole story (headline, numbers, five tags, to-do) reads in one screen from the back of the
room. B is better for an owner reading alone on a phone, because it pages the details.
