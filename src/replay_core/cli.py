"""Command line for recording, replaying, and uploading results.

``record`` and ``run`` work offline. ``projects create`` and ``upload`` talk to
the hosted API that stores the same JSON files without re-diffing them.
"""

import asyncio
import json
from pathlib import Path
from typing import NoReturn

import typer

from replay_core.client import ApiError, ReplayApiClient
from replay_core.compare import build_report
from replay_core.har import HarError, import_har_file
from replay_core.loader import (
    LoadError,
    load_baseline,
    load_report,
    load_requests,
    save_baseline,
    save_report,
    save_requests,
    serialize,
)
from replay_core.models import Baseline, Diff, Report, RequestCollection
from replay_core.runner import Attempt, TargetError, UnsafeRequestsError, execute

app = typer.Typer(no_args_is_help=True, add_completion=False)
projects_app = typer.Typer(no_args_is_help=True, add_completion=False, help="Manage hosted projects.")
app.add_typer(projects_app, name="projects")


class UsageError(Exception):
    """The command line itself was invalid."""


@app.command()
def record(
    target: str = typer.Option(..., "--target", help="Base URL to send the request file to."),
    requests_path: Path = typer.Option(
        ...,
        "--requests",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON file of requests to send.",
    ),
    out: Path = typer.Option(..., "--out", dir_okay=False, help="Where to write the baseline JSON."),
    concurrency: int = typer.Option(10, "--concurrency", help="Maximum in-flight requests."),
    timeout: float = typer.Option(10.0, "--timeout", help="Per-request timeout in seconds."),
    unsafe: bool = typer.Option(
        False,
        "--unsafe",
        help="Allow POST, PUT, PATCH, and DELETE. Replay can change server state.",
    ),
) -> None:
    """Send a request file and save sanitized responses as a baseline."""

    _check_limits(concurrency, timeout)
    collection = _load_collection(requests_path)
    attempts = _send(target, collection, concurrency, timeout, unsafe)
    save_baseline(
        out,
        Baseline(
            name=collection.name,
            target=target,
            exchanges=[item.exchange for item in attempts],
        ),
    )
    failed = [item.exchange for item in attempts if item.exchange.error]
    if failed:
        typer.echo(
            f"recorded {len(attempts) - len(failed)} of {len(attempts)}; {len(failed)} failed",
            err=True,
        )
        for exchange in failed:
            typer.echo(f"  {exchange.id}: {exchange.error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"recorded {len(attempts)} responses to {out}")


@app.command()
def run(
    target: str = typer.Option(..., "--target", help="Base URL of the API version to check."),
    requests_path: Path = typer.Option(
        ...,
        "--requests",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON file of requests to send.",
    ),
    baseline_path: Path = typer.Option(
        ...,
        "--baseline",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Baseline JSON previously written by record.",
    ),
    out: Path = typer.Option(..., "--out", dir_okay=False, help="Where to write the JSON report."),
    output_format: str = typer.Option("text", "--format", help="stdout format: text or json."),
    concurrency: int = typer.Option(10, "--concurrency", help="Maximum in-flight requests."),
    timeout: float = typer.Option(10.0, "--timeout", help="Per-request timeout in seconds."),
    unsafe: bool = typer.Option(
        False,
        "--unsafe",
        help="Allow POST, PUT, PATCH, and DELETE. Replay can change server state.",
    ),
) -> None:
    """Replay a request file against a target and compare it to a baseline."""

    if output_format not in {"text", "json"}:
        _abort(UsageError("--format must be text or json"))
    _check_limits(concurrency, timeout)
    collection = _load_collection(requests_path)
    try:
        baseline = load_baseline(baseline_path)
    except LoadError as exc:
        _abort(exc)
    attempts = _send(target, collection, concurrency, timeout, unsafe)
    report = build_report(
        collection.name,
        collection.requests,
        baseline.exchanges,
        [item.exchange for item in attempts],
        collection.ignore,
    )
    save_report(out, report)
    rendered = serialize(report) if output_format == "json" else render_text(report)
    typer.echo(rendered, nl=False)
    if report.summary.regressed or report.summary.errored:
        raise typer.Exit(code=1)


@app.command("import-har")
def import_har(
    har_path: Path = typer.Option(
        ...,
        "--har",
        exists=True,
        dir_okay=False,
        readable=True,
        help="HAR file exported from Chrome, Firefox, or Postman.",
    ),
    out: Path = typer.Option(..., "--out", dir_okay=False, help="Where to write the request JSON."),
    name: str = typer.Option("imported", "--name", help="Name stored in the request collection."),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Optional API base URL. Paths are stored relative to this prefix.",
    ),
) -> None:
    """Convert a HAR capture into the request-file schema used by record/run."""

    try:
        collection = import_har_file(har_path, name=name, base_url=base_url)
    except HarError as exc:
        _abort(exc)
    save_requests(out, collection)
    typer.echo(f"imported {len(collection.requests)} requests to {out}")


@projects_app.command("create")
def projects_create(
    name: str = typer.Option(..., "--name", help="Human-readable project name."),
    api_url: str = typer.Option(..., "--api-url", help="Base URL of the hosted API."),
) -> None:
    """Create a hosted project and print its id and one-time API token."""

    client = ReplayApiClient(api_url)
    try:
        created = client.create_project(name)
    except ApiError as exc:
        _abort(exc)
    typer.echo(f"project_id={created['id']}")
    typer.echo(f"slug={created['slug']}")
    typer.echo(f"token={created['token']}")
    typer.echo("Store the token now. The API only keeps a hash.", err=True)


@app.command()
def upload(
    api_url: str = typer.Option(..., "--api-url", help="Base URL of the hosted API."),
    token: str = typer.Option(..., "--token", help="Project API token from projects create."),
    project_id: str = typer.Option(..., "--project-id", help="Project UUID."),
    report_path: Path = typer.Option(
        ...,
        "--report",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Regression report JSON from replay run.",
    ),
    requests_path: Path | None = typer.Option(
        None,
        "--requests",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional request file to store with the run.",
    ),
    baseline_path: Path | None = typer.Option(
        None,
        "--baseline",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional baseline file to store with the run.",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Optional candidate API URL that was replayed.",
    ),
) -> None:
    """Upload a local report (and optional request/baseline files) to the API."""

    try:
        report = load_report(report_path)
    except LoadError as exc:
        _abort(exc)

    client = ReplayApiClient(api_url, token=token)
    collection_id = None
    baseline_id = None
    try:
        if requests_path is not None:
            collection = load_requests(requests_path)
            created_collection = client.upload_collection(project_id, collection)
            collection_id = created_collection["id"]
        if baseline_path is not None:
            baseline = load_baseline(baseline_path)
            created_baseline = client.upload_baseline(
                project_id,
                baseline,
                collection_id=collection_id,
            )
            baseline_id = created_baseline["id"]
        created_run = client.upload_run(
            project_id,
            report,
            target=target,
            collection_id=collection_id,
            baseline_id=baseline_id,
        )
    except (LoadError, ApiError) as exc:
        _abort(exc)

    typer.echo(f"uploaded run {created_run['id']}")
    typer.echo(
        f"summary: {created_run['total']} total, {created_run['matched']} matched, "
        f"{created_run['regressed']} regressed, {created_run['errored']} errored"
    )


@app.command()
def diagnose(
    api_url: str = typer.Option(..., "--api-url", help="Base URL of the hosted API."),
    token: str = typer.Option(..., "--token", help="Project API token from projects create."),
    project_id: str = typer.Option(..., "--project-id", help="Project UUID."),
    run_id: str = typer.Option(..., "--run-id", help="Run UUID to explain."),
) -> None:
    """Ask the hosted API to explain stored regressions for a run."""

    client = ReplayApiClient(api_url, token=token)
    try:
        diagnosis = client.diagnose_run(project_id, run_id)
    except ApiError as exc:
        _abort(exc)
    typer.echo(diagnosis["content"])


def render_text(report: Report) -> str:
    """Summarize a report. Matching requests stay in the counts and out of the details."""

    summary = report.summary
    lines = [
        f"{report.name}: {summary.total} total, {summary.matched} matched, "
        f"{summary.regressed} regressed, {summary.errored} errored"
    ]
    for result in report.results:
        if result.outcome == "matched":
            continue
        lines.append("")
        lines.append(f"{result.outcome.upper()} {result.id} {result.method} {result.path}")
        if result.error:
            lines.append(f"  {result.error}")
        for diff in result.diffs:
            lines.append(f"  {_format_diff(diff)}")
    lines.append("")
    return "\n".join(lines)


def _format_diff(diff: Diff) -> str:
    label = diff.kind if diff.path == "" else f"{diff.kind} {diff.path}"
    return f"{label}: {_shown(diff, 'baseline')} -> {_shown(diff, 'candidate')}"


def _shown(diff: Diff, side: str) -> str:
    if side == "baseline" and diff.op == "add":
        return "<missing>"
    if side == "candidate" and diff.op == "remove":
        return "<missing>"
    value = diff.baseline if side == "baseline" else diff.candidate
    return json.dumps(value, ensure_ascii=False)


def _load_collection(path: Path) -> RequestCollection:
    try:
        return load_requests(path)
    except LoadError as exc:
        _abort(exc)


def _send(
    target: str,
    collection: RequestCollection,
    concurrency: int,
    timeout: float,
    unsafe: bool,
) -> list[Attempt]:
    try:
        return asyncio.run(
            execute(
                target,
                collection.requests,
                concurrency=concurrency,
                timeout=timeout,
                unsafe=unsafe,
            )
        )
    except (TargetError, UnsafeRequestsError) as exc:
        _abort(exc)


def _check_limits(concurrency: int, timeout: float) -> None:
    if concurrency < 1:
        _abort(UsageError("--concurrency must be at least 1"))
    if timeout <= 0:
        _abort(UsageError("--timeout must be positive"))


def _abort(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
