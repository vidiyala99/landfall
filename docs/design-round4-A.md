# Design round 4: harbor-a (interim)

Open: `python -m landfall.mcp_server --port 8771`, then http://127.0.0.1:8771/reports/small-town-blooms?v=harbor-a

## Screenshots
- 1920x1080 projector, first viewport: docs/shots/r4-harbor-a-1920.png
- 1920 with the bot-wall tag turned over (proof showing): docs/shots/r4-harbor-a-1920-open.png
- 390 phone, top of page: docs/shots/r4-harbor-a-390.png

## What it is
The dock board. One projector screen: a carved quarterboard carries the headline in gilt Ultra, the slate tally shows
Read / Do / Found before and after in chalk, the yellow enamel plate is "Your to-do" (5 files and 2 questions), and each
problem hangs on the twine as a manila cargo tag (severity stamp + plain problem + fix status). Open a tag to turn it
over: one-sentence detail, the saved excerpt, and the proof link. Tasks, the customer question and the fix files sit
below the fold. CSS only, no script.

## Skill proof so far
- impeccable: `impeccable context --target landfall/report.py` returned NO_PRODUCT_MD + PRODUCT_INIT_REQUIRED, so I
  wrote PRODUCT.md from docs/DESIGN.md plus the owner's brief, with the assumptions labeled (subagent, no way to ask).
  `concept-seed --scope surface --mode read` dealt structures 6, 2, 5. The world was already fixed (Harbor/Shipyard)
  and the owner's brief named the two compositions, so the brief wins. craft-floor applied: no eyebrows, no gradient
  text, no hard offset shadows, browser surfaces themed (selection, focus).
- taste-core: "Reading this as: an owner report for judges on a projector, with a crafted harbor-signage language,
  leaning toward native CSS + Ultra + Atkinson." Dials VARIANCE 7 / MOTION 4 / DENSITY 3.
- ui-ux-pro-max: search.py style returned "vintage-analog-retro-film" (grain, light leaks). Rejected: the owner wants
  well kept, not distressed. Typography returned Abril Fatface + Merriweather. Rejected: Didone, not Clarendon. UX
  contrast rule (4.5:1) kept: chalk on slate and ink on manila both pass.
- emil-design-eng: one authored moment. Tags swing onto the line (900ms, ease-out cubic-bezier(0.23,1,0.32,1),
  70ms stagger, `backwards` fill so hover and open still work), then the after-numbers land. Press scale 0.97/0.985,
  hover only under (hover:hover) and (pointer:fine), an open tag straightens to 0deg. Reduced motion: no swing, no transitions.
- frontend-design: direction is "the harbor at dusk where the report comes ashore". The bold move is the line of
  hanging cargo tags; everything else stays quiet.

## Fonts
Ultra (heavy Clarendon slab) and Big Shoulders Display both load from Google Fonts. No font files ship in this public
repo: the Shipyard copies have no license file next to them.

## Assets
The harbor ground plate (no signage, no names) and the wood, slate and quarterboard plates come from the owner's
approved FLUX art in Shipyard, saved as webp in landfall/static/harbor/ (332 KB total). The portal home comp was
rejected as a background because it shows Shipyard UI and company names.
