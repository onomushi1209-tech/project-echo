from __future__ import annotations

from datetime import datetime, timezone

from echo.brains import default_brains
from echo.core.pipeline import EchoPipeline, PipelineDependencies
from echo.core.trace import TraceIDGenerator
from echo.storage.repository import EchoRepository
from echo.verticals.ai.dummy_data import sample_sources

FIXED_NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


def _deps(repository: EchoRepository, score_threshold: float) -> PipelineDependencies:
    return PipelineDependencies(
        brains=default_brains(),
        repository=repository,
        trace_generator=TraceIDGenerator(
            vertical="ai", sequence_provider=repository.next_trace_sequence
        ),
        score_threshold=score_threshold,
    )


def test_pipeline_runs_all_stages_and_persists_when_threshold_is_low(
    repository: EchoRepository,
) -> None:
    sources = sample_sources(retrieved_at=FIXED_NOW)
    deps = _deps(repository, score_threshold=0.0)

    results = EchoPipeline(deps).run(sources)

    assert len(results) == len(sources)
    for item in results:
        assert item.passed_threshold is True
        assert item.draft is not None

        # every stage's output was actually persisted, not just returned
        assert repository.get_trend(item.trend.trend_id) is not None
        assert repository.get_research_by_trend(item.trend.trend_id) is not None
        assert repository.get_score_by_trend(item.trend.trend_id) is not None
        assert repository.get_draft(item.draft.draft_id) is not None

    # drafts reached the Human Review Gate queue
    pending_ids = {d.draft_id for d in repository.list_drafts_pending_review()}
    assert pending_ids == {item.draft.draft_id for item in results}


def test_pipeline_stops_before_create_when_threshold_is_unreachable(
    repository: EchoRepository,
) -> None:
    sources = sample_sources(retrieved_at=FIXED_NOW)
    deps = _deps(repository, score_threshold=1.01)

    results = EchoPipeline(deps).run(sources)

    assert len(results) == len(sources)
    for item in results:
        assert item.passed_threshold is False
        assert item.draft is None
        # trend/research/score are still persisted for audit purposes
        assert repository.get_trend(item.trend.trend_id) is not None
        assert repository.get_score_by_trend(item.trend.trend_id) is not None

    assert repository.list_drafts_pending_review() == []


def test_pipeline_assigns_distinct_sequential_trace_ids(repository: EchoRepository) -> None:
    sources = sample_sources(retrieved_at=FIXED_NOW)
    deps = _deps(repository, score_threshold=0.0)

    results = EchoPipeline(deps).run(sources)

    trace_ids = [item.trend.trace_id for item in results]
    assert len(trace_ids) == len(set(trace_ids))
    assert all(t.startswith("ECHO-AI-") for t in trace_ids)


def test_pipeline_carries_one_trace_id_through_every_stage(repository: EchoRepository) -> None:
    sources = sample_sources(retrieved_at=FIXED_NOW)
    deps = _deps(repository, score_threshold=0.0)

    results = EchoPipeline(deps).run(sources)

    for item in results:
        assert item.research.trace_id == item.trend.trace_id
        assert item.score.trace_id == item.trend.trace_id
        assert item.draft is not None
        assert item.draft.trace_id == item.trend.trace_id
