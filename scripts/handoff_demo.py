import argparse
from pathlib import Path

from cuauto.intervention import InterventionManager

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path)
args = parser.parse_args()
lines: list[str] = []


def emit(value: str) -> None:
    lines.append(value)
    print(value)


manager = InterventionManager()
item = manager.request(
    capability_id="lookup_savings_balance",
    session_id="demo-session",
    current_step="search",
    reason="operator decision requested",
    category="policy_block",
    sanitized_state="Member Search (fictional data only)",
)
emit("paused " + item.model_dump_json(exclude={"token"}))
human = manager.transfer_to_human(item.intervention_id, item.token, item.session_id)
emit(f"human owns same session {human.session_id} {human.state.value}")
resumed = manager.resume(
    item.intervention_id,
    item.token,
    item.session_id,
    "Operator reviewed the fictional record and requested resume.",
)
emit(f"automation resumed {resumed.session_id} {resumed.state.value}")
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
