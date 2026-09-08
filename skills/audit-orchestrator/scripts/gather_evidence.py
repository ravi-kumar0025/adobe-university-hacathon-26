#!/usr/bin/env python3
"""Shared evidence gatherer for the brand-ai-readiness-audit marketplace.

Fetches a target URL exactly once (one raw, non-JS-executing HTTP fetch and one
headless-rendered pass) and writes a single evidence.json that every sub-skill's
check_*.py script reads. This script only *collects* signals -- it makes no
severity judgments. See ../references/evidence-contract.md for the exact schema.

Usage:
    python gather_evidence.py <url> <output_json_path> [--timeout-ms N]

Dependencies: Python stdlib + Playwright (`pip install playwright && playwright
install chromium`). No other third-party packages, by design -- this keeps the
marketplace easy to run in an unfamiliar sandbox within the 5-minute budget.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

RAW_FETCH_UA = "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"
RENDER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
FETCH_TIMEOUT_S = 10
MAX_BODY_BYTES = 3_000_000
MAX_STORED_HTML_CHARS = 1_500_000

CURATED_AGENTS = ["*", "GPTBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot",
                  "Google-Extended", "CCBot", "Bingbot", "meta-externalagent"]


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------

def parse_robots_txt(text):
    """Small, line-based robots.txt parser -> {agent: {"disallow": [...], "allow": [...]}}.

    Handles the standard grouping rule: consecutive `User-agent:` lines belong to one
    group and share whatever Allow/Disallow lines follow, until the next `User-agent:`
    line that appears *after* at least one directive, which starts a new group.
    """
    blocks = {}
    sitemaps = []
    current_agents = []
    group_has_directives = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if group_has_directives or not current_agents:
                current_agents = [value]
                group_has_directives = False
            else:
                current_agents.append(value)
            blocks.setdefault(value, {"disallow": [], "allow": []})
        elif field in ("disallow", "allow") and current_agents:
            group_has_directives = True
            for a in current_agents:
                blocks.setdefault(a, {"disallow": [], "allow": []})
                if value != "":
                    blocks[a][field].append(value)
        elif field == "sitemap":
            sitemaps.append(value)
    return blocks, sitemaps


def path_allowed(path, rules):
    """Longest-match-wins robots.txt evaluation for a single agent's rule set."""
    if not rules:
        return True
    best_len = -1
    best_allow = True
    for pattern in rules.get("disallow", []):
        if pattern == "":
            continue
        if _pattern_matches(path, pattern) and len(pattern) > best_len:
            best_len = len(pattern)
            best_allow = False
    for pattern in rules.get("allow", []):
        if pattern == "":
            continue
        if _pattern_matches(path, pattern) and len(pattern) > best_len:
            best_len = len(pattern)
            best_allow = True
    return best_allow


def _pattern_matches(path, pattern):
    regex = re.escape(pattern).replace(r"\*", ".*")
    if pattern.endswith("$"):
        regex = re.escape(pattern[:-1]).replace(r"\*", ".*") + "$"
    else:
        regex = "^" + regex
    try:
        return re.match(regex, path) is not None
    except re.error:
        return path.startswith(pattern)


def fetch_robots(base_url, target_path):
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    result = {"url": robots_url, "fetched": False, "status_code": None, "content": "",
              "sitemap_urls": [], "rules_by_agent": {}, "target_path_allowed": {}}
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": RAW_FETCH_UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            body = resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
            result["fetched"] = True
            result["status_code"] = resp.status
            result["content"] = body[:20000]
            blocks, sitemaps = parse_robots_txt(body)
            result["sitemap_urls"] = sitemaps
            for agent in CURATED_AGENTS:
                rules = blocks.get(agent) or blocks.get("*") or {"disallow": [], "allow": []}
                result["rules_by_agent"][agent] = rules
                result["target_path_allowed"][agent] = path_allowed(target_path or "/", rules)
    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
        # No robots.txt (404) conventionally means "everything allowed".
        for agent in CURATED_AGENTS:
            result["rules_by_agent"][agent] = {"disallow": [], "allow": []}
            result["target_path_allowed"][agent] = True
    except Exception as e:  # noqa: BLE001 - collection must never crash the audit
        result["error"] = str(e)
        for agent in CURATED_AGENTS:
            result["target_path_allowed"][agent] = True
    return result


# --------------------------------------------------------------------------
# Raw (non-JS-executing) fetch
# --------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Pulls visible text out of raw HTML the way a non-rendering crawler effectively would."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self.chunks.append(stripped)

    def text(self):
        return " ".join(self.chunks)


def extract_visible_text(html):
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass
    return parser.text()


JSON_LD_RE = re.compile(
    r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
DSD_TEMPLATE_RE = re.compile(r'<template[^>]*\bshadowroot(mode)?\s*=', re.IGNORECASE)


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({"url": newurl, "status": code})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_raw(url):
    result = {"user_agent": RAW_FETCH_UA, "status_code": None, "final_url": url,
              "redirect_chain": [], "response_headers": {}, "html_length": 0,
              "text_content": "", "text_length": 0, "elapsed_ms": 0, "error": None,
              "json_ld_raw": [], "dsd_template_present": False, "html": ""}
    start = time.time()
    recorder = _RedirectRecorder()
    opener = urllib.request.build_opener(recorder)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": RAW_FETCH_UA, "Accept": "text/html,application/xhtml+xml"},
        )
        with opener.open(req, timeout=FETCH_TIMEOUT_S) as resp:
            body_bytes = resp.read(MAX_BODY_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
            html = body_bytes.decode(charset, errors="replace")
            result["status_code"] = resp.status
            result["final_url"] = resp.geturl()
            result["response_headers"] = dict(resp.headers.items())
            result["redirect_chain"] = recorder.chain
            result["html_length"] = len(html)
            result["html"] = html[:MAX_STORED_HTML_CHARS]
            text = extract_visible_text(html)
            result["text_content"] = text[:50000]
            result["text_length"] = len(text)
            result["json_ld_raw"] = [m.strip() for m in JSON_LD_RE.findall(html)]
            result["dsd_template_present"] = bool(DSD_TEMPLATE_RE.search(html))
    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
        result["error"] = f"HTTPError: {e.code} {e.reason}"
        result["redirect_chain"] = recorder.chain
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    result["elapsed_ms"] = int((time.time() - start) * 1000)
    return result


# --------------------------------------------------------------------------
# Rendered (headless browser) pass
# --------------------------------------------------------------------------

BATCH_EVALUATE_JS = r"""
() => {
  const meta = document.querySelector('meta[name="description" i]');
  const canon = document.querySelector('link[rel="canonical" i]');
  const heads = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(h => ({
    level: parseInt(h.tagName[1], 10), text: (h.innerText || '').trim().slice(0, 200)
  }));
  const og = {};
  document.querySelectorAll('meta[property^="og:" i]').forEach(m => {
    og[m.getAttribute('property')] = m.getAttribute('content');
  });
  const tw = {};
  document.querySelectorAll('meta[name^="twitter:" i]').forEach(m => {
    tw[m.getAttribute('name')] = m.getAttribute('content');
  });
  const jsonLdRaw = Array.from(document.querySelectorAll('script[type="application/ld+json" i]'))
    .map(s => s.textContent || '');
  const microdataCount = document.querySelectorAll('[itemscope]').length;
  const navPresent = !!document.querySelector('nav, [role="navigation" i]');
  const breadcrumbPresent = !!document.querySelector(
    '[class*="breadcrumb" i], [aria-label*="breadcrumb" i], nav[aria-label*="breadcrumb" i]'
  );
  const linksAll = Array.from(document.querySelectorAll('a[href]'));
  const origin = location.origin;
  let internal = 0, external = 0;
  const sampleInternal = [];
  for (const a of linksAll) {
    let href = a.getAttribute('href') || '';
    let isInternal = true;
    try {
      const u = new URL(href, location.href);
      isInternal = (u.origin === origin);
    } catch (e) { isInternal = true; }
    if (isInternal) {
      internal++;
      if (sampleInternal.length < 40) {
        // Fall back to aria-label/title when innerText is empty -- a visually-hidden
        // accessible label (a common, *good* pattern for icon-only links) is real information
        // scent even though it renders no visible text, and treating it as "generic/empty"
        // would be a false positive against a legitimate accessibility technique.
        const text = (a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '').trim();
        sampleInternal.push({ href, text: text.slice(0, 100) });
      }
    } else {
      external++;
    }
  }
  return {
    meta_description: meta ? meta.getAttribute('content') : null,
    canonical: canon ? canon.getAttribute('href') : null,
    headings: heads,
    og, twitter: tw,
    json_ld_raw: jsonLdRaw,
    microdata_itemscope_count: microdataCount,
    nav_present: navPresent,
    breadcrumb_present: breadcrumbPresent,
    internal_count: internal,
    external_count: external,
    sample_internal: sampleInternal,
    dom_node_count: document.getElementsByTagName('*').length,
  };
}
"""

CUSTOM_ELEMENTS_JS = r"""
() => {
  const all = Array.from(document.querySelectorAll('*'));
  const seen = {};
  for (const el of all) {
    const tag = el.tagName.toLowerCase();
    if (tag.indexOf('-') === -1) continue;
    if (!seen[tag]) seen[tag] = el;
  }
  const results = [];
  for (const tag of Object.keys(seen)) {
    const el = seen[tag];
    const rect = el.getBoundingClientRect();
    let shadowOpen = false, shadowTextLen = 0;
    if (el.shadowRoot) {
      shadowOpen = true;
      shadowTextLen = (el.shadowRoot.textContent || '').trim().length;
    }
    results.push({
      tag,
      instance_count: document.querySelectorAll(tag).length,
      shadow_root_open: shadowOpen,
      shadow_text_length: shadowTextLen,
      host_light_dom_text_length: (el.textContent || '').trim().length,
      host_bbox_area: Math.round(rect.width * rect.height),
    });
  }
  return results.slice(0, 60);
}
"""

CANVAS_JS = r"""
() => {
  const canvases = Array.from(document.querySelectorAll('canvas'));
  return canvases.slice(0, 30).map((c, i) => {
    const rect = c.getBoundingClientRect();
    let ctxType = 'unknown';
    try {
      if (c.getContext('2d', { willReadFrequently: false })) ctxType = '2d';
    } catch (e) { /* ignore */ }
    if (ctxType === 'unknown') {
      try { if (c.getContext('webgl') || c.getContext('webgl2')) ctxType = 'webgl'; } catch (e) { /* ignore */ }
    }
    const fallbackText = (c.textContent || '').trim();
    const ariaLabel = c.getAttribute('aria-label') || c.getAttribute('aria-describedby');
    let nearbyText = '';
    let parent = c.parentElement;
    if (parent) nearbyText = (parent.innerText || '').slice(0, 400);
    const hasNumeric = /[$€£]|\d+[\d,.]*\s*(%|percent)?/.test(nearbyText);
    return {
      index: i,
      bbox_area: Math.round(rect.width * rect.height),
      context_type: ctxType,
      has_fallback_text: fallbackText.length > 0,
      accessible_name: ariaLabel || null,
      nearby_text_has_numeric_or_currency: hasNumeric,
    };
  });
}
"""

LIST_CANDIDATES_JS = r"""
() => {
  const all = Array.from(document.querySelectorAll('body *'));
  const candidates = [];
  for (const el of all) {
    const children = Array.from(el.children);
    if (children.length < 6) continue;
    const tagCounts = {};
    for (const c of children) tagCounts[c.tagName] = (tagCounts[c.tagName] || 0) + 1;
    const maxTag = Object.keys(tagCounts).reduce((a, b) => (tagCounts[a] > tagCounts[b] ? a : b));
    if (tagCounts[maxTag] / children.length >= 0.8) {
      candidates.push(el);
    }
  }
  candidates.sort((a, b) => b.children.length - a.children.length);
  const top = candidates.slice(0, 4);
  top.forEach((el, i) => el.setAttribute('data-audit-list-candidate', String(i)));
  const idOf = (c) => c.id || c.getAttribute('data-id') || c.getAttribute('data-key')
    || (c.querySelector('a[href]') ? c.querySelector('a[href]').getAttribute('href') : null);
  const hrefOf = (c) => {
    const a = c.matches('a[href]') ? c : c.querySelector('a[href]');
    return a ? a.getAttribute('href') : null;
  };
  return top.map((el, i) => ({
    index: i,
    initial_count: el.children.length,
    initial_ids: Array.from(el.children).map(idOf).filter(Boolean).slice(0, 400),
    initial_hrefs: Array.from(el.children).map(hrefOf).filter(Boolean).slice(0, 400),
  }));
}
"""

SCROLL_TRIGGER_JS_TEMPLATE = r"""
() => {
  const el = document.querySelector('[data-audit-list-candidate="%d"]');
  window.scrollTo(0, document.body.scrollHeight);
  // Also walk up from the candidate looking for an internally-scrollable ancestor
  // (the far more common real-world pattern: a fixed-height panel with overflow-y:auto,
  // not a page-length list keyed off window scroll).
  let node = el;
  for (let i = 0; node && i < 6; i++, node = node.parentElement) {
    if (node.scrollHeight > node.clientHeight + 4) {
      node.scrollTop = node.scrollHeight;
    }
  }
  if (el) el.dispatchEvent(new Event('scroll', { bubbles: true }));
}
"""

RESAMPLE_JS_TEMPLATE = r"""
() => {
  const el = document.querySelector('[data-audit-list-candidate="%d"]');
  if (!el) return null;
  const idOf = (c) => c.id || c.getAttribute('data-id') || c.getAttribute('data-key')
    || (c.querySelector('a[href]') ? c.querySelector('a[href]').getAttribute('href') : null);
  const hrefOf = (c) => {
    const a = c.matches('a[href]') ? c : c.querySelector('a[href]');
    return a ? a.getAttribute('href') : null;
  };
  return {
    count: el.children.length,
    ids: Array.from(el.children).map(idOf).filter(Boolean).slice(0, 400),
    hrefs: Array.from(el.children).map(hrefOf).filter(Boolean).slice(0, 400),
  };
}
"""

STATED_TOTAL_RE = re.compile(
    r'\b(\d[\d,]{1,9})\s+(?:results|items|products|listings|entries|total)\b|'
    r'\b(?:of|/)\s*(\d[\d,]{1,9})\b',
    re.IGNORECASE,
)


def extract_stated_total(text):
    best = None
    for m in STATED_TOTAL_RE.finditer(text or ""):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        if raw.isdigit():
            n = int(raw)
            if best is None or n > best:
                best = n
    return best


def render_page(url, timeout_ms):
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    result = {
        "status_code": None, "final_url": url, "html_length": 0, "html": "",
        "text_content": "", "text_length": 0, "dom_node_count": 0, "title": "",
        "meta_description": None, "canonical": None, "headings": [], "console_errors": [],
        "elapsed_ms": 0, "error": None,
        "custom_elements": [], "canvases": [], "list_candidates": [],
        "network": {"websocket_count": 0, "sse_count": 0, "xhr_fetch_count": 0,
                    "post_settle_text_growth_chars": 0},
        "og": {}, "twitter": {}, "json_ld_raw": [], "microdata_itemscope_count": 0,
        "nav_present": False, "breadcrumb_present": False,
        "internal_count": 0, "external_count": 0, "sample_internal": [],
    }
    start = time.time()
    console_errors = []
    counters = {"ws": 0, "sse": 0, "xhrfetch": 0}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            context = browser.new_context(user_agent=RENDER_UA, viewport={"width": 1366, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("websocket", lambda ws: counters.__setitem__("ws", counters["ws"] + 1))

            def on_response(resp):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "text/event-stream" in ct:
                        counters["sse"] += 1
                except Exception:  # noqa: BLE001
                    pass

            page.on("response", on_response)

            def on_request(req):
                if req.resource_type in ("xhr", "fetch"):
                    counters["xhrfetch"] += 1

            page.on("request", on_request)

            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            text_at_dcl = page.evaluate("document.body ? document.body.innerText.length : 0")
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
            except PWTimeout:
                pass
            page.wait_for_timeout(1200)

            if resp is not None:
                result["status_code"] = resp.status
                result["final_url"] = resp.url

            html = page.content()
            result["html_length"] = len(html)
            result["html"] = html[:MAX_STORED_HTML_CHARS]
            text = page.evaluate("document.body ? document.body.innerText : ''")
            result["text_content"] = text[:50000]
            result["text_length"] = len(text)
            result["network"]["post_settle_text_growth_chars"] = max(0, len(text) - text_at_dcl)
            result["title"] = page.title()

            batch = page.evaluate(BATCH_EVALUATE_JS)
            result["meta_description"] = batch["meta_description"]
            result["canonical"] = batch["canonical"]
            result["headings"] = batch["headings"]
            result["og"] = batch["og"]
            result["twitter"] = batch["twitter"]
            result["json_ld_raw"] = batch["json_ld_raw"]
            result["microdata_itemscope_count"] = batch["microdata_itemscope_count"]
            result["nav_present"] = batch["nav_present"]
            result["breadcrumb_present"] = batch["breadcrumb_present"]
            result["internal_count"] = batch["internal_count"]
            result["external_count"] = batch["external_count"]
            result["sample_internal"] = batch["sample_internal"]
            result["dom_node_count"] = batch["dom_node_count"]

            result["custom_elements"] = page.evaluate(CUSTOM_ELEMENTS_JS)
            result["canvases"] = page.evaluate(CANVAS_JS)

            list_candidates = page.evaluate(LIST_CANDIDATES_JS)
            stated_total = extract_stated_total(text)
            for cand in list_candidates:
                idx = cand["index"]
                try:
                    page.evaluate(SCROLL_TRIGGER_JS_TEMPLATE % idx)
                    page.wait_for_timeout(350)
                    page.evaluate(SCROLL_TRIGGER_JS_TEMPLATE % idx)
                    page.wait_for_timeout(500)
                    resample = page.evaluate(RESAMPLE_JS_TEMPLATE % idx)
                except Exception:  # noqa: BLE001
                    resample = None
                initial_ids = set(cand["initial_ids"])
                new_id_set = set((resample or {}).get("ids", [])) - initial_ids
                added = len(new_id_set)
                # Sample newly-revealed per-item hrefs (tracked independently of the identity
                # field above, since an element can have both an id and a permalink -- the id
                # would otherwise shadow the href in idOf's priority order).
                initial_hrefs = set(cand.get("initial_hrefs", []))
                new_hrefs = set((resample or {}).get("hrefs", [])) - initial_hrefs
                newly_revealed_hrefs = sorted(new_hrefs)[:5]
                result["list_candidates"].append({
                    "container_hint": f"candidate-{idx} ({cand['initial_count']} children)",
                    "initial_count": cand["initial_count"],
                    "post_scroll_ids_added": added,
                    "post_scroll_count": (resample or {}).get("count", cand["initial_count"]),
                    "stated_total_in_page_text": stated_total,
                    "newly_revealed_hrefs": newly_revealed_hrefs,
                })

            result["network"]["websocket_count"] = counters["ws"]
            result["network"]["sse_count"] = counters["sse"]
            result["network"]["xhr_fetch_count"] = counters["xhrfetch"]
            result["console_errors"] = console_errors[:40]

            context.close()
            browser.close()
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    result["elapsed_ms"] = int((time.time() - start) * 1000)
    return result


# --------------------------------------------------------------------------
# Structured-data / links / identity assembly
# --------------------------------------------------------------------------

def try_parse_json(raw):
    try:
        return json.loads(raw), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def extract_same_as(parsed_blocks):
    same_as = []
    org_present = False

    def walk(node):
        nonlocal org_present
        if isinstance(node, dict):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "organization" for x in types if x):
                org_present = True
            sa = node.get("sameAs")
            if isinstance(sa, str):
                same_as.append(sa)
            elif isinstance(sa, list):
                same_as.extend([s for s in sa if isinstance(s, str)])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in parsed_blocks:
        if block is not None:
            walk(block)
    return list(dict.fromkeys(same_as)), org_present


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def gather(url, timeout_ms=20000):
    parsed = urlparse(url)
    site = parsed.netloc

    raw = fetch_raw(url)
    robots = fetch_robots(url, parsed.path or "/")
    rendered = render_page(url, timeout_ms)

    raw_ld_parsed = [try_parse_json(b)[0] for b in raw.get("json_ld_raw", [])]
    rendered_ld_parsed = [try_parse_json(b)[0] for b in rendered.get("json_ld_raw", [])]
    same_as, org_present = extract_same_as(raw_ld_parsed + rendered_ld_parsed)

    evidence = {
        "schema_version": "1.0",
        "input_url": url,
        "site": site,
        "gathered_at": datetime.now(timezone.utc).isoformat(),
        "robots": robots,
        "raw_fetch": {
            "user_agent": raw["user_agent"],
            "status_code": raw["status_code"],
            "final_url": raw["final_url"],
            "redirect_chain": raw["redirect_chain"],
            "response_headers": raw["response_headers"],
            "html_length": raw["html_length"],
            "html": raw["html"],
            "text_content": raw["text_content"],
            "text_length": raw["text_length"],
            "elapsed_ms": raw["elapsed_ms"],
            "error": raw["error"],
            "json_ld_raw": raw["json_ld_raw"],
            "json_ld_parsed": [try_parse_json(b)[0] for b in raw["json_ld_raw"]],
            "dsd_template_present": raw["dsd_template_present"],
        },
        "rendered": {
            "status_code": rendered["status_code"],
            "final_url": rendered["final_url"],
            "html_length": rendered["html_length"],
            "html": rendered["html"],
            "text_content": rendered["text_content"],
            "text_length": rendered["text_length"],
            "dom_node_count": rendered["dom_node_count"],
            "title": rendered["title"],
            "meta_description": rendered["meta_description"],
            "canonical": rendered["canonical"],
            "headings": rendered["headings"],
            "console_errors": rendered["console_errors"],
            "elapsed_ms": rendered["elapsed_ms"],
            "error": rendered["error"],
        },
        "structural": {
            "custom_elements": rendered["custom_elements"],
            "canvases": rendered["canvases"],
            "list_candidates": rendered["list_candidates"],
            "network": rendered["network"],
            "dsd_template_present_in_raw_html": raw["dsd_template_present"],
        },
        "structured_data": {
            "raw_json_ld": [{"raw": b, "parsed": try_parse_json(b)[0], "parse_error": try_parse_json(b)[1]}
                            for b in raw["json_ld_raw"]],
            "rendered_json_ld": [{"raw": b, "parsed": try_parse_json(b)[0], "parse_error": try_parse_json(b)[1]}
                                 for b in rendered["json_ld_raw"]],
            "microdata_itemscope_count": rendered.get("microdata_itemscope_count", 0),
            "open_graph": rendered.get("og", {}),
            "twitter_card": rendered.get("twitter", {}),
        },
        "links": {
            "internal_count": rendered.get("internal_count", 0),
            "external_count": rendered.get("external_count", 0),
            "nav_present": rendered.get("nav_present", False),
            "breadcrumb_present": rendered.get("breadcrumb_present", False),
            "sample_internal": rendered.get("sample_internal", []),
        },
        "meta_identity": {
            "same_as": same_as,
            "organization_schema_present": org_present,
        },
        "errors": [e for e in [raw.get("error"), rendered.get("error"), robots.get("error")] if e],
    }
    return evidence


def main():
    if len(sys.argv) < 3:
        print("Usage: python gather_evidence.py <url> <output_json_path> [--timeout-ms N]", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    out_path = sys.argv[2]
    timeout_ms = 20000
    if "--timeout-ms" in sys.argv:
        idx = sys.argv.index("--timeout-ms")
        timeout_ms = int(sys.argv[idx + 1])

    evidence = gather(url, timeout_ms=timeout_ms)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
