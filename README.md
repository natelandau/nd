[![Automated Tests](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml/badge.svg)](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml) [![codecov](https://codecov.io/gh/natelandau/nd/graph/badge.svg?token=HpyhUwExqh)](https://codecov.io/gh/natelandau/nd)

# nd

A friendly command-line tool for managing a Nomad cluster.

`nd` wraps the Nomad HTTP API and the local `nomad` binary behind a small set of
task-focused commands. Instead of stitching together multiple nomad commands, you
get easy to remember commands that marry your on-disk job and volume files and the
live cluster. No more no more hunting for an allocation ID or task name, just use
your easy to remember job and volume names and the cli does the rest.

## Features

- A one-screen cluster dashboard covering nodes, jobs, allocations, deployments,
  evaluations, and host volumes.
- Deploy and stop commands that watch the rollout or drain live and report a clear
  success or failure at the end.
- Job-file aware commands that discover and work with your local `.hcl` and `.nomad` specs
- Interactive shell and log streaming for any task, with a prompt to pick the job,
  allocation, and task when the choice is ambiguous.
- Dynamic host volume management: register, delete, and list host volumes across
  every eligible node.
- Standard `NOMAD_*` environment variables work out of the box, with an optional
  config file for anything you would rather not retype.

## Requirements

- Python 3.13 or 3.14.
- A reachable Nomad cluster.
- The `nomad` binary on your `PATH`. The `plan`, `run`, `update`, `exec`, and `logs`
  commands shell out to it, because the HTTP API cannot parse HCL2 job files and does
  not own the interactive exec protocol. The other commands use the API only.

## Installation

The tool is published to PyPI as `nomadctl`. The installed command is `nd`.

Install it as an isolated CLI with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install nomadctl
```

Or with `pipx`:

```bash
pipx install nomadctl
```

Confirm the install:

```bash
nd --version
```

## Configuration

`nd` reads the standard Nomad environment variables first, then overrides them with
an optional config file. If you already run `nomad` from your shell, `nd` targets
the same cluster with no extra setup.

### Environment variables

| Variable                | Purpose                      | Default                    |
| ----------------------- | ---------------------------- | -------------------------- |
| `NOMAD_ADDR`            | Cluster API address          | `http://127.0.0.1:4646`    |
| `NOMAD_TOKEN`           | ACL token                    | none                       |
| `NOMAD_NAMESPACE`       | Default namespace            | none                       |
| `NOMAD_REGION`          | Default region               | none                       |
| `NOMAD_CACERT`          | Path to a CA certificate     | none                       |
| `NOMAD_CLIENT_CERT`     | Path to a client certificate | none                       |
| `NOMAD_CLIENT_KEY`      | Path to a client key         | none                       |
| `NOMAD_TLS_SERVER_NAME` | TLS server name override     | none                       |
| `NOMAD_UI_URL`          | Base URL for web UI links    | falls back to `NOMAD_ADDR` |

### Config file

For settings you do not want to export every session, create
`~/.config/nd/config.toml` (or `$XDG_CONFIG_HOME/nd/config.toml`). Values here
override the environment.

```toml
[nomad]
address = "https://nomad.example.com:4646"
token   = "your-acl-token"
ui_url  = "https://nomad.example.com"

# Directories nd searches for .hcl and .nomad job files.
[jobs]
directories = ["~/homelab/jobs"]

# Directories nd searches for host volume spec files.
[volumes]
directories = ["~/homelab/volumes"]
```

The `[jobs]` and `[volumes]` directory lists power the file-aware commands. Without
them, `list`, `plan`, `run`, and the `volume` commands have nothing to discover.

## Quick start

Point `nd` at your cluster, then look at it:

```bash
export NOMAD_ADDR="https://nomad.example.com:4646"
export NOMAD_TOKEN="your-acl-token"

nd
```

Add a job directory to your config file, then list your specs against the live
cluster:

```bash
nd list
```

Deploy a job that is not yet running and watch it roll out:

```bash
nd run web
```

Tail its logs, then open a shell inside it:

```bash
nd logs web
nd exec web
```

## Commands

Run `nd --help`, or `nd <command> --help`, for the full option list at any time.

| Command                     | What it does                                                                      |
| --------------------------- | --------------------------------------------------------------------------------- |
| `nd status`                 | Show an at-a-glance overview of the cluster. Also runs when you type `nd` alone.  |
| `nd list`                   | List discovered job files and whether each is running, dead, or not deployed.     |
| `nd plan [JOB]`             | Preview the changes one or more job files would apply, including to running jobs. |
| `nd run [JOB]`              | Deploy not-yet-running job files and watch the rollout.                           |
| `nd update [JOB]`           | Recreate a running job from its local file and watch the rollout.                 |
| `nd stop [JOB]`             | Stop, and optionally purge, running jobs and watch them drain.                    |
| `nd logs [JOB]`             | Stream, tail, or export a task's logs.                                            |
| `nd exec [JOB]`             | Open an interactive shell inside a running task.                                  |
| `nd clean`                  | Force garbage collection and reconcile job summaries.                             |
| `nd volume register [NAME]` | Register host volumes on every eligible node.                                     |
| `nd volume delete [NAME]`   | Delete registered host volumes matching the selected specs.                       |
| `nd volume list [NAME]`     | List host volume specs and where each is registered.                              |

### Targeting jobs by name

Commands that take a `JOB` or `NAME` argument match by case-insensitive name prefix.
A single match runs straight away; several matches open a prompt. Omit the argument
to pick from a list of every candidate.

```bash
nd run web          # runs the one job whose name starts with "web"
nd stop             # prompts you to choose from all running jobs
```

### Previewing before you act

Lifecycle commands accept `--dry-run` (`-n`) to report their targets without
touching the cluster:

```bash
nd run --dry-run
nd update web --dry-run
nd stop web --dry-run
nd volume register --dry-run
```

For `nd run` and `nd update`, a dry run still validates each job file locally, so it
catches a broken spec without registering anything.

### Deploying jobs

`nd run` only offers jobs that are not already running. Each selected file is
validated and registered, then watched live until its deployment or allocations
settle. Use `--detach` to register and return without watching the rollout.

```bash
nd run                # choose from every deployable job
nd run web            # deploy the job whose name starts with "web"
nd run web --detach   # register and return immediately
```

### Updating jobs

`nd update` recreates a job that is already running. Reach for it to roll out an
edited job file, or to pull a fresh version when the file is unchanged, such as a
container that tracks a moving tag. It only offers jobs that are both running and
have a local file.

Each selected job is stopped, drained, purged, then re-registered from its local
file and watched until the new rollout settles. The job is fully recreated, so
expect brief downtime. `nd update` confirms before it acts unless you pass `--force`
(`-f`), and purges by default (unlike `nd stop`, which keeps the job unless you pass
`--purge`); pass `--no-purge` to keep the job's version history.

```bash
nd update                 # choose from every running job that has a local file
nd update web             # recreate the job whose name starts with "web"
nd update web --no-purge  # recreate but keep the version history
nd update web --force     # skip the confirmation prompt
```

Whether a new container image is actually pulled depends on the job's Docker driver
config, such as `force_pull` or a pinned digest, not on `nd`. The recreate
guarantees fresh allocations; the image policy stays with your job spec.

### Working with logs

`nd logs` streams both stdout and stderr live until you press Ctrl-C. Narrow or
redirect the output with flags:

```bash
nd logs web                 # follow stdout and stderr
nd logs web --stderr        # follow stderr only
nd logs web --tail 100      # print the last 100 lines, no follow
nd logs web --export run.log  # write the current logs to a file
```

### Stopping jobs

`nd stop` confirms before it acts unless you pass `--force`. Use `--purge` to
garbage-collect the job afterward, `--detach` to return without watching the drain,
and `--no-shutdown-delay` to skip the configured shutdown delays for an immediate
teardown.

```bash
nd stop web                       # confirm, stop, and watch it drain
nd stop web --purge --force       # purge without a prompt
nd stop web --detach              # request the stop and return immediately
```

### Verbosity

Add `-v` for debug output or `-vv` to trace each API request with timings. The flag
works before or after the subcommand.

```bash
nd status -v
nd -vv run web
```

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management and
[duty](https://pawamoy.github.io/duty/) as a task runner.

```bash
uv sync                  # install dependencies
uv run nd --help         # run the CLI from source
uv run duty lint         # run ruff, ty, typos, and prek
uv run duty test         # run the test suite with coverage
```

## License

MIT. See [LICENSE](LICENSE).
