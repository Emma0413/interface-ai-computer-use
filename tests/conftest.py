from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cuauto.events import EventRecorder
from cuauto.intervention import InterventionManager
from cuauto.models import CapabilityArtifact, Condition, Observation, Step
from cuauto.policy import AllowedTarget, PolicyConfig, PolicyEngine
from cuauto.surface import AmbiguousControl, MissingControl, SurfaceAdapter, SurfaceTimeout


class FakeSurface(SurfaceAdapter):
    def __init__(self, member: str = "M1001", failure: str | None = None):
        self.member, self.failure, self.stage, self.calls = member, failure, "blank", []
        self.failures = 0

    @property
    def session_id(self) -> str:
        return "session-fixed"

    def observe(self) -> Observation:
        texts = {
            "blank": "",
            "search": "Member Search Search members",
            "results": "Search results Open member",
            "detail": "Member record Savings balance $1,245.67",
            "not_found": "No member found",
            "expired": "Session expired authentication required",
            "denied": "Permission denied",
            "app_error": "Application error",
        }
        text = texts[self.stage]
        return Observation(
            url="http://127.0.0.1:8765/",
            title=self.stage,
            text=text,
            controls=(),
            fingerprint=hashlib.sha256(text.encode()).hexdigest(),
        )

    def act(self, step: Step, value: str | None = None) -> str | None:
        self.calls.append(step.action.value)
        if self.failure == "ambiguous":
            raise AmbiguousControl("two matches")
        if self.failure == "missing":
            raise MissingControl("zero matches")
        if self.failure == "timeout" and step.id == "search" and self.failures == 0:
            self.failures += 1
            raise SurfaceTimeout("slow")
        if step.action.value == "navigate":
            self.stage = "search"
        elif step.action.value == "fill":
            self.member = value or ""
        elif step.action.value == "click":
            if self.stage == "search":
                self.stage = "results" if self.member == "M1001" else "not_found"
            elif self.stage == "results":
                self.stage = "detail"
        elif step.action.value == "extract":
            if self.failure == "bad_output":
                return "not money"
            return "$1,245.67"
        return None

    def check(self, condition: Condition) -> bool:
        if condition.kind == "text_present":
            return condition.value in self.observe().text
        return True

    def wait(self, condition: Condition, timeout_ms: int) -> None:
        return None

    def capture(self, path: Path, *, screenshot: bool) -> tuple[str, ...]:
        return (str(path / "dom.txt"),)

    def expose_live_session(self) -> str:
        return "same session"

    def close(self) -> None:
        return None


@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine(
        PolicyConfig(
            targets=(
                AllowedTarget(scheme="http", host="127.0.0.1", port=8765, allow_private=True),
            ),
            allowed_actions=frozenset(
                {
                    "navigate",
                    "fill",
                    "click",
                    "extract",
                    "wait",
                    "dismiss_dialog",
                    "complete",
                    "escalate",
                }
            ),
        )
    )


@pytest.fixture
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate(
        {
            "capability_id": "lookup",
            "name": "Lookup",
            "description": "Lookup balance",
            "revision": 1,
            "vendor": "Demo",
            "application": "Legacy",
            "compatible_versions": ">=1,<2",
            "base_url": "http://127.0.0.1:8765/",
            "inputs": [
                {
                    "name": "member_id",
                    "value_type": "string",
                    "min_length": 2,
                    "max_length": 12,
                    "pattern": "^M[0-9]{4}$",
                    "sensitive": True,
                }
            ],
            "outputs": [{"name": "balance", "value_type": "decimal", "description": "balance"}],
            "steps": [
                {
                    "id": "navigate",
                    "action": "navigate",
                    "risk": "read_only",
                    "destination": "http://127.0.0.1:8765/",
                },
                {
                    "id": "fill",
                    "action": "fill",
                    "risk": "read_only",
                    "locators": [{"strategy": "label", "value": "Member number"}],
                    "value": {"param": "member_id"},
                },
                {
                    "id": "search",
                    "action": "click",
                    "risk": "read_only",
                    "locators": [{"strategy": "role", "role": "button", "value": "Search"}],
                    "retry": {"max_attempts": 2},
                },
                {
                    "id": "open",
                    "action": "click",
                    "risk": "read_only",
                    "locators": [{"strategy": "role", "role": "link", "value": "Open member"}],
                },
                {
                    "id": "extract",
                    "action": "extract",
                    "risk": "read_only",
                    "locators": [{"strategy": "text", "value": "$1,245.67", "scope": "#accounts"}],
                    "extraction": {"output": "balance", "value_type": "decimal", "pattern": "[$,]"},
                },
            ],
            "checkpoint": {"kind": "text_present", "value": "Savings balance"},
            "business_outcomes": [
                {
                    "code": "member_not_found",
                    "condition": {"kind": "text_present", "value": "No member found"},
                }
            ],
            "provenance": {
                "discovered_at": "2026-01-01T00:00:00Z",
                "model_provider": "test",
                "model_name": "fake",
                "run_id": "run",
                "observation_sha256": "a" * 64,
            },
        }
    )


@pytest.fixture
def runtime(tmp_path: Path, policy: PolicyEngine):
    def make(surface: FakeSurface):
        from cuauto.replay import ReplayEngine

        return ReplayEngine(
            surface,
            policy,
            EventRecorder(tmp_path / "events.jsonl"),
            InterventionManager(),
            tmp_path / "evidence",
        )

    return make
