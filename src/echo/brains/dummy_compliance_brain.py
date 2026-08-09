"""DummyComplianceBrain: deterministic stub compliance check.

Flags a fixed list of high-risk terms. Never rejects on its own -- results
are informational and are always routed through the Human Review Gate.
"""

from __future__ import annotations

from echo.models.compliance import ComplianceResult
from echo.models.draft import ContentDraft

_RISK_TERMS = (
    "guaranteed",
    "guarantee",
    "financial advice",
    "investment advice",
    "get rich",
    "100% safe",
)


class DummyComplianceBrain:
    def check(self, draft: ContentDraft) -> ComplianceResult:
        text = f"{draft.hook} {draft.body} {draft.cta or ''}".lower()
        flags = [term for term in _RISK_TERMS if term in text]
        risk_score = 0.8 if flags else 0.1
        return ComplianceResult(
            draft_id=draft.draft_id,
            trace_id=draft.trace_id,
            risk_score=risk_score,
            flags=flags,
        )
