---
name: context-lock-audit
description: Check whether a human visitor landing on a specific URL — the kind an AI assistant would cite for one particular fact — actually gets that fact, or gets stranded. Detects list-virtualization deep-link voids (with a bounded, live replay to confirm reproducibility when a real per-item permalink exists) and live-data regions that stay visibly unresolved after full page settle. This is the on-site-engagement half of the marketplace, distinct from render-fidelity-audit which asks whether a crawler can read content — this skill asks whether a human, on the exact URL, gets what the citation promised.
license: MIT
allowed-tools: Bash, Read
---

# Context Lock Audit

## When to use

Run this to check the technical half of on-site engagement: a visitor who arrives — often because
an assistant cited a specific fact and linked to it — lands on a state that doesn't contain, or
doesn't resolve to, the thing that got them there. This is a different failure from weak content
structure or weak navigation (that's `orientation-engagement-audit`); this is an engineering/state
problem: the fact is real and was real when the assistant found it, but the exact URL doesn't
reliably reproduce it on a fresh, un-scrolled, session-less load.

## Inputs

`evidence.json`'s `structural.list_candidates` (virtualization signature, stated totals,
newly-revealed per-item hrefs) and `structural.network` + `rendered.html` (for the stuck-live-
region check). Also performs its own bounded extra work: at most one fresh, isolated-context
Playwright navigation to replay a single deep link, only when a real per-item href was found.

## Procedure

1. Run `python scripts/check_context_lock.py <evidence.json> <url>`. It:
   - Flags a list container as virtualized when new item identifiers appear after scrolling while
     the DOM node count stays roughly stable (a recycling/windowing signature, distinct from plain
     infinite-append growth where old items remain and the count simply grows).
   - When a real per-item permalink was captured among the newly-revealed items, performs **one**
     bounded (≤9s) fresh-context navigation to that exact URL and checks whether the item's
     identifier appears anywhere in that fresh page — turning a structural suspicion into a
     confirmed, reproduced failure (or ruling it out) with concrete before/after evidence.
   - Separately, flags a live-data region (WebSocket/SSE active) that still carries
     `aria-busy="true"` after full network-idle-plus-settle — a page-authored signal, not a guess,
     that the region considers itself unresolved.
2. If no script runtime is available: identify long, uniform-tag child lists; scroll and re-sample
   to check whether the item *set* churns while the *count* stays flat; if a per-item URL exists,
   load it fresh (no prior navigation history) and confirm the target content is present.
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "context-lock"`.

See `references/thresholds.md` for exact ratios and the virtualization-vs-infinite-scroll
distinction, and for why the aria-busy check stays this conservative on purpose.

## Output

A JSON array of findings printed to stdout. Composed into the final report by the entrypoint.
