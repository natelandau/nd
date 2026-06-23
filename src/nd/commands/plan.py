"""The ``nd plan`` command: preview job-file changes via `nomad job plan`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated

import typer
from nclutils import pp

from nd import jobspec
from nd.jobfiles import candidates_for, discover_job_files, load_job_directories
from nd.jobspec import JobSpecError
from nd.nomad import NomadConfig
from nd.selection import resolve_targets, select_candidates

if TYPE_CHECKING:
    from nd.jobfiles import JobCandidate
    from nd.selection import TargetResolution


# allow_interspersed_args lets options follow the positional JOB (e.g. `nd plan web -n`);
# Typer groups disable that by default, which would parse `-n` as a subcommand.
app = typer.Typer(context_settings={"allow_interspersed_args": True})


@app.callback(invoke_without_command=True)
def plan(
    ctx: typer.Context,
    job: Annotated[
        str | None,
        typer.Argument(help="Job to plan; matches any job whose name starts with this."),
    ] = None,
    dry_run: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--dry-run", "-n", help="Report what would be planned without running plan."),
    ] = False,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Preview changes for one or more job files (plan includes running jobs)."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    exit_code = asyncio.run(_run(job_arg=job, dry_run=dry_run))
    if exit_code != 0:
        raise typer.Exit(exit_code)


async def _run(*, job_arg: str | None, dry_run: bool) -> int:
    """Resolve candidates (all files), then validate + plan each selected one."""
    files = discover_job_files(load_job_directories())
    candidates = candidates_for(files)
    if not candidates:
        pp.info("No job files found; set [jobs] directories in your nd config.")
        return 0

    resolution: TargetResolution[JobCandidate] = resolve_targets(
        candidates, job_arg, name_of=lambda c: c.name
    )
    targets = await select_candidates(
        resolution, "Select jobs to plan", label_of=lambda c: f"{c.name}  [{c.file.path.name}]"
    )
    if targets is None:
        return 0
    if not targets:
        pp.error(f"No job file matching '{job_arg}'")
        return 1

    if dry_run:
        for c in targets:
            pp.dryrun(f"would plan {c.name} ({c.file.path})")
        return 0

    return _plan_all(targets)


def _plan_all(targets: list[JobCandidate]) -> int:
    """Validate then plan each unique file, surfacing `nomad job plan` verbatim.

    Returns 0 when every plan ran (including "changes present"); 1 if any file
    failed validation or the binary could not run.
    """
    try:
        jobspec.ensure_nomad()
    except JobSpecError as exc:
        pp.error(str(exc))
        return 1

    # Resolve config so the binary targets the same cluster as nd (including
    # config-file overrides), not just whatever NOMAD_* env vars are ambient.
    config = NomadConfig.resolve()
    failures = 0
    # dict.fromkeys dedups while preserving order, so a multi-job file is planned once.
    for path in dict.fromkeys(c.file.path for c in targets):
        pp.header(f"plan: {path.name}")
        try:
            jobspec.validate(path, config)
            jobspec.plan(path, config)
        except JobSpecError as exc:
            pp.error(str(exc))
            failures += 1
    return 1 if failures else 0
