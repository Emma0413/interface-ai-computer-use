import json
from pathlib import Path

EVIDENCE = Path("evidence")


def artifact_run_id() -> str:
    artifact = json.loads((EVIDENCE / "capability.json").read_text(encoding="utf-8"))
    return str(artifact["provenance"]["run_id"])


def result_run_ids() -> set[str]:
    names = ("genuine-replay-result.json", "genuine-not-found-result.json")
    return {
        str(json.loads((EVIDENCE / name).read_text(encoding="utf-8"))["run_id"]) for name in names
    }


def filter_jsonl(source: str, destination: str, run_ids: set[str]) -> None:
    rows = []
    for line in (EVIDENCE / source).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("run_id") in run_ids:
            rows.append(json.dumps(row, separators=(",", ":")))
    if not rows:
        raise RuntimeError(f"no matching events found in {source}")
    (EVIDENCE / destination).write_text("\n".join(rows) + "\n", encoding="utf-8")


filter_jsonl("discovery.jsonl", "genuine-discovery.jsonl", {artifact_run_id()})
filter_jsonl("replay.jsonl", "genuine-replay.jsonl", result_run_ids())
print("curated genuine discovery and replay JSONL evidence")
