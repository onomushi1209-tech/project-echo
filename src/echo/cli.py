"""Echo CLI.

    echo init            - initialize the SQLite database
    echo demo            - run dummy data through DISCOVER..COMPLIANCE and queue for review
    echo review          - inspect / decide on the Human Review Gate queue
    echo sources list    - list the Source Registry for a vertical
    echo sources check   - check that enabled sources are currently reachable
    echo ingest          - fetch -> normalize -> deduplicate -> store SourceItems
    echo trends detect   - cluster stored SourceItems into TrendCandidates
    echo trends list     - list persisted TrendCandidates

No X posting, no external AI APIs -- STEP 1/2 Foundation only.
"""

from __future__ import annotations

import typer

from echo.brains import default_brains
from echo.brains.real_trend_brain import RealTrendBrain
from echo.config.settings import get_settings
from echo.core.ids import IdFactory
from echo.core.pipeline import EchoPipeline, PipelineDependencies
from echo.core.trace import TraceIDGenerator
from echo.models.enums import DecisionType, FetchStatus, RejectReason, SourceType
from echo.review.service import pending_queue, record_decision
from echo.source.adapters import ADAPTERS, AdapterError, load_fixture
from echo.source.http_client import fetch as http_fetch
from echo.source.ingest import ingest_sources
from echo.source.reliability import reliability_score
from echo.source.registry import enabled_sources, load_source_registry
from echo.storage.repository import EchoRepository
from echo.trend.service import partition_trends_by_novelty
from echo.verticals.ai.dummy_data import sample_sources
from echo.verticals.registry import load_vertical_config

app = typer.Typer(help="Project Echo -- AI Media Operating System (STEP 1/2 Foundation)")
review_app = typer.Typer(help="Inspect and decide on the Human Review Gate queue.")
sources_app = typer.Typer(help="Inspect the Source Registry for a vertical.")
trends_app = typer.Typer(help="Detect and inspect TrendCandidates from stored SourceItems.")
app.add_typer(review_app, name="review")
app.add_typer(sources_app, name="sources")
app.add_typer(trends_app, name="trends")


@app.command()
def init() -> None:
    """Initialize the SQLite database."""
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    repository.initialize()
    typer.echo(f"Initialized database at {settings.database_path}")


@app.command()
def demo(vertical: str = typer.Option("ai", help="Vertical id to run the demo for.")) -> None:
    """Run dummy AI-vertical data through DISCOVER -> RESEARCH -> SCORE ->
    threshold -> CREATE -> COMPLIANCE, queuing anything that passes for
    human review. Uses only offline dummy data and dummy brains -- no
    external AI APIs, no real trend scraping, no X posting.
    """
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    repository.initialize()

    vertical_config = load_vertical_config(vertical, config_dir=settings.config_dir)

    if vertical_config.id != "ai":
        typer.echo(f"No dummy data source is registered for vertical '{vertical_config.id}' yet.")
        raise typer.Exit(code=1)
    sources = sample_sources()

    trace_generator = TraceIDGenerator(
        vertical=vertical_config.id,
        sequence_provider=repository.next_trace_sequence,
    )
    deps = PipelineDependencies(
        brains=default_brains(),
        repository=repository,
        trace_generator=trace_generator,
        score_threshold=settings.score_threshold,
    )
    results = EchoPipeline(deps).run(sources)

    typer.echo(f"Discovered {len(results)} trend candidate(s) for vertical '{vertical_config.id}':\n")
    for item in results:
        status = "QUEUED FOR REVIEW" if item.draft else "BELOW THRESHOLD"
        typer.echo(f"[{item.trend.trace_id}] {item.trend.topic}")
        typer.echo(f"    final_score={item.score.final_score:.2f}  threshold={deps.score_threshold:.2f}  -> {status}")
        if item.draft:
            typer.echo(f"    draft_id={item.draft.draft_id}  compliance_flags={item.draft.compliance_flags}")
        typer.echo("")

    typer.echo("Run `echo review` to see the Human Review Gate queue.")


@review_app.callback(invoke_without_command=True)
def review_main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        review_list()


@review_app.command("list")
def review_list() -> None:
    """List drafts awaiting a Human Review Gate decision."""
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    drafts = pending_queue(repository)

    if not drafts:
        typer.echo("Review queue is empty.")
        return

    typer.echo(f"{len(drafts)} draft(s) awaiting review:\n")
    for draft in drafts:
        typer.echo(f"[{draft.draft_id}] ({draft.trace_id}) {draft.hook}")
        typer.echo(f"    type={draft.content_type.value}  confidence={draft.confidence:.2f}")
        if draft.compliance_flags:
            typer.echo(f"    compliance_flags={draft.compliance_flags}")
        typer.echo("")


@review_app.command("decide")
def review_decide(
    draft_id: str = typer.Argument(..., help="Draft id to record a decision for."),
    decision: DecisionType = typer.Argument(..., help="approve | reject | edit | skip"),
    reason: RejectReason | None = typer.Option(
        None, "--reason", help="Required when decision is 'reject'."
    ),
    note: str | None = typer.Option(None, "--note", help="Optional free-text reviewer note."),
) -> None:
    """Record an APPROVE / REJECT / EDIT / SKIP decision for a draft.

    This only records the decision -- STEP 1 does not publish to X.
    """
    settings = get_settings()
    repository = EchoRepository(settings.database_path)

    draft = repository.get_draft(draft_id)
    if draft is None:
        typer.echo(f"No draft found with id '{draft_id}'.")
        raise typer.Exit(code=1)

    if decision == DecisionType.REJECT and reason is None:
        typer.echo("`--reason` is required when decision is 'reject'.")
        raise typer.Exit(code=1)

    review = record_decision(
        repository=repository,
        draft=draft,
        decision=decision,
        review_reason=reason,
        reviewer_note=note,
    )
    typer.echo(f"Recorded {review.decision.value.upper()} for draft {draft_id} (review_id={review.review_id}).")


@sources_app.command("list")
def sources_list(vertical: str = typer.Option("ai", help="Vertical id.")) -> None:
    """List registered sources (enabled and disabled) for a vertical."""
    settings = get_settings()
    registry = load_source_registry(vertical, config_dir=settings.config_dir)

    if not registry:
        typer.echo(f"No sources registered for vertical '{vertical}'.")
        return

    typer.echo(f"{len(registry)} source(s) registered for vertical '{vertical}':\n")
    for source in registry:
        status = "enabled" if source.enabled else "disabled"
        primary = " (primary)" if source.primary_source else ""
        typer.echo(
            f"[{source.id}] {source.name}{primary} -- {source.source_type.value} "
            f"tier={source.reliability_tier.value} {status}"
        )
        typer.echo(f"    url={source.url}")


@sources_app.command("check")
def sources_check(vertical: str = typer.Option("ai", help="Vertical id.")) -> None:
    """Check that every *enabled* source is currently reachable.

    Makes one real HTTP request per enabled RSS/ATOM/JSON source (bounded
    by the fetch layer's own timeout/retry cap -- no extra retry loop, no
    bypass of robots/WAF/rate limits). STATIC_FIXTURE sources are checked
    by reading their local fixture file instead of the network.
    """
    settings = get_settings()
    sources = enabled_sources(vertical, config_dir=settings.config_dir)

    if not sources:
        typer.echo(f"No enabled sources for vertical '{vertical}'.")
        return

    for source in sources:
        if source.source_type == SourceType.STATIC_FIXTURE:
            fixture_path = settings.fixtures_dir / f"{source.id}.json"
            try:
                records = load_fixture(fixture_path)
                typer.echo(f"[OK] {source.id}: fixture has {len(records)} item(s) ({fixture_path})")
            except AdapterError as exc:
                typer.echo(f"[FAIL] {source.id}: {exc}")
            continue

        outcome = http_fetch(str(source.url))
        if not outcome.ok:
            typer.echo(f"[FAIL] {source.id}: {outcome.error_type} -- {outcome.message}")
            continue
        try:
            records = ADAPTERS[source.source_type](outcome.body or b"")
            typer.echo(f"[OK] {source.id}: HTTP {outcome.status_code}, {len(records)} item(s) parsed")
        except AdapterError as exc:
            typer.echo(f"[FAIL] {source.id}: fetched but failed to parse -- {exc}")


@app.command()
def ingest(
    vertical: str = typer.Option("ai", help="Vertical id to ingest sources for."),
    fixture: bool = typer.Option(
        False, "--fixture", help="Offline mode: only ingest STATIC_FIXTURE sources, no network access."
    ),
) -> None:
    """Fetch enabled sources -> normalize -> deduplicate -> store SourceItems.

    Without --fixture, this makes real HTTP requests to enabled sources
    (see `echo sources list`). With --fixture, only STATIC_FIXTURE sources
    are used -- fully offline and reproducible. One source failing never
    stops ingestion of the others.
    """
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    repository.initialize()

    sources = enabled_sources(vertical, config_dir=settings.config_dir)
    if fixture:
        sources = [s for s in sources if s.source_type == SourceType.STATIC_FIXTURE]

    if not sources:
        typer.echo("No matching enabled sources to ingest.")
        raise typer.Exit(code=1)

    report = ingest_sources(sources, repository, fixtures_dir=settings.fixtures_dir)

    for source_report in report.per_source:
        if source_report.status == FetchStatus.FAILED:
            typer.echo(f"[FAILED] {source_report.source_key}: {source_report.error_type} -- {source_report.error_message}")
        else:
            typer.echo(
                f"[OK] {source_report.source_key}: fetched={source_report.items_fetched} "
                f"normalized={source_report.items_normalized} "
                f"age_filtered={source_report.items_age_filtered} "
                f"limit_filtered={source_report.items_item_limit_filtered} "
                f"duplicates={source_report.items_deduplicated} stored={source_report.items_stored}"
            )

    typer.echo(
        f"\nTotal stored: {report.total_stored}  Total deduplicated: {report.total_deduplicated}  "
        f"Total age-filtered: {report.total_age_filtered}  Total limit-filtered: {report.total_item_limit_filtered}"
    )


@trends_app.command("detect")
def trends_detect(vertical: str = typer.Option("ai", help="Vertical id.")) -> None:
    """Cluster stored SourceItems into TrendCandidates using RealTrendBrain.

    Run `echo ingest` (or `echo ingest --fixture`) first to have
    SourceItems to cluster.
    """
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    repository.initialize()

    vertical_config = load_vertical_config(vertical, config_dir=settings.config_dir)
    source_registry = load_source_registry(vertical, config_dir=settings.config_dir)
    source_reliability = {s.id: reliability_score(s.reliability_tier) for s in source_registry}

    source_items = repository.list_source_items(vertical=vertical)
    if not source_items:
        typer.echo("No stored SourceItems for this vertical -- run `echo ingest` first.")
        raise typer.Exit(code=1)

    recent_trends = repository.list_trends()
    trace_generator = TraceIDGenerator(
        vertical=vertical_config.id, sequence_provider=repository.next_trace_sequence
    )
    ids = IdFactory(trace_generator)
    signal_config = settings.trend_signal_config()
    brain = RealTrendBrain(
        topic_keywords=vertical_config.topic_keywords,
        source_reliability=source_reliability,
        recent_trends=recent_trends,
        signal_config=signal_config,
    )

    candidates = brain.detect(source_items, vertical_config.id, ids)
    to_persist, skipped_count = partition_trends_by_novelty(
        candidates, signal_config.trend_persistence_novelty_threshold
    )
    for candidate in to_persist:
        repository.save_trend(candidate)

    typer.echo(
        f"Detected {len(candidates)} trend candidate(s) from {len(source_items)} source item(s): "
        f"{len(to_persist)} persisted, {skipped_count} skipped (already-known, low novelty).\n"
    )
    for candidate in candidates:
        persisted = candidate in to_persist
        status = "" if persisted else "  [SKIPPED -- already-known, low novelty, not persisted]"
        typer.echo(f"[{candidate.trace_id}] {candidate.topic}{status}")
        typer.echo(
            f"    freshness={candidate.freshness:.2f} velocity={candidate.velocity:.2f} "
            f"novelty={candidate.novelty:.2f} relevance={candidate.relevance:.2f}"
        )
        typer.echo(
            f"    source_quality={candidate.source_quality:.2f} source_count={candidate.source_count} "
            f"cross_source_confirmation={candidate.cross_source_confirmation:.2f}"
        )
        typer.echo("")


@trends_app.command("list")
def trends_list() -> None:
    """List all persisted TrendCandidates."""
    settings = get_settings()
    repository = EchoRepository(settings.database_path)
    candidates = repository.list_trends()

    if not candidates:
        typer.echo("No trend candidates stored yet.")
        return

    typer.echo(f"{len(candidates)} trend candidate(s):\n")
    for candidate in candidates:
        typer.echo(f"[{candidate.trace_id}] {candidate.topic}")
        typer.echo(
            f"    velocity={candidate.velocity:.2f} novelty={candidate.novelty:.2f} "
            f"relevance={candidate.relevance:.2f} source_count={candidate.source_count}"
        )
        typer.echo("")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
