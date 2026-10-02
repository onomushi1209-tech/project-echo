"""Source-neutral discovery intent and observations; no HTTP implementation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Self

from pydantic import Field, model_validator

from echo.models.affiliate import AffiliateModel, EvidenceStatus, ProductCandidate


class DiscoverySource(str, Enum):
    SEARCH = "search"
    RANKING = "ranking"
    GENRES = "genres"


class DiscoveryIdentityMismatch(RuntimeError):
    """Fixed, source-neutral diagnostic; never includes the returned identity."""


class HydrationOutcome(AffiliateModel):
    provider_item_id: str = Field(repr=False)
    status: Literal["success", "not_found", "identity_mismatch", "out_of_stock", "missing_exact_price", "availability_unknown"]
    affiliate_destination_present: bool = False


class HydrationReport(AffiliateModel):
    selected_count: int = Field(default=0, ge=0, le=5)
    requests: int = Field(default=0, ge=0, le=5)
    skipped_current_search: int = Field(default=0, ge=0)
    outcomes: tuple[HydrationOutcome, ...] = ()


class DiscoveryQuery(AffiliateModel):
    source: DiscoverySource = DiscoverySource.SEARCH
    keyword: str | None = Field(default=None, min_length=1, max_length=128)
    category_id: str | None = Field(default=None, pattern=r"^[0-9]{1,18}$")
    provider_item_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$")
    merchant_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    limit: int = Field(default=30, strict=True, ge=1, le=30)
    page: int = Field(default=1, strict=True, ge=1, le=100)
    sort: Literal["relevance", "price_asc", "price_desc", "reviews_desc"] = "relevance"
    available_only: bool = True
    minimum_price: int | None = Field(default=None, strict=True, ge=1, le=999999998)
    maximum_price: int | None = Field(default=None, strict=True, ge=1, le=999999998)
    reviews_only: bool = False
    category: str = Field(default="unclassified", min_length=1, max_length=80)
    lifestyle_context: str | None = Field(default=None, min_length=1, max_length=80)
    complementary_role: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def _intent(self) -> Self:
        if self.keyword is not None:
            if self.keyword != self.keyword.strip() or len(self.keyword.encode("utf-8")) > 128:
                raise ValueError("keyword must be trimmed and at most 128 UTF-8 bytes")
            for word in self.keyword.split(" "):
                if not word or any(ord(c) < 32 for c in word):
                    raise ValueError("keyword tokens must be nonempty printable text")
                if len(word) == 1 and (word.isascii() or "\u3040" <= word <= "\u30ff" or not word.isalnum()):
                    raise ValueError("unsupported one-character keyword")
        if self.minimum_price is not None and self.maximum_price is not None and self.maximum_price <= self.minimum_price:
            raise ValueError("maximum price must exceed minimum price")
        if self.source == DiscoverySource.SEARCH:
            if not any((self.keyword, self.category_id, self.provider_item_id, self.merchant_id)):
                raise ValueError("search needs an explicit selector")
        else:
            if any((self.keyword, self.provider_item_id, self.merchant_id, self.minimum_price,
                    self.maximum_price, self.reviews_only, self.sort != "relevance")):
                raise ValueError("search-only options cannot be used with this source")
            if self.source == DiscoverySource.RANKING and self.page > 34:
                raise ValueError("ranking page must be in 1..34")
            if self.source == DiscoverySource.GENRES and (self.category_id is None or self.page != 1):
                raise ValueError("genre lookup needs a category ID and page 1; root is 0")
        return self


class SourceAssetReference(AffiliateModel):
    url: str = Field(repr=False)
    source_field: str
    status: EvidenceStatus
    rights_status: Literal["unknown"] = "unknown"
    transformation_rights_proven: Literal[False] = False


class ProviderObservation(AffiliateModel):
    candidate: ProductCandidate = Field(repr=False)
    query: DiscoveryQuery
    source: DiscoverySource
    observed_at: datetime
    source_url: str | None = Field(default=None, repr=False)
    returned_affiliate_url: str | None = Field(default=None, repr=False)
    assets: tuple[SourceAssetReference, ...] = Field(default=(), repr=False)
    shop_name: str | None = None
    shop_code: str | None = None
    genre_id: str | None = None
    source_updated_at_raw: str | None = None
    ranking_snapshot_at: datetime | None = None
    raw_timing: tuple[tuple[str, str], ...] = ()
    normalization_notes: tuple[str, ...] = ()


class DiscoveryPage(AffiliateModel):
    observations: tuple[ProviderObservation, ...] = Field(default=(), repr=False)
    page: int = Field(ge=1)
    total_pages: int | None = Field(default=None, ge=0, le=100)
    total_items: int | None = Field(default=None, ge=0)
    not_found: bool = False


class GenreNode(AffiliateModel):
    category_id: str
    name: str
    level: int = Field(strict=True, ge=0)


class GenreResult(AffiliateModel):
    current: GenreNode | None = None
    ancestors: tuple[GenreNode, ...] = ()
    siblings: tuple[GenreNode, ...] = ()
    children: tuple[GenreNode, ...] = ()
    not_found: bool = False
