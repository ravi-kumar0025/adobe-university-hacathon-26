---
name: structured-fact-audit
description: Check whether a page's facts are stated in a form a machine can lift verbatim — JSON-LD/schema.org presence, validity, and reachability without JavaScript; summary metadata (title, meta description, Open Graph); and heading-structure density, using thresholds measured from real 2026 AI-citation studies rather than generic SEO advice. Use after render-fidelity-audit confirms the content is readable at all; this skill asks whether the content, once readable, is stated in an extractable, quotable form.
license: MIT
allowed-tools: Bash, Read
---

# Structured Fact Audit

## When to use

Run this once content is confirmed readable (after `render-fidelity-audit`). It answers the third
link in the PS appendix's chain: "it has to be able to pick out the specific fact someone is
looking for." A page can be perfectly crawlable and perfectly rendered and still bury its facts in
a form nothing can reliably lift out — no structured data, no headings, no stated summary.

## Inputs

`evidence.json`'s `structured_data`, `rendered` (headings, title, meta_description), and
`raw_fetch` (text, for the entity-signal check) sections.

## Procedure

1. Run `python scripts/check_structured_facts.py <evidence.json> <url>`. It checks:
   - Whether JSON-LD exists at all, and specifically whether it exists in the **raw** (pre-JS)
     HTML — JSON-LD injected only client-side is invisible to non-executing crawlers exactly like
     any other CSR content, so this is reported at critical severity, distinct from simply missing.
   - Whether existing JSON-LD parses as valid JSON and carries an `@type`/`@context`.
   - Whether the page shows genuine commerce/transaction signals (a currency amount, an explicit
     purchase-flow phrase, or a product/article `og:type`) with no JSON-LD at all — escalated to
     high severity, since this is close to the PS's own example finding (missing Product/Offer
     markup). Deliberately narrow: earlier testing showed a loose regex on bare "%" or the word
     "review" false-positived on a non-commerce stats page, so the signal requires an actual
     currency/purchase-flow token, not any number.
   - Heading-structure density on substantial pages (≥ 1500 characters of text) — see
     `references/thresholds.md` for the citation-study numbers this is grounded in.
   - Presence of a title/og:title and a meta description/og:description.
2. If no script runtime is available, reproduce these checks by reading the raw HTML directly for
   `<script type="application/ld+json">` blocks and comparing against what's present after render.
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "structured-fact"`.

Do **not** suggest converting content to Q&A/FAQ format as a blanket fix — see
`references/thresholds.md` for why that's deliberately excluded despite being common generic advice.

## Output

A JSON array of findings printed to stdout. Composed into the final report by the entrypoint.
