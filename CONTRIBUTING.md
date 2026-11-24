# Contributing to nd

This guide shows how to set up a development environment, run the checks, and submit
a change.

## Prerequisites

You need these tools:

- [uv](https://docs.astral.sh/uv/), which installs Python and the project dependencies.
- Python 3.13, 3.14, or 3.15. If you do not have one, uv installs it.
- Optional: the `nomad` binary and a Nomad cluster, to try your change by hand. The
  test suite does not need either.

## Set up the project

To install the project and its Git hooks, do these steps:

1. Clone the repository and go into it:

    ```bash
    git clone https://github.com/natelandau/nd.git
    cd nd
    ```

2. Install the dependencies:

    ```bash
    uv sync
    ```

3. Install the Git hooks:

    ```bash
    uv run prek install
    ```

The hooks run the linters and tests before each commit, check each commit message,
and check the commits on your branch before each push.

## Run the CLI from source

Use `uv run` to run your working copy of `nd`:

```bash
uv run nd --help
uv run nd status
```

## Run the checks

The project uses [duty](https://pawamoy.github.io/duty/) as a task runner. Run the
checks through `duty`, not through the tools directly:

```bash
uv run duty lint   # ruff, ty, typos, and the pre-commit hooks
uv run duty test   # the test suite, with coverage
```

The test suite must keep at least 90% coverage. Tests run in random order. If a test
fails only in some orders, run the suite again with the seed from the start of the
output:

```bash
uv run duty test -p randomly --randomly-seed=SEED
```

`duty test` and the pre-commit hooks in `duty lint` do not run again on files that
already passed. A skipped run is a pass, and `duty test` shows a line that contains
`already passed on`. To force a full run, set `GATE_CACHE_DISABLE=1`:

```bash
GATE_CACHE_DISABLE=1 uv run duty test
```

## Submit a change

Commit messages and pull request titles use
[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject`.
The scope is optional. The subject starts with a lowercase letter. The pull request
title accepts these types:

| Type       | Use it for                                     |
| ---------- | ---------------------------------------------- |
| `feat`     | A new feature                                  |
| `fix`      | A bug fix                                      |
| `docs`     | Documentation only                             |
| `style`    | Formatting that does not change behavior       |
| `refactor` | A code change that is not a fix or a feature   |
| `perf`     | A performance improvement                      |
| `test`     | Tests only                                     |
| `build`    | The build system or dependencies               |
| `ci`       | The CI configuration                           |

Before you open a pull request, make sure that `uv run duty lint` and
`uv run duty test` pass. CI runs the tests on Python 3.13, 3.14, and 3.15, and the
linters once.
