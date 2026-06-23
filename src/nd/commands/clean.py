"""The ``nd clean`` command: force Nomad cluster garbage collection."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Protocol

import typer
from nclutils import pp
from nclutils.pp import Verbosity

from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable


class _StepLike(Protocol):
    """Structural type for the progress step object yielded by ``pp.step``."""

    def sub(self, text: str) -> None: ...


app = typer.Typer()


@app.callback(invoke_without_command=True)
def clean(
    ctx: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."
        ),
    ] = 0,
) -> None:
    """Force garbage collection and reconcile job summaries on the cluster."""
    # Accept -v/-vv either before the command (root callback) or here; take the louder.
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    asyncio.run(_run(verbose=verbose))


async def _run(*, verbose: int) -> None:
    """Run the cluster housekeeping operations and report a friendly result.

    Garbage collection and summary reconciliation run sequentially so the
    progress sub-lines render in a stable order. Both are safe, idempotent
    operations whose Nomad failures propagate as ``NomadError`` for ``main()``
    to map onto a clean non-zero exit.
    """
    config = NomadConfig.resolve()
    pp.debug("Resolved Nomad config", details=[f"address={config.address}"])
    async with NomadClient.from_config(config) as client:
        with pp.step("Cleaning up the cluster") as step:
            await _record("/system/gc", client.system.gc(), step=step, verbose=verbose)
            await _record(
                "/system/reconcile/summaries",
                client.system.reconcile_summaries(),
                step=step,
                verbose=verbose,
            )
    pp.success("Cluster cleaned", details=["garbage collected", "job summaries reconciled"])


async def _record(path: str, coro: Awaitable[None], *, step: _StepLike, verbose: int) -> None:
    """Await one housekeeping call, recording the request on the progress step.

    The default view stays quiet (the friendly summary comes from ``pp.success``);
    ``-v`` names each ``PUT`` request, and ``-vv`` adds the elapsed time.
    """
    start = perf_counter()
    await coro
    if verbose >= Verbosity.TRACE:
        elapsed_ms = (perf_counter() - start) * 1000
        step.sub(f"PUT /v1{path} → {elapsed_ms:.0f}ms")
    elif verbose >= Verbosity.DEBUG:
        step.sub(f"PUT /v1{path}")
