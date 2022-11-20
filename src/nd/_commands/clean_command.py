"""Clean command."""
from pathlib import Path

from nd._utils import make_nomad_api_call
from nd._utils.alerts import logger as log


def run_garbage_collection(
    verbosity: int,
    dry_run: bool,
    log_to_file: bool,
    log_file: Path,
    config: dict,
) -> bool:
    """Run garbage collection."""
    api_url = f"{config['nomad_api_url']}/system/gc"
    if make_nomad_api_call(api_url, "put") is True:
        log.success("Garbage collection complete")
        return True

    log.error("Garbage collection failed")
    return False
