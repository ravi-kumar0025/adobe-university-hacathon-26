# Brand AI-Readiness Audit

An Agent Skill Marketplace that audits a website for both **off-site AI discoverability** (why a
brand isn't found or cited by AI assistants) and **on-site engagement** (why visitors who do
arrive don't stay), and emits one structured report of evidence-backed findings and prioritized,
mechanism-sound fixes.

## Quick start

```
pip install playwright && playwright install chromium
python skills/audit-orchestrator/scripts/run_audit.py https://example.com
```

## Why six skills instead of one

Every reasoning path in the PS appendix chains through a different, independently-failing
mechanism — a crawler has to be *let in*, then able to *read* the page, then able to *pick out* a
specific fact, then the wider web has to *agree* with it — and on-site engagement splits again into
a technical failure (the fact is real but the exact URL doesn't reproduce it) and a design failure
(the fact is there and stable but hard to notice or trust). Six single-concern skills map onto
those six distinct mechanisms; each is independently testable, and none of them could be merged
without conflating causes that need different fixes.

| Skill | Answers | Category tag |
|---|---|---|
| `audit-orchestrator` (**entrypoint**) | Runs the shared crawl/render pass once, dispatches the other six, composes their findings into the final report | — |
| `crawl-access-audit` | Can a crawler get in at all? robots.txt, status codes, redirects, WAF-level bot blocking | `crawl-access` |
| `render-fidelity-audit` | Given a fetch, can the content be read? CSR empty shells, Shadow DOM encapsulation, Canvas/WebGL black holes, WebSocket/SSE-gated facts | `render-fidelity` |
| `structured-fact-audit` | Is a fact stated in an extractable form? JSON-LD presence/validity/reachability, heading-structure density, summary metadata — thresholds pulled from measured 2026 AI-citation research | `structured-fact` |
| `corroboration-freshness-audit` | Does the wider web agree, and does the page agree with itself? Entity identity (`sameAs`/Wikidata), freshness signals, multi-fetch self-consistency, optional agent-assisted external-corroboration search | `corroboration-freshness` |
| `context-lock-audit` | Does a specific cited fact actually materialize for a human who clicks through? List-virtualization deep-link voids (with a live replay to confirm), stuck live-data regions | `context-lock` |
| `orientation-engagement-audit` | Can a human quickly tell what the page is and where to go? Page-purpose clarity, navigation/breadcrumb wayfinding, internal-link information scent — grounded in Pirolli & Card's Information Scent theory | `orientation-engagement` |

## How the entrypoint composes them

`audit-orchestrator` runs one shared evidence-gathering pass
(`scripts/gather_evidence.py`: one raw non-JS-executing fetch + one full headless render, capturing
DOM, accessibility-relevant structure, network/WebSocket traffic, structured data, and links) and
writes it to a single `evidence.json`. Every sub-skill reads that same artifact instead of
re-fetching the page, so six audits cost roughly one page load, not six. Two sub-skills also do a
small amount of narrowly-scoped extra live work no shared pass could cover: `context-lock-audit`
performs one bounded fresh-context deep-link replay, and `corroboration-freshness-audit` performs
two bounded fresh-context re-fetches to test self-consistency. Every sub-skill prints a JSON array
of findings in a shared contract (`skills/audit-orchestrator/references/finding-contract.md`); the
orchestrator's `compose_report.py` merges them, assigns severity-ordered `F-NNN` IDs, computes the
summary counts, and emits the final report. `run_audit.py` runs this whole pipeline end to end in
one command.

Findings marked `beyond_defect: true` are proactive suggestions offered even where no defect was
detected, per the PS's explicit invitation to go beyond the problems found — they are always
`severity: "low"` so they never inflate the critical/high/medium counts.

## Guardrails

Recommend-only and fully read-only — no skill ever writes to, authenticates against, or otherwise
modifies the audited site. `crawl-access-audit`'s own extra per-agent probes skip any user agent
robots.txt disallows for the audited path. Every live extra fetch across the marketplace is capped
in count and wrapped in a timeout; measured end-to-end runtime against real production sites during
development was 8–30 seconds, comfortably inside the PS's 5-minute budget.

## Design notes

Each sub-skill's `references/thresholds.md` documents the exact numeric thresholds it uses and
where they came from — measured 2026 AI-citation-behavior research where one exists, or the
underlying browser/DOM platform mechanism where the check is architectural. Several thresholds were
tightened during development after producing a real false positive against a live site (documented
inline where it happened) rather than left at a first-guess value.
