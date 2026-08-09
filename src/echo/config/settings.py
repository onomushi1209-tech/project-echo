"""Runtime settings, loaded from environment variables / .env.

Nothing secret is hard-coded here. STEP 1 has no external API keys to
manage, but this is the single place later steps should add them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    config_dir: Path
    data_dir: Path
    database_path: Path
    score_threshold: float

    @classmethod
    def load(cls) -> Settings:
        config_dir = Path(os.getenv("ECHO_CONFIG_DIR", str(PROJECT_ROOT / "config")))
        data_dir = Path(os.getenv("ECHO_DATA_DIR", str(PROJECT_ROOT / "data")))
        database_path = Path(os.getenv("ECHO_DATABASE_PATH", str(data_dir / "echo.db")))
        score_threshold = float(os.getenv("ECHO_SCORE_THRESHOLD", "0.5"))
        return cls(
            project_root=PROJECT_ROOT,
            config_dir=config_dir,
            data_dir=data_dir,
            database_path=database_path,
            score_threshold=score_threshold,
        )


def get_settings() -> Settings:
    return Settings.load()
