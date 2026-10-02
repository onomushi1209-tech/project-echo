"""Validated, project-local Affiliate Phase 0 policy loading."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml
from pydantic import ConfigDict, Field, BaseModel, model_validator

from echo.models.affiliate import BUY_NOW_EVIDENCE_TYPES, EvidenceType, OpportunityScoreConfig
from echo.models.affiliate_visual import VisualPolicy
from echo.models.affiliate_visual import SocialPlatform
from decimal import Decimal


SIGNAL_EVIDENCE_TYPES = BUY_NOW_EVIDENCE_TYPES


class StrictConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SignalFreshness(StrictConfig):
    evidence_type: EvidenceType
    max_age_hours: int = Field(ge=1)


class BuyNowPolicy(StrictConfig):
    signal_freshness: tuple[SignalFreshness, ...]

    @model_validator(mode="after")
    def _complete_signal_freshness(self) -> Self:
        evidence_types = [item.evidence_type for item in self.signal_freshness]
        if set(evidence_types) != SIGNAL_EVIDENCE_TYPES or len(evidence_types) != len(SIGNAL_EVIDENCE_TYPES):
            raise ValueError("freshness must be configured for every supported BuyNow evidence type")
        return self

    @property
    def max_age_by_type(self) -> dict[EvidenceType, int]:
        """Return a fresh lookup so the frozen freshness policy stays immutable."""
        return {item.evidence_type: item.max_age_hours for item in self.signal_freshness}


class CompliancePolicy(StrictConfig):
    max_price_age_hours: int = Field(ge=1)
    max_promotion_age_hours: int = Field(ge=1)
    max_destination_age_hours: int = Field(default=24, ge=1)
    required_platforms: tuple[SocialPlatform, ...] = (SocialPlatform.X,)
    require_affiliate_disclosure: bool = True
    require_verified_destination: bool = True
    require_verified_asset_rights: bool = True

    @model_validator(mode="after")
    def _safety_checks_cannot_be_disabled(self) -> Self:
        if not self.require_affiliate_disclosure:
            raise ValueError("affiliate disclosure is mandatory")
        if not self.require_verified_destination:
            raise ValueError("verified item and affiliate destinations are mandatory")
        if not self.require_verified_asset_rights:
            raise ValueError("verified visual-asset rights are mandatory")
        if SocialPlatform.X not in self.required_platforms:
            raise ValueError("X is the required initial Project Echo social channel")
        if len(set(self.required_platforms)) != len(self.required_platforms):
            raise ValueError("required social platforms must be unique")
        return self


class AffiliatePhase0Config(StrictConfig):
    score: OpportunityScoreConfig
    scoring_max_evidence_age_hours: int = Field(ge=1)
    buy_now: BuyNowPolicy
    compliance: CompliancePolicy
    visual: VisualPolicy


def load_phase0_config(path: Path | None = None) -> AffiliatePhase0Config:
    """Read the committed offline policy; no environment or remote settings are used."""
    config_path = path or Path(__file__).resolve().parents[3] / "config" / "affiliate_phase0.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Affiliate Phase 0 config must be a YAML mapping")
    if set(loaded) != {"score", "scoring_max_evidence_age_hours", "buy_now", "compliance", "visual"}:
        raise ValueError("Affiliate Phase 0 config has missing or unexpected top-level sections")
    return AffiliatePhase0Config.model_validate(loaded)


class DiscoveryPolicy(StrictConfig):
    top_n: int = Field(default=5, strict=True, ge=1, le=20)
    minimum_score: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    pages_per_query: int = Field(default=1, strict=True, ge=1, le=5)
    max_queries: int = Field(default=5, strict=True, ge=1, le=10)
    timeout_seconds: float = Field(default=10, gt=0, le=30, allow_inf_nan=False)
    max_response_bytes: int = Field(default=1048576, strict=True, ge=1, le=2097152)
    max_attempts: int = Field(default=3, strict=True, ge=1, le=3)
    backoff_seconds: float = Field(default=0.25, ge=0, le=2, allow_inf_nan=False)
    review_count_target: int = Field(default=100, strict=True, ge=1)
    affiliate_percent_target: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    observed_price_assessment: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    contextual_identity_assessment: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)


def load_discovery_policy(path: Path | None = None) -> DiscoveryPolicy:
    config_path = path or Path(__file__).resolve().parents[3] / "config" / "affiliate_phase1.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("discovery policy must be a YAML mapping")
    return DiscoveryPolicy.model_validate(loaded)
