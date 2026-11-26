"""Shared wiring for the ``nd`` subcommands: app, options, verbosity, and progress steps."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, Protocol

import typer
from nclutils import pp
from nclutils.pp import Verbosity

from nd.binary import NomadBinary, NomadBinaryError
from nd.nomad import NomadError
from nd.targets import resolve_target

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from typer.core import TyperGroup
    from typer.models import OptionInfo

    from nd.nomad import NomadClient
    from nd.nomad.config import NomadConfig
    from nd.nomad.models.volume import HostVolumeListStub

# Every subcommand accepts the same -v/--verbose count option; declare it once.
VerboseOption = Annotated[
    int,
    typer.Option("-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."),
]

ForceOption = Annotated[bool, typer.Option("--force", "-f", help="Skip the confirmation prompt.")]


def dry_run_option(help_text: str) -> OptionInfo:
    """Declare a command's ``--dry-run/-n`` flag with help saying what it skips.

    The flag is the same everywhere, but what a dry run leaves undone differs per
    command, so each command supplies its own help text.

    Args:
        help_text: What the dry run reports or skips for this command.

    Returns:
        OptionInfo: The option, for use as ``Annotated[bool, dry_run_option(...)]``.
    """
    return typer.Option("--dry-run", "-n", help=help_text)


def command_app(*, cls: type[TyperGroup] | None = None) -> typer.Typer:
    """Create a single-command subcommand app that accepts options after its arguments.

    Args:
        cls: A custom group class, for a command that preprocesses its argv.

    Returns:
        typer.Typer: The app to register the command's callback on.
    """
    # Typer groups disable interspersed args, which would parse an option after the
    # positional argument (`nd stop web -p`) as a subcommand name.
    return typer.Typer(cls=cls, context_settings={"allow_interspersed_args": True})


def configure_verbosity(ctx: typer.Context, verbose: int, *, json_output: bool = False) -> int:
    """Apply the effective verbosity and return it.

    A subcommand accepts ``-v``/``-vv`` either before it (the root callback, which
    stores its count on ``ctx.obj``) or after it; take the louder of the two so
    either position works, then configure ``pp`` with the result.

    Args:
        ctx: The command's Typer context.
        verbose: The ``-v`` count given after the subcommand.
        json_output: Reserve stdout for a ``--json`` document: hide info and success
            lines and send every other ``pp`` line, including ``-v`` progress, to stderr.

    Returns:
        int: The effective verbosity.
    """
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
    if json_output:
        pp.configure(quiet=True, console=pp.err_console())
    return verbose


class StepLike(Protocol):
    """Structural type for the progress step object yielded by ``pp.step``."""

    def sub(self, text: str) -> None: ...


async def record_step(
    coro: Awaitable[Any],
    *,
    step: StepLike | None,
    verbose: int,
    method: str,
    path: str,
    count_items: bool = False,
) -> Any:  # noqa: ANN401
    """Await one API call, recording the request on the progress step per verbosity.

    The default view stays quiet; ``-v`` names the ``<method> /v1<path>`` request, and
    ``-vv`` adds the elapsed time (plus the response item count when ``count_items`` is
    set and the result is a list). Returns the awaited result so callers can use it.
    """
    start = perf_counter()
    result = await coro
    if step is not None:
        if verbose >= Verbosity.TRACE:
            count = len(result) if count_items and isinstance(result, list) else None
            elapsed_ms = (perf_counter() - start) * 1000
            items = f"{count} items, " if count is not None else ""
            step.sub(f"{method} /v1{path} → {items}{elapsed_ms:.0f}ms")
        else:
            step.sub(f"{method} /v1{path}")
    return result


def run_alloc_action(
    config: NomadConfig,
    *,
    job: str | None,
    task: str | None,
    running_only: bool,
    action: Callable[[NomadBinary, str, str], int],
) -> NoReturn:
    """Resolve an exec/logs target, run a ``nomad`` binary action against it, then exit.

    Shared tail of ``nd exec`` and ``nd logs``: resolve the (job, allocation, task)
    target through the API client, exit cleanly when there is nothing to act on, then
    build the configured ``NomadBinary`` and hand it (with the resolved alloc id and
    task name) to ``action``. A missing binary or failed invocation becomes a friendly
    exit 1; otherwise the command exits with the action's own return code, with a
    signal death translated to the shell's ``128 + signal`` convention.
    """
    exit_code, target = asyncio.run(
        resolve_target(config, job_arg=job, task_arg=task, running_only=running_only)
    )
    if target is None:
        raise typer.Exit(exit_code)
    try:
        nomad = NomadBinary.create(config)
        code = action(nomad, target.alloc_id, target.task)
    except NomadBinaryError as exc:
        pp.error(str(exc))
        raise typer.Exit(1) from exc
    # A child killed by a signal reports a negative code; sys.exit truncates that to a
    # meaningless status (SIGPIPE -> 243), so map it to the shell's 128 + signal (141).
    raise typer.Exit(128 - code if code < 0 else code)


async def list_volumes_or_empty(client: NomadClient) -> list[HostVolumeListStub]:
    """Return host volumes, or an empty list when the volumes endpoint is unavailable.

    Older Nomad versions and tokens without volume read access make the endpoint fail.
    A cluster overview still shows everything else, so the failure only drops volumes.
    """
    try:
        return await client.volumes.list()
    except NomadError as exc:
        pp.debug(f"Skipping volumes: {exc}")
        return []
