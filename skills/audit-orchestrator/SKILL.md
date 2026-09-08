---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Given a URL, audits it for both off-site AI discoverability and on-site engagement problems by running one shared crawl/render pass and composing the six focused sub-skills (crawl-access-audit, render-fidelity-audit, structured-fact-audit, corroboration-freshness-audit, context-lock-audit, orientation-engagement-audit) into a single, fixed-schema report of evidence-backed findings and prioritized suggested actions. Use this skill whenever asked to audit a website's AI discoverability, why a brand is missing or misrepresented in AI assistants, or why visitors who arrive don't engage — this is the one skill to invoke; it composes the rest.
license: MIT
allowed-tools: Bash, Read, WebSearch
---

# Brand AI-Readiness Audit — Orchestrator (entrypoint)

## When to use

This is the marketplace's designated entrypoint — the skill an agent invokes to audit a website.
It does not implement any detection logic itself; its only job is to run the shared evidence
gathering once, dispatch it to six single-concern audit skills, and compose their independent
findings into one report. See the root `README.md` for what each sub-skill covers and why the
marketplace is split this way instead of one large skill.

## Inputs

A URL (or bare domain — normalize to `https://<domain>/` if no scheme is given). Everything else
is derived automatically.

## Procedure

**Fastest path — one command:**

```
python skills/audit-orchestrator/scripts/run_audit.py <url> [<output_report_path>]
```

This gathers evidence, runs all six sub-skills, composes the report, and either writes it to
`<output_report_path>` or prints it to stdout. Typical runtime on a real production site is well
under a minute; the PS's 5-minute budget has comfortable headroom (see `references/` for the
runtime data this was tested against).

**What that command does, step by step** (reproduce manually if no Python/Playwright runtime is
available — every check has a "no script runtime" fallback documented in its own `SKILL.md`):

1. Run `scripts/gather_evidence.py <url> <evidence.json>` — one raw, non-JS-executing HTTP fetch
   (the pattern most AI crawlers use) and one full headless-rendered pass, producing the shared
   evidence artifact described in `references/evidence-contract.md`. This exists so the six
   sub-skills don't each redundantly re-fetch and re-render the same page.
2. Run each sub-skill's `scripts/check_*.py <evidence.json> <url>` (each prints a JSON array of
   findings per `references/finding-contract.md`):
   - `crawl-access-audit` — can a crawler get in at all (robots.txt, status codes, WAF blocking)?
   - `render-fidelity-audit` — given a fetch, can the content be read (CSR shell, Shadow DOM,
     canvas, WebSocket-gated facts)?
   - `structured-fact-audit` — is a fact stated in an extractable form (JSON-LD, headings,
     summary metadata)?
   - `corroboration-freshness-audit` — does the wider web agree, and does the page agree with
     itself (entity identity, freshness, multi-fetch self-consistency, optional agent-assisted
     external-corroboration search)?
   - `context-lock-audit` — does a specific cited fact materialize for a human who clicks through
     (deep-link fidelity into virtualized lists, stuck live-data regions)?
   - `orientation-engagement-audit` — can a human quickly tell what the page is and where to go
     (page-purpose clarity, navigation/breadcrumb wayfinding, link information scent)?
3. Run `scripts/compose_report.py <url> <output.json> <findings-file>...` — merges every finding,
   sorts by severity (critical → high → medium → low; within a tier, real problems before
   `beyond_defect` proactive suggestions), assigns globally unique `F-NNN` IDs in that order, and
   computes the summary counts.

## Output

The final report, matching the PS's required schema exactly plus two additive fields (not a
replacement — every required field is still present):

```jsonc
{
  "site": "example.com",
  "audited_url": "https://example.com/page",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3, "low": 0 },
  "findings": [
    {
      "id": "F-001", "title": "...", "severity": "high",
      "category": "structured-fact",
      "evidence": "...", "suggested_action": { "summary": "...", "priority": "high" },
      "beyond_defect": false
    }
  ]
}
```

`category` names which sub-skill produced the finding (useful for a report reader who wants to act
on one dimension at a time). `beyond_defect: true` marks a proactive suggestion made even though no
defect was detected, per the PS's explicit invitation to go beyond the problems found.

## Guardrails this orchestrator enforces

- **Recommend-only**: nothing in this marketplace ever writes to, authenticates against, or
  otherwise modifies the audited site. Every check is a read (HTTP GET / headless page load).
- **robots.txt is respected structurally**: `crawl-access-audit`'s own extra per-agent probes
  explicitly skip any agent robots.txt disallows for the audited path — it never fetches what it
  was told not to, even to test whether it *would* be blocked anyway.
- **Bounded, capped work**: every live extra fetch (the deep-link replay in `context-lock-audit`,
  the two isolated re-fetches in `corroboration-freshness-audit`, the per-agent probes in
  `crawl-access-audit`) is capped in count and wrapped in a timeout, so total runtime stays well
  inside the 5-minute budget even on a large, slow site.
