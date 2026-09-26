from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cuauto.events import EventRecorder
from cuauto.intervention import Intervention, InterventionManager
from cuauto.models import ActionType, Risk, Step
from cuauto.policy import PolicyEngine
from cuauto.surface import SurfaceAdapter


class OperatorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["resume", "cancel"]
    note: str = Field(default="", max_length=500)


class HandoffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["resumed", "cancelled", "failure"]
    run_id: str
    intervention_id: str
    session_ref: str
    initial_fingerprint: str
    resumed_fingerprint: str | None = None
    operator_note: str = ""
    error: str | None = None


OperatorCallback = Callable[[Intervention, str], OperatorDecision]


class LiveHandoffDemo:
    """Exercise control transfer while retaining one live surface session."""

    def __init__(
        self,
        surface: SurfaceAdapter,
        policy: PolicyEngine,
        recorder: EventRecorder,
        manager: InterventionManager,
        evidence_dir: Path,
    ) -> None:
        self.surface = surface
        self.policy = policy
        self.recorder = recorder
        self.manager = manager
        self.evidence_dir = evidence_dir

    def run(
        self,
        *,
        target: str,
        operator: OperatorCallback,
        capability_id: str = "live_handoff_demo",
    ) -> HandoffResult:
        run_id = uuid.uuid4().hex
        raw_session_id = self.surface.session_id
        session_ref = hashlib.sha256(raw_session_id.encode()).hexdigest()[:20]

        self.policy.check_url(target)
        self.policy.check_action(ActionType.NAVIGATE, Risk.READ_ONLY)
        self.surface.act(
            Step(
                id="open_demo",
                action=ActionType.NAVIGATE,
                risk=Risk.READ_ONLY,
                destination=target,
                timeout_ms=10_000,
            )
        )
        initial = self.surface.observe()
        evidence_refs = self.surface.capture(
            self.evidence_dir / f"{run_id}-handoff", screenshot=False
        )
        evidence_ref = evidence_refs[0] if evidence_refs else None
        intervention = self.manager.request(
            capability_id=capability_id,
            session_id=raw_session_id,
            current_step="operator_takeover",
            reason="Demonstrate same-session human control and handback",
            category="operator_requested",
            sanitized_state=(
                f"url={initial.url} title={initial.title} fingerprint={initial.fingerprint}"
            ),
            evidence_ref=evidence_ref,
        )
        self._record(
            run_id,
            raw_session_id,
            "automation_paused",
            initial.fingerprint,
            evidence_ref,
        )
        self.manager.transfer_to_human(
            intervention.intervention_id, intervention.token, raw_session_id
        )
        live_message = self.surface.expose_live_session()
        self._record(
            run_id,
            raw_session_id,
            "control_transferred",
            initial.fingerprint,
            evidence_ref,
        )

        decision = operator(intervention, live_message)
        if decision.action == "cancel":
            self.manager.cancel(
                intervention.intervention_id,
                intervention.token,
                raw_session_id,
                decision.note or "Operator cancelled",
            )
            self._record(
                run_id,
                raw_session_id,
                "operator_cancelled",
                initial.fingerprint,
                evidence_ref,
            )
            return HandoffResult(
                kind="cancelled",
                run_id=run_id,
                intervention_id=intervention.intervention_id,
                session_ref=session_ref,
                initial_fingerprint=initial.fingerprint,
                operator_note=decision.note,
            )

        self.manager.resume(
            intervention.intervention_id,
            intervention.token,
            raw_session_id,
            decision.note,
        )
        try:
            self.manager.ensure_automation(raw_session_id)
            resumed = self.surface.observe()
            self.policy.check_url(resumed.url)
        except Exception as exc:
            self.manager.fail(raw_session_id, "session revalidation failed")
            self._record(
                run_id,
                raw_session_id,
                "handoff_revalidation_failed",
                "unavailable",
                evidence_ref,
                error="session_revalidation",
            )
            return HandoffResult(
                kind="failure",
                run_id=run_id,
                intervention_id=intervention.intervention_id,
                session_ref=session_ref,
                initial_fingerprint=initial.fingerprint,
                operator_note=decision.note,
                error=f"session revalidation failed: {type(exc).__name__}",
            )

        self._record(
            run_id,
            raw_session_id,
            "automation_resumed",
            resumed.fingerprint,
            evidence_ref,
        )
        return HandoffResult(
            kind="resumed",
            run_id=run_id,
            intervention_id=intervention.intervention_id,
            session_ref=session_ref,
            initial_fingerprint=initial.fingerprint,
            resumed_fingerprint=resumed.fingerprint,
            operator_note=decision.note,
        )

    def _record(
        self,
        run_id: str,
        session_id: str,
        event_type: str,
        observation: str,
        evidence_ref: str | None,
        *,
        error: str | None = None,
    ) -> None:
        self.recorder.record(
            run_id=run_id,
            invocation_id=run_id,
            event_type=event_type,
            timestamp=time.time(),
            mode="human",
            capability_version="1.0.0",
            session_id=session_id,
            control_owner=(
                self.manager.current.control_owner if self.manager.current else "automation"
            ),
            step_id="operator_takeover",
            action_summary={"event": event_type},
            observation_summary={"fingerprint": observation},
            duration_ms=0,
            retry_count=0,
            outcome="failure" if error else "success",
            error_taxonomy=error,
            evidence_refs=[evidence_ref] if evidence_ref else [],
        )
