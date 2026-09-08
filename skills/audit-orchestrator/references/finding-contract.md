# Finding contract (sub-skill output → orchestrator input)

Each `check_*.py` script prints a JSON array to stdout. Every element is one finding, in this
shape (the orchestrator adds `id` and folds these into the final report — sub-skills never
invent an `id`, so IDs stay globally unique and ordered):

```jsonc
{
  "title": "No JSON-LD structured data on product pages",
  "severity": "critical" | "high" | "medium" | "low",
  "category": "crawl-access" | "render-fidelity" | "structured-fact"
             | "corroboration-freshness" | "context-lock" | "orientation-engagement",
  "evidence": "Concrete, specific, reproducible: what was measured, on what page, what the number was.",
  "suggested_action": {
    "summary": "What to change and how.",
    "priority": "critical" | "high" | "medium" | "low"
  },
  "beyond_defect": false
}
```

- `beyond_defect: true` marks a proactive improvement suggested even though nothing broken was
  detected (the PS explicitly wants these). `severity` for a `beyond_defect` finding is always
  `"low"` — it is not a problem, so it must not inflate the critical/high/medium counts.
- `evidence` must always be concrete and falsifiable (a count, a byte length, a status code, a
  literal quoted string) — never a vibe. This is what keeps false-positive rate down and is
  explicitly graded.
- A script that finds nothing for its category prints `[]`. That is a valid, expected result on
  a healthy site — do not manufacture a finding to avoid an empty array.
