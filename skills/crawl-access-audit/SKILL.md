---
name: crawl-access-audit
description: Check whether AI crawlers and answer-engine fetchers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, and others) can actually reach a page at all — robots.txt rules, HTTP status codes, redirect chains, and WAF/CDN-level bot blocking that robots.txt alone doesn't reveal. Use this first, before any content-quality check, because a gatekeeping failure here makes every downstream signal irrelevant — a page a crawler can't fetch might as well not exist for that system.
license: MIT
allowed-tools: Bash, Read
---

# Crawl Access Audit

## When to use

Run this as the first audit against any URL. It answers one question only: **can a crawler get
in the door at all?** Every other skill in this marketplace assumes a successful fetch already
happened — if this skill finds a hard block, that finding dominates the report, because nothing
downstream can be true for a page the crawler never received.

## Inputs

- `evidence.json` produced by `audit-orchestrator/scripts/gather_evidence.py` (see
  `../audit-orchestrator/references/evidence-contract.md`) — specifically its `robots` and
  `raw_fetch` sections.
- The audited URL.

## Procedure

1. Run `python scripts/check_crawl_access.py <evidence.json> <url>`. It:
   - Reads `robots.txt` rules already resolved per-agent in `evidence.json.robots` and flags any
     major AI crawler (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`) disallowed on the
     exact audited path.
   - Checks the status code of the shared non-JS-executing raw fetch (`evidence.json.raw_fetch`).
   - Flags redirect chains longer than 3 hops.
   - Flags an unreachable (non-404-erroring) robots.txt.
   - Flags a missing `Sitemap:` declaration as a low-priority proactive suggestion.
   - Performs one additional small, capped GET per major AI-crawler user agent — but **only** for
     agents robots.txt does not already disallow for this path — to catch WAF/CDN bot-blocking
     that permits the crawler in robots.txt but still 403s the literal request. This never fetches
     anything robots.txt told it not to.
2. If no script runtime is available, reproduce the same checks manually using whatever fetch/
   browser tool you have: fetch `robots.txt` at the site root, evaluate its rules for the agents
   above against the exact audited path (longest-match-wins), fetch the target URL with each
   allowed agent's real UA string, and record status codes and redirect hops.
3. Emit findings per `../audit-orchestrator/references/finding-contract.md`, `category: "crawl-access"`.

See `references/severity-guide.md` for exactly how each condition maps to a severity.

## Output

A JSON array of findings (possibly empty on a healthy site) printed to stdout by the script, or
produced directly by the agent following step 2. The entrypoint composes this into the final report.
