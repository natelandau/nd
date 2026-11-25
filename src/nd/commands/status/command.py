"""Typer wiring and async data collection for ``nd status``."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Annotated, Any

import typer
from nclutils import pp

from nd.commands._common import (
    VerboseOption,
    configure_verbosity,
    list_volumes_or_empty,
    record_step,
)
from nd.commands.status.json_output import build_status_json
from nd.commands.status.render import render_hosts, render_report
from nd.commands.status.report import build_host_report, build_report
from nd.nomad import NomadClient, NomadConfig
from nd.ui.json_output import print_json

if TYPE_CHECKING:
    from nd.commands.status.report import HostPanel, StatusReport


app = typer.Typer()


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    verbose: VerboseOption = 0,
    hosts: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--hosts", help="Pivot the dashboard to one panel per host (jobs, status, uptime)."
        ),
    ] = False,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--json",
            help="Print a JSON object on stdout instead of the dashboard: health, cluster, servers, "
            "nodes, jobs, allocations, volumes, deployments, problem_evaluations, and hosts "
            "with --hosts.",
        ),
    ] = False,
) -> None:
    """Show an at-a-glance overview of the Nomad cluster."""
    verbose = configure_verbosity(ctx, verbose, json_output=json_output)
    report, host_panels = asyncio.run(_collect(verbose=verbose, hosts=hosts))
    if json_output:
        print_json(build_status_json(report, host_panels if hosts else None))
        return
    if verbose:  # separate the progress tree from the dashboard
        pp.console().print()
    if hosts:
        render_hosts(report, host_panels)
    else:
        render_report(report)


async def _collect(*, verbose: int, hosts: bool = False) -> tuple[StatusReport, list[HostPanel]]:
    """Fetch all cluster endpoints concurrently and build the report and host panels.

    Both views share one fetch: the default dashboard consumes the `StatusReport`, and
    ``--hosts`` also consumes the per-host panels, which are built only when ``hosts``
    is set. The default view is silent; ``-v`` shows a `pp.step` tree of the requests
    we make, and ``-vv`` adds each response's item count and elapsed time.
    """
    config = NomadConfig.resolve()
    pp.debug(
        "Resolved Nomad config",
        details=[
            f"address={config.address}",
            f"region={config.region}",
            f"namespace={config.namespace}",
        ],
    )
    async with NomadClient(config) as client:
        step_cm: contextlib.AbstractContextManager[Any] = (
            pp.step("Querying Nomad cluster") if verbose else contextlib.nullcontext(None)
        )
        with step_cm as step:

            def fetch(path: str, coro: Any) -> Any:  # noqa: ANN401
                return record_step(
                    coro, step=step, verbose=verbose, method="GET", path=path, count_items=True
                )

            (
                nodes,
                jobs,
                allocs,
                members,
                leader,
                deployments,
                evals,
                volumes,
            ) = await asyncio.gather(
                fetch("/nodes", client.nodes.list()),
                fetch("/jobs", client.jobs.list()),
                fetch("/allocations", client.allocations.list()),
                fetch("/agent/members", client.agent.members()),
                fetch("/status/leader", client.status.leader()),
                fetch("/deployments", client.deployments.list()),
                fetch("/evaluations", client.evaluations.list()),
                fetch("/volumes", list_volumes_or_empty(client)),
            )
    report = build_report(
        nodes=nodes,
        jobs=jobs,
        allocs=allocs,
        config=config,
        members=members,
        leader=leader,
        deployments=deployments,
        evals=evals,
        volumes=volumes,
    )
    host_panels = build_host_report(nodes=nodes, jobs=jobs, allocs=allocs) if hosts else []
    return report, host_panels
