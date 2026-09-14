"""Research Summary: deterministic, LLM-free ResearchPacket.summary text.

A templated rollup of counts, not prose generation -- see
docs/RESEARCH_INTELLIGENCE.md "LLM-free design" for the explicit boundary
where a future LLM-based summarizer could replace this module, and
docs/DEVELOPMENT_RULES.md rule 7 for why this must not try to be
Content Brain's job (no hook/body/CTA writing here).
"""

from __future__ import annotations

from echo.models.enums import ClaimStatus
from echo.models.research import ResearchClaim


def build_summary(
    topic: str,
    claims: list[ResearchClaim],
    source_count: int,
    primary_source_present: bool,
    conflict_count: int,
) -> str:
    confirmed = sum(1 for c in claims if c.status in (ClaimStatus.CONFIRMED, ClaimStatus.SUPPORTED))
    single_source = sum(1 for c in claims if c.status == ClaimStatus.SINGLE_SOURCE)
    unverified = sum(1 for c in claims if c.status == ClaimStatus.UNVERIFIED)
    conflicted = sum(1 for c in claims if c.status == ClaimStatus.CONFLICTED)

    primary_note = "a primary source" if primary_source_present else "no primary source"
    parts = [
        f"Research for '{topic}': {len(claims)} claim(s) from {source_count} source(s) ({primary_note}).",
        f"{confirmed} confirmed/supported, {single_source} single-source, "
        f"{unverified} unverified, {conflicted} conflicted.",
    ]
    if conflict_count:
        parts.append(f"{conflict_count} conflict(s) detected across evidence.")
    return " ".join(parts)
