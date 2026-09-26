from __future__ import annotations

import secrets
import threading
from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import Field

from .models import StrictModel


class ControlState(str, Enum):
    AUTOMATION_ACTIVE = "automation_active"
    PAUSING = "pausing"
    HUMAN_ACTIVE = "human_active"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Intervention(StrictModel):
    intervention_id: str
    token: str = Field(repr=False)
    capability_id: str
    session_id: str
    current_step: str | None
    reason: str
    category: str
    sanitized_state: str
    evidence_ref: str | None
    requested_decision: str
    created_at: datetime
    expires_at: datetime
    control_owner: str
    state: ControlState
    acknowledgement: str | None = None


class InterventionError(RuntimeError):
    pass


class InterventionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: Intervention | None = None

    @property
    def current(self) -> Intervention | None:
        return self._current

    def ensure_automation(self, session_id: str) -> None:
        with self._lock:
            if self._current and self._current.session_id == session_id:
                if self._current.state != ControlState.AUTOMATION_ACTIVE:
                    raise InterventionError("automation does not own this session")

    def request(
        self,
        *,
        capability_id: str,
        session_id: str,
        current_step: str | None,
        reason: str,
        category: str,
        sanitized_state: str,
        evidence_ref: str | None = None,
        ttl_seconds: int = 300,
    ) -> Intervention:
        with self._lock:
            if self._current and self._current.state in {
                ControlState.PAUSING,
                ControlState.HUMAN_ACTIVE,
            }:
                raise InterventionError("an intervention is already active")
            now = datetime.now(UTC)
            self._current = Intervention(
                intervention_id=secrets.token_urlsafe(18),
                token=secrets.token_urlsafe(32),
                capability_id=capability_id,
                session_id=session_id,
                current_step=current_step,
                reason=reason,
                category=category,
                sanitized_state=sanitized_state,
                evidence_ref=evidence_ref,
                requested_decision="resume or cancel",
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                control_owner="automation",
                state=ControlState.PAUSING,
            )
            return self._current

    def transfer_to_human(self, intervention_id: str, token: str, session_id: str) -> Intervention:
        with self._lock:
            item = self._validate(intervention_id, token, session_id)
            if item.state != ControlState.PAUSING:
                raise InterventionError("invalid or duplicate takeover")
            self._current = item.model_copy(
                update={"state": ControlState.HUMAN_ACTIVE, "control_owner": "human"}
            )
            return self._current

    def resume(self, intervention_id: str, token: str, session_id: str, note: str) -> Intervention:
        with self._lock:
            item = self._validate(intervention_id, token, session_id)
            if item.state != ControlState.HUMAN_ACTIVE:
                raise InterventionError("stale or duplicate resume")
            self._current = item.model_copy(
                update={
                    "state": ControlState.RESUMING,
                    "control_owner": "none",
                    "acknowledgement": note[:500],
                }
            )
            self._current = self._current.model_copy(
                update={"state": ControlState.AUTOMATION_ACTIVE, "control_owner": "automation"}
            )
            return self._current

    def cancel(self, intervention_id: str, token: str, session_id: str, note: str) -> Intervention:
        with self._lock:
            item = self._validate(intervention_id, token, session_id)
            if item.state not in {ControlState.PAUSING, ControlState.HUMAN_ACTIVE}:
                raise InterventionError("stale cancellation")
            self._current = item.model_copy(
                update={
                    "state": ControlState.CANCELLED,
                    "control_owner": "none",
                    "acknowledgement": note[:500],
                }
            )
            return self._current

    def _validate(self, intervention_id: str, token: str, session_id: str) -> Intervention:
        item = self._current
        if not item or not secrets.compare_digest(item.intervention_id, intervention_id):
            raise InterventionError("unknown intervention")
        if not secrets.compare_digest(item.token, token) or item.session_id != session_id:
            raise InterventionError("cross-session or invalid operator request")
        if item.expires_at <= datetime.now(UTC):
            self._current = item.model_copy(
                update={"state": ControlState.EXPIRED, "control_owner": "none"}
            )
            raise InterventionError("intervention expired")
        return item
