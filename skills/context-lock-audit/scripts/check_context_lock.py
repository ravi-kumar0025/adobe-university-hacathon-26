#!/usr/bin/env python3
"""context-lock-audit: does the specific fact an AI would cite actually materialize for the
human who clicks through?

Reads the shared evidence.json and checks for "Context Lock" -- a visitor arriving at a URL
(often via an AI citation to one specific fact) landing on a state that doesn't contain, or
doesn't resolve to, the fact that got them there. Three checks: list-virtualization deep-link
voids (with one bounded, live deep-link replay to confirm when a real permalink is available),
and a conservative stuck-live-region check. Distinct from render-fidelity-audit, which asks
whether a *crawler* can read the content -- this skill asks whether a *human*, landing fresh on
the exact URL an assistant would cite, gets the content that citation promised.

Usage: python check_context_lock.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import re
import sys
from urllib.parse import urljoin

STUCK_ARIA_BUSY_RE = re.compile(r'aria-busy\s*=\s*"true"', re.IGNORECASE)
COUNT_STABLE_RATIO = 1.3
STATED_TOTAL_VOID_RATIO = 3.0
REPLAY_TIMEOUT_MS = 9000


def finding(title, severity, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": "context-lock", "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def replay_deep_link(href, base_url):
    """One bounded, fresh-context navigation to confirm whether a specific item permalink
    actually reproduces its content with no prior scroll/session history. Returns
    (reproduced: bool|None, detail: str). None means the replay itself could not be attempted."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright not available for live deep-link replay; structural signature only."

    target = urljoin(base_url, href)
    slug = href.rstrip("/").rsplit("/", 1)[-1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            context = browser.new_context()  # fresh context: no cookies, no scroll history
            page = context.new_page()
            resp = page.goto(target, wait_until="domcontentloaded", timeout=REPLAY_TIMEOUT_MS)
            page.wait_for_timeout(1000)
            status = resp.status if resp else None
            body_text = page.evaluate("document.body ? document.body.innerText : ''")
            found = bool(slug) and slug.lower() in body_text.lower()
            html_len = len(page.content())
            browser.close()
            if status is not None and status >= 400:
                return False, f"Fresh navigation to {target} returned HTTP {status}."
            if not found:
                return False, (f"Fresh navigation to {target} returned HTTP {status}, "
                                f"{html_len} bytes of HTML, but the item identifier '{slug}' "
                                "does not appear anywhere in the rendered page text.")
            return True, f"Fresh navigation to {target} reproduced content containing '{slug}'."
    except Exception as e:  # noqa: BLE001
        return None, f"Replay attempt raised {type(e).__name__}: {e}"


def check_virtualization(ev, url, findings):
    for cand in ev.get("structural", {}).get("list_candidates", []):
        added = cand.get("post_scroll_ids_added", 0)
        initial = max(cand.get("initial_count", 0), 1)
        post = cand.get("post_scroll_count", initial)
        if added <= 0:
            continue
        count_stable = post / initial < COUNT_STABLE_RATIO
        if not count_stable:
            continue  # looks like plain append-growth (infinite scroll keeping old items), not windowed recycling

        hint = cand.get("container_hint")
        stated_total = cand.get("stated_total_in_page_text")
        hrefs = cand.get("newly_revealed_hrefs", [])

        replay_result = None
        replay_detail = None
        if hrefs:
            replay_result, replay_detail = replay_deep_link(hrefs[0], url)

        if replay_result is False:
            findings.append(finding(
                title="Confirmed: a deep link into a virtualized list does not reproduce its content",
                severity="critical",
                evidence=(f"List container ({hint}) shows a virtualization signature: {added} new item "
                          f"identifiers appeared after scrolling while the rendered DOM count stayed at "
                          f"~{post} (started at {initial}). {replay_detail}"),
                action_summary=("Wire the virtualizer's imperative scroll-to-index/item API into route or "
                                 "fragment parsing on page load, so navigating directly to an item's URL "
                                 "restores that item's visible state instead of the default window. Pair "
                                 "virtualization with a genuinely crawlable, paginated fallback view."),
                action_priority="critical",
            ))
        elif stated_total and stated_total > post * STATED_TOTAL_VOID_RATIO:
            findings.append(finding(
                title="List virtualization likely creates deep-link voids for most of a large catalog",
                severity="high",
                evidence=(f"List container ({hint}): {added} new item identifiers appeared after scrolling "
                          f"while DOM count stayed at ~{post} (of a total of {stated_total} stated in page "
                          "text) -- a windowed/recycling pattern, not simple infinite-append growth. An "
                          "assistant that obtained the full dataset another way can cite a specific item's "
                          "URL; a visitor who clicks it gets the virtualizer's default window, not that item."),
                action_summary=("Wire the virtualizer's scroll-to-index API into URL/fragment parsing on "
                                 "mount, and publish a paginated, non-virtualized fallback view so the full "
                                 "catalog is reachable via real per-page URLs."),
                action_priority="high",
            ))
        elif hrefs:
            findings.append(finding(
                title="List virtualization detected on a container with real per-item permalinks",
                severity="medium",
                evidence=(f"List container ({hint}): {added} new item identifiers (e.g. {hrefs[:2]}) appeared "
                          f"only after scrolling, while DOM count stayed at ~{post}. "
                          + (replay_detail or "Live replay was not conclusive.")),
                action_summary="Confirm that navigating directly to one of these item URLs restores that item's visible state on load rather than the default virtualized window.",
                action_priority="medium",
            ))
        else:
            findings.append(finding(
                title="List virtualization detected with no discoverable per-item permalinks",
                severity="medium",
                evidence=(f"List container ({hint}): {added} item identifiers churned after scrolling with no "
                          "href/permalink pattern found on any item. Beyond the virtualization risk itself, "
                          "an assistant has no per-item URL to cite for anything outside the default window "
                          "in the first place."),
                action_summary="Give each item in this list its own stable, linkable URL (or at least a URL fragment) -- without one, individual items are neither citable by an assistant nor deep-linkable by anyone.",
                action_priority="medium",
            ))


def check_stuck_live_region(ev, url, findings):
    rendered = ev.get("rendered", {})
    net = ev.get("structural", {}).get("network", {})
    html = rendered.get("html", "")
    if (net.get("websocket_count", 0) > 0 or net.get("sse_count", 0) > 0) and STUCK_ARIA_BUSY_RE.search(html):
        findings.append(finding(
            title="A live-data region is still marked aria-busy after full page settle",
            severity="high",
            evidence=(f"{url} has an active WebSocket/SSE connection and, even after network-idle plus a "
                      "settle delay, still contains an element with aria-busy=\"true\" -- an explicit signal "
                      "the page itself considers this region not-yet-resolved. A visitor landing here (e.g. "
                      "via an AI citation, or behind a proxy that blocks the live channel) may see this "
                      "indefinitely with no explanation."),
            action_summary="Give the live-fed region a bounded timeout: after a few seconds with no update, replace the busy state with an explicit 'live data unavailable, showing last known value' message rather than an indefinite busy indicator.",
            action_priority="high",
        ))


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_context_lock.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    check_virtualization(ev, url, findings)
    check_stuck_live_region(ev, url, findings)

    print(json.dumps(findings, ensure_ascii=False))


if __name__ == "__main__":
    main()
