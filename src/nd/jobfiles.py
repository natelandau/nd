"""Discover Nomad job files from configured directories and read their names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils.fs import find_files

from nd.constants import JOB_FILE_GLOBS
from nd.nomad.config import load_config_directories

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet
    from pathlib import Path

# Matches a top-level `job "name" {` block opener with a literal (non-interpolated)
# name. Interpolated names (containing `${`) are intentionally skipped.
_JOB_BLOCK_RE = re.compile(r'^\s*job\s+"([^"$]+)"\s*\{', re.MULTILINE)

# Detects the presence of a top-level `job "..." {` block regardless of whether the
# name is literal or interpolated, so a real job file with a computed name still
# validates as a job file (its name just resolves to nothing via extract_job_names).
_JOB_BLOCK_DETECT_RE = re.compile(r'^\s*job\s+"[^"]+"\s*\{', re.MULTILINE)


@dataclass(frozen=True)
class JobFile:
    """A discovered job file and the job names it declares."""

    path: Path
    job_names: list[str]


@dataclass(frozen=True)
class JobCandidate:
    """A selectable job: one job name bound to the file that declares it."""

    name: str
    file: JobFile


def candidates_for(
    files: list[JobFile], exclude_names: AbstractSet[str] = frozenset()
) -> list[JobCandidate]:
    """Flatten job files into one candidate per declared job name.

    Names in ``exclude_names`` (e.g. jobs already running in the cluster) are
    omitted, so ``nd run`` can offer only not-running jobs while ``nd plan`` passes
    no exclusions and gets every declared job.

    Args:
        files: Discovered job files and the job names each declares.
        exclude_names: Job names to leave out of the result.

    Returns:
        Flat list of candidates, one per included job name.
    """
    return [
        JobCandidate(name=name, file=jf)
        for jf in files
        for name in jf.job_names
        if name not in exclude_names
    ]


def extract_job_names(text: str) -> list[str]:
    """Return every literal ``job "<name>"`` in declaration order, deduplicated."""
    seen: dict[str, None] = {}
    for match in _JOB_BLOCK_RE.finditer(text):
        seen.setdefault(match.group(1), None)
    return list(seen)


def is_job_file(text: str) -> bool:
    """Return whether ``text`` contains a top-level Nomad ``job`` block.

    A ``.hcl``/``.nomad`` extension alone does not make a file a job spec, so callers
    validate by content before treating a file as a job.
    """
    return _JOB_BLOCK_DETECT_RE.search(text) is not None


def discover_job_files(directories: list[Path]) -> list[JobFile]:
    """Find job files in each existing directory and parse their job names.

    Non-existent directories are skipped silently. Files are returned sorted
    by path so output is deterministic across runs.

    Args:
        directories: Directories to search for Nomad job files.

    Returns:
        JobFile instances for every matching file, sorted by path.
    """
    files: list[JobFile] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in find_files(directory, globs=JOB_FILE_GLOBS):
            text = path.read_text(encoding="utf-8")
            if not is_job_file(text):
                continue
            files.append(JobFile(path=path, job_names=extract_job_names(text)))
    return sorted(files, key=lambda jf: str(jf.path))


def load_job_directories(config_path: Path | None = None) -> list[Path]:
    """Read the ``[jobs] directories`` list from the nd TOML config, expanding ``~``.

    Returns an empty list when the config file or ``[jobs]`` table is absent.

    Args:
        config_path: Explicit path to an nd config file. Defaults to the
            XDG config location when omitted.

    Returns:
        Expanded Path objects for each configured job directory.

    Raises:
        NomadConfigError: If the config file cannot be read or the ``[jobs]``
            section or ``directories`` value has the wrong type.
    """
    return load_config_directories(section="jobs", config_path=config_path)
