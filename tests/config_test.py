# type: ignore
"""Test configuration model."""
import filecmp
import shutil
from pathlib import Path

import pytest
import typer

from nd.config.config import PATH_CONFIG_DEFAULT, Config


def test_init_config_1():
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN no path is provided
    THEN raise an exception
    """
    with pytest.raises(typer.Exit):
        Config()


def test_init_config_2(tmp_path):
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN a path to a non-existent file is provided
    THEN create the default configuration file and exit
    """
    config_path = Path(tmp_path / "config.toml")
    with pytest.raises(typer.Exit):
        Config(config_path=config_path)
    assert config_path.exists()
    assert filecmp.cmp(config_path, PATH_CONFIG_DEFAULT) is True


def test_init_config_3(tmp_path):
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN a path to the default configuration file is provided
    THEN load the configuration file
    """
    path_to_config = Path(tmp_path / "config.toml")
    shutil.copy(PATH_CONFIG_DEFAULT, path_to_config)
    config = Config(config_path=path_to_config)
    assert config.config_path == path_to_config
    assert config.config == {
        "file_ignore_strings": ["temp"],
        "job_file_locations": ["/some/path", "~/some/other/path"],
        "nomad_address": "http://localhost:4646",
    }
    assert config.context == {}
    assert config.dry_run is False
    assert config.force is False
    assert config.nomad_address == "http://localhost:4646"
    assert config.job_file_locations == ["/some/path", "~/some/other/path"]


def test_init_config_4(tmp_path):
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN values are provided in the context
    THEN load the configuration file
    """
    path_to_config = Path(tmp_path / "config.toml")
    shutil.copy(PATH_CONFIG_DEFAULT, path_to_config)
    config = Config(config_path=path_to_config, context={"dry_run": True, "force": True})
    assert config.config_path == path_to_config
    assert config.config == {
        "file_ignore_strings": ["temp"],
        "job_file_locations": ["/some/path", "~/some/other/path"],
        "nomad_address": "http://localhost:4646",
    }
    assert config.context == {"dry_run": True, "force": True}
    assert config.dry_run is True
    assert config.force is True


def test_init_config_5(tmp_path):
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN `file_ignore_strings` is not provided
    THEN `file_ignore_strings` is set to an empty list
    """
    config_text = """
job_file_locations = ['/some/path', '~/some/other/path']
nomad_address = 'http://localhost:4646'
    """

    path_to_config = Path(tmp_path / "config.toml")
    path_to_config.write_text(config_text)
    config = Config(config_path=path_to_config)
    assert config.file_ignore_strings == []


def test_init_config_6(tmp_path):
    """Test initializing a configuration file.

    GIVEN a request to initialize a configuration file
    WHEN `file_ignore_strings` is not a list
    THEN `file_ignore_strings` is set to an empty list
    """
    config_text = """
file_ignore_strings = 'temp'
job_file_locations = ['/some/path', '~/some/other/path']
nomad_address = 'http://localhost:4646'
    """

    path_to_config = Path(tmp_path / "config.toml")
    path_to_config.write_text(config_text)
    config = Config(config_path=path_to_config)
    assert config.file_ignore_strings == []


def test_validate_config_1(tmp_path):
    """Test validating a configuration file.

    GIVEN a request to validate a configuration file
    WHEN the api url is not valid
    THEN raise an exception
    """
    config_text = """
job_files_locations = ['/some/path', '~/some/other/path']
nomad_address       = ''
    """
    path_to_config = Path(tmp_path / "config.toml")
    path_to_config.write_text(config_text)
    with pytest.raises(typer.Exit):
        Config(config_path=path_to_config)


def test_validate_config_2(tmp_path):
    """Test validating a configuration file.

    GIVEN a request to validate a configuration file
    WHEN the web url is not valid
    THEN raise an exception
    """
    config_text = """
job_files_locations = ['/some/path', '~/some/other/path']
nomad_address       = 'http://localhost:4646'
    """
    path_to_config = Path(tmp_path / "config.toml")
    path_to_config.write_text(config_text)
    with pytest.raises(typer.Exit):
        Config(config_path=path_to_config)
