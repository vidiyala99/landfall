# ChatGPT live check: products visible, prices not (2026-11-20 ~14:12 PST)

Prompt (ChatGPT, no connector): "Open https://www.smalltownbloomsky.com/ right now and tell me the exact name and price of
the first arrangement on the page."

ChatGPT's reply (verbatim excerpt): "I opened Small Town Blooms and checked the homepage. First listed arrangement:
Back2School Special. Product ID: B2S. Price: Not displayed in the accessible page content, so I can't verify the exact
price. ... I can confirm the name, but I don't want to invent a price."

Why: the page's visible text has product names but no prices; the prices exist only inside script data (`"value":95,"value_formatted":"$95.00"`) that a script paints in (`data-bind="text: price"`). Correction (15:23): an earlier version said the raw HTML had zero dollar amounts; that check had stripped script blocks. See evidence/rea/README.md.
A real browser after scrolling shows them (34 products, $22.00 to $99.99, see runs/small-town-blooms/products.json).
After Landfall's product-listing worker, the no-JavaScript reader answers "Lots of Love: $95.00" on the fixed copy
(price-proof.json).
