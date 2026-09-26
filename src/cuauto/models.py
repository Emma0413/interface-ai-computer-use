from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    FILL = "fill"
    CLICK = "click"
    EXTRACT = "extract"
    WAIT = "wait"
    DISMISS_DIALOG = "dismiss_dialog"
    COMPLETE = "complete"
    ESCALATE = "escalate"


class Risk(str, Enum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible_mutation"
    HIGH = "irreversible_high_risk"


class ValueType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class ParamRef(StrictModel):
    param: str

    @field_validator("param")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.fullmatch(value):
            raise ValueError("invalid parameter reference")
        return value


class LiteralValue(StrictModel):
    literal: str = Field(max_length=256)


SafeValue = ParamRef | LiteralValue


class Locator(StrictModel):
    strategy: Literal["role", "label", "text", "attribute", "relative", "row_value", "coordinates"]
    value: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=30)
    scope: str | None = Field(default=None, max_length=100)
    attribute: str | None = Field(default=None, pattern=r"^(id|name|title|placeholder|aria-label)$")
    fragile: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Locator:
        if self.strategy == "role" and not self.role:
            raise ValueError("role locator requires role")
        if self.strategy == "attribute" and not self.attribute:
            raise ValueError("attribute locator requires allowed attribute")
        if self.strategy == "coordinates" and not self.fragile:
            raise ValueError("coordinates must be marked fragile")
        return self


class Condition(StrictModel):
    kind: Literal["url_matches", "visible", "text_present", "dialog_absent"]
    value: str = Field(min_length=1, max_length=300)
    locators: tuple[Locator, ...] = Field(default=(), max_length=6)


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=1, ge=1, le=3)
    backoff_ms: int = Field(default=100, ge=0, le=2_000)
    safe_only: bool = True


class Extraction(StrictModel):
    output: str
    value_type: ValueType
    pattern: str | None = Field(default=None, max_length=200)


class Step(StrictModel):
    id: str
    action: ActionType
    risk: Risk
    locators: tuple[Locator, ...] = Field(default=(), max_length=6)
    value: SafeValue | None = None
    destination: str | None = Field(default=None, max_length=300)
    preconditions: tuple[Condition, ...] = Field(default=(), max_length=8)
    postconditions: tuple[Condition, ...] = Field(default=(), max_length=8)
    wait: Condition | None = None
    timeout_ms: int = Field(default=5_000, ge=100, le=30_000)
    retry: RetryPolicy = RetryPolicy()
    extraction: Extraction | None = None

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.fullmatch(value):
            raise ValueError("invalid step ID")
        return value

    @model_validator(mode="after")
    def action_fields(self) -> Step:
        needs_target = {ActionType.FILL, ActionType.CLICK, ActionType.EXTRACT}
        if self.action in needs_target and not self.locators:
            raise ValueError("action requires locators")
        if self.action == ActionType.FILL and self.value is None:
            raise ValueError("fill requires safe value")
        if self.action == ActionType.NAVIGATE and not self.destination:
            raise ValueError("navigate requires destination")
        if self.action == ActionType.EXTRACT and self.extraction is None:
            raise ValueError("extract requires declaration")
        if self.risk != Risk.READ_ONLY and self.retry.max_attempts > 1:
            raise ValueError("mutations cannot be retried")
        return self


class InputDecl(StrictModel):
    name: str
    value_type: ValueType
    required: bool = True
    min_length: int | None = Field(default=None, ge=0, le=100)
    max_length: int | None = Field(default=None, ge=1, le=256)
    pattern: str | None = Field(default=None, max_length=200)
    sensitive: bool = False


class OutputDecl(StrictModel):
    name: str
    value_type: ValueType
    description: str = Field(max_length=300)


class BusinessOutcome(StrictModel):
    code: str
    condition: Condition


class Recovery(StrictModel):
    condition: Condition
    action: Literal["dismiss_dialog", "retry_wait"]
    max_attempts: int = Field(ge=1, le=3)


class VariantOverride(StrictModel):
    variant: str
    compatible_versions: str
    locator_overrides: dict[str, tuple[Locator, ...]] = Field(default_factory=dict)


class Provenance(StrictModel):
    discovered_at: datetime
    model_provider: str
    model_name: str
    run_id: str
    observation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApprovalMetadata(StrictModel):
    status: Literal["draft", "approved", "retired"] = "draft"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class CapabilityArtifact(StrictModel):
    schema_name: Literal["cuauto.capability"] = "cuauto.capability"
    schema_version: Literal["1.0.0"] = "1.0.0"
    capability_id: str
    name: str = Field(max_length=100)
    description: str = Field(max_length=500)
    revision: int = Field(ge=1)
    vendor: str = Field(max_length=100)
    application: str = Field(max_length=100)
    compatible_versions: str = Field(max_length=100)
    base_url: HttpUrl
    variants: tuple[VariantOverride, ...] = Field(default=(), max_length=20)
    inputs: tuple[InputDecl, ...] = Field(max_length=30)
    outputs: tuple[OutputDecl, ...] = Field(max_length=30)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=100)
    checkpoint: Condition
    business_outcomes: tuple[BusinessOutcome, ...] = Field(default=(), max_length=20)
    recoveries: tuple[Recovery, ...] = Field(default=(), max_length=10)
    escalation_conditions: tuple[str, ...] = Field(default=(), max_length=20)
    approval: ApprovalMetadata = ApprovalMetadata()
    provenance: Provenance

    @field_validator("capability_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_RE.fullmatch(value):
            raise ValueError("invalid capability ID")
        return value

    @model_validator(mode="after")
    def cross_validate(self) -> CapabilityArtifact:
        step_ids = [s.id for s in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate step IDs")
        inputs = {i.name for i in self.inputs}
        outputs = {o.name: o.value_type for o in self.outputs}
        for step in self.steps:
            if isinstance(step.value, ParamRef) and step.value.param not in inputs:
                raise ValueError(f"unknown parameter reference: {step.value.param}")
            if (
                step.extraction
                and outputs.get(step.extraction.output) != step.extraction.value_type
            ):
                raise ValueError("extraction does not match output declaration")
        return self


class ModelAction(StrictModel):
    action: ActionType
    rationale: str = Field(min_length=1, max_length=240)
    locators: tuple[Locator, ...] = Field(default=(), max_length=6)
    value: SafeValue | None = None
    destination: str | None = Field(default=None, max_length=300)
    success_checkpoint: Condition | None = None
    output: Extraction | None = None


class Observation(StrictModel):
    url: str
    title: str = Field(max_length=200)
    text: str = Field(max_length=8_000)
    controls: tuple[dict[str, str], ...] = Field(default=(), max_length=100)
    fingerprint: str


class FailureDetail(StrictModel):
    category: str
    step_id: str | None = None
    expected_state: str | None = None
    observed_state: str | None = None
    retry_count: int = 0
    evidence: tuple[str, ...] = ()


class SuccessResult(StrictModel):
    kind: Literal["success"] = "success"
    outputs: dict[str, Any]
    run_id: str


class BusinessResult(StrictModel):
    kind: Literal["business_outcome"] = "business_outcome"
    outcome: str
    run_id: str


class EscalatedResult(StrictModel):
    kind: Literal["escalated"] = "escalated"
    intervention_id: str
    reason: str
    run_id: str


class FailureResult(StrictModel):
    kind: Literal["failure"] = "failure"
    error: FailureDetail
    run_id: str


RunResult = Annotated[
    SuccessResult | BusinessResult | EscalatedResult | FailureResult,
    Field(discriminator="kind"),
]


def utc_now() -> datetime:
    return datetime.now(UTC)
