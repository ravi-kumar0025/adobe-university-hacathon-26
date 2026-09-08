# Render-fidelity thresholds and sources

## CSR empty-shell ratio

`raw_text_length / rendered_text_length < 0.10` → critical, `< 0.30` → high (only evaluated when
the raw fetch returned HTTP 200 and the rendered page has at least 500 characters of text, so the
ratio is meaningful rather than noise from a near-empty page in both states).

The 0.1 threshold matches the independently-converged heuristic used across prior research into
this exact failure mode (raw-vs-rendered text-density comparison against a spoofed-bot-UA fetch).
Traffic analysis has found GPTBot and ClaudeBot fetch a site's JS bundles without executing them
in roughly 11% and 24% of requests respectively, and no major AI crawler currently renders
JavaScript at all in consistent cross-stack testing — so a page relying on CSR for its primary
content is not "slow to index," it is invisible to that fetch pattern outright.

## Shadow DOM lock

Open shadow root: flag when `shadow_text_length >= 100` and
`host_light_dom_text_length < 0.10 * shadow_text_length`. Closed/unknown shadow root: flag when
`host_bbox_area >= 5000px²` (roughly a 70×70 region — large enough to be a real content block, not
an icon) and `host_light_dom_text_length < 20`.

`element.textContent` does not descend into a shadow root regardless of open/closed mode — this is
a spec property of the encapsulation boundary, not a parsing gap — and Playwright's own
`page.content()` (the call most ingestion pipelines use to pull "the page's HTML" out of a headless
browser) excludes shadow DOM content entirely unless the newer `getHTML({serializableShadowRoots:
true})` API is explicitly invoked. `mode: "closed"` roots go further: `element.shadowRoot` returns
`null` by specification, so even an inspecting script can't reach in from outside.

## Canvas black hole

Flag canvases ≥ 20,000px² (roughly 140×140) with no fallback text and no accessible name/
description; escalate to high when nearby text contains numeric or currency tokens (a signal the
canvas is illustrating a real, citable figure rather than decoration). Canvas/WebGL output is
bitmap pixels with no default DOM or accessibility-tree representation — Chart.js's own
documentation states its canvas output carries no built-in screen-reader accessibility unless ARIA
attributes or fallback markup are added manually, and this generalizes to any canvas/WebGL use.
Once a fact is rasterized, no DOM-, accessibility-tree-, or rendered-HTML-based extraction method
can recover it — there is no "wait longer" remedy available, unlike ordinary CSR.

## WebSocket/SSE mirage

Flag when at least one WebSocket connection or SSE stream was observed **and** at least 200
characters of visible text appeared between initial parse and post-settle. This is a correlation,
not proof of causation — the finding language says "consistent with," not "caused by" — because a
generic script-driven DOM update could coincidentally overlap with socket activity. The mechanism
that makes this worth checking at all: a non-JS-executing crawler never opens a WebSocket or holds
an SSE connection in the first place, so any fact genuinely gated behind one is categorically
absent to that crawler, not merely delayed the way ordinary CSR content is.
