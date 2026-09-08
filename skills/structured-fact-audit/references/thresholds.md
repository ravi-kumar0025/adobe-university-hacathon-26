# Structured-fact thresholds and sources

## JSON-LD presence, location, and validity

Client-side-only JSON-LD (present after render, absent from the raw fetch) is treated the same as
any other CSR-gated content: critical, because the AI crawlers that dominate this traffic do not
execute JavaScript, so structured data that only exists post-hydration was never received.

A missing-entirely JSON-LD block escalates from low (generic "add markup" suggestion, marked
`beyond_defect`) to high when the page shows a genuine commerce/transaction signal — this mirrors
the PS's own example finding almost exactly ("No JSON-LD structured data on product pages"). The
entity-signal regex was deliberately tightened during testing: an early version matched a bare `%`
or the word "review," which false-positived on a GitHub statistics page ("90% Fortune 100") that
has nothing to do with commerce. It now requires a currency amount or an explicit purchase-flow
phrase (`add to cart`, `in stock`, `SKU`, etc.) or a product/article `og:type` — a real signal, not
any number near the word "percent."

## Heading-structure density

Flag zero headings on pages with ≥ 1,500 characters of text (medium); flag a single heading on
pages with ≥ 3,000 characters (low, `beyond_defect`). Source: a synthesis of six 2026 empirical
studies on AI-citation behavior (1,516 ranking queries; 366,000+ real citations across three
providers; 17 million AI citations analyzed in aggregate) found top-quartile cited pages carry
roughly **11.4x the word count, 12.5x the heading count, and 8.9x the list density** of
bottom-quartile cited pages. Heading structure is a measured correlate of citability, not a style
preference — it's also the mechanism by which a retrieval system can chunk and cite one section
instead of an undifferentiated wall of text.

## Why Q&A/FAQ reformatting is deliberately NOT recommended

Generic "GEO" advice often pushes converting content into Q&A blocks. The same citation-behavior
synthesis found the opposite in its data: **Q&A-formatted content hurt absorption into AI answers
by 5.74%**, while the content types that most improved absorption were code snippets (+76.9%),
statistics (+61.6%), definitions (+57.3%), and comparisons (+55.3%). This skill does not emit a
finding recommending Q&A restructuring, and if an agent following this procedure manually is
tempted to suggest it, it should not — the measured effect runs the other way.

## Summary metadata (title / meta description / og:description)

Missing a title is high severity — it's the single most load-bearing identity string on a page.
Missing a description is medium: the same mechanism the PS appendix describes for AI email
summarizers dropping content that isn't available as clear, extractable text ("when the genuinely
important lines are surrounded by low-value filler, the important part can simply disappear")
generalizes to page-level summarization — a page with no stated summary gives a generating system
nothing reliable to build one from.
