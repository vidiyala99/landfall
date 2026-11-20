# REA teardown: where the florist's prices come from (2026-11-20 ~15:20 PST, read-only)

Tool: REA `capture_browser_scenario` (Playwright provider), real Chrome (headless: false), start
https://www.smalltownbloomsky.com/, wait 5 s, press End, wait 6 s, network capture with response bodies.

- Headless Chrome first got CloudFront 403 (evidence ev_6a5e0eb7...): the site turns away the "HeadlessChrome" identity.
- Real Chrome: 301 -> 307 -> 200, 86-88 responses: 3 documents, 53-54 scripts, 25 images, 2 stylesheets, 2 fonts,
  and exactly ONE data request: `GET /customer/section/load/?force_new_section_timestamp=true` (cart/session data).
  Captures: florist-network-capture.json, florist-network-capture-scrolled.json.
- No request loads prices. They are embedded in the homepage HTML inside script configuration (Magento price boxes):
  `"value":95,"value_formatted":"$95.00"`, `"value":64.95,"value_formatted":"$64.95"`, `"value":79.95,...`.
  A script (Knockout `data-bind="text: price"`) turns that data into the visible prices.

Correction to earlier wording: the raw HTML does contain prices, but only inside script data, not in the page's
visible text. Assistants that extract page text without running scripts (ChatGPT's live answer: "Price: not displayed
in the accessible page content") see no prices. The fix stands: put prices in visible text and schema.org Offer data.
