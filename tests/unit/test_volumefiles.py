"""Tests for host-volume spec discovery and parsing."""

from pathlib import Path

from nd.volumefiles import (
    discover_volume_files,
    load_volume_directories,
    parse_volume_spec,
)

_HOST_SPEC = """
name = "data"
type = "host"
capability {
  access_mode     = "single-node-writer"
  attachment_mode = "file-system"
}
parameters {
  relative_path = "data"
}
"""


def test_parse_volume_spec_reads_host_volume(tmp_path: Path) -> None:
    """Verify a host volume spec parses name, capability, and relative_path."""
    # Given a host volume HCL spec
    f = tmp_path / "data.hcl"
    f.write_text(_HOST_SPEC, encoding="utf-8")
    # When parsing
    spec = parse_volume_spec(f)
    # Then its fields are populated
    assert spec is not None
    assert spec.name == "data"
    assert spec.relative_path == "data"
    assert spec.capabilities == [
        {"access_mode": "single-node-writer", "attachment_mode": "file-system"}
    ]


def test_parse_volume_spec_skips_non_host(tmp_path: Path) -> None:
    """Verify a non-host spec (e.g. a job file) parses to None."""
    # Given a job file in the same directory
    f = tmp_path / "web.hcl"
    f.write_text('job "web" {}', encoding="utf-8")
    # When parsing
    spec = parse_volume_spec(f)
    # Then it is not a host volume
    assert spec is None


def test_parse_volume_spec_defaults_capabilities(tmp_path: Path) -> None:
    """Verify a host volume without a capability block gets the default capability."""
    # Given a host spec lacking a capability block
    f = tmp_path / "data.hcl"
    f.write_text('name = "data"\ntype = "host"', encoding="utf-8")
    # When parsing
    spec = parse_volume_spec(f)
    # Then the default multi-node-multi-writer/file-system capability is applied
    assert spec is not None
    assert spec.capabilities == [
        {"access_mode": "multi-node-multi-writer", "attachment_mode": "file-system"}
    ]


def test_parse_volume_spec_ignores_incomplete_capability(tmp_path: Path) -> None:
    """Verify a capability block lacking access_mode or attachment_mode is ignored."""
    # Given a host spec with an incomplete capability block (only access_mode)
    f = tmp_path / "data.hcl"
    f.write_text(
        'name = "data"\ntype = "host"\ncapability {\n  access_mode = "single-node-writer"\n}',
        encoding="utf-8",
    )
    # When parsing
    spec = parse_volume_spec(f)
    # Then the incomplete capability is skipped and default is applied
    assert spec is not None
    assert spec.capabilities == [
        {"access_mode": "multi-node-multi-writer", "attachment_mode": "file-system"}
    ]


def test_parse_volume_spec_skips_interpolated_name(tmp_path: Path) -> None:
    """Verify a host spec with an interpolated name is not returned as a usable spec."""
    # Given a host volume spec with an HCL-interpolated name
    f = tmp_path / "data.hcl"
    f.write_text('name = "${var.name}"\ntype = "host"', encoding="utf-8")
    # When parsing
    # Then the interpolated name is skipped and None is returned
    assert parse_volume_spec(f) is None


def test_discover_volume_files_keeps_only_host_specs(tmp_path: Path) -> None:
    """Verify discovery returns host specs sorted by name and skips other files."""
    # Given a dir with a host volume, a job file, and unparsable and non-UTF-8 files
    d = tmp_path / "vols"
    d.mkdir()
    (d / "data.hcl").write_text(_HOST_SPEC, encoding="utf-8")
    (d / "web.hcl").write_text('job "web" {}', encoding="utf-8")
    (d / "broken.nomad").write_text("not = = hcl", encoding="utf-8")
    (d / "binary.hcl").write_bytes(b"\xff\xfe")
    # When discovering
    specs = discover_volume_files([d])
    # Then only the host volume spec is returned
    assert [s.name for s in specs] == ["data"]


def test_load_volume_directories_reads_table(tmp_path: Path) -> None:
    """Verify the [volumes] directories list is read and ~ is expanded."""
    # Given an nd config with a [volumes] table
    cfg = tmp_path / "config.toml"
    cfg.write_text('[volumes]\ndirectories = ["~/vols", "/srv/vols"]\n', encoding="utf-8")
    # When
    dirs = load_volume_directories(cfg)
    # Then ~ expands and order is preserved
    assert dirs[0] == Path.home() / "vols"
    assert dirs[1] == Path("/srv/vols")


def test_parse_volume_spec_skips_job_files(tmp_path: Path) -> None:
    """Verify a file containing a job block is never read as a volume spec."""
    # Given a job file that also carries host-volume top-level attributes
    f = tmp_path / "web.hcl"
    f.write_text('name = "data"\ntype = "host"\njob "web" {}', encoding="utf-8")

    # When parsing it as a volume spec
    # Then it is treated as a job file and skipped
    assert parse_volume_spec(f) is None
