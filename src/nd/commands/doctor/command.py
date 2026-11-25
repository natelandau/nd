"""Typer wiring for ``nd doctor``."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, command_app, configure_verbosity
from nd.commands.doctor.checks import run_checks
from nd.commands.doctor.findings import DoctorSnapshot, Finding, FindingSeverity
from nd.commands.doctor.render import render_findings
from nd.commands.doctor.snapshot import collect_snapshot
from nd.nomad import NomadClient, NomadConfig
from nd.targets.selection import resolve_targets
from nd.ui.links import WebUi

app = command_app()


@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Only show findings on jobs whose name contains this."),
    ] = None,
    verbose: VerboseOption = 0,
) -> None:
    """List common job and cluster problems, worst first, with a fix where nd has one."""
    configure_verbosity(ctx, verbose)
    config = NomadConfig.resolve()

    async def collect() -> tuple[DoctorSnapshot, list[Finding]]:
        async with NomadClient(config) as client:
            snapshot = await collect_snapshot(client=client, config=config)
        return snapshot, run_checks(snapshot)

    snapshot, findings = asyncio.run(collect())
    if name is not None:
        if not resolve_targets(snapshot.jobs, name, name_of=lambda job: job.name).candidates:
            pp.error(f"No job matching '{name}'")
            raise typer.Exit(code=1)
        job_findings = [f for f in findings if f.job_name]
        findings = resolve_targets(
            job_findings, name, name_of=lambda f: f.job_name or ""
        ).candidates
    render_findings(findings, file_paths=snapshot.job_file_paths, ui=WebUi(config.ui_base))
    # Info findings are advice only; anything worse fails the command.
    if any(f.severity is not FindingSeverity.INFO for f in findings):
        raise typer.Exit(code=1)
