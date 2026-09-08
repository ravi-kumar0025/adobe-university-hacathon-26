#!/usr/bin/env python3
"""structured-fact-audit: is a fact stated in a form a machine can lift verbatim?

Reads the shared evidence.json and checks structured-data presence/validity/reachability
(JSON-LD, Open Graph) and structural extractability (heading density, summary metadata),
grounded in measured 2026 citation-behavior research rather than generic SEO folklore.
See references/thresholds.md for the exact numbers and their sources.

Usage: python check_structured_facts.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import re
import sys

MIN_SUBSTANTIAL_TEXT_CHARS = 1500
# Deliberately narrow: a bare "%" or the word "review" appears on almost any content page and
# produced a false positive during testing (a GitHub stats page: "90% Fortune 100"). Require an
# actual commerce/transaction signal -- a currency amount or an explicit purchase-flow phrase --
# not just any number or vaguely entity-adjacent word.
ENTITY_SIGNAL_RE = re.compile(
    r'[$€£¥]\s?\d[\d,]*(\.\d+)?|\badd to cart\b|\bbuy now\b|\bin stock\b|\bout of stock\b|\bSKU[:\s]|\bfree shipping\b',
    re.IGNORECASE,
)
ENTITY_OG_TYPES = {"product", "article", "book", "music.song", "music.album", "video.movie"}


def finding(title, severity, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": "structured-fact", "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_structured_facts.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    sd = ev.get("structured_data", {})
    rendered = ev.get("rendered", {})
    raw = ev.get("raw_fetch", {})

    raw_ld = sd.get("raw_json_ld", [])
    rendered_ld = sd.get("rendered_json_ld", [])
    raw_ld_valid = [b for b in raw_ld if b.get("parsed") is not None]
    raw_ld_invalid = [b for b in raw_ld if b.get("parsed") is None]

    body_text = (rendered.get("text_content") or "") + " " + (raw.get("text_content") or "")
    looks_like_entity_page = bool(ENTITY_SIGNAL_RE.search(body_text)) or \
        str(sd.get("open_graph", {}).get("og:type", "")).lower() in ENTITY_OG_TYPES

    # Only compare raw-vs-rendered JSON-LD presence when the raw fetch actually succeeded --
    # if it was blocked (see crawl-access-audit), an empty raw_ld is explained by the block, not
    # by a client-side-only rendering architecture, and claiming otherwise would misattribute a
    # gatekeeping failure as a structured-data defect (found via NYT, whose GPTBot-UA fetch is
    # 403'd: raw_ld was empty purely because the fetch failed, not because of CSR).
    if raw.get("status_code") == 200:
        if not raw_ld and rendered_ld:
            findings.append(finding(
                title="JSON-LD structured data is injected client-side only",
                severity="critical",
                evidence=(f"{len(rendered_ld)} `application/ld+json` block(s) found after JS execution, but "
                          f"zero appear in the raw, non-JS-executing HTML fetch of {url}."),
                action_summary=("Render JSON-LD server-side (SSR/SSG) so it ships in the initial HTML response. "
                                 "Most AI crawlers fetch pages without executing JavaScript, so client-injected "
                                 "structured data is invisible to exactly the systems this markup exists for."),
                action_priority="critical",
            ))
        elif not raw_ld and not rendered_ld:
            if looks_like_entity_page:
                findings.append(finding(
                    title="No JSON-LD structured data despite entity-like page content",
                    severity="high",
                    evidence=(f"0/1 pages checked contain schema.org JSON-LD markup at {url}, but the page's own "
                              f"text/meta signals (a currency amount, an explicit purchase-flow phrase, or an "
                              f"og:type of {sorted(ENTITY_OG_TYPES)}) indicate it describes a concrete, "
                              f"transactable entity worth marking up."),
                    action_summary="Add JSON-LD (Product/Offer, Article, or the appropriate schema.org type) describing this page's primary entity, server-rendered in the initial HTML.",
                    action_priority="high",
                ))
            else:
                findings.append(finding(
                    title="No JSON-LD structured data on the page",
                    severity="low",
                    evidence=f"0 `application/ld+json` blocks found in either the raw or rendered HTML of {url}.",
                    action_summary="Add a JSON-LD block (at minimum Organization/WebPage) describing the page and its parent entity — a low-cost, direct way to hand a machine an unambiguous fact set instead of making it infer one from prose.",
                    action_priority="low",
                    beyond_defect=True,
                ))

    if raw_ld_invalid:
        findings.append(finding(
            title="JSON-LD block present but fails to parse as valid JSON",
            severity="high",
            evidence=f"{len(raw_ld_invalid)} of {len(raw_ld)} `application/ld+json` block(s) on {url} raised a parse error, e.g.: {raw_ld_invalid[0].get('parse_error')}",
            action_summary="Fix the malformed JSON-LD (trailing commas, unescaped quotes, or template-engine artifacts are the usual cause) — an unparsable block is discarded entirely by any consumer, identical in effect to having none.",
            action_priority="high",
        ))
    elif raw_ld_valid:
        missing_type = [b for b in raw_ld_valid if not _has_type(b.get("parsed"))]
        if missing_type:
            findings.append(finding(
                title="JSON-LD block is valid JSON but missing @type/@context",
                severity="medium",
                evidence=f"{len(missing_type)} of {len(raw_ld_valid)} JSON-LD block(s) on {url} parse successfully but lack an @type (or @context), so a consumer can't tell what kind of entity it describes.",
                action_summary="Add @context (https://schema.org) and an explicit, correct @type to every JSON-LD block.",
                action_priority="medium",
            ))

    headings = rendered.get("headings", [])
    text_len = max(rendered.get("text_length", 0), raw.get("text_length", 0))
    if text_len >= MIN_SUBSTANTIAL_TEXT_CHARS and len(headings) == 0:
        findings.append(finding(
            title="Substantial page content with zero heading structure",
            severity="medium",
            evidence=(f"Page has {text_len} characters of visible text and 0 heading elements (h1-h6). "
                      "A synthesis of 2026 AI-citation studies found top-quartile cited pages carry roughly "
                      "12.5x the heading count of bottom-quartile cited pages — heading structure is a "
                      "measured extractability signal, not just a style preference."),
            action_summary="Break the content into sections with real h2/h3 headings that state the fact or topic each section covers, so a retrieval system can chunk and cite a specific section rather than the whole page.",
            action_priority="medium",
        ))
    elif text_len >= MIN_SUBSTANTIAL_TEXT_CHARS * 2 and len(headings) <= 1:
        findings.append(finding(
            title="Long page content relies on a single heading",
            severity="low",
            evidence=f"Page has {text_len} characters of visible text but only {len(headings)} heading element(s).",
            action_summary="Add subheadings roughly every few hundred words — denser heading structure is measurably associated with higher citation rates in AI answer engines.",
            action_priority="low",
            beyond_defect=True,
        ))

    og = sd.get("open_graph", {})
    has_summary = bool(og.get("og:description")) or bool(rendered.get("meta_description"))
    has_title = bool(og.get("og:title")) or bool(rendered.get("title"))
    if not has_summary:
        findings.append(finding(
            title="No summary metadata (meta description / og:description)",
            severity="medium",
            evidence=f"Neither <meta name=\"description\"> nor og:description is present on {url}.",
            action_summary=("Add a concise, specific meta description stating the page's core fact in one or "
                             "two sentences. The same mechanism that causes AI email summarizers to drop "
                             "content with no clear, extractable substance applies to page summarization: "
                             "if the important line isn't stated plainly and locatably, it can simply be "
                             "left out of a generated summary."),
            action_priority="medium",
        ))
    if not has_title:
        findings.append(finding(
            title="No page title / og:title",
            severity="high",
            evidence=f"Neither <title> nor og:title resolves to a non-empty value on {url}.",
            action_summary="Set an explicit, descriptive <title> and og:title — this is the single most load-bearing piece of identity text on the page for both search and AI systems.",
            action_priority="high",
        ))

    print(json.dumps(findings, ensure_ascii=False))


def _has_type(parsed):
    if isinstance(parsed, dict):
        if "@type" in parsed and parsed["@type"]:
            return True
        if "@graph" in parsed and isinstance(parsed["@graph"], list):
            return any(_has_type(n) for n in parsed["@graph"])
        return False
    if isinstance(parsed, list):
        return any(_has_type(n) for n in parsed)
    return False


if __name__ == "__main__":
    main()
