"""Shared test utilities: the mock cluster address, async drivers, and output capture."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nclutils import pp
from rich.console import Console

from nd.nomad import NomadClient, NomadConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from nd.ui.live_panel import LiveChild

# The `.test` TLD never resolves, so a route the test forgot to mock cannot reach a real host
NOMAD_TEST_ADDR = "http://nomad.test:4646"


def run_with_client[T](call: Callable[[NomadClient], Awaitable[T]]) -> T:
    """Run an async call against a client for the mock cluster, then close the client.

    Use this to drive client-backed async code from a sync test.

    Args:
        call: Receives the open client and returns the awaitable under test.

    Returns:
        T: What the awaitable returned.
    """

    async def _run() -> T:
        async with NomadClient(NomadConfig(address=NOMAD_TEST_ADDR)) as client:
            return await call(client)

    return asyncio.run(_run())


def async_return[T](value: T) -> Callable[..., Awaitable[T]]:
    """Build an async stand-in that accepts any arguments and returns `value`.

    Returns:
        Callable[..., Awaitable[T]]: The async function.
    """

    async def _return(*_args: object, **_kwargs: object) -> T:
        return value

    return _return


def discard_panel_update(phase: str, children: Sequence[LiveChild] = ()) -> None:
    """Accept and drop a live-panel row update, for tests that do not inspect the panel."""


def capture_output(*, width: int = 100) -> Console:
    """Route all `pp` output, stdout and stderr, to a recording console.

    The autouse `isolate_console_output` fixture restores the default emitter after the test.

    Args:
        width: Console width in columns.

    Returns:
        Console: The recording console; read it with `export_text()`.
    """
    console = Console(theme=pp.THEME, record=True, force_terminal=True, width=width)
    pp.set_default(pp.Emitter(console=console, err_console=console))
    return console
