"""Ingest orchestration: Source Registry -> Fetch -> Normalize -> Deduplicate -> persistence.

Each source is processed independently. A single source's failure (fetch
error, malformed response, unsupported type, ...) is caught, persisted to
``source_failures``, and never stops ingestion of the remaining sources --
see ``_ingest_one_source``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from echo.models.enums import FetchStatus, SourceType
from echo.models.source import SourceItem
from echo.source.adapters import ADAPTERS, AdapterError, load_fixture
from echo.source.config import SourceConfig
from echo.source.dedup import DedupDecision, Deduplicator
from echo.source.http_client import fetch
from echo.source.normalize import normalize_record
from echo.source.records import RawRecord
from echo.storage.repository import EchoRepository


@dataclass
class SourceIngestReport:
    source_key: str
    status: FetchStatus
    items_fetched: int = 0
    items_normalized: int = 0
    items_age_filtered: int = 0
    items_item_limit_filtered: int = 0
    items_deduplicated: int = 0
    items_stored: int = 0
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class IngestReport:
    per_source: list[SourceIngestReport] = field(default_factory=list)

    @property
    def total_stored(self) -> int:
        return sum(r.items_stored for r in self.per_source)

    @property
    def total_deduplicated(self) -> int:
        return sum(r.items_deduplicated for r in self.per_source)

    @property
    def total_age_filtered(self) -> int:
        return sum(r.items_age_filtered for r in self.per_source)

    @property
    def total_item_limit_filtered(self) -> int:
        return sum(r.items_item_limit_filtered for r in self.per_source)

    @property
    def total_failed_sources(self) -> int:
        return sum(1 for r in self.per_source if r.status == FetchStatus.FAILED)


class _IngestFailure(Exception):
    def __init__(self, stage: str, error_type: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.error_type = error_type
        self.message = message


def ingest_sources(
    sources: list[SourceConfig],
    repository: EchoRepository,
    *,
    fixtures_dir: Path | None = None,
    now: datetime | None = None,
) -> IngestReport:
    """Run the full ingest pipeline for every given (already-filtered,
    e.g. enabled-only) source. Always returns a report -- never raises."""
    retrieved_at = now or datetime.now(timezone.utc)
    dedup = Deduplicator(
        seen_canonical_urls=repository.list_known_canonical_urls(),
        seen_fingerprints=repository.list_known_content_fingerprints(),
    )

    report = IngestReport()
    for source in sources:
        report.per_source.append(_ingest_one_source(source, repository, dedup, retrieved_at, fixtures_dir))
    return report


def _ingest_one_source(
    source: SourceConfig,
    repository: EchoRepository,
    dedup: Deduplicator,
    retrieved_at: datetime,
    fixtures_dir: Path | None,
) -> SourceIngestReport:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(timezone.utc)

    try:
        raw_records = _fetch_and_parse(source, fixtures_dir)
    except _IngestFailure as failure:
        repository.save_source_failure(
            failure_id=f"failure-{uuid.uuid4().hex[:12]}",
            source_key=source.id,
            vertical=source.vertical,
            occurred_at=datetime.now(timezone.utc),
            stage=failure.stage,
            error_type=failure.error_type,
            message=failure.message,
        )
        repository.save_source_fetch_run(
            run_id=run_id,
            source_key=source.id,
            vertical=source.vertical,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=FetchStatus.FAILED,
            items_fetched=0,
            items_normalized=0,
            items_age_filtered=0,
            items_item_limit_filtered=0,
            items_deduplicated=0,
        )
        return SourceIngestReport(
            source_key=source.id,
            status=FetchStatus.FAILED,
            error_type=failure.error_type,
            error_message=failure.message,
        )

    items_fetched = len(raw_records)
    normalized_items: list[SourceItem] = []
    for record in raw_records:
        result = normalize_record(record, source, retrieved_at)
        if result.item is None:
            continue
        normalized_items.append(result.item)
    items_normalized = len(normalized_items)

    bounded_items, items_age_filtered, items_item_limit_filtered = _apply_source_bounds(
        normalized_items, source, retrieved_at
    )

    items_deduplicated = 0
    items_stored = 0
    for item in bounded_items:
        outcome = dedup.process(item)
        if outcome.decision != DedupDecision.KEEP:
            items_deduplicated += 1
            continue

        repository.save_source_item(
            item, canonical_url=outcome.canonical_url, content_fingerprint=outcome.fingerprint
        )
        items_stored += 1

    repository.save_source_fetch_run(
        run_id=run_id,
        source_key=source.id,
        vertical=source.vertical,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        status=FetchStatus.SUCCESS,
        items_fetched=items_fetched,
        items_normalized=items_normalized,
        items_age_filtered=items_age_filtered,
        items_item_limit_filtered=items_item_limit_filtered,
        items_deduplicated=items_deduplicated,
    )
    return SourceIngestReport(
        source_key=source.id,
        status=FetchStatus.SUCCESS,
        items_fetched=items_fetched,
        items_normalized=items_normalized,
        items_age_filtered=items_age_filtered,
        items_item_limit_filtered=items_item_limit_filtered,
        items_deduplicated=items_deduplicated,
        items_stored=items_stored,
    )


def _apply_source_bounds(
    items: list[SourceItem], source: SourceConfig, retrieved_at: datetime
) -> tuple[list[SourceItem], int, int]:
    """Enforce ``SourceConfig.max_item_age_hours`` / ``max_items_per_fetch``
    after normalization -- deliberately not in a format adapter (parser),
    which knows nothing about a source's config.

    Items whose timestamp fell back to ``retrieved_at`` (missing/malformed
    ``published_at`` -- see ``echo.source.normalize``) have age 0 at the
    moment they're normalized, so they are never dropped by the age bound;
    this keeps the existing fallback policy intact rather than treating a
    missing timestamp as "old".

    Returns ``(kept_items, age_filtered_count, item_limit_filtered_count)``.
    ``kept_items`` is sorted newest-first (by ``published_at``) so the
    per-fetch cap keeps the newest items and ordering is deterministic for
    a given input.
    """
    if source.max_item_age_hours is None:
        within_age = list(items)
        age_filtered = 0
    else:
        within_age = []
        age_filtered = 0
        for item in items:
            age_hours = (retrieved_at - item.published_at).total_seconds() / 3600.0
            if age_hours > source.max_item_age_hours:
                age_filtered += 1
            else:
                within_age.append(item)

    ordered = sorted(within_age, key=lambda item: item.published_at, reverse=True)

    if source.max_items_per_fetch is None or len(ordered) <= source.max_items_per_fetch:
        return ordered, age_filtered, 0

    kept = ordered[: source.max_items_per_fetch]
    item_limit_filtered = len(ordered) - len(kept)
    return kept, age_filtered, item_limit_filtered


def _fetch_and_parse(source: SourceConfig, fixtures_dir: Path | None) -> list[RawRecord]:
    if source.source_type == SourceType.STATIC_FIXTURE:
        if fixtures_dir is None:
            raise _IngestFailure("fetch", "missing_fixtures_dir", "STATIC_FIXTURE source requires fixtures_dir")
        fixture_path = fixtures_dir / f"{source.id}.json"
        try:
            return load_fixture(fixture_path)
        except AdapterError as exc:
            raise _IngestFailure("parse", "adapter_error", str(exc)) from exc

    outcome = fetch(str(source.url))
    if not outcome.ok:
        raise _IngestFailure("fetch", outcome.error_type or "fetch_failed", outcome.message)

    adapter = ADAPTERS.get(source.source_type)
    if adapter is None:
        raise _IngestFailure("parse", "unsupported_source_type", f"no adapter for {source.source_type}")

    try:
        return adapter(outcome.body or b"")
    except AdapterError as exc:
        raise _IngestFailure("parse", "adapter_error", str(exc)) from exc
