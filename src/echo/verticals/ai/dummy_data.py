"""Dummy AI-vertical SourceItems for ``echo demo`` and tests.

Static, offline placeholder data -- no scraping, no external APIs. Real
source ingestion is out of scope for STEP 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from echo.models.source import SourceItem

_VERTICAL = "ai"

_RAW_ITEMS = [
    {
        "source_id": "ai-src-001",
        "url": "https://example.com/echo/ai/sample-1",
        "source_name": "Echo Sample Feed",
        "title": "New open-weight LLM claims state-of-the-art reasoning benchmarks",
        "content": (
            "A research lab released a new open-weight large language model, "
            "reporting state-of-the-art results on several reasoning benchmarks. "
            "The release includes model weights and a technical report."
        ),
        "hours_ago": 2,
    },
    {
        "source_id": "ai-src-002",
        "url": "https://example.com/echo/ai/sample-2",
        "source_name": "Echo Sample Feed",
        "title": "AI agent framework adds native tool-use memory across sessions",
        "content": (
            "A widely used AI agent framework shipped an update adding persistent, "
            "cross-session memory for tool use, aimed at long-running autonomous tasks."
        ),
        "hours_ago": 5,
    },
    {
        "source_id": "ai-src-003",
        "url": "https://example.com/echo/ai/sample-3",
        "source_name": "Echo Sample Feed",
        "title": "Robotics startup demonstrates warehouse robot trained with AI agents",
        "content": (
            "A robotics startup published a demo of a warehouse picking robot whose "
            "control policy was trained using an AI agent-based simulation pipeline."
        ),
        "hours_ago": 9,
    },
]


def sample_sources(retrieved_at: datetime | None = None) -> list[SourceItem]:
    """Deterministic, offline sample SourceItems for the AI vertical."""
    retrieved = retrieved_at or datetime.now(timezone.utc)
    return [
        SourceItem(
            source_id=item["source_id"],
            source_key="dummy_fixture",
            url=item["url"],
            source_name=item["source_name"],
            title=item["title"],
            published_at=retrieved - timedelta(hours=item["hours_ago"]),
            retrieved_at=retrieved,
            content=item["content"],
            language="en",
            vertical=_VERTICAL,
        )
        for item in _RAW_ITEMS
    ]
