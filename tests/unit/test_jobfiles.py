"""Tests for job-file discovery and the [jobs] config table."""

from __future__ import annotations

from pathlib import Path

import pytest

from nd.jobfiles import discover_job_files, extract_job_names, load_job_directories
from nd.nomad.errors import NomadConfigError


def test_extract_job_names_multiple_blocks() -> None:
    """Verify every job block name is extracted in order, deduplicated."""
    # Given an HCL file with two job blocks
    text = 'job "web" {\n}\njob   "worker" {\n}\njob "web" {}\n'
    # When
    names = extract_job_names(text)
    # Then
    assert names == ["web", "worker"]


def test_extract_job_names_ignores_interpolated() -> None:
    """Verify an interpolated job name is skipped rather than parsed incorrectly."""
    text = 'job "${var.name}" {\n}\njob "static" {}\n'
    assert extract_job_names(text) == ["static"]


def test_discover_job_files_scans_existing_dirs(tmp_path: Path) -> None:
    """Verify discovery finds .hcl/.nomad files in existing dirs and parses names."""
    # Given a directory with two job files and one non-job file
    d = tmp_path / "jobs"
    d.mkdir()
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")
    (d / "batch.nomad").write_text('job "batch" {}', encoding="utf-8")
    (d / "notes.txt").write_text("ignore me", encoding="utf-8")
    missing = tmp_path / "nope"
    # When (a non-existent directory is silently skipped)
    files = discover_job_files([d, missing])
    # Then
    names = {jf.path.name: jf.job_names for jf in files}
    assert names == {"web.hcl": ["web"], "batch.nomad": ["batch"]}


def test_load_job_directories_reads_table(tmp_path: Path) -> None:
    """Verify the [jobs] directories list is read and ~ is expanded."""
    # Given an nd config file with a [jobs] table
    cfg = tmp_path / "config.toml"
    cfg.write_text('[jobs]\ndirectories = ["~/jobs", "/srv/nomad"]\n', encoding="utf-8")
    # When
    dirs = load_job_directories(cfg)
    # Then
    assert dirs[0] == Path.home() / "jobs"
    assert dirs[1] == Path("/srv/nomad")


def test_load_job_directories_missing_table(tmp_path: Path) -> None:
    """Verify a config with no [jobs] table yields no directories."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[nomad]\naddress = "http://x:4646"\n', encoding="utf-8")
    assert load_job_directories(cfg) == []


def test_load_job_directories_unreadable_toml(tmp_path: Path) -> None:
    """Verify malformed TOML raises NomadConfigError."""
    # Given a config file containing invalid TOML
    cfg = tmp_path / "config.toml"
    cfg.write_text("[jobs\ndirectories = ", encoding="utf-8")

    # When loading job directories from the malformed file
    # Then a NomadConfigError is raised
    with pytest.raises(NomadConfigError):
        load_job_directories(cfg)


def test_load_job_directories_non_table_jobs(tmp_path: Path) -> None:
    """Verify a [jobs] section that is a scalar instead of a table raises NomadConfigError."""
    # Given a config file where jobs is a plain string, not a table
    cfg = tmp_path / "config.toml"
    cfg.write_text('jobs = "not a table"\n', encoding="utf-8")

    # When loading job directories from the config
    # Then a NomadConfigError is raised because [jobs] must be a table
    with pytest.raises(NomadConfigError):
        load_job_directories(cfg)


def test_load_job_directories_non_list_directories(tmp_path: Path) -> None:
    """Verify a directories value that is not a list raises NomadConfigError."""
    # Given a config file where directories is a plain string, not a list
    cfg = tmp_path / "config.toml"
    cfg.write_text('[jobs]\ndirectories = "string"\n', encoding="utf-8")

    # When loading job directories from the config
    # Then a NomadConfigError is raised because directories must be a list
    with pytest.raises(NomadConfigError):
        load_job_directories(cfg)
