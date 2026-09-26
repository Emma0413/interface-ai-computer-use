from __future__ import annotations

import decimal
import re
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .events import EventRecorder
from .intervention import InterventionManager
from .models import (
    ActionType,
    BusinessResult,
    CapabilityArtifact,
    FailureDetail,
    FailureResult,
    ParamRef,
    Risk,
    Step,
    SuccessResult,
    ValueType,
)
from .policy import PolicyEngine, PolicyViolation
from .redaction import redact
from .surface import SurfaceAdapter, SurfaceError


def validate_inputs(artifact: CapabilityArtifact, supplied: dict[str, Any]) -> dict[str, str]:
    declarations = {item.name: item for item in artifact.inputs}
    if set(supplied) - set(declarations):
        raise ValueError("unknown invocation input")
    result: dict[str, str] = {}
    for name, declaration in declarations.items():
        if declaration.required and name not in supplied:
            raise ValueError(f"missing input: {name}")
        value = supplied.get(name)
        if declaration.value_type != ValueType.STRING or not isinstance(value, str):
            raise ValueError(f"invalid input type: {name}")
        if declaration.min_length is not None and len(value) < declaration.min_length:
            raise ValueError(f"input too short: {name}")
        if declaration.max_length is not None and len(value) > declaration.max_length:
            raise ValueError(f"input too long: {name}")
        if declaration.pattern and not re.fullmatch(declaration.pattern, value):
            raise ValueError(f"input pattern mismatch: {name}")
        result[name] = value
    return result


def convert_output(raw: str, kind: ValueType, pattern: str | None) -> Any:
    clean = re.sub(pattern, "", raw) if pattern else raw
    if kind == ValueType.STRING:
        return clean
    if kind == ValueType.INTEGER:
        return int(clean)
    if kind == ValueType.DECIMAL:
        return str(decimal.Decimal(clean))
    if kind == ValueType.BOOLEAN:
        values = {"true": True, "false": False}
        if clean.lower() not in values:
            raise ValueError("invalid boolean output")
        return values[clean.lower()]
    raise ValueError("unsupported output type")


class ReplayEngine:
    def __init__(
        self,
        surface: SurfaceAdapter,
        policy: PolicyEngine,
        recorder: EventRecorder,
        interventions: InterventionManager,
        evidence_dir: Path,
    ):
        self.surface, self.policy, self.recorder = surface, policy, recorder
        self.interventions, self.evidence_dir = interventions, evidence_dir

    def run(
        self, artifact: CapabilityArtifact, supplied: dict[str, Any]
    ) -> SuccessResult | BusinessResult | FailureResult:
        run_id, invocation_id = uuid.uuid4().hex, uuid.uuid4().hex
        outputs: dict[str, Any] = {}
        try:
            inputs = validate_inputs(artifact, supplied)
            self.policy.check_url(str(artifact.base_url))
            recovery_counts = {index: 0 for index, _ in enumerate(artifact.recoveries)}
            for step in artifact.steps:
                self.interventions.ensure_automation(self.surface.session_id)
                observed_text = self.surface.observe().text.casefold()
                runtime_states = {
                    "session expired": "session_expired",
                    "authentication required": "authentication_required",
                    "permission denied": "permission_denied",
                    "application error": "application_error",
                    "validation error": "validation_error",
                }
                for marker, category in runtime_states.items():
                    if marker in observed_text:
                        return self._failure(run_id, step.id, category, marker)
                for index, recovery in enumerate(artifact.recoveries):
                    if self.surface.check(recovery.condition):
                        if recovery_counts[index] >= recovery.max_attempts:
                            return self._failure(
                                run_id, step.id, "recovery_exhausted", recovery.action
                            )
                        recovery_counts[index] += 1
                        recovery_step = Step(
                            id=f"recovery_{index}",
                            action=ActionType(recovery.action),
                            risk=Risk.READ_ONLY,
                        )
                        self.policy.check_action(recovery_step.action, recovery_step.risk)
                        self.surface.act(recovery_step)
                self.policy.check_action(step.action, step.risk)
                if step.destination:
                    self.policy.check_url(step.destination)
                for condition in step.preconditions:
                    if not self.surface.check(condition):
                        return self._failure(run_id, step.id, "precondition_failed", str(condition))
                value = (
                    inputs[step.value.param]
                    if isinstance(step.value, ParamRef)
                    else (step.value.literal if step.value else None)
                )
                attempts, started = 0, time.monotonic()
                while True:
                    try:
                        raw = self.surface.act(step, value)
                        break
                    except SurfaceError as exc:
                        attempts += 1
                        safe = step.risk.value == "read_only" and step.retry.safe_only
                        if not safe or attempts >= step.retry.max_attempts:
                            return self._failure(
                                run_id, step.id, exc.category, str(exc), attempts - 1
                            )
                        self.policy.check_action(step.action, step.risk)
                if step.wait:
                    self.surface.wait(step.wait, step.timeout_ms)
                for condition in step.postconditions:
                    if not self.surface.check(condition):
                        return self._failure(
                            run_id, step.id, "postcondition_failed", str(condition)
                        )
                for outcome in artifact.business_outcomes:
                    if self.surface.check(outcome.condition):
                        return BusinessResult(outcome=outcome.code, run_id=run_id)
                if step.extraction and raw is not None:
                    outputs[step.extraction.output] = convert_output(
                        raw, step.extraction.value_type, step.extraction.pattern
                    )
                self.recorder.record(
                    run_id=run_id,
                    invocation_id=invocation_id,
                    event_type="step",
                    mode="replay",
                    capability_version=artifact.schema_version,
                    session_id=self.surface.session_id,
                    control_owner="automation",
                    step_id=step.id,
                    action_summary={"action": step.action.value},
                    observation_summary={},
                    duration_ms=int((time.monotonic() - started) * 1000),
                    retry_count=attempts,
                    outcome="executed",
                )
            if not self.surface.check(artifact.checkpoint):
                return self._failure(
                    run_id, artifact.steps[-1].id, "checkpoint_mismatch", str(artifact.checkpoint)
                )
            final_outputs = outputs
            if set(final_outputs) != {o.name for o in artifact.outputs}:
                return self._failure(
                    run_id, artifact.steps[-1].id, "output_type_mismatch", "declared outputs"
                )
            return SuccessResult(outputs=final_outputs, run_id=run_id)
        except PolicyViolation as exc:
            return self._failure(run_id, None, "policy_violation", str(exc))
        except (ValueError, decimal.InvalidOperation) as exc:
            return self._failure(run_id, None, "input_or_output_validation", str(exc))
        except Exception as exc:
            return self._failure(run_id, None, "internal_error", str(exc))

    def _failure(
        self, run_id: str, step_id: str | None, category: str, expected: str, retry_count: int = 0
    ) -> FailureResult:
        try:
            refs = self.surface.capture(
                self.evidence_dir / run_id, screenshot=self.policy.config.screenshot_persistence
            )
            observed = str(
                redact(self.surface.observe().model_dump(), self.policy.config.pii_fields)
            )
        except Exception:
            refs, observed = (), "surface unavailable"
        return FailureResult(
            run_id=run_id,
            error=FailureDetail(
                category=category,
                step_id=step_id,
                expected_state=expected[:500],
                observed_state=observed[:1000],
                retry_count=retry_count,
                evidence=refs,
            ),
        )


RESULT_ADAPTER: TypeAdapter[SuccessResult | BusinessResult | FailureResult] = TypeAdapter(
    SuccessResult | BusinessResult | FailureResult
)
