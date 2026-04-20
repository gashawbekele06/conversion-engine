"""Evidence-graph validator.

Walks `memo_evidence_graph.json` (written in Act V) and confirms every
numeric claim resolves to a trace row or a published reference. For the
interim submission we include a minimal scaffold so the Act V script
can be wired quickly on Day 5.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def validate(graph_path: Path | str) -> dict[str, Any]:
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    trace_path = ROOT / "eval" / "traces" / "trace_log.jsonl"
    trace_ids = set()
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                trace_ids.add(json.loads(line)["trace_id"])
            except Exception:
                pass

    issues: list[str] = []
    for claim_id, claim in graph.get("claims", {}).items():
        source = claim.get("source_ref", "")
        if source.startswith("trace:"):
            if source.split(":", 1)[1] not in trace_ids:
                issues.append(f"{claim_id} → unknown trace_id {source}")
        elif source.startswith("pub:"):
            continue
        else:
            issues.append(f"{claim_id} → source_ref must start with trace: or pub:")

    return {"ok": not issues, "issues": issues,
            "n_claims": len(graph.get("claims", {})), "n_traces": len(trace_ids)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: evidence_graph.py <graph.json>", file=sys.stderr)
        sys.exit(2)
    out = validate(sys.argv[1])
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["ok"] else 1)
