[![Automated Tests](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml/badge.svg)](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml) [![codecov](https://codecov.io/github/natelandau/nd/branch/main/graph/badge.svg?token=TXHNQ55UZ9)](https://codecov.io/github/natelandau/nd)

# nd

A highly personalized CLI wrapper for Nomad providing quick shortcuts to commonly used commands and workflows.

-   Access a shell or run a command in a running task
-   Display live logs from a running task
-   Show cluster status information
-   List valid nomad job files
-   Stop, Plan, Run, and Rebuild job placements

## Install

Requires Python v3.10 or above.

Pip

```bash
pip install git+https://github.com/natelandau/nd
```

[PIPX](https://pypa.github.io/pipx/)

```bash
pipx install git+https://github.com/natelandau/nd
```

## Usage

Run `nd --help` for usage

## Configuration

Requires a valid configuration file at `~/nd.toml` for use. On first run, the following template will be created for you.

```toml
# Job files which include the following strings will be ignored
file_ignore_strings = ["temp"]

# Locations to the job files on the local filesystem
job_file_locations = ['/some/path', '~/some/other/path']

# Nomad API address
nomad_address = 'http://localhost:4646'
```

## Caveats

Built this application for personal use in my own Nomad environment and configuration. YMMV with how it functions with more advanced configurations (multi-region, ACLs, etc.).

# Contributing

## Setup: Once per project

There are two ways to contribute to this project.

### 1. Containerized development (Recommended)

1. Clone this repository. `git clone https://github.com/natelandau/nd`
2. Open the repository in Visual Studio Code
3. Start the [Dev Container](https://code.visualstudio.com/docs/remote/containers). Run <kbd>Ctrl/⌘</kbd> + <kbd>⇧</kbd> + <kbd>P</kbd> → _Remote-Containers: Reopen in Container_.
4. Run `poetry env info -p` to find the PATH to the Python interpreter if needed by VSCode.

### 2. Local development

1. Install Python 3.10 and [Poetry](https://python-poetry.org)
2. Clone this repository. `git clone https://github.com/natelandau/nd`
3. Install the Poetry environment with `poetry install`.
4. Activate your Poetry environment with `poetry shell`.
5. Install the pre-commit hooks with `pre-commit install --install-hooks`.

## Developing

-   This project follows the [Conventional Commits](https://www.conventionalcommits.org/) standard to automate [Semantic Versioning](https://semver.org/) and [Keep A Changelog](https://keepachangelog.com/) with [Commitizen](https://github.com/commitizen-tools/commitizen).
    -   When you're ready to commit changes run `cz c`
-   Run `poe` from within the development environment to print a list of [Poe the Poet](https://github.com/nat-n/poethepoet) tasks available to run on this project. Common commands:
    -   `poe lint` runs all linters
    -   `poe test` runs all tests with Pytest
-   Run `poetry add {package}` from within the development environment to install a run time dependency and add it to `pyproject.toml` and `poetry.lock`.
-   Run `poetry remove {package}` from within the development environment to uninstall a run time dependency and remove it from `pyproject.toml` and `poetry.lock`.
-   Run `poetry update` from within the development environment to upgrade all dependencies to the latest versions allowed by `pyproject.toml`.
