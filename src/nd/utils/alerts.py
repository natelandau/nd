"""Logging and alerts."""

from enum import Enum
from textwrap import wrap

from nd.utils.console import console


class LogLevel(Enum):
    """Enum for log levels."""

    TRACE = 5
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    EXCEPTION = 60


class VerboseLevel(Enum):
    """Enum for verbose levels."""

    WARN = 0
    INFO = 1
    DEBUG = 2
    TRACE = 3


def dryrun(msg: str) -> None:
    """Print a message if the dry run flag is set.

    Args:
        msg: Message to print
    """
    console.print(f"[cyan]DRYRUN   | {msg}[/cyan]")


def success(msg: str) -> None:
    """Print a success message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"[green]SUCCESS  | {msg}[/green]")


def warning(msg: str) -> None:
    """Print a warning message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"[yellow]WARNING  | {msg}[/yellow]")


def error(msg: str) -> None:
    """Print an error message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"[red]ERROR    | {msg}[/red]")


def notice(msg: str) -> None:
    """Print a notice message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"[bold]NOTICE   | {msg}[/bold]")


def info(msg: str) -> None:
    """Print a notice message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"INFO     | {msg}")


def usage(msg: str, width: int = 80) -> None:
    """Print a usage message without using logging.

    Args:
        msg: Message to print
        width (optional): Width of the message
    """
    for _n, line in enumerate(wrap(msg, width=width)):
        if _n == 0:
            console.print(f"[dim]USAGE    | {line}")
        else:
            console.print(f"[dim]         | {line}")


def debug(msg: str) -> None:
    """Print a debug message without using logging.

    Args:
        msg: Message to print
    """
    console.print(f"[blue]DEBUG    | {msg}[/blue]")


def dim(msg: str) -> None:
    """Print a message in dimmed color.

    Args:
        msg: Message to print
    """
    console.print(f"[dim]{msg}[/dim]")
