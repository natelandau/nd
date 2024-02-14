# type: ignore
"""Test utility helper functions."""

from pathlib import Path

from nd.models.nomad_api import NomadAPI
from nd.utils.helpers import find_job_files, find_nodes, find_running_jobs


def test_find_job_files_1(tmp_path, mock_config):
    """Test find_job_files function.

    GIVEN a directory with no job files
    WHEN the directory is searched
    THEN return an empty list
    """
    directory = Path(tmp_path / "directory")
    directory.mkdir()

    config = mock_config
    config.job_file_locations = [directory]
    assert find_job_files(config=config) == []


def test_find_job_files_2(tmp_path, mock_config):
    """Test find_job_files function.

    GIVEN a list of containing a file
    WHEN when the list is searched
    THEN files are ignored
    """
    directory = Path(tmp_path / "directory")
    file = Path(tmp_path / "file.hcl")
    file.touch
    directory.mkdir()

    config = mock_config
    config.job_file_locations = [directory, file]

    assert find_job_files(config) == []


def test_find_job_files_3(mock_config, tmp_path):
    """Test find_job_files function.

    GIVEN a directory with job files
    WHEN the directory is searched
    THEN return a list of JobFile objects
    """
    config = mock_config
    config.file_ignore_strings = []
    file = Path(tmp_path / "file.hcl")
    file.touch
    assert len(find_job_files(config)) == 4


def test_find_job_files_4(mock_config, tmp_path):
    """Test find_job_files function.

    GIVEN multiple directories with job files
    WHEN the directories are searched
    THEN return a deduplicated list of JobFile objects
    """
    config = mock_config
    config.file_ignore_strings = []
    config.job_file_locations = [Path(tmp_path / "job_dir"), tmp_path]
    assert len(find_job_files(config)) == 4


def test_find_job_files_5(mock_config, tmp_path):
    """Test find_job_files function.

    GIVEN a directory containing directories with job files
    WHEN the directory is searched
    THEN return a deduplicated list of JobFile objects from all subdirectories
    """
    config = mock_config
    config.file_ignore_strings = []
    config.job_file_locations = [tmp_path]
    assert len(find_job_files(config)) == 4


def test_find_job_files_6(mock_config):
    """Test find_job_files function.

    GIVEN a directory with job files
    WHEN an ignore string is provided
    THEN return a list of JobFile objects excluding files matching the ignore string
    """
    assert len(find_job_files(mock_config)) == 3


def test_find_job_files_7(mock_config):
    """Test find_job_files function.

    GIVEN a directory with job files
    WHEN a search string is provided
    THEN return a list of JobFile objects matching the search string
    """
    assert len(find_job_files(mock_config, search_string="exam")) == 3


def test_find_job_files_8(mock_config):
    """Test find_job_files function.

    GIVEN a directory with job files
    WHEN a search string is provided and the search string is not found
    THEN return an empty list
    """
    assert len(find_job_files(mock_config, search_string="no_match")) == 0


def test_find_nodes_1(mocker, mock_api_responses):
    """Test find_nodes function.

    GIVEN a valid JSON response containing nodes
    WHEN the response is parsed
    THEN return a list of Node objects
    """
    api = NomadAPI(url="http://192.168.1.1")
    mocker.patch.object(NomadAPI, "get_nodes", return_value=mock_api_responses[0])
    nodes = find_nodes(api)
    assert len(nodes) == 2
    assert nodes[0].name == "node1"


def test_find_nodes_2(mocker):
    """Test find_nodes function.

    GIVEN a valid JSON response not containing nodes
    WHEN the response is parsed
    THEN return an empty list
    """
    api = NomadAPI(url="http://192.168.1.1")
    mocker.patch.object(NomadAPI, "get_nodes", return_value=[])
    nodes = find_nodes(api)
    assert len(nodes) == 0


def test_find_running_jobs_1(mocker, mock_api_responses):
    """Test find_running_jobs function.

    GIVEN a valid JSON response containing jobs
    WHEN the response is parsed
    THEN return a list of Job objects
    """
    api = NomadAPI(url="http://192.168.1.1")
    mocker.patch.object(NomadAPI, "get_jobs", return_value=mock_api_responses[1])
    mocker.patch.object(
        NomadAPI, "get_allocations", side_effect=[mock_api_responses[2], mock_api_responses[3]]
    )
    jobs = find_running_jobs(api, nomad_address="http://192.168.1.1")
    assert len(jobs) == 2
    assert jobs[0].name == "job1"


def test_find_running_jobs_2(mocker):
    """Test find_running_jobs function.

    GIVEN a valid JSON response not containing jobs
    WHEN the response is parsed
    THEN return an empty list
    """
    api = NomadAPI(url="http://192.168.1.1")
    mocker.patch.object(NomadAPI, "get_jobs", return_value=[])
    jobs = find_running_jobs(api, nomad_address="http://192.168.1.1")
    assert len(jobs) == 0
