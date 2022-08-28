import sys
from pathlib import Path

import rich.repr
import typer
from loguru import logger
from rich import print


def dryrun(msg: str) -> None:
    """Print a message if the dry run flag is set.

    Args:
        msg: Message to print
    """
    print(f"[cyan]DRYRUN   | {msg}[/cyan]")


def success(msg: str) -> None:
    """Print a success message without using logging."""
    print(f"[green]SUCCESS  | {msg}[/green]")


def warning(msg: str) -> None:
    """Print a warning message without using logging."""
    print(f"[yellow]WARNING  | {msg}[/yellow]")


def error(msg: str) -> None:
    """Print an error message without using logging."""
    print(f"[red]ERROR    | {msg}[/red]")


def notice(msg: str) -> None:
    """Print a notice message without using logging."""
    print(f"[bold]NOTICE   | {msg}[/bold]")


def info(msg: str) -> None:
    """Print a notice message without using logging."""
    print(f"INFO     | {msg}")


def dim(msg: str) -> None:
    """Print a message in dimmed color."""
    print(f"[dim]{msg}[/dim]")


def _log_formatter(record: dict) -> str:
    """Create custom log formatter based on the log level.  This effects the logs sent to stdout/stderr but not the log file."""
    if (
        record["level"].name == "INFO"
        or record["level"].name == "SUCCESS"
        or record["level"].name == "WARNING"
    ):
        return "<level>{level: <8}</level> | <level>{message}</level>\n{exception}"
    else:
        return "<level>{level: <8}</level> | <level>{message}</level> <fg #c5c5c5>({name}:{function}:{line})</fg #c5c5c5>\n{exception}"


@rich.repr.auto
class LoggerManager:
    """Instantiate the loguru logging system with the following levels.

        - TRACE: Usage: log.trace("")
        - DEBUG: Usage: log.debug("")
        - INFO: Usage: log.info("")
        - WARNING: Usage: log.warning("")
        - ERROR: Usage: log.error("")
        - CRITICAL: Usage: log.critical("")
        - EXCEPTION: Usage: log.exception("")

    Args:
        verbosity (int): Integer value representing the verbosity level.
        log_to_file (bool): Boolean value representing whether or not to output to a file
        log_file (Path): Path object representing the log file. Defaults to ~/logs/[scriptname].log

    Methods:
        is_trace(): True if the current log level is TRACE or lower, False otherwise.
        is_debug(): True if the current log level is DEBUG or lower, False otherwise.
        is_info(): True if the current log level is INFO or lower, False otherwise.
        is_default(): True if the current log level is default level or lower, False otherwise.

    Usage:
        # Instantiate logging
        log = Log(verbosity, log_to_file, log_file, log_level)
    """

    def __init__(
        self,
        log_file: Path = Path("/logs"),
        verbosity: int = 0,
        log_to_file: bool = False,
        log_level: int = 30,
    ) -> None:
        self.verbosity = verbosity
        self.log_to_file = log_to_file
        self.log_file = log_file
        self.log_level = log_level

        if self.log_file == Path("/logs") and self.log_to_file:  # pragma: no cover
            print("No log file specified")
            raise typer.Exit(1)

        if self.verbosity >= 3:
            logger.remove()
            logger.add(
                sys.stderr,
                level="TRACE",
                format=_log_formatter,  # type: ignore[arg-type]
                backtrace=False,
                diagnose=True,
            )
            self.log_level = 5
        elif self.verbosity == 2:
            logger.remove()
            logger.add(
                sys.stderr,
                level="DEBUG",
                format=_log_formatter,  # type: ignore[arg-type]
                backtrace=False,
                diagnose=True,
            )
            self.log_level = 10
        elif self.verbosity == 1:
            logger.remove()
            logger.add(
                sys.stderr,
                level="INFO",
                format=_log_formatter,  # type: ignore[arg-type]
                backtrace=False,
                diagnose=True,
            )
            self.log_level = 20
        else:
            logger.remove()
            logger.add(
                sys.stderr,
                format=_log_formatter,  # type: ignore[arg-type]
                level="WARNING",
                backtrace=False,
                diagnose=True,
            )
            self.log_level = 30

        if self.log_to_file is True:
            logger.add(
                self.log_file,
                rotation="5 MB",
                level=self.log_level,
                backtrace=False,
                diagnose=True,
                delay=True,
            )
            logger.debug(f"Logging to file: {self.log_file}")

        logger.debug("Logging instantiated")

    def is_trace(self, msg: str | None = None) -> bool:
        """Check if the current log level is TRACE.

        Args:
            msg (optional): Message to print. Defaults to None.

        Returns:
            bool: True if the current log level is TRACE or lower, False otherwise.
        """
        if self.log_level <= 5:
            if msg:
                print(msg)
            return True
        else:
            return False

    def is_debug(self, msg: str | None = None) -> bool:
        """Check if the current log level is DEBUG.

        Args:
            msg (optional): Message to print. Defaults to None.

        Returns:
            bool: True if the current log level is DEBUG or lower, False otherwise.
        """
        if self.log_level <= 10:
            if msg:
                print(msg)
            return True
        else:
            return False

    def is_info(self, msg: str | None = None) -> bool:
        """Check if the current log level is INFO.

        Args:
            msg (optional): Message to print. Defaults to None.

        Returns:
            bool: True if the current log level is INFO or lower, False otherwise.
        """
        if self.log_level <= 20:
            if msg:
                print(msg)
            return True
        else:
            return False

    def is_default(self, msg: str | None = None) -> bool:
        """Check if the current log level is default level (SUCCESS or WARNING).

        Args:
            msg (optional): Message to print. Defaults to None.

        Returns:
            bool: True if the current log level is default or lower, False otherwise.
        """
        if self.log_level <= 30:
            if msg:
                print(msg)
            return True
        else:
            return False
