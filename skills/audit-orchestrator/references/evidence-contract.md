# Shared evidence contract

`gather_evidence.py` fetches a target URL **once** (one raw HTTP fetch + one headless
render) and writes a single `evidence.json`. Every sub-skill's `check_*.py` script reads this
file instead of re-fetching, so the marketplace does one expensive crawl/render pass, not six.
Sub-skills that structurally need more than this (isolated multi-context fetches, extra
UA-specific requests) do that narrowly-scoped extra work themselves — see each skill's own
`SKILL.md`.

`gather_evidence.py` only **collects** signals. It applies no thresholds and makes no
severity judgments — that reasoning belongs in each sub-skill's script, per the required
progressive-disclosure split between `scripts/` (mechanical) and each skill's own checks.

## Top-level shape

```jsonc
{
  "schema_version": "1.0",
  "input_url": "https://example.com/page",
  "site": "example.com",
  "gathered_at": "2026-09-08T12:00:00Z",

  "robots": {
    "url": "https://example.com/robots.txt",
    "fetched": true,
    "status_code": 200,
    "content": "raw text, truncated to 20000 chars",
    "sitemap_urls": ["https://example.com/sitemap.xml"],
    "rules_by_agent": {
      "*": {"disallow": ["/admin"], "allow": []},
      "GPTBot": {"disallow": []},
      "ClaudeBot": {"disallow": []},
      "PerplexityBot": {"disallow": []},
      "Google-Extended": {"disallow": []},
      "CCBot": {"disallow": []},
      "Bingbot": {"disallow": []},
      "meta-externalagent": {"disallow": []}
    },
    "target_path_allowed": {"*": true, "GPTBot": true, "...": true}
  },

  "raw_fetch": {
    "user_agent": "GPTBot representative string",
    "status_code": 200,
    "final_url": "https://example.com/page",
    "redirect_chain": [{"url": "...", "status": 301}],
    "response_headers": {"content-type": "text/html; charset=utf-8", "...": "..."},
    "html_length": 12345,
    "text_content": "visible text extracted from the raw HTML only (script/style stripped)",
    "text_length": 456,
    "elapsed_ms": 120,
    "error": null
  },

  "rendered": {
    "status_code": 200,
    "final_url": "https://example.com/page",
    "html_length": 54321,
    "text_content": "document.body.innerText after network-idle + settle delay",
    "text_length": 3456,
    "dom_node_count": 1234,
    "title": "...",
    "meta_description": "...",
    "canonical": "...",
    "headings": [{"level": 1, "text": "..."}],
    "console_errors": ["..."],
    "elapsed_ms": 2200,
    "error": null
  },

  "structural": {
    "custom_elements": [
      {"tag": "product-card", "instance_count": 4, "dsd_template_present": false,
       "shadow_root_open": false, "shadow_text_length": 0,
       "host_light_dom_text_length": 6, "host_bbox_area": 148000}
    ],
    "canvases": [
      {"index": 0, "bbox_area": 240000, "context_type": "2d", "has_fallback_text": false,
       "accessible_name": null, "nearby_text_has_numeric_or_currency": true}
    ],
    "list_candidates": [
      {"container_hint": "ul.results > li", "initial_count": 24,
       "post_scroll_ids_added": 18, "post_scroll_count": 24,
       "stated_total_in_page_text": 500,
       "newly_revealed_hrefs": ["/item/847", "/item/848"]}
    ],
    "network": {
      "websocket_count": 0,
      "sse_count": 0,
      "xhr_fetch_count": 12,
      "post_settle_text_growth_chars": 340
    }
  },

  "structured_data": {
    "json_ld_blocks": [{"raw": "...", "parsed": {"...": "..."}, "parse_error": null}],
    "microdata_itemscope_count": 0,
    "open_graph": {"og:title": "...", "og:description": "...", "og:image": "..."},
    "twitter_card": {"twitter:card": "..."}
  },

  "links": {
    "internal_count": 40,
    "external_count": 6,
    "nav_present": true,
    "breadcrumb_present": false,
    "sample_internal": [{"href": "/products", "text": "Products"}]
  },

  "meta_identity": {
    "same_as": ["https://www.wikidata.org/wiki/Q000000"],
    "organization_schema_present": false
  },

  "errors": ["non-fatal collection errors go here"]
}
```

Every sub-skill script is invoked as `python check_X.py <path-to-evidence.json> [<url>]` and
prints a JSON array of findings to stdout (see `finding-contract.md` in this same folder).
