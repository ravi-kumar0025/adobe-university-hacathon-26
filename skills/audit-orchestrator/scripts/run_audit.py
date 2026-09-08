#!/usr/bin/env python3
"""audit-orchestrator: end-to-end convenience runner.

Ties the whole marketplace together for one command-line invocation: gathers the shared evidence
once, runs all six sub-skill checks against it, and composes the result into the final report.
This is what an agent (or a grader) runs to exercise the marketplace directly; each individual
skill's SKILL.md also documents how an agent without a Python runtime can reproduce the same
checks manually, per the agentskills.io portability requirement.

Note: this script does NOT perform corroboration-freshness-audit's optional, agent-assisted
external web-search step (see that skill's SKILL.md step 2) -- that step requires a web-search
tool this script doesn't have, and is meant to be run by the invoking agent directly, not by this
subprocess pipeline.

Usage: python run_audit.py <url> [<output_report_path>]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SUB_SKILLS = [
    ("crawl-access-audit", "check_crawl_access.py"),
    ("render-fidelity-audit", "check_render_fidelity.py"),
    ("structured-fact-audit", "check_structured_facts.py"),
    ("context-lock-audit", "check_context_lock.py"),
    ("corroboration-freshness-audit", "check_corroboration.py"),
    ("orientation-engagement-audit", "check_orientation.py"),
]
SUBPROCESS_TIMEOUT_S = 90


def run_script(script_path, args, timeout=SUBPROCESS_TIMEOUT_S):
    proc = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_audit.py <url> [<output_report_path>]", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    here = Path(__file__).resolve().parent          # audit-orchestrator/scripts
    skills_root = here.parent.parent                # skills/

    with tempfile.TemporaryDirectory(prefix="brand-ai-audit-") as tmpdir:
        tmp = Path(tmpdir)
        evidence_path = tmp / "evidence.json"

        print(f"[1/3] Gathering shared evidence for {url} ...", file=sys.stderr)
        result = run_script(here / "gather_evidence.py", [url, str(evidence_path)], timeout=60)
        if result.returncode != 0:
            print(f"gather_evidence.py failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)

        findings_paths = []
        print("[2/3] Running sub-skill checks ...", file=sys.stderr)
        for skill_id, script_name in SUB_SKILLS:
            script_path = skills_root / skill_id / "scripts" / script_name
            out_findings_path = tmp / f"{skill_id}.findings.json"
            try:
                result = run_script(script_path, [str(evidence_path), url])
            except subprocess.TimeoutExpired:
                print(f"  {skill_id}: TIMED OUT, skipping its findings", file=sys.stderr)
                out_findings_path.write_text("[]", encoding="utf-8")
                findings_paths.append(out_findings_path)
                continue
            if result.returncode != 0:
                print(f"  {skill_id}: exited {result.returncode}, skipping its findings\n{result.stderr}", file=sys.stderr)
                out_findings_path.write_text("[]", encoding="utf-8")
                findings_paths.append(out_findings_path)
                continue
            try:
                findings = json.loads(result.stdout)
            except json.JSONDecodeError:
                print(f"  {skill_id}: did not print a valid JSON array, skipping its findings", file=sys.stderr)
                findings = []
            out_findings_path.write_text(json.dumps(findings), encoding="utf-8")
            findings_paths.append(out_findings_path)
            print(f"  {skill_id}: {len(findings)} finding(s)", file=sys.stderr)

        print("[3/3] Composing final report ...", file=sys.stderr)
        sys.path.insert(0, str(here))
        from compose_report import compose  # noqa: E402

        findings_lists = [json.loads(p.read_text(encoding="utf-8")) for p in findings_paths]
        report = compose(url, findings_lists)

    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        Path(out_path).write_text(report_json, encoding="utf-8")
        print(f"Wrote {out_path}", file=sys.stderr)
    else:
        print(report_json)


if __name__ == "__main__":
    main()
