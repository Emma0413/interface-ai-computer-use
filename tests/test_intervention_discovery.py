from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeSurface

from cuauto.discovery import DiscoveryAgent, ModelProvider
from cuauto.events import EventRecorder
from cuauto.intervention import ControlState, InterventionError, InterventionManager
from cuauto.models import ModelAction


def test_pause_same_session_and_resume():
    manager = InterventionManager()
    item = manager.request(
        capability_id="c",
        session_id="s",
        current_step="x",
        reason="stuck",
        category="loop",
        sanitized_state="safe",
    )
    with pytest.raises(InterventionError):
        manager.ensure_automation("s")
    human = manager.transfer_to_human(item.intervention_id, item.token, "s")
    assert human.state == ControlState.HUMAN_ACTIVE and human.session_id == item.session_id
    resumed = manager.resume(item.intervention_id, item.token, "s", "clicked continue")
    assert (
        resumed.state == ControlState.AUTOMATION_ACTIVE
        and resumed.acknowledgement == "clicked continue"
    )
    manager.ensure_automation("s")
    with pytest.raises(InterventionError):
        manager.resume(item.intervention_id, item.token, "s", "again")


def test_cross_session_cancel_and_expiry():
    manager = InterventionManager()
    item = manager.request(
        capability_id="c",
        session_id="s",
        current_step=None,
        reason="x",
        category="x",
        sanitized_state="x",
    )
    with pytest.raises(InterventionError):
        manager.transfer_to_human(item.intervention_id, item.token, "other")
    cancelled = manager.cancel(item.intervention_id, item.token, "s", "operator cancelled")
    assert cancelled.state == ControlState.CANCELLED
    manager = InterventionManager()
    item = manager.request(
        capability_id="c",
        session_id="s",
        current_step=None,
        reason="x",
        category="x",
        sanitized_state="x",
    )
    manager._current = item.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    with pytest.raises(InterventionError):
        manager.transfer_to_human(item.intervention_id, item.token, "s")


class LoopModel(ModelProvider):
    def decide(self, **kwargs):
        return ModelAction(
            action="fill",
            rationale="repeat",
            locators=({"strategy": "label", "value": "Member number"},),
            value={"param": "member_id"},
        )


class HistoryModel(ModelProvider):
    def __init__(self):
        self.observations = []

    def decide(self, **kwargs):
        self.observations.append(kwargs["observation"])
        if len(self.observations) == 1:
            return ModelAction.model_validate(
                {
                    "action": "fill",
                    "rationale": "fill once",
                    "locators": [{"strategy": "label", "value": "Member number"}],
                    "value": {"param": "member_id"},
                }
            )
        return ModelAction.model_validate({"action": "escalate", "rationale": "test complete"})


def test_discovery_supplies_bounded_success_history(tmp_path, policy):
    manager, surface, model = InterventionManager(), FakeSurface(), HistoryModel()
    DiscoveryAgent(model, surface, policy, EventRecorder(tmp_path / "log"), manager).run(
        goal="x", target="http://127.0.0.1:8765/", max_steps=3
    )
    assert model.observations[1]["prior_successful_actions"] == [
        {"step_id": "step_1", "action": "fill", "outcome": "executed"}
    ]


def test_stuck_loop_escalates(tmp_path, policy):
    manager = InterventionManager()
    surface = FakeSurface()
    result = DiscoveryAgent(
        LoopModel(), surface, policy, EventRecorder(tmp_path / "log"), manager
    ).run(goal="x", target="http://127.0.0.1:8765/", max_steps=8)
    assert isinstance(result, str) and manager.current.state == ControlState.PAUSING


class InjectionModel(ModelProvider):
    def decide(self, **kwargs):
        return ModelAction(
            action="navigate", rationale="page asked", destination="http://evil.example/"
        )


def test_prompt_injection_cannot_expand_target(tmp_path, policy):
    manager = InterventionManager()
    surface = FakeSurface()
    result = DiscoveryAgent(
        InjectionModel(), surface, policy, EventRecorder(tmp_path / "log"), manager
    ).run(goal="x", target="http://127.0.0.1:8765/", max_steps=2)
    assert isinstance(result, str)


class RepairModel(ModelProvider):
    def __init__(self):
        self.calls = 0

    def decide(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ModelAction.model_validate(
                {
                    "action": "click",
                    "rationale": "bad target",
                    "locators": [{"strategy": "text", "value": "Missing"}],
                }
            )
        return ModelAction.model_validate({"action": "escalate", "rationale": "bounded test stop"})


def test_discovery_feeds_back_rejected_locator(tmp_path, policy):
    from conftest import FakeSurface

    class MissingAfterNavigate(FakeSurface):
        def act(self, step, value=None):
            if step.action.value == "navigate":
                original, self.failure = self.failure, None
                try:
                    return super().act(step, value)
                finally:
                    self.failure = original
            return super().act(step, value)

    surface = MissingAfterNavigate(failure="missing")
    manager, model = InterventionManager(), RepairModel()
    result = DiscoveryAgent(model, surface, policy, EventRecorder(tmp_path / "log"), manager).run(
        goal="x", target="http://127.0.0.1:8765/", max_steps=3
    )
    assert isinstance(result, str) and model.calls == 2
    assert "discovery_action_rejected" in (tmp_path / "log").read_text()


class ExtractionModel(ModelProvider):
    def decide(self, **kwargs):
        return ModelAction.model_validate(
            {
                "action": "extract",
                "rationale": "read balance",
                "locators": [{"strategy": "row_value", "value": "Savings balance"}],
                "output": {
                    "output": "savings_balance",
                    "value_type": "decimal",
                    "pattern": "[$,]",
                },
            }
        )


def test_successful_extraction_establishes_verified_checkpoint(tmp_path, policy):
    from conftest import FakeSurface

    class DetailSurface(FakeSurface):
        def act(self, step, value=None):
            result = super().act(step, value)
            if step.action.value == "navigate":
                self.stage = "detail"
            return result

    surface = DetailSurface()
    artifact = DiscoveryAgent(
        ExtractionModel(), surface, policy, EventRecorder(tmp_path / "log"), InterventionManager()
    ).run(goal="x", target="http://127.0.0.1:8765/", max_steps=2)
    assert not isinstance(artifact, str)
    assert artifact.checkpoint.value == "Savings balance"
