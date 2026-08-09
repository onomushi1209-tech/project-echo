"""COMPLIANCE stage.

Compliance never auto-rejects content. ``apply_compliance`` folds findings
into the draft's compliance_* fields so the Human Review Gate always sees
them and makes the final call -- see docs/DEVELOPMENT_RULES.md.
"""

from __future__ import annotations

from echo.core.interfaces import ComplianceBrain
from echo.models.compliance import ComplianceResult
from echo.models.draft import ContentDraft
from echo.storage.repository import EchoRepository


def check_compliance(brain: ComplianceBrain, draft: ContentDraft) -> ComplianceResult:
    return brain.check(draft)


def apply_compliance(
    draft: ContentDraft, result: ComplianceResult, repository: EchoRepository
) -> ContentDraft:
    updated = draft.model_copy(
        update={
            "compliance_risk_score": result.risk_score,
            "compliance_flags": result.flags,
        }
    )
    repository.save_draft(updated)
    return updated
