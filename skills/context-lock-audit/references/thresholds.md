# Context-lock thresholds and sources

## Virtualization vs. infinite-append

A list container is treated as virtualized (windowed/recycled) when at least one new item
identifier appears after scrolling **and** the post-scroll DOM count stays under 1.3x the initial
count. This distinguishes it from plain infinite-scroll append, where old items stay in the DOM and
the count grows roughly in proportion to what's been revealed — a generally more crawlable pattern
that this skill deliberately does not flag, because scrolling through it eventually surfaces
everything a bounded crawl visits, unlike true recycling where off-window items are never
simultaneously present.

Mechanism: list virtualization keeps only the currently-visible slice of a long list as real DOM
nodes, recycling nodes on scroll. An assistant that obtained the full dataset some other way (a
sitemap, an API, a paginated fallback) can cite a real, specific link to item #1,847 of a catalog;
a human who clicks it gets a fresh load where the virtualizer initializes at its default window,
and unless the application explicitly wired a route-parameter-to-scroll-index bridge on mount —
invisible in any manual QA pass a sighted developer does by scrolling normally — the item is one
un-searchable scroll position away from nonexistent. Browser find-in-page fails for the identical
structural reason: it only searches nodes that currently exist.

## Severity ladder

1. **Critical** — a live deep-link replay was performed and confirmed the failure (fresh navigation
   404s, or the item's identifier is absent from the fresh page's rendered text). This is no longer
   a suspicion; it's a reproduced failure with a concrete before/after.
2. **High** — no permalink was available to replay directly, but the page states a total (e.g.
   "24 total", "1,847 results") far larger (> 3x) than the post-scroll DOM count, meaning most of a
   large catalog is structurally at risk even without testing every item.
3. **Medium** — virtualization detected with real per-item permalinks but no stated total large
   enough to escalate, or virtualization detected with **no** discoverable per-item permalink at
   all (a distinct, milder-worded problem: there's nothing to deep-link into yet, so an assistant
   can't cite an individual item in the first place, separate from whether citing one would work).

## Why the replay is capped at one candidate

The audit runtime budget is 5 minutes for the whole marketplace. A live replay launches a second
headless browser context, which costs real wall-clock time. Testing every candidate item on every
list would not scale; testing one representative item, chosen from the highest-priority virtualized
candidate, is a bounded, honest sample rather than an exhaustive proof — the finding language
reflects that ("Confirmed" applies to the tested item; the broader "likely" framing at the High tier
covers the untested remainder).

## Stuck aria-busy check — why it stays conservative

An earlier design considered matching common CSS class names (`spinner`, `skeleton`, `loading`)
against the settled HTML. That was dropped: a class name proves nothing about current visibility —
plenty of components ship a `.spinner` class that's simply unused, hidden, or template markup, and
flagging on class-name presence alone would produce exactly the kind of false positive the rubric
penalizes. `aria-busy="true"` is different: it's the page's own explicit, machine-readable claim
that a region is not yet resolved, authored by the developer for exactly this purpose — a much
stronger and lower-false-positive signal, and it's only reported here alongside confirmed live
(WebSocket/SSE) channel activity, so the finding ties a real mechanism to a real, self-reported
state rather than inferring one from styling conventions.
