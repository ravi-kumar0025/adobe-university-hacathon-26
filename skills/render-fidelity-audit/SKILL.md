---
name: render-fidelity-audit
description: Given a page a crawler successfully fetched, check whether its content is actually machine-readable — client-side-rendered "empty shell" pages, Shadow DOM encapsulation hiding real text, Canvas/WebGL data with no text or accessibility equivalent, and WebSocket/SSE-gated facts invisible to non-JS-executing crawlers. Use after crawl-access-audit confirms the fetch succeeds; this skill answers whether what was fetched can be read, not whether it could be reached.
license: MIT
allowed-tools: Bash, Read
---

# Render Fidelity Audit

## When to use

Run this after `crawl-access-audit`. It assumes the fetch already succeeded and asks the next
question in the PS appendix's chain: "it has to be able to read what's on the page." A page that
loads but hides its facts behind client-side rendering, closed Shadow DOM, canvas pixels, or a
live-data channel is invisible to a non-executing crawler in exactly the same practical sense as
a page it couldn't reach — the difference matters for diagnosis, not for the outcome.

## Inputs

`evidence.json` produced by `audit-orchestrator/scripts/gather_evidence.py`, specifically its
`raw_fetch`, `rendered`, and `structural` sections (custom elements, canvases, network summary).

## Procedure

1. Run `python scripts/check_render_fidelity.py <evidence.json> <url>`. It runs four independent
   checks (see `references/thresholds.md` for exact numbers and sources):
   - **CSR empty shell**: compares raw-fetch text length to rendered text length. Skipped entirely
     if the raw fetch didn't return 200 — that's `crawl-access-audit`'s finding, not this skill's;
     conflating a blocked fetch with a rendering-architecture problem would misattribute the cause.
   - **Shadow DOM lock**: for each custom element, compares its shadow-root text (if the root is
     open and inspectable) or its bounding-box size (if not) against its light-DOM text length.
   - **Canvas black hole**: flags large canvases with no fallback text/accessible name, escalating
     severity when the surrounding prose contains numeric/currency tokens suggesting the canvas
     illustrates a real, citable figure.
   - **WebSocket/SSE mirage**: flags a live channel being open alongside a large amount of text
     appearing only after settle, since a non-JS-executing crawler never opens that channel at all.
2. If no script runtime is available, reproduce these checks with whatever browser-automation tool
   you have: compare `page.content()` (light DOM only) against each custom element's shadow-root
   text; enumerate canvases and check for an accessible name or nearby quotable data; watch for
   WebSocket/SSE traffic correlated with late-arriving text.
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "render-fidelity"`.

## Output

A JSON array of findings printed to stdout. Composed into the final report by the entrypoint.
