# Corroboration & freshness thresholds and sources

## Entity identity (sameAs / Wikidata)

No Organization schema and no `sameAs` links at all → medium. `sameAs` present but none point to
Wikidata → low, `beyond_defect`. Each `sameAs` URL functions as a vote for entity disambiguation;
Wikidata is treated as the strongest anchor because it assigns a stable Q-number that feeds
directly into the knowledge graphs major assistants and search engines consult, letting scattered
mentions of a brand collapse into one confident, citable entity instead of several ambiguous ones.

## Freshness signal

No `dateModified`/`datePublished` in JSON-LD and no visible "updated"/"published" date text on a
page with ≥ 1,500 characters of content → medium. A visible date with no matching structured-data
field → low, `beyond_defect` (a human can see it's current; a system parsing structured data
cannot). A comparative audit of AI-cited content found Claude's median cited-content age running
62–148 days depending on vertical versus Google's 130–493 days, and a separate analysis of 17
million AI citations found AI-surfaced URLs run roughly 25.7% fresher than traditional search
results — freshness is a measurably stronger signal for AI engines specifically, not just a general
SEO nicety. Citation sets also rotate substantially month to month (roughly 40–60% turnover across
engines in one longitudinal study), so an undated page is more exposed to being dropped in favor of
a fresher-looking competitor even when its content hasn't actually gone stale.

## Self-consistency across independent fetches

Flagged when 2 additional fresh, isolated-context fetches (no shared cookies/cache/storage) diverge
from the shared evidence's original render in title, price/currency tokens, or body-text word-set
overlap (Jaccard similarity on the first ~1,500 characters, threshold 0.5). Severity is **critical**
when the title or price tokens differ outright (a decision-relevant, unambiguous contradiction) and
**high** when only the looser word-overlap signal fires (still a real divergence, less certain to be
decision-relevant).

Two mechanically distinct causes converge on this signature: SSR/CSR hydration mismatch (an
engineering bug — a non-deterministic value or client-only branch computed differently between
server and client renders) and deliberate client-side experimentation/personalization (one
canonical payload with regions swapped post-load based on a bucketing decision). Given that
corroboration works by *agreement* — a claim repeated consistently across independent sources is
more likely to be believed — a URL that disagrees with *itself* across fetches is a **strictly
worse** signal than a URL with no corroboration at all: it doesn't just fail to build confidence, it
actively teaches a retrieval system the domain is an unreliable witness to its own content. This is
also, mechanistically, a plausible root cause behind some cases blamed on "AI hallucination" when
the actual fault was source inconsistency, not model error.

## Why the external-corroboration check is agent-assisted, not scripted

Whether an independent, off-domain source corroborates a specific claim cannot be determined from
fetching the audited page alone — by definition it requires searching the wider web. The bundled
Python script does not attempt this; instead, `SKILL.md` step 2 asks the invoking agent to use its
own web-search tool, if one is available, for at most 1–2 targeted queries. This keeps the check
honest about what a single-page, sandboxed fetch can and cannot establish, rather than faking
corroboration evidence the script never actually gathered. The underlying signal is real: one audit
found AI engines show a strong, measured bias toward earned/third-party coverage over brand-owned
content (one comparison: 65% earned media / 1% social for one assistant, versus a much more
even split for traditional search) — a fact with zero independent corroboration is structurally
disadvantaged for citation even when it's perfectly marked up on-page.
