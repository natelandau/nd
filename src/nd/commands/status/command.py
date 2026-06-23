"""Typer wiring and async data collection for ``nd status``."""

from __future__ import annotations

import asyncio
import contextlib
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any, Protocol

import typer
from nclutils import pp
from nclutils.pp import Verbosity

from nd.commands.status.render import render_report
from nd.commands.status.report import build_report
from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from nd.commands.status.report import StatusReport


class _StepLike(Protocol):
    """Structural type for the progress step object yielded by ``pp.step``."""

    def sub(self, text: str) -> None: ...


app = typer.Typer()


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Show an at-a-glance overview of the Nomad cluster."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    report = asyncio.run(_collect(verbose=verbose))
    if verbose:  # separate the progress tree from the dashboard
        pp.console().print()
    render_report(report)


async def _fetch(path: str, coro: Awaitable[Any], *, step: _StepLike | None, verbose: int) -> Any:  # noqa: ANN401
    """Await one resource call, recording it on the progress step per verbosity.

    At ``-v`` the step records the action (the request); at ``-vv`` it also records
    the response (item count and elapsed time).
    """
    start = perf_counter()
    result = await coro
    if step is not None:
        if verbose >= Verbosity.TRACE:
            count = len(result) if isinstance(result, list) else None
            elapsed_ms = (perf_counter() - start) * 1000
            items = f"{count} items, " if count is not None else ""
            step.sub(f"GET /v1{path} → {items}{elapsed_ms:.0f}ms")
        else:
            step.sub(f"GET /v1{path}")
    return result


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
            nodes, jobs, allocs, members, leader, deployments, evals = await asyncio.gather(
                _fetch("/nodes", client.nodes.list(), step=step, verbose=verbose),
                _fetch("/jobs", client.jobs.list(), step=step, verbose=verbose),
                _fetch("/allocations", client.allocations.list(), step=step, verbose=verbose),
                _fetch("/agent/members", client.agent.members(), step=step, verbose=verbose),
                _fetch("/status/leader", client.status.leader(), step=step, verbose=verbose),
                _fetch("/deployments", client.deployments.list(), step=step, verbose=verbose),
                _fetch("/evaluations", client.evaluations.list(), step=step, verbose=verbose),
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
