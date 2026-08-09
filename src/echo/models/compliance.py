"""ComplianceResult: output of the COMPLIANCE stage.

This is informational only -- compliance never auto-rejects content. Its
findings are folded into ContentDraft.compliance_risk_score /
compliance_flags so the Human Review Gate always makes the final call.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ComplianceResult(BaseModel):
    draft_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=1.0)
    flags: list[str] = Field(default_factory=list)
