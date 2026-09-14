"""Claim Grouping: FactCandidate sentences -> ResearchClaim + EvidenceItem +
ConflictRecord.

Deterministic token-Jaccard grouping (same technique as
``echo.trend.clustering``, not the same code -- this groups individual
fact sentences, not whole SourceItems, and needs no time-window/entity-term
signal since its input is already the pre-selected, same-event source
pool from ``echo.research.source_selection``). Two sentences describing
the same fact with different wording (e.g. "OpenAI launches X" / "OpenAI
announces the launch of X") land in one group; sentences that share most
words but assert opposite things (e.g. "launches X" / "delays X") are
still grouped (they're about the same subject) but ``echo.research.conflicts``
catches the contradiction, so they are never silently counted as agreeing.
"""

from __future__ import annotations

from echo.core.ids import IdFactory
from echo.core.text import jaccard_similarity, token_set
from echo.models.enums import ClaimStatus, ConflictSeverity, ReliabilityTier
from echo.models.research import ConflictRecord, EvidenceItem, ResearchClaim
from echo.research.confidence import claim_confidence
from echo.research.conflicts import detect_conflict
from echo.research.config import ResearchConfig
from echo.research.evidence import SourceRegistryInfo, build_evidence_item
from echo.research.extraction import FactCandidate
from echo.research.independence import independent_source_count
from echo.core.reliability import reliability_score


def _stemmed_tokens(text: str) -> set[str]:
    """Grouping-only token set: ``echo.core.text.tokenize`` plus a crude
    suffix strip (releases/released/releasing -> release) so wording
    differences alone (e.g. "launches" vs "announces the launch of")
    don't block grouping two sentences about the same fact -- see
    docs/RESEARCH_INTELLIGENCE.md "Claim grouping". Deliberately local to
    claim grouping, not folded into ``echo.core.text.tokenize`` itself,
    which STEP 2 dedup/clustering/relevance rely on staying unchanged."""
    return {_stem(token) for token in token_set(text)}


def _stem(token: str) -> str:
    """Strip a common inflectional suffix, then a lingering silent 'e' --
    the second pass is what makes the base form ("release") land on the
    same stem as its inflections ("releases"/"released" -> "releas"),
    which a single-pass strip alone would miss."""
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "i"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        token = token[:-1]
    if token.endswith("e") and len(token) > 4:
        token = token[:-1]
    return token


def group_fact_candidates(
    candidates: list[FactCandidate], config: ResearchConfig
) -> list[list[FactCandidate]]:
    """Greedy single-pass grouping by stemmed-token Jaccard similarity
    against ``config.claim_grouping_similarity_threshold``. Sentences that
    share a subject but assert opposite things (e.g. "launches X" /
    "delays X") are still grouped here -- ``echo.research.conflicts``
    catches the contradiction within the group, see module docstring."""
    groups: list[list[FactCandidate]] = []
    group_tokens: list[set[str]] = []

    for candidate in candidates:
        tokens = _stemmed_tokens(candidate.normalized_text)
        best_index: int | None = None
        best_score = 0.0
        for index, existing_tokens in enumerate(group_tokens):
            score = jaccard_similarity(tokens, existing_tokens)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index is not None and best_score >= config.claim_grouping_similarity_threshold:
            groups[best_index].append(candidate)
            group_tokens[best_index] |= tokens
        else:
            groups.append([candidate])
            group_tokens.append(tokens)

    return groups


def build_claims(
    candidate_groups: list[list[FactCandidate]],
    registry_info: dict[str, SourceRegistryInfo],
    config: ResearchConfig,
    ids: IdFactory,
) -> tuple[list[ResearchClaim], list[EvidenceItem], list[ConflictRecord]]:
    """Turn each fact-candidate group into one ResearchClaim, the
    EvidenceItems backing it, and any ConflictRecords found within it."""
    all_claims: list[ResearchClaim] = []
    all_evidence: list[EvidenceItem] = []
    all_conflicts: list[ConflictRecord] = []

    for group in candidate_groups:
        claim_id = ids.claim_id()

        evidence_by_candidate = [
            build_evidence_item(candidate, registry_info.get(candidate.source_item.source_key), config, ids)
            for candidate in group
        ]
        all_evidence.extend(evidence_by_candidate)

        representative_index = min(
            range(len(group)), key=lambda i: group[i].source_item.published_at
        )
        representative_candidate = group[representative_index]

        conflicts_in_group = _detect_group_conflicts(group, evidence_by_candidate, claim_id, ids)
        all_conflicts.extend(conflicts_in_group)

        # A merely-POTENTIAL conflict is recorded (above) for audit/
        # traceability but deliberately does not, by itself, flip a claim
        # to CONFLICTED or reassign supporting/contradicting sources --
        # see docs/RESEARCH_INTELLIGENCE.md "Conflict detection".
        confirmed_conflicts = [c for c in conflicts_in_group if c.severity != ConflictSeverity.POTENTIAL]

        contradicting_source_keys = {
            c.source_key_b
            for c in confirmed_conflicts
            if c.source_key_a == representative_candidate.source_item.source_key
        } | {
            c.source_key_a
            for c in confirmed_conflicts
            if c.source_key_b == representative_candidate.source_item.source_key
        }

        supporting_items = [
            c.source_item for c in group if c.source_item.source_key not in contradicting_source_keys
        ]
        contradicting_items = [
            c.source_item for c in group if c.source_item.source_key in contradicting_source_keys
        ]

        supporting_source_ids = sorted({item.source_key for item in supporting_items})
        contradicting_source_ids = sorted({item.source_key for item in contradicting_items})

        support_registry = [registry_info.get(key) for key in supporting_source_ids]
        reliabilities = [
            (info.reliability_tier if info else ReliabilityTier.C) for info in support_registry
        ]
        reliability_scores = [reliability_score(tier) for tier in reliabilities]
        primary_present = any(info.is_primary_source for info in support_registry if info)
        has_conflict = bool(confirmed_conflicts)
        independence = independent_source_count(supporting_items) or independent_source_count(
            [c.source_item for c in group]
        )

        status = _claim_status(
            has_conflict=has_conflict,
            independent_count=independence,
            primary_present=primary_present,
            best_tier=max(reliabilities, default=ReliabilityTier.C, key=reliability_score),
        )

        confidence = claim_confidence(
            reliabilities=reliability_scores,
            independent_count=independence,
            primary_present=primary_present,
            has_conflict=has_conflict,
            config=config,
        )

        all_claims.append(
            ResearchClaim(
                claim_id=claim_id,
                text=representative_candidate.text,
                normalized_text=representative_candidate.normalized_text,
                evidence_ids=sorted({e.evidence_id for e in evidence_by_candidate}),
                supporting_source_ids=supporting_source_ids,
                contradicting_source_ids=contradicting_source_ids,
                confidence=confidence,
                status=status,
            )
        )

    return all_claims, all_evidence, all_conflicts


def _detect_group_conflicts(
    group: list[FactCandidate], evidence: list[EvidenceItem], claim_id: str, ids: IdFactory
) -> list[ConflictRecord]:
    conflicts: list[ConflictRecord] = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            if group[i].source_item.source_key == group[j].source_item.source_key:
                continue  # same source can't conflict with itself
            signal = detect_conflict(group[i].text, group[j].text)
            if signal is None:
                continue
            conflicts.append(
                ConflictRecord(
                    conflict_id=ids.conflict_id(),
                    claim_id=claim_id,
                    evidence_id_a=evidence[i].evidence_id,
                    evidence_id_b=evidence[j].evidence_id,
                    source_key_a=group[i].source_item.source_key,
                    source_key_b=group[j].source_item.source_key,
                    conflict_type=signal.conflict_type,
                    reason=signal.reason,
                    severity=signal.severity,
                )
            )
    return conflicts


def _claim_status(
    has_conflict: bool, independent_count: int, primary_present: bool, best_tier: ReliabilityTier
) -> ClaimStatus:
    if has_conflict:
        return ClaimStatus.CONFLICTED
    if independent_count >= 2:
        if primary_present or best_tier in (ReliabilityTier.A,):
            return ClaimStatus.CONFIRMED
        return ClaimStatus.SUPPORTED
    if independent_count == 1:
        if primary_present or best_tier in (ReliabilityTier.A, ReliabilityTier.B):
            return ClaimStatus.SINGLE_SOURCE
        return ClaimStatus.UNVERIFIED
    return ClaimStatus.UNVERIFIED
