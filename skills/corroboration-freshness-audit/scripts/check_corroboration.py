#!/usr/bin/env python3
"""corroboration-freshness-audit: does the wider web agree with this page, and does the page
agree with itself?

Reads the shared evidence.json for entity-identity and freshness signals, then performs its own
narrowly-scoped extra work: 2 additional fresh, isolated-context fetches of the same URL, diffed
against the shared evidence's rendered pass, to catch a URL that returns genuinely different facts
across fetches (hydration nondeterminism or personalization/experiment bucketing) -- a strictly
worse corroboration signal than having no corroboration at all, per the mechanism documented in
references/thresholds.md.

Usage: python check_corroboration.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import re
import sys

PRICE_RE = re.compile(r'[$€£¥]\s?\d[\d,]*(\.\d+)?')
JACCARD_DIVERGENCE_THRESHOLD = 0.5
MULTI_FETCH_COUNT = 2  # additional fetches beyond the one already in evidence.json
MULTI_FETCH_TIMEOUT_MS = 12000


def finding(title, severity, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": "corroboration-freshness", "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def check_entity_identity(ev, url, findings):
    mi = ev.get("meta_identity", {})
    same_as = mi.get("same_as", [])
    org_present = mi.get("organization_schema_present", False)
    has_wikidata = any("wikidata.org" in s for s in same_as)

    if not org_present and not same_as:
        findings.append(finding(
            title="No Organization schema or sameAs identity links found",
            severity="medium",
            evidence=f"No schema.org Organization block and zero `sameAs` URLs found anywhere in JSON-LD on {url}.",
            action_summary=("Add an Organization JSON-LD block with `sameAs` links to authoritative external "
                             "identity anchors (Wikidata above all — it assigns a stable Q-number that feeds "
                             "major knowledge graphs, plus official social/profile pages). Each sameAs link is "
                             "effectively a vote that lets a system collapse scattered mentions of the brand "
                             "into one confident, citable entity instead of several ambiguous ones."),
            action_priority="medium",
        ))
    elif same_as and not has_wikidata:
        findings.append(finding(
            title="Entity identity links present but none point to Wikidata",
            severity="low",
            evidence=f"{len(same_as)} `sameAs` URL(s) found on {url}, none pointing to wikidata.org.",
            action_summary="Add (or create) a Wikidata item for this entity and link it via sameAs — it's the highest-authority identity anchor available and feeds directly into the knowledge graphs major assistants consult.",
            action_priority="low",
            beyond_defect=True,
        ))


def _extract_dates(parsed_blocks):
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("dateModified", "datePublished", "dateCreated"):
                if key in node and node[key]:
                    found.append((key, node[key]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for b in parsed_blocks:
        if b is not None:
            walk(b)
    return found


VISIBLE_DATE_RE = re.compile(
    r'\b(updated|last updated|published|posted)\b[^.\n]{0,40}?'
    r'(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})',
    re.IGNORECASE,
)


def check_freshness(ev, url, findings):
    sd = ev.get("structured_data", {})
    raw_parsed = [b.get("parsed") for b in sd.get("raw_json_ld", [])]
    rendered_parsed = [b.get("parsed") for b in sd.get("rendered_json_ld", [])]
    dates = _extract_dates(raw_parsed + rendered_parsed)

    body_text = (ev.get("rendered", {}).get("text_content") or "")
    visible_date_match = VISIBLE_DATE_RE.search(body_text)

    text_len = ev.get("rendered", {}).get("text_length", 0)
    if text_len < 1500:
        return  # too little content to be a freshness-relevant "article-like" page

    if not dates and not visible_date_match:
        findings.append(finding(
            title="No machine-readable or visible freshness signal (dateModified / \"last updated\")",
            severity="medium",
            evidence=(f"{url} has {text_len} characters of substantive content but no `dateModified`/"
                      "`datePublished` in JSON-LD and no visible \"updated\"/\"published\" date text found."),
            action_summary=("Add `dateModified` (and `datePublished`) to the page's JSON-LD, and show a "
                             "plain-text \"Updated on <date>\" near the top of the content. A comparative audit "
                             "found AI-surfaced citations run measurably fresher than traditional search "
                             "results (~25.7% fresher in one 17M-citation analysis), and citation sets rotate "
                             "substantially month to month — an undated page is a weaker freshness signal even "
                             "when its content hasn't actually gone stale."),
            action_priority="medium",
        ))
    elif visible_date_match and not dates:
        findings.append(finding(
            title="Freshness date is visible to readers but not machine-readable",
            severity="low",
            evidence=f"Found visible date text ({visible_date_match.group(0)!r}) but no `dateModified`/`datePublished` in JSON-LD on {url}.",
            action_summary="Add the same date as `dateModified`/`datePublished` in JSON-LD — the visible text version doesn't reliably reach a system parsing structured data rather than reading prose.",
            action_priority="low",
            beyond_defect=True,
        ))


def _fact_signature(title, text, html_len):
    words = set(re.findall(r"[a-z0-9]{4,}", (text or "").lower()[:1500]))
    prices = sorted(set(PRICE_RE.findall(text or "")))
    return {"title": (title or "").strip(), "words": words, "prices": prices, "html_len": html_len}


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def multi_fetch(url):
    from playwright.sync_api import sync_playwright

    sigs = []
    details = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            for i in range(MULTI_FETCH_COUNT):
                context = browser.new_context()  # fresh: no shared cookies/cache/storage
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=MULTI_FETCH_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(500)
                    title = page.title()
                    text = page.evaluate("document.body ? document.body.innerText : ''")
                    html_len = len(page.content())
                    sigs.append(_fact_signature(title, text, html_len))
                    details.append(f"fetch#{i + 2}: title={title!r}, html_len={html_len}")
                finally:
                    context.close()
            browser.close()
    except Exception as e:  # noqa: BLE001
        return [], [f"multi-fetch error: {type(e).__name__}: {e}"]
    return sigs, details


def check_self_consistency(ev, url, findings):
    rendered = ev.get("rendered", {})
    if rendered.get("status_code") != 200 or rendered.get("text_length", 0) < 200:
        return  # nothing reliable to compare against

    baseline = _fact_signature(rendered.get("title"), rendered.get("text_content"), rendered.get("html_length"))
    extra_sigs, details = multi_fetch(url)
    if not extra_sigs:
        return

    all_sigs = [baseline] + extra_sigs
    titles = {s["title"] for s in all_sigs if s["title"]}
    price_sets = [frozenset(s["prices"]) for s in all_sigs if s["prices"]]
    min_jaccard = min(_jaccard(all_sigs[0]["words"], s["words"]) for s in all_sigs[1:])

    divergences = []
    if len(titles) > 1:
        divergences.append(f"title differs across fetches: {sorted(titles)}")
    if len(set(price_sets)) > 1:
        divergences.append(f"price/currency tokens differ across fetches: {[sorted(p) for p in price_sets]}")
    if min_jaccard < JACCARD_DIVERGENCE_THRESHOLD:
        divergences.append(f"body-text overlap across fetches dropped as low as {min_jaccard:.2f} (word-set Jaccard)")

    if divergences:
        findings.append(finding(
            title="The same URL returns materially different facts across independent fetches",
            severity="critical" if (len(titles) > 1 or len(set(price_sets)) > 1) else "high",
            evidence=(f"Fetched {url} in {len(all_sigs)} independent, isolated browser contexts (no shared "
                      f"cookies/cache). Divergences: {'; '.join(divergences)}. Fetch details: {details}."),
            action_summary=("Treat the server-rendered initial payload as the canonical baseline for every "
                             "decision-relevant fact, with personalization or A/B bucketing applied strictly "
                             "additively on top of it — never as a pre-hydration replacement. If this is caused "
                             "by hydration nondeterminism rather than intentional personalization, fix the "
                             "source of the mismatch and add a server-HTML-vs-hydrated-DOM diff to the deploy "
                             "pipeline. A URL that disagrees with itself across fetches is a worse trust signal "
                             "than a URL with no external corroboration at all — it teaches a retrieval system "
                             "the domain is an unreliable witness to its own content."),
            action_priority="critical" if (len(titles) > 1 or len(set(price_sets)) > 1) else "high",
        ))


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_corroboration.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    check_entity_identity(ev, url, findings)
    check_freshness(ev, url, findings)
    check_self_consistency(ev, url, findings)

    print(json.dumps(findings, ensure_ascii=False))


if __name__ == "__main__":
    main()
