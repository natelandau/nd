"""Discover and parse Nomad dynamic host-volume specs from configured directories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import hcl2
from lark.exceptions import LarkError
from nclutils import pp

from nd.jobfiles import find_spec_files, is_job_file
from nd.nomad.config import load_config_directories

if TYPE_CHECKING:
    from pathlib import Path

# Default capability applied when a host volume spec omits its own `capability` block,
# matching the permissive default the homelab relies on for shared NFS-backed mounts.
DEFAULT_CAPABILITIES: list[dict[str, str]] = [
    {"access_mode": "multi-node-multi-writer", "attachment_mode": "file-system"}
]

# Minimum length for a quoted string (opening quote + content + closing quote)
_MIN_QUOTED_LENGTH = 2


@dataclass(frozen=True)
class VolumeSpec:
    """A discovered host-volume spec file and the fields needed to register it."""

    path: Path
    name: str
    capabilities: list[dict[str, str]]
    relative_path: str | None


def _first(value: Any) -> Any:  # noqa: ANN401
    """Unwrap python-hcl2's single-element block list into the block dict.

    python-hcl2 represents a `parameters {}` / `capability {}` block as a one-element
    list, so the actual mapping lives at index 0.
    """
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _unquote(value: Any) -> Any:  # noqa: ANN401
    """Unquote a string value parsed by hcl2, preserving non-strings.

    python-hcl2 represents quoted HCL strings with their quote characters included,
    so we strip them to get the actual string value.
    """
    if (
        isinstance(value, str)
        and len(value) >= _MIN_QUOTED_LENGTH
        and value[0] == '"'
        and value[-1] == '"'
    ):
        return value[1:-1]
    return value


def parse_volume_spec(path: Path) -> VolumeSpec | None:
    """Parse an HCL file into a `VolumeSpec`, or None if it is not a host volume.

    Returns None when the file is a job file, does not parse as HCL, is not
    ``type = "host"``, or has no name, so non-volume files sharing the directory are
    skipped rather than failing discovery.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        pp.debug(f"Skipping {path}: not readable ({exc})")
        return None
    # Job files skip the HCL parse: it is the slow step, and job specs often use
    # syntax python-hcl2 rejects.
    if is_job_file(text):
        return None
    try:
        data: dict[str, Any] = hcl2.loads(text)
    except (ValueError, LarkError) as exc:
        pp.debug(f"Skipping {path}: not parseable as HCL ({exc})")
        return None

    spec_type = _unquote(data.get("type"))
    spec_name = _unquote(data.get("name"))
    # An unresolved interpolation cannot be registered as a literal volume name, so a
    # spec with an interpolated name is skipped (mirrors jobfiles name handling).
    if spec_type != "host" or not spec_name or "${" in str(spec_name):
        return None

    capabilities = [
        {
            "access_mode": _unquote(c.get("access_mode")),
            "attachment_mode": _unquote(c.get("attachment_mode")),
        }
        for c in (data.get("capability") or [])
        if isinstance(c, dict)
        and c.get("access_mode") is not None
        and c.get("attachment_mode") is not None
    ] or [dict(c) for c in DEFAULT_CAPABILITIES]

    params = _first(data.get("parameters"))
    relative_path = _unquote(params.get("relative_path")) if isinstance(params, dict) else None

    return VolumeSpec(
        path=path,
        name=str(spec_name),
        capabilities=capabilities,
        relative_path=relative_path,
    )


def discover_volume_files(directories: list[Path]) -> list[VolumeSpec]:
    """Find and parse the host-volume specs in the given directories, sorted by name.

    A directory may hold both job and volume specs; only volume specs are returned.
    """
    specs = [spec for path in find_spec_files(directories) if (spec := parse_volume_spec(path))]
    return sorted(specs, key=lambda s: s.name)


def load_volume_directories(config_path: Path | None = None) -> list[Path]:
    """Read the volume directories from the ``[volumes]`` table of the nd config.

    See ``load_config_directories`` for the file format and errors.
    """
    return load_config_directories(section="volumes", config_path=config_path)
