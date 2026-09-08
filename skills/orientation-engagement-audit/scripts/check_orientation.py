#!/usr/bin/env python3
"""orientation-engagement-audit: once a fact is technically present, can a human find and trust
it fast?

Reads the shared evidence.json and checks page-purpose clarity, navigation/breadcrumb wayfinding,
and internal-link "information scent" -- grounded in Pirolli & Card's Information Scent theory
(see references/thresholds.md), a different failure class from the technical Context-Lock checks
in context-lock-audit: a page can be perfectly stable and perfectly fetchable and still lose a
visitor to weak orientation cues alone.

Usage: python check_orientation.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import re
import sys
from urllib.parse import urlparse

MIN_TEXT_FOR_ORIENTATION_CHECKS = 800
GENERIC_LINK_TEXTS = {
    "click here", "here", "read more", "learn more", "more", "link", "this", "details",
    "more info", "more information", "continue reading", "see more", "go", "view",
}
GENERIC_LINK_FRACTION_THRESHOLD = 0.30
MIN_SAMPLE_FOR_LINK_SCENT_CHECK = 6


def finding(title, severity, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": "orientation-engagement", "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def check_page_purpose(ev, url, findings):
    headings = ev.get("rendered", {}).get("headings", [])
    text_len = ev.get("rendered", {}).get("text_length", 0)
    if text_len < MIN_TEXT_FOR_ORIENTATION_CHECKS:
        return
    h1s = [h for h in headings if h.get("level") == 1]
    if not h1s:
        findings.append(finding(
            title="No H1 heading stating what this page is",
            severity="high",
            evidence=f"{url} has {text_len} characters of content and 0 level-1 headings.",
            action_summary=("Add a single, specific H1 that states the page's subject in plain language. "
                             "Per information-scent theory (Pirolli & Card), a visitor's first move is to "
                             "match the page against the cue that brought them here — with no H1, there is "
                             "no immediate, scannable confirmation they landed in the right place, which "
                             "raises abandonment risk independent of whether the content itself is good."),
            action_priority="high",
        ))
    elif len(h1s) > 1:
        findings.append(finding(
            title=f"Multiple H1 headings ({len(h1s)}) on one page",
            severity="low",
            evidence=f"{url} has {len(h1s)} level-1 headings: {[h.get('text') for h in h1s[:5]]}",
            action_summary="Use exactly one H1 stating the page's primary subject; demote the rest to H2/H3 — multiple H1s dilute which one thing a scanning visitor (or a machine chunking the page) should treat as the page's identity.",
            action_priority="low",
            beyond_defect=True,
        ))


def check_navigation(ev, url, findings):
    links = ev.get("links", {})
    text_len = ev.get("rendered", {}).get("text_length", 0)
    if not links.get("nav_present", False):
        findings.append(finding(
            title="No navigation landmark (<nav> or role=\"navigation\") found",
            severity="high",
            evidence=f"No element matching `nav` or `[role=\"navigation\"]` was found in the rendered DOM of {url}.",
            action_summary=("Add a navigation landmark with links to the site's main sections. Wayfinding "
                             "research frames navigation as forward-looking scent toward a visitor's goal — "
                             "without a discoverable nav landmark, a visitor who arrives on this exact page "
                             "(e.g. via an AI citation, not the homepage) has no structured path to anywhere "
                             "else on the site."),
            action_priority="high",
        ))
        return  # breadcrumb check below is moot without any nav structure at all

    path_depth = len([seg for seg in urlparse(url).path.split("/") if seg])
    if path_depth >= 3 and not links.get("breadcrumb_present", False):
        findings.append(finding(
            title="No breadcrumb trail on a deep page",
            severity="low",
            evidence=f"{url} has a path depth of {path_depth} segments and a nav landmark, but no element matching a breadcrumb pattern was found.",
            action_summary=("Add a breadcrumb trail. Orientation research distinguishes forward-looking "
                             "navigation scent from orientation scent — \"the scent of the path behind you\" — "
                             "and a breadcrumb is the direct mechanism for the latter: it tells a visitor who "
                             "landed deep in the site, out of context, where they are before they decide "
                             "whether to explore further or bounce."),
            action_priority="low",
            beyond_defect=True,
        ))


def check_link_scent(ev, url, findings):
    links = ev.get("links", {})
    sample = links.get("sample_internal", [])
    if len(sample) < MIN_SAMPLE_FOR_LINK_SCENT_CHECK:
        return
    generic = [l for l in sample if (l.get("text") or "").strip().lower() in GENERIC_LINK_TEXTS
               or len((l.get("text") or "").strip()) <= 2]
    fraction = len(generic) / len(sample)
    if fraction >= GENERIC_LINK_FRACTION_THRESHOLD:
        findings.append(finding(
            title="Many internal links use generic, low-information text",
            severity="medium",
            evidence=(f"{len(generic)} of {len(sample)} sampled internal links ({fraction:.0%}) use generic "
                      f"text such as {sorted({l['text'] for l in generic if l.get('text')})[:6]}."),
            action_summary=("Rewrite link text to name the destination or the specific fact it leads to "
                             "(e.g. \"2026 pricing tiers\" instead of \"learn more\"). Information-scent theory "
                             "treats link-label relevance as the primary cue a visitor (or an agent following "
                             "links) uses to predict whether following it serves their goal — generic labels "
                             "carry zero scent and raise the cognitive cost of every navigation decision on "
                             "the page."),
            action_priority="medium",
        ))

    if links.get("internal_count", 0) == 0:
        text_len = ev.get("rendered", {}).get("text_length", 0)
        if text_len >= MIN_TEXT_FOR_ORIENTATION_CHECKS:
            findings.append(finding(
                title="Zero internal links on a substantial page",
                severity="high",
                evidence=f"{url} has {text_len} characters of content and 0 internal links.",
                action_summary="Link to at least the site's main sections and any directly related content — a page with no way out is a dead end for both a visitor trying to explore further and a crawler trying to discover the rest of the site from this entry point.",
                action_priority="high",
            ))


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_orientation.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    check_page_purpose(ev, url, findings)
    check_navigation(ev, url, findings)
    check_link_scent(ev, url, findings)

    print(json.dumps(findings, ensure_ascii=False))


if __name__ == "__main__":
    main()
