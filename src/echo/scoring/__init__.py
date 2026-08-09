"""SCORE stage service and threshold gate."""

from echo.scoring.service import passes_threshold, score_trend

__all__ = ["passes_threshold", "score_trend"]
