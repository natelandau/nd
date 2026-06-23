"""Typer wiring and async data collection for ``nd status``."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, configure_verbosity, record_step
from nd.commands.status.render import render_report
from nd.commands.status.report import build_report
from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from nd.commands.status.report import StatusReport


app = typer.Typer()


@app.callback(invoke_without_command=True)
def status(ctx: typer.Context, verbose: VerboseOption = 0) -> None:
    """Show an at-a-glance overview of the Nomad cluster."""
    verbose = configure_verbosity(ctx, verbose)
    report = asyncio.run(_collect(verbose=verbose))
    if verbose:  # separate the progress tree from the dashboard
        pp.console().print()
    render_report(report)


async def _collect(*, verbose: int) -> StatusReport:
    """Fetch all cluster endpoints concurrently and build a `StatusReport`.

    The default view is silent; ``-v`` shows a `pp.step` tree of the requests we
    make, and ``-vv`` adds each response's item count and elapsed time.
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
    async with NomadClient.from_config(config) as client:
        step_cm: contextlib.AbstractContextManager[Any] = (
            pp.step("Querying Nomad cluster") if verbose else contextlib.nullcontext(None)
        )
        with step_cm as step:

            def fetch(path: str, coro: Any) -> Any:  # noqa: ANN401
                return record_step(
                    coro, step=step, verbose=verbose, method="GET", path=path, count_items=True
                )

            nodes, jobs, allocs, members, leader, deployments, evals = await asyncio.gather(
                fetch("/nodes", client.nodes.list()),
                fetch("/jobs", client.jobs.list()),
                fetch("/allocations", client.allocations.list()),
                fetch("/agent/members", client.agent.members()),
                fetch("/status/leader", client.status.leader()),
                fetch("/deployments", client.deployments.list()),
                fetch("/evaluations", client.evaluations.list()),
            )
    return build_report(
        nodes=nodes,
        jobs=jobs,
        allocs=allocs,
        config=config,
        members=members,
        leader=leader,
        deployments=deployments,
        evals=evals,
    )
