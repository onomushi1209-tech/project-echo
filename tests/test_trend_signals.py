from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from echo.models.source import SourceItem
from echo.models.trend import TrendCandidate
from echo.trend.cross_source import cross_source_confirmation_score
from echo.trend.freshness import freshness_score
from echo.trend.novelty import novelty_score
from echo.trend.relevance import relevance_score
from echo.trend.signal_config import TrendSignalConfig, VelocityWindow
from echo.trend.source_quality import aggregate_source_quality
from echo.trend.velocity import velocity_score

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = TrendSignalConfig()


def _item(source_key: str, minutes_ago: int, title: str = "Title") -> SourceItem:
    return SourceItem(
        source_id=f"{source_key}-{minutes_ago}",
        source_key=source_key,
        url=f"https://example.com/{source_key}/{minutes_ago}",
        source_name=source_key,
        title=title,
        published_at=NOW - timedelta(minutes=minutes_ago),
        retrieved_at=NOW,
        content="body",
        language="en",
        vertical="ai",
    )


# -- freshness ---------------------------------------------------------


def test_freshness_is_near_one_for_brand_new_item() -> None:
    assert freshness_score(NOW, NOW, half_life_hours=6.0) == pytest.approx(1.0)


def test_freshness_is_half_at_one_half_life() -> None:
    published = NOW - timedelta(hours=6)
    assert freshness_score(published, NOW, half_life_hours=6.0) == pytest.approx(0.5, abs=1e-6)


def test_freshness_decays_further_at_two_half_lives() -> None:
    published = NOW - timedelta(hours=12)
    assert freshness_score(published, NOW, half_life_hours=6.0) == pytest.approx(0.25, abs=1e-6)


def test_freshness_clamps_future_timestamp_to_full_score() -> None:
    future = NOW + timedelta(hours=1)
    assert freshness_score(future, NOW, half_life_hours=6.0) == 1.0


def test_freshness_rejects_non_positive_half_life() -> None:
    with pytest.raises(ValueError):
        freshness_score(NOW, NOW, half_life_hours=0)


# -- velocity ---------------------------------------------------------


def test_velocity_is_zero_for_no_items() -> None:
    assert velocity_score([], NOW, CONFIG) == 0.0


def test_velocity_rewards_very_recent_items_over_old_ones() -> None:
    recent = [_item("s", minutes_ago=5)]
    old = [_item("s", minutes_ago=60 * 30)]  # 30 hours old -- outside every window
    assert velocity_score(recent, NOW, CONFIG) > velocity_score(old, NOW, CONFIG)


def test_velocity_many_old_items_does_not_beat_few_recent_items() -> None:
    """A topic with lots of *old* coverage must not out-score a topic with
    a couple of very fresh items -- this is the requirement's explicit
    'old but high volume' guard."""
    many_old = [_item("s", minutes_ago=60 * 30 + i) for i in range(50)]  # all > 24h old
    few_recent = [_item("s", minutes_ago=5), _item("s", minutes_ago=10)]
    assert velocity_score(few_recent, NOW, CONFIG) > velocity_score(many_old, NOW, CONFIG)
    assert velocity_score(many_old, NOW, CONFIG) == 0.0


def test_velocity_score_is_clamped_to_one() -> None:
    swarm = [_item("s", minutes_ago=1) for _ in range(100)]
    assert velocity_score(swarm, NOW, CONFIG) == 1.0


def test_velocity_rejects_non_positive_saturation() -> None:
    bad_config = TrendSignalConfig(velocity_saturation=0)
    with pytest.raises(ValueError):
        velocity_score([_item("s", 1)], NOW, bad_config)


# -- novelty ---------------------------------------------------------


def _trend(topic: str, detected_minutes_ago: int) -> TrendCandidate:
    return TrendCandidate(
        trend_id=f"trend-{topic}",
        trace_id="ECHO-AI-20260809-000001",
        topic=topic,
        detected_at=NOW - timedelta(minutes=detected_minutes_ago),
        velocity=0.5,
        novelty=0.5,
        relevance=0.5,
        vertical="ai",
    )


def test_novelty_is_full_when_no_prior_trends() -> None:
    assert novelty_score("Brand new topic nobody covered", [], NOW, CONFIG) == 1.0


def test_novelty_drops_for_near_identical_prior_topic() -> None:
    prior = [_trend("New open weight LLM claims state of the art reasoning benchmarks", 30)]
    score = novelty_score(
        "New open weight LLM claims state of the art reasoning benchmarks", prior, NOW, CONFIG
    )
    assert score < 0.5


def test_novelty_ignores_prior_trends_outside_lookback_window() -> None:
    long_ago = [_trend("New open weight LLM claims state of the art reasoning benchmarks", 60 * 200)]
    score = novelty_score(
        "New open weight LLM claims state of the art reasoning benchmarks", long_ago, NOW, CONFIG
    )
    assert score == 1.0


def test_novelty_unaffected_by_dissimilar_prior_topic() -> None:
    prior = [_trend("Completely unrelated robotics warehouse story", 30)]
    score = novelty_score("New open weight LLM release", prior, NOW, CONFIG)
    assert score == 1.0


# -- relevance ---------------------------------------------------------


TOPIC_KEYWORDS = {
    "llm": ["LLM", "large language model"],
    "ai_agents": ["AI agent", "autonomous agent"],
}


def test_relevance_scores_zero_with_no_keyword_matches() -> None:
    score, topics = relevance_score("Quarterly earnings beat expectations", TOPIC_KEYWORDS, CONFIG)
    assert score == 0.0
    assert topics == []


def test_relevance_matches_case_insensitively_and_returns_topic() -> None:
    score, topics = relevance_score("A new large language model was released today", TOPIC_KEYWORDS, CONFIG)
    assert score > 0.0
    assert "llm" in topics


def test_relevance_word_boundary_avoids_false_substring_match() -> None:
    # "ai" (as a topic keyword) must not match inside unrelated words like "again" or "chair".
    score, topics = relevance_score(
        "We will try again in a chair factory", {"ai_agents": ["ai"]}, CONFIG
    )
    assert score == 0.0
    assert topics == []


def test_relevance_saturates_at_one() -> None:
    text = "LLM large language model AI agent autonomous agent"
    score, _ = relevance_score(text, TOPIC_KEYWORDS, CONFIG)
    assert score == 1.0


def test_relevance_rejects_non_positive_saturation() -> None:
    bad_config = TrendSignalConfig(relevance_saturation_matches=0)
    with pytest.raises(ValueError):
        relevance_score("LLM", TOPIC_KEYWORDS, bad_config)


# -- source_quality ---------------------------------------------------------


def test_source_quality_averages_distinct_sources() -> None:
    items = [_item("tier_a_source", 1), _item("tier_c_source", 2)]
    reliability = {"tier_a_source": 1.0, "tier_c_source": 0.4}
    assert aggregate_source_quality(items, reliability) == pytest.approx(0.7)


def test_source_quality_repeated_low_tier_source_does_not_drown_out_high_tier() -> None:
    items = [_item("tier_a_source", 1)] + [_item("tier_c_source", i) for i in range(2, 10)]
    reliability = {"tier_a_source": 1.0, "tier_c_source": 0.4}
    # distinct-source average, not per-item weighted -- still (1.0 + 0.4) / 2
    assert aggregate_source_quality(items, reliability) == pytest.approx(0.7)


def test_source_quality_unknown_source_defaults_to_zero() -> None:
    items = [_item("unregistered_source", 1)]
    assert aggregate_source_quality(items, {}) == 0.0


def test_source_quality_empty_items_is_zero() -> None:
    assert aggregate_source_quality([], {}) == 0.0


# -- cross_source_confirmation ---------------------------------------------


def test_cross_source_confirmation_zero_for_single_source() -> None:
    items = [_item("s", 1), _item("s", 2), _item("s", 3)]
    assert cross_source_confirmation_score(items, CONFIG) == 0.0


def test_cross_source_confirmation_increases_with_distinct_sources() -> None:
    two_sources = [_item("a", 1), _item("b", 2)]
    three_sources = [_item("a", 1), _item("b", 2), _item("c", 3)]
    assert cross_source_confirmation_score(three_sources, CONFIG) > cross_source_confirmation_score(
        two_sources, CONFIG
    )


def test_cross_source_confirmation_saturates_at_one() -> None:
    config = TrendSignalConfig(cross_source_saturation=3)
    items = [_item(k, 1) for k in ("a", "b", "c", "d", "e")]
    assert cross_source_confirmation_score(items, config) == 1.0


def test_cross_source_confirmation_rejects_saturation_of_one() -> None:
    bad_config = TrendSignalConfig(cross_source_saturation=1)
    with pytest.raises(ValueError):
        cross_source_confirmation_score([_item("a", 1)], bad_config)


def test_velocity_window_dataclass_is_plain_data() -> None:
    window = VelocityWindow(hours=1.0, weight=2.0)
    assert window.hours == 1.0
    assert window.weight == 2.0
