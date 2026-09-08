# Orientation & engagement thresholds and sources

## Why Information Scent theory, specifically

The PS appendix asks for checks against "weak on-site orientation / no context retention" without
prescribing a framework. Rather than inventing ad hoc UX heuristics, this skill grounds its checks
in Pirolli and Card's Information Scent theory: visitors navigate by following the strongest local
cue (a link label, a heading, a breadcrumb) toward their goal, and weak scent — an unclear heading,
an unlabeled link, no stated page purpose — raises cognitive load and drives abandonment
independent of whether the underlying content is actually good. This is a decades-old, well-tested
HCI theory, and a genuinely different failure class from the technical Context-Lock checks in
`context-lock-audit`: a page can be perfectly stable and fully fetchable and still lose a visitor to
weak orientation cues alone. It also directly maps onto the appendix's own framing: navigation is
forward-looking scent, and a breadcrumb trail is explicitly "the scent of the path behind you."

## Thresholds

- Zero H1 on a page with ≥ 800 characters of content → high. Multiple H1s → low, `beyond_defect`.
- No navigation landmark at all → high.
- Nav present, no breadcrumb, path depth ≥ 3 segments → low, `beyond_defect`.
- ≥ 30% of a ≥ 6-link sample using generic text (a fixed list: "click here", "read more", "learn
  more", etc., or ≤ 2 characters) → medium.
- Zero internal links on a ≥ 800-character page → high.

## A known limitation of the link-scent measurement, stated honestly

The generic-link-text check reads `innerText` first, falling back to `aria-label` then `title` —
this was added specifically after early testing found the naive innerText-only version flagged
Wikipedia's icon-only sidebar links as "generic," when in fact most of them carry a genuinely
descriptive `title` attribute (e.g. "Visit the main page [alt-z]") that plain `innerText` misses
entirely, since visually-hidden text is excluded from `innerText` by design. That fix closed the
Wikipedia case. Testing against a second real site (GitHub) still showed several icon-only links
with no visible text, no `aria-label`, and no `title` — this may be a genuine missing-accessible-
name defect on that page, or content whose real accessible name lives in a visually-hidden
`<span>` this check does not read (a full accessibility-tree accessible-name computation, e.g. via
`page.accessibility.snapshot()` or an ARIA-snapshot API, would resolve this precisely but was out
of scope for the current script). The finding's wording ("low-information text," not "broken
links") is deliberately hedged to stay honest about this residual uncertainty rather than overclaim
certainty the measurement doesn't have.
