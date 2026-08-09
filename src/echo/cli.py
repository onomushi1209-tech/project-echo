"""Echo CLI.

    echo init    - initialize the SQLite database
    echo demo    - run dummy data through DISCOVER..COMPLIANCE and queue for review
    echo review  - inspect / decide on the Human Review Gate queue

No X posting, no external AI APIs -- STEP 1 Foundation only.
"""

from __future__ import annotations

import typer

from echo.brains import default_brains
from echo.config.settings import get_settings
from echo.core.pipeline import EchoPipeline, PipelineDependencies
from echo.core.trace import TraceIDGenerator
from echo.models.enums import DecisionType, RejectReason
from echo.review.service import pending_queue, record_decision
from echo.storage.repository import EchoRepository
from echo.verticals.ai.dummy_data import sample_sources
from echo.verticals.registry import load_vertical_config

app = typer.Typer(help="Project Echo -- AI Media Operating System (STEP 1 Foundation)")
review_app = typer.Typer(help="Inspect and decide on the Human Review Gate queue.")
app.add_typer(review_app, name="review")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
