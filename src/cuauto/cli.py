from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .demo_app import serve
from .discovery import DiscoveryAgent, FakeDiscoveryModel, OpenAICompatibleModel
from .events import EventRecorder
from .handoff import LiveHandoffDemo, OperatorDecision
from .intervention import InterventionManager
from .models import ActionType, CapabilityArtifact
from .policy import AllowedTarget, PolicyConfig, PolicyEngine
from .replay import ReplayEngine
from .storage import ArtifactStore
from .surface import PlaywrightSurface

app = typer.Typer(no_args_is_help=True)


def demo_policy() -> PolicyEngine:
    return PolicyEngine(
        PolicyConfig(
            targets=(
                AllowedTarget(
                    scheme="http",
                    host="127.0.0.1",
                    port=8765,
                    route_prefixes=("/",),
                    allow_private=True,
                ),
            ),
            allowed_actions=frozenset(ActionType),
        )
    )


@app.command("serve-demo")
def serve_demo() -> None:
    """Start the synthetic localhost-only legacy app."""
    serve()


@app.command()
def validate(artifact: Annotated[Path, typer.Argument(exists=True)]) -> None:
    loaded = ArtifactStore(artifact.parent).load(artifact.name)
    demo_policy().check_url(str(loaded.base_url))
    for step in loaded.steps:
        demo_policy().check_action(step.action, step.risk)
    typer.echo(
        f"valid {loaded.capability_id} schema={loaded.schema_version} revision={loaded.revision}"
    )


@app.command()
def discover(
    goal: str = "Look up member M1001 and read the savings balance",
    target: str = "http://127.0.0.1:8765/",
    offline: bool = False,
    headful: bool = False,
    output: Path = Path("evidence/capability.json"),
    max_steps: int = typer.Option(10, min=1, max=30),
    timeout_seconds: int = typer.Option(180, min=10, max=900),
) -> None:
    policy, manager = demo_policy(), InterventionManager()
    surface = PlaywrightSurface(policy, headless=not headful)
    recorder = EventRecorder(Path("evidence/discovery.jsonl"), policy.config.pii_fields)
    try:
        model = FakeDiscoveryModel() if offline else OpenAICompatibleModel.from_env()
        selected_name = "offline-fake" if offline else getattr(model, "model", "unknown")
        artifact = DiscoveryAgent(model, surface, policy, recorder, manager).run(
            goal=goal,
            target=target,
            model_name=selected_name,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(artifact, CapabilityArtifact):
            typer.echo(f"escalated intervention={artifact}", err=True)
            raise typer.Exit(3)
        ArtifactStore(output.parent).save(output.name, artifact)
        typer.echo(f"saved {output} ({'OFFLINE FIXTURE' if offline else 'GENUINE MODEL'})")
    except typer.Exit:
        raise
    except RuntimeError as exc:
        typer.echo(f"discovery failed: {exc}", err=True)
        raise typer.Exit(4) from None
    finally:
        surface.close()


@app.command()
def replay(
    artifact: Annotated[Path, typer.Argument()] = Path("evidence/capability.json"),
    member_id: str = "M1001",
    headful: bool = False,
    result: Path = Path("evidence/replay-result.json"),
) -> None:
    policy, manager = demo_policy(), InterventionManager()
    loaded = ArtifactStore(artifact.parent).load(artifact.name)
    surface = PlaywrightSurface(policy, headless=not headful)
    try:
        outcome = ReplayEngine(
            surface,
            policy,
            EventRecorder(Path("evidence/replay.jsonl"), policy.config.pii_fields),
            manager,
            Path("evidence/runtime"),
        ).run(loaded, {"member_id": member_id})
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(outcome.model_dump_json(indent=2))
        if outcome.kind == "failure":
            raise typer.Exit(2)
    finally:
        surface.close()


@app.command("handoff-demo")
def handoff_demo(
    target: str = "http://127.0.0.1:8765/",
    result: Path = Path("evidence/live-handoff-result.json"),
) -> None:
    """Transfer one live headful browser session to a human and back."""
    policy, manager = demo_policy(), InterventionManager()
    surface = PlaywrightSurface(policy, headless=False)
    recorder = EventRecorder(Path("evidence/live-handoff.jsonl"), policy.config.pii_fields)

    def operator_prompt(_item: object, live_message: str) -> OperatorDecision:
        intervention = manager.current
        if intervention is None:
            raise RuntimeError("intervention disappeared before takeover")
        typer.echo(f"\n{live_message}")
        typer.echo(f"intervention: {intervention.intervention_id}")
        typer.echo(f"reason: {intervention.reason}")
        typer.echo(f"state: {intervention.sanitized_state}")
        typer.echo("Operate the open browser now. Return here when finished.")
        while True:
            decision = typer.prompt("Type resume or cancel").strip().lower()
            if decision in {"resume", "cancel"}:
                break
            typer.echo("Please type exactly 'resume' or 'cancel'.")
        note = typer.prompt("Short completion note", default="operator completed review")
        return OperatorDecision.model_validate({"action": decision, "note": note})

    try:
        outcome = LiveHandoffDemo(
            surface,
            policy,
            recorder,
            manager,
            Path("evidence/runtime"),
        ).run(target=target, operator=operator_prompt)
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(outcome.model_dump_json(indent=2))
        if outcome.kind == "failure":
            raise typer.Exit(2)
    finally:
        surface.close()


if __name__ == "__main__":
    app()
