"""Shared wiring for the ``nd`` subcommands: verbosity and progress-step helpers."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any, Protocol

import typer
from nclutils import pp
from nclutils.pp import Verbosity

if TYPE_CHECKING:
    from collections.abc import Awaitable

# Every subcommand accepts the same -v/--verbose count option; declare it once.
VerboseOption = Annotated[
    int,
    typer.Option("-v", "--verbose", count=True, help="Increase verbosity (-v debug, -vv trace)."),
]


def configure_verbosity(ctx: typer.Context, verbose: int) -> int:
    """Apply the effective verbosity and return it.

    A subcommand accepts ``-v``/``-vv`` either before it (the root callback, which
    stores its count on ``ctx.obj``) or after it; take the louder of the two so
    either position works, then configure ``pp`` with the result.
    """
    verbose = max(getattr(ctx.obj, "verbose", 0), verbose)
    pp.configure(verbosity=verbose)
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
