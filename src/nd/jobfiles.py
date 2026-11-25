"""Discover Nomad job files from configured directories and read their names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp
from nclutils.fs import find_files

from nd.constants import JOB_FILE_GLOBS
from nd.nomad.config import load_config_directories

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet
    from pathlib import Path

# A `job "name" {` block opener. The name may be an interpolation such as `${var.x}`:
# such a file is still a job file, but its name cannot be selected.
_JOB_BLOCK_RE = re.compile(r'^\s*job\s+"([^"]+)"\s*\{', re.MULTILINE)


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
    names = (match.group(1) for match in _JOB_BLOCK_RE.finditer(text))
    return list(dict.fromkeys(name for name in names if "${" not in name))


def is_job_file(text: str) -> bool:
    """Return whether ``text`` contains a top-level Nomad ``job`` block.

    A ``.hcl``/``.nomad`` extension alone does not make a file a job spec, so callers
    validate by content before treating a file as a job.
    """
    return _JOB_BLOCK_RE.search(text) is not None


def find_spec_files(directories: list[Path]) -> list[Path]:
    """List the Nomad spec files (``*.hcl``/``*.nomad``) in the given directories.

    Use for job and volume discovery alike, since both kinds share these extensions
    and are told apart by content. A directory listed twice is scanned once, and a
    missing directory contributes no files.

    Args:
        directories: Directories to search, in configured order.

    Returns:
        list[Path]: Matching files, sorted by path.
    """
    unique_directories = dict.fromkeys(directories)
    return sorted(
        path
        for directory in unique_directories
        for path in find_files(path=directory, globs=JOB_FILE_GLOBS)
    )


def discover_job_files(directories: list[Path]) -> list[JobFile]:
    """Find the job files in the given directories and read the job names each declares.

    Args:
        directories: Directories to search for Nomad job files.

    Returns:
        list[JobFile]: Every readable file containing a ``job`` block, sorted by path.
    """
    files: list[JobFile] = []
    for path in find_spec_files(directories):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            pp.warning(f"Skipping {path}: expected a readable UTF-8 file ({exc})")
            continue
        if is_job_file(text):
            files.append(JobFile(path=path, job_names=extract_job_names(text)))
    return files


def load_job_directories(config_path: Path | None = None) -> list[Path]:
    """Read the job directories from the ``[jobs]`` table of the nd config.

    See ``load_config_directories`` for the file format and errors.
    """
    return load_config_directories(section="jobs", config_path=config_path)
