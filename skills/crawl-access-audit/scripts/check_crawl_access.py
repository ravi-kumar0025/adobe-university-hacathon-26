#!/usr/bin/env python3
"""crawl-access-audit: can a crawler even get in?

Reads the shared evidence.json (see ../../audit-orchestrator/references/evidence-contract.md)
and performs one additional narrowly-scoped step: a small, capped, per-agent GET loop to catch
WAF/CDN-level bot blocking that robots.txt alone can't reveal (a site can permit GPTBot in
robots.txt while a security layer still 403s the literal UA string). Every extra request this
script makes is skipped for any agent robots.txt already disallows for this exact path, so it
never fetches content robots.txt told it not to.

Usage: python check_crawl_access.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import sys
import urllib.error
import urllib.request

# Live WAF/CDN probe list. Deliberately excludes "Google-Extended": it is a robots.txt-only
# opt-out token, not a crawler with its own distinct fetching UA -- Google's real crawlers are
# verified by IP/reverse-DNS, not UA string alone. Live-testing it with a bare "Googlebot" UA
# would conflate a genuine WAF block with Google's own (correct, expected) anti-spoofing
# rejection of an unverified UA claim -- confirmed during testing: Wikipedia 403s a spoofed
# Googlebot UA from a non-Google IP, which is Wikipedia behaving correctly, not a discoverability
# defect. Google-Extended's permission is still checked, just via robots.txt only (see the
# robots.txt-disallow finding above), never via a live fetch this script has no way to make
# credibly as "Google".
AI_AGENTS = [
    ("GPTBot", "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"),
    ("ClaudeBot", "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"),
    ("PerplexityBot", "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
]
PROBE_TIMEOUT_S = 6
MAJOR_AGENTS = {"GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"}


def probe_status(url, ua):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            resp.read(2000)  # just enough to complete the request; we only need the status
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def finding(title, severity, category, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": category, "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_crawl_access.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    robots = ev.get("robots", {})
    raw = ev.get("raw_fetch", {})

    blocked_major = [a for a in MAJOR_AGENTS if robots.get("target_path_allowed", {}).get(a) is False]
    if blocked_major:
        findings.append(finding(
            title=f"robots.txt disallows {', '.join(sorted(blocked_major))} on the audited path",
            severity="critical",
            category="crawl-access",
            evidence=(f"robots.txt at {robots.get('url')} disallows {sorted(blocked_major)} for path "
                      f"'{url}'. Rules: " + json.dumps({a: robots.get("rules_by_agent", {}).get(a) for a in blocked_major})),
            action_summary=("If this exclusion is unintentional, remove the Disallow rule (or add an "
                             "explicit Allow) for these agents on this path — a robots.txt block is a total, "
                             "unconditional cutoff, upstream of every other discoverability signal on the page. "
                             "If it is a deliberate policy choice, no action is needed, but note it trades away "
                             "citation/discovery in that assistant entirely."),
            action_priority="critical",
        ))

    raw_status = raw.get("status_code")
    if raw_status is not None and raw_status >= 400:
        findings.append(finding(
            title=f"Non-2xx response ({raw_status}) to a non-JS-executing AI-crawler fetch",
            severity="critical",
            category="crawl-access",
            evidence=(f"A GET to {url} with User-Agent '{raw.get('user_agent')}' (the fetch pattern most "
                      f"AI crawlers use — they do not execute JavaScript) returned HTTP {raw_status}."),
            action_summary=("Investigate why this UA/request pattern gets a non-2xx response — common "
                             "causes are bot-detection middleware, a missing Accept-Language/Accept header "
                             "check, or geofencing. Confirm with server/CDN access logs which layer issued "
                             "the response."),
            action_priority="critical",
        ))
    elif raw_status is None:
        findings.append(finding(
            title="Raw HTTP fetch failed outright",
            severity="critical",
            category="crawl-access",
            evidence=f"A direct GET to {url} raised: {raw.get('error')}",
            action_summary="Confirm the URL resolves and the server responds to a plain HTTP client without TLS/redirect errors.",
            action_priority="critical",
        ))

    redirects = raw.get("redirect_chain") or []
    if len(redirects) > 3:
        findings.append(finding(
            title=f"Redirect chain of {len(redirects)} hops before reaching final content",
            severity="medium",
            category="crawl-access",
            evidence=f"Redirect hops: {json.dumps(redirects)}",
            action_summary="Collapse to a single redirect (or none) from the canonical entry URL to the final page — each extra hop is another point where a bounded-timeout crawler can give up.",
            action_priority="medium",
        ))

    if robots.get("fetched") is False and robots.get("status_code") not in (404, None):
        findings.append(finding(
            title="robots.txt is unreachable (non-404 error)",
            severity="medium",
            category="crawl-access",
            evidence=f"GET {robots.get('url')} did not return a normal 200/404 response (status={robots.get('status_code')}, error={robots.get('error')}).",
            action_summary="Serve robots.txt reliably with a 200 (or a clean 404 if none is intended) — some crawlers back off site-wide when robots.txt itself errors, treating it as an ambiguous signal rather than an open one.",
            action_priority="medium",
        ))

    if not robots.get("sitemap_urls"):
        findings.append(finding(
            title="No sitemap declared in robots.txt",
            severity="low",
            category="crawl-access",
            evidence=f"robots.txt at {robots.get('url')} declares zero `Sitemap:` entries.",
            action_summary="Add a `Sitemap:` line to robots.txt pointing at an XML sitemap — it's the cheapest, most direct way to hand a crawler the full set of URLs worth fetching instead of relying purely on discovered internal links.",
            action_priority="low",
            beyond_defect=True,
        ))

    # Narrow, capped WAF-level probe: only for agents robots.txt does NOT already disallow.
    waf_blocked = []
    for agent, ua in AI_AGENTS:
        if robots.get("target_path_allowed", {}).get(agent) is False:
            continue  # already covered by the robots.txt finding above; do not fetch what robots disallows
        status, err = probe_status(url, ua)
        if status is not None and status >= 400:
            waf_blocked.append({"agent": agent, "status": status})
        elif status is None:
            waf_blocked.append({"agent": agent, "error": err})
    if waf_blocked:
        findings.append(finding(
            title="Server/CDN blocks specific AI-crawler user agents even though robots.txt allows them",
            severity="critical",
            category="crawl-access",
            evidence=("robots.txt permits these agents, but a direct GET using their real UA string still "
                      f"failed: {json.dumps(waf_blocked)}. A plain-browser fetch of the same URL succeeded "
                      f"(status {ev.get('rendered', {}).get('status_code')})."),
            action_summary=("Check the WAF/CDN/bot-management layer (e.g. Cloudflare Bot Fight Mode, "
                             "Akamai Bot Manager) for a rule matching these UA strings and add an explicit "
                             "allow-list entry — robots.txt is a courtesy signal, but a network-layer block "
                             "overrides it completely and is invisible to anyone only checking robots.txt."),
            action_priority="critical",
        ))

    print(json.dumps(findings, ensure_ascii=False))


if __name__ == "__main__":
    main()
