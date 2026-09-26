from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import FakeSurface

from cuauto.events import EventRecorder
from cuauto.handoff import LiveHandoffDemo, OperatorDecision
from cuauto.intervention import ControlState, InterventionError, InterventionManager
from cuauto.policy import PolicyEngine


def test_live_handoff_retains_session_and_revalidates(tmp_path: Path, policy: PolicyEngine) -> None:
    surface = FakeSurface()
    manager = InterventionManager()
    event_path = tmp_path / "handoff.jsonl"
    session_before = surface.session_id

    def operate(item: object, message: str) -> OperatorDecision:
        assert "same session" in message
        assert surface.session_id == session_before
        assert manager.current is not None
        assert manager.current.state == ControlState.HUMAN_ACTIVE
        with pytest.raises(InterventionError, match="does not own"):
            manager.ensure_automation(session_before)
        surface.stage = "detail"
        return OperatorDecision(action="resume", note="reviewed member record")

    outcome = LiveHandoffDemo(
        surface,
        policy,
        EventRecorder(event_path),
        manager,
        tmp_path,
    ).run(target="http://127.0.0.1:8765/", operator=operate)

    assert outcome.kind == "resumed"
    assert outcome.session_ref == hashlib.sha256(session_before.encode()).hexdigest()[:20]
    assert outcome.resumed_fingerprint == surface.observe().fingerprint
    assert surface.calls == ["navigate"]
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "automation_paused",
        "control_transferred",
        "automation_resumed",
    ]
    assert {event["session_id"] for event in events} == {outcome.session_ref}
    assert all(event["session_id"] != "[REDACTED]" for event in events)


def test_live_handoff_cancellation(tmp_path: Path, policy: PolicyEngine) -> None:
    manager = InterventionManager()
    outcome = LiveHandoffDemo(
        FakeSurface(),
        policy,
        EventRecorder(tmp_path / "handoff.jsonl"),
        manager,
        tmp_path,
    ).run(
        target="http://127.0.0.1:8765/",
        operator=lambda _item, _message: OperatorDecision(
            action="cancel", note="operator stopped the run"
        ),
    )

    assert outcome.kind == "cancelled"
    assert manager.current is not None
    assert manager.current.state == ControlState.CANCELLED


def test_live_handoff_browser_closure_fails_terminally(
    tmp_path: Path, policy: PolicyEngine
) -> None:
    class ClosedAfterTakeover(FakeSurface):
        observations = 0

        def observe(self):  # type: ignore[no-untyped-def]
            self.observations += 1
            if self.observations > 1:
                raise RuntimeError("browser closed")
            return super().observe()

    manager = InterventionManager()
    outcome = LiveHandoffDemo(
        ClosedAfterTakeover(),
        policy,
        EventRecorder(tmp_path / "handoff.jsonl"),
        manager,
        tmp_path,
    ).run(
        target="http://127.0.0.1:8765/",
        operator=lambda _item, _message: OperatorDecision(action="resume"),
    )

    assert outcome.kind == "failure"
    assert outcome.error == "session revalidation failed: RuntimeError"
    assert manager.current is not None
    assert manager.current.state == ControlState.FAILED
