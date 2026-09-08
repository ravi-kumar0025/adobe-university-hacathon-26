#!/usr/bin/env python3
"""render-fidelity-audit: given a successful fetch, can the content actually be read?

Reads the shared evidence.json and checks four independent machine-readability gaps:
CSR "empty shell" (raw vs. rendered text ratio), Shadow DOM content lock, WebSocket/SSE-gated
facts with no static fallback, and Canvas/WebGL pixel-locked data. Thresholds and their sources
are documented in references/thresholds.md.

Usage: python check_render_fidelity.py <evidence_json_path> <url>
Prints a JSON array of findings to stdout.
"""
import json
import sys

CSR_CRITICAL_RATIO = 0.10
CSR_HIGH_RATIO = 0.30
MIN_RENDERED_TEXT_FOR_CSR_CHECK = 500

SHADOW_LOCK_MIN_SHADOW_TEXT = 100
SHADOW_LOCK_MAX_HOST_RATIO = 0.10
CLOSED_LOCK_MIN_BBOX_AREA = 5000
CLOSED_LOCK_MAX_HOST_TEXT = 20

CANVAS_MIN_BBOX_AREA = 20000

WS_MIN_TEXT_GROWTH = 200


def finding(title, severity, evidence, action_summary, action_priority, beyond_defect=False):
    return {
        "title": title, "severity": severity, "category": "render-fidelity", "evidence": evidence,
        "suggested_action": {"summary": action_summary, "priority": action_priority},
        "beyond_defect": beyond_defect,
    }


def check_csr_empty_shell(ev, url, findings):
    raw = ev.get("raw_fetch", {})
    rendered = ev.get("rendered", {})
    if raw.get("status_code") != 200:
        # A non-200 raw fetch (blocked, redirected-to-error, etc.) is crawl-access-audit's finding,
        # not a rendering-architecture one -- comparing text lengths here would misattribute a
        # gatekeeping failure as a CSR problem and duplicate that other skill's finding.
        return
    raw_len = raw.get("text_length", 0)
    rendered_len = rendered.get("text_length", 0)
    if rendered_len < MIN_RENDERED_TEXT_FOR_CSR_CHECK:
        return  # too little content either way to draw a CSR conclusion from a ratio
    ratio = raw_len / max(rendered_len, 1)
    if ratio < CSR_CRITICAL_RATIO:
        severity = "critical"
    elif ratio < CSR_HIGH_RATIO:
        severity = "high"
    else:
        return
    findings.append(finding(
        title="Client-side rendering leaves the raw HTML response nearly empty",
        severity=severity,
        evidence=(f"Raw (non-JS-executing) fetch of {url} contains {raw_len} characters of visible text; "
                  f"the fully rendered page contains {rendered_len}. Ratio {ratio:.3f} "
                  f"(< {CSR_CRITICAL_RATIO if severity == 'critical' else CSR_HIGH_RATIO} threshold). "
                  "Independent traffic analysis has found major AI crawlers (GPTBot, ClaudeBot) fetch "
                  "pages without executing JavaScript in the large majority of requests."),
        action_summary=("Server-render (SSR) or statically pre-render (SSG) this page's primary content, "
                         "or add pre-rendering middleware for crawler user agents, so the initial HTTP "
                         "response already contains the facts — not just the application shell."),
        action_priority=severity,
    ))


def check_shadow_dom(ev, url, findings):
    dsd_present = ev.get("structural", {}).get("dsd_template_present_in_raw_html", False)
    any_open_shadow = False
    for el in ev.get("structural", {}).get("custom_elements", []):
        tag = el.get("tag")
        if el.get("shadow_root_open"):
            any_open_shadow = True
            shadow_len = el.get("shadow_text_length", 0)
            host_len = el.get("host_light_dom_text_length", 0)
            if shadow_len >= SHADOW_LOCK_MIN_SHADOW_TEXT and host_len < SHADOW_LOCK_MAX_HOST_RATIO * shadow_len:
                findings.append(finding(
                    title=f"Open Shadow DOM on <{tag}> hides {shadow_len} characters of text from light-DOM extraction",
                    severity="critical",
                    evidence=(f"<{tag}> has an open shadow root containing {shadow_len} characters of text, "
                              f"but the host element's own light-DOM textContent is only {host_len} characters. "
                              "Standard DOM extraction (including Playwright's own page.content()) does not "
                              "descend into shadow roots by default — this content is invisible to any "
                              "extractor that reads element.textContent or the serialized light-DOM HTML."),
                    action_summary=("Emit this component via Declarative Shadow DOM (a <template shadowrootmode="
                                     "\"open\"> parsed straight into a shadow root, no script required) so the "
                                     "content ships in the initial HTML, or mirror the key facts in plain, "
                                     "visually-hidden light-DOM markup as a fallback."),
                    action_priority="critical",
                ))
        else:
            bbox = el.get("host_bbox_area", 0)
            host_len = el.get("host_light_dom_text_length", 0)
            if bbox >= CLOSED_LOCK_MIN_BBOX_AREA and host_len < CLOSED_LOCK_MAX_HOST_TEXT:
                findings.append(finding(
                    title=f"<{tag}> renders a visible region with no corresponding light-DOM text",
                    severity="high",
                    evidence=(f"<{tag}> occupies a {bbox}px² on-screen area but its light-DOM textContent is "
                              f"only {host_len} characters, and no open shadow root is exposed to inspect. "
                              "This is consistent with a closed shadow root (element.shadowRoot returns null "
                              "by specification) or a JS-only rendering path — either way, the visible content "
                              "is not present anywhere a light-DOM/HTML-based extractor looks."),
                    action_summary=("Never ship `mode: \"closed\"` shadow roots for user-facing facts — it buys "
                                     "negligible security benefit on public content and unconditionally hides "
                                     "it from every non-interactive consumer. Confirm this component's real "
                                     "content is reachable as plain light-DOM text."),
                    action_priority="high",
                ))
    if any_open_shadow and not dsd_present:
        findings.append(finding(
            title="Site uses Shadow DOM but ships no Declarative Shadow DOM anywhere",
            severity="medium",
            evidence=(f"At least one custom element on {url} has an open shadow root, but zero "
                      "`<template shadowrootmode>` markers were found in the raw (pre-JS) HTML — shadow roots "
                      "are being attached imperatively via script, so a non-JS-executing crawler receives none "
                      "of this content regardless of open/closed mode."),
            action_summary="Migrate fact-bearing Web Components to Declarative Shadow DOM so their content exists in the wire bytes, not just after a script runs.",
            action_priority="medium",
            beyond_defect=True,
        ))


def check_canvas(ev, url, findings):
    for c in ev.get("structural", {}).get("canvases", []):
        if c.get("bbox_area", 0) < CANVAS_MIN_BBOX_AREA:
            continue
        if c.get("has_fallback_text") or c.get("accessible_name"):
            continue
        idx = c.get("index")
        if c.get("nearby_text_has_numeric_or_currency"):
            findings.append(finding(
                title=f"Canvas #{idx} likely renders data with no text/accessibility equivalent",
                severity="high",
                evidence=(f"Canvas element (index {idx}, {c.get('bbox_area')}px², context {c.get('context_type')}) "
                          "has no fallback text and no accessible name/description, and the surrounding text "
                          "contains numeric or currency tokens suggesting the canvas is illustrating a real "
                          "figure. Canvas content is bitmap output with no default DOM or accessibility "
                          "representation — a fact rasterized to pixels is not recoverable by any DOM-, "
                          "accessibility-tree-, or rendered-HTML-based extraction method."),
                action_summary=("Render the same data as a real (visually-hidden if needed) HTML table or "
                                 "labeled text block alongside the canvas — treat the canvas as a visualization "
                                 "layer over data that also exists as text, not as the data's only home."),
                action_priority="high",
            ))
        else:
            findings.append(finding(
                title=f"Canvas #{idx} has no text/accessibility fallback",
                severity="medium",
                evidence=(f"Canvas element (index {idx}, {c.get('bbox_area')}px², context {c.get('context_type')}) "
                          "has no fallback text and no accessible name or description."),
                action_summary="Add an aria-label/aria-describedby or in-DOM fallback content describing what this canvas shows, even if it turns out to be decorative — this makes the intent explicit instead of ambiguous.",
                action_priority="low",
                beyond_defect=True,
            ))


def check_websocket_gated(ev, url, findings):
    net = ev.get("structural", {}).get("network", {})
    growth = net.get("post_settle_text_growth_chars", 0)
    ws = net.get("websocket_count", 0)
    sse = net.get("sse_count", 0)
    if (ws > 0 or sse > 0) and growth >= WS_MIN_TEXT_GROWTH:
        findings.append(finding(
            title="A live channel (WebSocket/SSE) is open and a large amount of text appears only after it settles",
            severity="high",
            evidence=(f"{ws} WebSocket connection(s) and {sse} SSE stream(s) were observed, and roughly {growth} "
                      "characters of visible text appeared between initial parse and post-settle — consistent "
                      "with (though not proof of) that text arriving over the live channel rather than in the "
                      "initial response. A non-JS-executing crawler never opens a WebSocket at all, so any fact "
                      "gated this way is categorically absent to it, not merely delayed."),
            action_summary=("Ship a server-rendered seed value for any fact currently sourced only from a "
                             "live channel, and use the socket exclusively to update it in place. Expose the "
                             "same fact through a plain request/response endpoint as a documented fallback."),
            action_priority="high",
        ))


def main():
    if len(sys.argv) < 3:
        print("Usage: python check_render_fidelity.py <evidence_json_path> <url>", file=sys.stderr)
        sys.exit(2)
    ev_path, url = sys.argv[1], sys.argv[2]
    with open(ev_path, "r", encoding="utf-8") as f:
        ev = json.load(f)

    findings = []
    check_csr_empty_shell(ev, url, findings)
    check_shadow_dom(ev, url, findings)
    check_canvas(ev, url, findings)
    check_websocket_gated(ev, url, findings)

    print(json.dumps(findings, ensure_ascii=False))


if __name__ == "__main__":
    main()
