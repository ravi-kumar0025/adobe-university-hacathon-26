#!/usr/bin/env python3
"""audit-orchestrator: compose sub-skill findings into the final, fixed-schema audit report.

Reads one or more JSON arrays of findings (the finding-contract.md shape -- no `id` yet) and
merges them into the single required report shape: assigns globally unique, severity-ordered IDs,
computes the counts-by-severity summary, and attaches site/audited_at metadata.

Usage: python compose_report.py <url> <output_report_path> <findings_json_path> [<findings_json_path> ...]
"""
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def compose(url, findings_lists):
    all_findings = []
    for lst in findings_lists:
        all_findings.extend(lst)

    def sort_key(f):
        return (SEVERITY_RANK.get(f.get("severity"), 9), 1 if f.get("beyond_defect") else 0)

    all_findings.sort(key=sort_key)

    findings_out = []
    for i, f in enumerate(all_findings, start=1):
        fid = f"F-{i:03d}"
        findings_out.append({
            "id": fid,
            "title": f.get("title"),
            "severity": f.get("severity"),
            "category": f.get("category"),
            "evidence": f.get("evidence"),
            "suggested_action": f.get("suggested_action"),
            "beyond_defect": bool(f.get("beyond_defect", False)),
        })

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings_out:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1

    report = {
        "site": urlparse(url).netloc or url,
        "audited_url": url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_findings": len(findings_out),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
        },
        "findings": findings_out,
    }
    return report


def main():
    if len(sys.argv) < 4:
        print("Usage: python compose_report.py <url> <output_report_path> <findings_json_path> [...]", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    out_path = sys.argv[2]
    findings_lists = []
    for path in sys.argv[3:]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                findings_lists.append(json.load(f))
        except Exception as e:  # noqa: BLE001
            print(f"Warning: could not read {path}: {e}", file=sys.stderr)

    report = compose(url, findings_lists)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
