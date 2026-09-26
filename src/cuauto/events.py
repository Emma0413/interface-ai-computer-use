from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import StrictModel
from .redaction import redact


class Event(StrictModel):
    run_id: str
    invocation_id: str
    event_type: str
    timestamp: datetime
    mode: Literal["discovery", "replay", "human"]
    capability_version: str | None = None
    session_id: str
    control_owner: Literal["automation", "human", "none"]
    step_id: str | None = None
    action_summary: dict[str, Any] = Field(default_factory=dict)
    observation_summary: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    retry_count: int = 0
    outcome: str | None = None
    error_taxonomy: str | None = None
    evidence_refs: tuple[str, ...] = ()


class EventRecorder:
    def __init__(self, path: Path, pii_fields: frozenset[str] = frozenset()):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("event path cannot be a symlink")
        self.path = path
        self.pii_fields = pii_fields

    def record(self, **fields: Any) -> Event:
        fields["timestamp"] = fields.get("timestamp", datetime.now(UTC))
        clean = redact(fields, self.pii_fields)
        event = Event.model_validate(clean)
        line = event.model_dump_json() + "\n"
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
        return event
