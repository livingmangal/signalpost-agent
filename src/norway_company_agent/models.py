"""Pydantic models and contract schemas for Norwegian company intelligence.

Defines schemas conforming to OUTPUT_CONTRACT.md and the batch execution pipeline.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AvailabilityState(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class TerminalBatchState(str, Enum):
    COMPLETE = "complete"
    NOT_APPLICABLE = "not_applicable"
    NOT_FOUND = "not_found"
    BLOCKED_POLICY = "blocked_policy"
    BLOCKED_ROBOTS = "blocked_robots"
    SOURCE_ERROR = "source_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SUBMISSION_ERROR = "submission_error"


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    source_url: str | None = None
    source_class: str | None = None
    retrieved_at: str | None = None
    content_sha256: str | None = None
    claim_span: str | None = None
    status: str | None = None
    value: Any = None
    note: str | None = None
    retry_count: int = 0


class ClaimModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str
    value: Any = None
    availability: AvailabilityState | str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)


class RunMetadataModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    started_at: str
    completed_at: str
    terminal_status: str = "completed"


class OperationsMetricModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    requests: int = 0
    runtime_ms: int | None = None
    third_party_cost_usd: float = 0.0
    bytes: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None


class ChangeRecordModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    organisation_number: str
    field: str
    old_value: Any = None
    new_value: Any = None
    source_url: str | None = None
    retrieved_at: str | None = None
    effective_at: str | None = None
    old_content_sha256: str | None = None
    new_content_sha256: str | None = None
    status: str | None = None


class OutputContractEnvelope(BaseModel):
    """Enforces OUTPUT_CONTRACT.md minimal output schema."""
    model_config = ConfigDict(extra="allow")

    organisation_number: str
    run: RunMetadataModel
    claims: list[ClaimModel] = Field(default_factory=list)
    evidence: list[EvidenceModel] = Field(default_factory=list)
    changes: list[ChangeRecordModel] = Field(default_factory=list)
    errors: list[Any] = Field(default_factory=list)
    operations: OperationsMetricModel = Field(default_factory=OperationsMetricModel)

    @field_validator("organisation_number")
    @classmethod
    def validate_org_number(cls, v: str) -> str:
        digits = "".join(c for c in str(v) if c.isdigit())
        if len(digits) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {v!r}")
        return digits


class ModuleStateModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: str
    retry_count: int = 0
    final_timestamp: str


class BatchTerminalEnvelope(BaseModel):
    """Enforces batch orchestrator terminal envelope schema."""
    model_config = ConfigDict(extra="allow")

    run_id: str
    organisation_number: str
    state: str
    started_at: str
    completed_at: str
    modules: dict[str, ModuleStateModel] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)

    @field_validator("organisation_number")
    @classmethod
    def validate_org_number(cls, v: str) -> str:
        digits = "".join(c for c in str(v) if c.isdigit())
        if len(digits) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {v!r}")
        return digits


def validate_batch_envelope(payload: dict[str, Any]) -> BatchTerminalEnvelope:
    """Validate a batch envelope against BatchTerminalEnvelope schema."""
    return BatchTerminalEnvelope.model_validate(payload)


def validate_output_contract_envelope(payload: dict[str, Any]) -> OutputContractEnvelope:
    """Validate a terminal output envelope against OutputContractEnvelope schema."""
    return OutputContractEnvelope.model_validate(payload)
