"""PerformanceSnapshot: point-in-time engagement metrics for a PublishedPost.

STEP 1 does not implement any collector for these -- the model and storage
table exist so later steps have a stable target to write to.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PerformanceSnapshot(BaseModel):
    """A single measurement of a published post's performance."""

    snapshot_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    captured_at: datetime
    impressions: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    replies: int = Field(default=0, ge=0)
    reposts: int = Field(default=0, ge=0)
    bookmarks: int = Field(default=0, ge=0)
    profile_visits: int = Field(default=0, ge=0)
    followers_gained: int = Field(default=0, ge=0)
    link_clicks: int = Field(default=0, ge=0)
