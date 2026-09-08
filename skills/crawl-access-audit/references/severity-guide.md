# Crawl-access severity guide

Mechanism: per the PS appendix (A), "for a page to be visible at all, three things have to
succeed in order — the crawler has to be let in, it has to be able to read what's on the page,
and it has to be able to pick out the specific fact." This skill only covers the first gate. A
failure here is upstream of every other skill in the marketplace — a page a crawler never
receives can't be helped by perfect structured data or perfect prose.

| Condition | Severity | Why |
|---|---|---|
| robots.txt disallows a major AI crawler (GPTBot/ClaudeBot/PerplexityBot/Google-Extended) on the exact audited path | critical | Total, unconditional exclusion from that assistant — not a quality issue, a wall. |
| Non-2xx status to the standard non-JS-executing fetch pattern | critical | Independent traffic analysis shows GPTBot and ClaudeBot routinely fetch pages without executing JavaScript; a non-2xx here means the page effectively doesn't exist for that fetch pattern, full stop. |
| Server/CDN blocks a specific AI-crawler UA even though robots.txt allows it | critical | Worse than a robots.txt block in one sense: it's invisible to anyone who only reads robots.txt, and it means the *intended* policy (robots.txt says "come in") is being silently overridden by a different layer. |
| Redirect chain > 3 hops | medium | Each hop is a place a bounded-timeout crawler can give up, and a JS/meta-refresh redirect mid-chain can silently strand a non-executing crawler entirely. |
| robots.txt unreachable with a non-404 error | medium | An ambiguous signal some crawlers treat conservatively (back off entirely) rather than treating as "no restrictions." |
| No sitemap declared | low, `beyond_defect: true` | Not a block — a proactive, cheap way to hand a crawler the complete URL set instead of relying on discovered links. |

## On intentional exclusions

A robots.txt block might be a deliberate publisher choice (e.g. paywall protection), not a bug.
This skill still reports it — the mechanism and its effect on discoverability are real regardless
of intent — but the suggested action is phrased conditionally rather than presuming it's a mistake.

## Why the live WAF/CDN probe excludes Google-Extended

The live per-agent probe (the "server/CDN blocks a specific UA" check) intentionally tests only
GPTBot, ClaudeBot, and PerplexityBot with a live fetch — not Google-Extended. Google-Extended is a
robots.txt-only opt-out token, not a crawler with its own distinct fetching user agent; Google's
real crawlers are verified by IP/reverse-DNS, not UA string alone. During development this was
tested against Wikipedia: a live fetch using a bare "Googlebot" UA string got a 403, which first
looked like a WAF-blocking finding — but that 403 is Wikipedia's infrastructure correctly rejecting
an *unverified* UA claim from a non-Google IP, exactly the anti-spoofing behavior a well-run site
should have, not a discoverability defect. Testing it live would have produced a confident-sounding
but methodologically unsound false positive. Google-Extended's permission is still evaluated, just
through robots.txt alone (the first row of the table above), which is the only thing this skill can
credibly test for an identity it cannot legitimately assume. The same Wikipedia test, with the same
methodology, found a live 403 specifically for ClaudeBot despite robots.txt permitting it — a real,
independently-reproduced finding, since ClaudeBot's identity in this test is exactly what it claims
to be (this skill's own request, not an impersonation question).
