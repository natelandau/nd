"""The ``nd clean`` command: force Nomad cluster garbage collection."""

from __future__ import annotations

import asyncio

import typer
from nclutils import pp

from nd.commands._common import VerboseOption, configure_verbosity, record_step
from nd.nomad import NomadClient, NomadConfig

app = typer.Typer()


@app.callback(invoke_without_command=True)
def clean(ctx: typer.Context, verbose: VerboseOption = 0) -> None:
    """Force garbage collection and reconcile job summaries on the cluster."""
    verbose = configure_verbosity(ctx, verbose)
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
            await record_step(
                client.system.gc(), step=step, verbose=verbose, method="PUT", path="/system/gc"
            )
            await record_step(
                client.system.reconcile_summaries(),
                step=step,
                verbose=verbose,
                method="PUT",
                path="/system/reconcile/summaries",
            )
    pp.success("Cluster cleaned", details=["garbage collected", "job summaries reconciled"])
