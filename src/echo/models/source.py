"""SourceItem: a single piece of raw material discovered from the outside world."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceItem(BaseModel):
    """A raw item (article, post, paper, etc.) collected for a vertical."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    url: HttpUrl
    source_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    published_at: datetime
    retrieved_at: datetime
    content: str = ""
    language: str = Field(default="en", min_length=2, max_length=8)
    vertical: str = Field(min_length=1)
