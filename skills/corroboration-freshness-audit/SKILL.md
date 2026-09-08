---
name: corroboration-freshness-audit
description: Check whether the wider web independently agrees with a page's facts, and whether the page agrees with itself. Covers entity-identity signals (Organization schema, sameAs links to Wikidata and other authoritative anchors), freshness signals (dateModified, visible update dates), self-consistency across independent fetches (hydration nondeterminism or personalization causing one URL to return contradictory facts), and — when a web-search tool is available to the invoking agent — a bounded check for independent, off-domain corroboration of the page's primary claim. Use to diagnose trust and citation-worthiness problems distinct from crawlability or content structure.
license: MIT
allowed-tools: Bash, Read, WebSearch
---

# Corroboration & Freshness Audit

## When to use

Run this to check the PS appendix's trust dimension: "machines tend to treat a fact as more
trustworthy when many independent places say the same thing... a claim that lives in only one spot
is fragile." This skill assumes the fact is readable and well-structured (that's covered by
`render-fidelity-audit` and `structured-fact-audit`) and asks whether it would be *believed*: is
the entity unambiguous, is it dated, does the wider web corroborate it, and — a subtler failure —
does the page even agree with itself across repeated, independent fetches?

## Inputs

`evidence.json`'s `meta_identity` (sameAs/Organization schema), `structured_data` (JSON-LD date
fields), and `rendered` (visible text, for date-text and freshness checks). Also performs its own
narrowly-scoped extra work: two additional fresh, isolated-context fetches of the same URL to test
self-consistency.

## Procedure

1. Run `python scripts/check_corroboration.py <evidence.json> <url>`. It checks:
   - **Entity identity**: presence of Organization schema and `sameAs` links, escalating from
     "none at all" (medium) to "present but missing Wikidata specifically" (low, `beyond_defect`).
   - **Freshness**: `dateModified`/`datePublished` in JSON-LD vs. a visible "updated on" date in
     the text, on pages with enough content (≥ 1,500 chars) for freshness to matter.
   - **Self-consistency**: fetches the URL twice more in fully isolated browser contexts (no
     shared cookies/cache/storage) and diffs title, price/currency tokens, and body-text word-set
     overlap against the shared evidence's original rendered fetch. A URL that disagrees with
     itself across fetches is flagged **critical** when the title or price tokens differ outright —
     see `references/thresholds.md` for why this is treated as worse than having no corroboration
     at all, not merely equivalent to it.
2. **If a web-search tool is available to you as the invoking agent**, perform at most 1–2
   targeted, read-only searches for the page's single most load-bearing claim (its primary product
   name + a distinguishing fact, or its organization name + a key figure) to check whether any
   independent, off-domain source states the same thing. If nothing independent turns up, add a
   finding: `title: "Primary claim appears only on the brand's own domain"`, `severity: "medium"`,
   noting that AI engines show a measured, substantial bias toward earned/third-party coverage over
   brand-owned content (see `references/thresholds.md`), so a fact with zero independent
   corroboration is structurally disadvantaged even when perfectly marked up. **Skip this step
   entirely** (do not guess, do not fabricate a finding) if no search tool is available — this is
   the one check in the marketplace that genuinely cannot be done from a single fetch, and an
   absent tool is a reason to omit the check, not to approximate it.
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "corroboration-freshness"`.

## Output

A JSON array of findings printed to stdout. Composed into the final report by the entrypoint.
