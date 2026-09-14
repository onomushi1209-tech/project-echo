"""Runtime settings, loaded from environment variables / .env.

Nothing secret is hard-coded here. STEP 1/2 have no external API keys to
manage, but this is the single place later steps should add them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from echo.research.config import ResearchConfig
from echo.trend.signal_config import TrendSignalConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    config_dir: Path
    data_dir: Path
    database_path: Path
    score_threshold: float
    fixtures_dir: Path

    @classmethod
    def load(cls) -> Settings:
        config_dir = Path(os.getenv("ECHO_CONFIG_DIR", str(PROJECT_ROOT / "config")))
        data_dir = Path(os.getenv("ECHO_DATA_DIR", str(PROJECT_ROOT / "data")))
        database_path = Path(os.getenv("ECHO_DATABASE_PATH", str(data_dir / "echo.db")))
        score_threshold = float(os.getenv("ECHO_SCORE_THRESHOLD", "0.5"))
        fixtures_dir = Path(
            os.getenv("ECHO_FIXTURES_DIR", str(PROJECT_ROOT / "tests" / "fixtures" / "sources"))
        )
        return cls(
            project_root=PROJECT_ROOT,
            config_dir=config_dir,
            data_dir=data_dir,
            database_path=database_path,
            score_threshold=score_threshold,
            fixtures_dir=fixtures_dir,
        )

    def trend_signal_config(self) -> TrendSignalConfig:
        """A handful of the most likely-to-need-tuning trend signal knobs,
        overridable via env var; everything else uses TrendSignalConfig's
        own documented defaults. See docs/SOURCE_INTELLIGENCE.md."""
        defaults = TrendSignalConfig()
        return TrendSignalConfig(
            freshness_half_life_hours=float(
                os.getenv("ECHO_FRESHNESS_HALF_LIFE_HOURS", defaults.freshness_half_life_hours)
            ),
            velocity_saturation=float(os.getenv("ECHO_VELOCITY_SATURATION", defaults.velocity_saturation)),
            novelty_similarity_threshold=float(
                os.getenv("ECHO_NOVELTY_SIMILARITY_THRESHOLD", defaults.novelty_similarity_threshold)
            ),
            cluster_similarity_threshold=float(
                os.getenv("ECHO_CLUSTER_SIMILARITY_THRESHOLD", defaults.cluster_similarity_threshold)
            ),
            trend_persistence_novelty_threshold=float(
                os.getenv(
                    "ECHO_TREND_PERSISTENCE_NOVELTY_THRESHOLD",
                    defaults.trend_persistence_novelty_threshold,
                )
            ),
        )

    def research_config(self) -> ResearchConfig:
        """A handful of the most likely-to-need-tuning Research
        Intelligence knobs, overridable via env var; everything else uses
        ResearchConfig's own documented defaults. See
        docs/RESEARCH_INTELLIGENCE.md."""
        defaults = ResearchConfig()
        return ResearchConfig(
            max_research_candidates=int(
                os.getenv("ECHO_MAX_RESEARCH_CANDIDATES", defaults.max_research_candidates)
            ),
            max_research_sources=int(
                os.getenv("ECHO_MAX_RESEARCH_SOURCES", defaults.max_research_sources)
            ),
            claim_grouping_similarity_threshold=float(
                os.getenv(
                    "ECHO_CLAIM_GROUPING_SIMILARITY_THRESHOLD",
                    defaults.claim_grouping_similarity_threshold,
                )
            ),
            minimum_evidence_items=int(
                os.getenv("ECHO_MINIMUM_EVIDENCE_ITEMS", defaults.minimum_evidence_items)
            ),
            minimum_independent_sources=int(
                os.getenv("ECHO_MINIMUM_INDEPENDENT_SOURCES", defaults.minimum_independent_sources)
            ),
            minimum_confidence=float(
                os.getenv("ECHO_MINIMUM_RESEARCH_CONFIDENCE", defaults.minimum_confidence)
            ),
        )


def get_settings() -> Settings:
    return Settings.load()
