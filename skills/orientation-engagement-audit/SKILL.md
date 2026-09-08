---
name: orientation-engagement-audit
description: Check whether a human visitor can quickly tell what a page is about and where to go next — page-purpose clarity (H1 presence/uniqueness), navigation and breadcrumb wayfinding, and internal-link "information scent" (specific vs. generic link text) — grounded in Pirolli and Card's Information Scent theory. This is the design/UX half of on-site engagement, distinct from context-lock-audit's technical state-fragmentation checks — a page can be perfectly stable and fully fetchable and still lose a visitor to weak orientation cues alone.
license: MIT
allowed-tools: Bash, Read
---

# Orientation & Engagement Audit

## When to use

Run this to check the human-orientation half of on-site engagement — a different mechanism from
`context-lock-audit`. That skill catches a fact that's technically unreachable at the URL a visitor
landed on; this skill catches a fact that's right there on the page but hard to *notice, trust, or
navigate from* because of weak orientation cues. Both produce a bounce; the root cause and the fix
are unrelated, which is why they're separate skills rather than one merged "engagement" check.

## Inputs

`evidence.json`'s `rendered.headings`, `links` (nav/breadcrumb presence, internal link sample,
internal/external counts), and the audited URL (for path-depth reasoning).

## Procedure

1. Run `python scripts/check_orientation.py <evidence.json> <url>`. It checks:
   - **Page-purpose clarity**: zero H1 headings on a substantial page (high — a visitor has no
     immediate confirmation they landed in the right place), or more than one H1 (low — dilutes
     which single thing the page claims to be about).
   - **Navigation landmark**: no `<nav>`/`[role="navigation"]` at all (high).
   - **Breadcrumb wayfinding**: nav present but no breadcrumb on a page 3+ path segments deep (low,
     `beyond_defect`) — orientation scent ("the path behind you") is a distinct mechanism from
     forward-looking nav scent.
   - **Internal-link information scent**: the fraction of sampled internal links using generic text
     ("click here", "read more", or ≤2 characters) — falls back to `aria-label`/`title` before
     judging a link generic, so a legitimately accessible icon-only link (a real, good pattern) with
     a descriptive accessible name isn't misread as empty. See `references/thresholds.md` for an
     honest note on this measurement's remaining limits.
   - **Zero internal links** on a substantial page (high) — a dead end for a visitor and a crawler.
2. If no script runtime is available, reproduce these checks by reading the rendered DOM directly:
   count H1s, look for a nav landmark and breadcrumb pattern, and sample internal `<a>` text
   (falling back to `aria-label`/`title` when the visible text is empty).
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "orientation-engagement"`.

## Output

A JSON array of findings printed to stdout. Composed into the final report by the entrypoint.
