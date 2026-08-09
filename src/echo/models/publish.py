"""PublishedPost: record of a draft that was actually posted.

STEP 1 does not implement any code path that creates these -- no X API
integration exists yet. The model and storage table exist so later steps
have a stable target to write to.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PublishedPost(BaseModel):
    """A ContentDraft that was published to X."""

    post_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    x_post_id: str = Field(min_length=1)
    published_at: datetime
