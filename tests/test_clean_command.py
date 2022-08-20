# type: ignore
"""Test clean command."""
from pathlib import Path

from nd._commands.clean_command import run_garbage_collection


def test_clean_command(mocker):
    """Test clean command."""
    mocker.patch(
        "nd._commands.clean_command.make_nomad_api_call",
        return_value=True,
    )

    assert (
        run_garbage_collection(
            verbosity=0,
            dry_run=False,
            log_to_file=False,
            log_file=Path("/dev/null"),
            config={"nomad_api_url": "http://localhost:4646"},
        )
        is True
    )


def test_clean_command_fail(mocker):
    """Test clean command."""
    mocker.patch(
        "nd._commands.clean_command.make_nomad_api_call",
        return_value=False,
    )

    assert (
        run_garbage_collection(
            verbosity=0,
            dry_run=False,
            log_to_file=False,
            log_file=Path("/dev/null"),
            config={"nomad_api_url": "http://localhost:4646"},
        )
        is False
    )
