"""Tests for job-file discovery and the [jobs] config table."""

from __future__ import annotations

from pathlib import Path

import pytest

from nd.jobfiles import (
    JobFile,
    candidates_for,
    discover_job_files,
    extract_job_names,
    find_spec_files,
    is_job_file,
    load_job_directories,
)


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param('job "web" {}', True, id="literal-name"),
        pytest.param('job "${var.name}" {\n}', True, id="interpolated-name"),
        pytest.param('type = "host"\nname = "data"', False, id="volume-spec"),
    ],
)
def test_is_job_file_detects_literal_and_interpolated(*, text: str, expected: bool) -> None:
    """Verify is_job_file recognizes job blocks with literal or interpolated names."""
    # Given job-block or non-job text
    # When classifying it
    # Then only a job block counts as a job file
    assert is_job_file(text) is expected


def test_discover_job_files_excludes_non_job_specs(tmp_path: Path) -> None:
    """Verify discovery keeps only files containing a job block, dropping volume specs."""
    # Given a directory holding a job file and a host-volume spec (both .hcl)
    d = tmp_path / "jobs"
    d.mkdir()
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")
    (d / "vol-data.hcl").write_text('name = "data"\ntype = "host"', encoding="utf-8")
    (d / "binary.hcl").write_bytes(b"\xff\xfe")
    # When discovering
    files = discover_job_files([d])
    # Then only the job file is returned and the non-UTF-8 file is skipped
    assert {jf.path.name for jf in files} == {"web.hcl"}


def test_discover_job_files_scans_existing_dirs(tmp_path: Path) -> None:
    """Verify discovery finds .hcl/.nomad files in existing dirs and parses names."""
    # Given a directory with two job files and one non-job file
    d = tmp_path / "jobs"
    d.mkdir()
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")
    (d / "batch.nomad").write_text('job "batch" {}', encoding="utf-8")
    (d / "notes.txt").write_text("ignore me", encoding="utf-8")
    # When
    files = discover_job_files([d])
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


def test_find_spec_files_scans_a_repeated_directory_once(tmp_path: Path) -> None:
    """Verify a directory listed twice yields each spec file once."""
    # Given a directory with one spec file, configured twice
    d = tmp_path / "jobs"
    d.mkdir()
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")

    # When listing spec files
    files = find_spec_files([d, d])

    # Then the file appears once
    assert files == [d / "web.hcl"]


def test_find_spec_files_skips_missing_directory(tmp_path: Path) -> None:
    """Verify a configured directory that does not exist contributes no files."""
    # Given one existing directory with a spec file and one missing directory
    d = tmp_path / "jobs"
    d.mkdir()
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")

    # When listing spec files
    files = find_spec_files([d, tmp_path / "missing"])

    # Then only the existing directory's file is listed
    assert files == [d / "web.hcl"]


def test_candidates_for_flattens_names() -> None:
    """Verify each job name in each file becomes its own candidate."""
    # Given one file with two jobs and one with a single job
    files = [
        JobFile(path=Path("/j/a.hcl"), job_names=["web", "worker"]),
        JobFile(path=Path("/j/b.hcl"), job_names=["db"]),
    ]

    # When computing candidates
    cands = candidates_for(files)

    # Then every name becomes a candidate tied to its file, in order
    assert [(c.name, c.file.path.name) for c in cands] == [
        ("web", "a.hcl"),
        ("worker", "a.hcl"),
        ("db", "b.hcl"),
    ]


def test_candidates_for_excludes_running() -> None:
    """Verify already-running job names are filtered out of run candidates."""
    # Given two job files, one whose job is already running
    files = [
        JobFile(path=Path("/j/a.hcl"), job_names=["web", "worker"]),
        JobFile(path=Path("/j/b.hcl"), job_names=["db"]),
    ]

    # When computing candidates excluding running names
    cands = candidates_for(files, exclude_names={"web"})

    # Then only the not-running job names are returned
    assert sorted(c.name for c in cands) == ["db", "worker"]
