# nd

`nd` is a command-line tool for managing a [Hashicorp Nomad](https://developer.hashicorp.com/nomad) homelab. It wraps the Nomad HTTP API behind a small, friendly CLI built with Typer and Rich.

> The package is published on PyPI as [`nomadctl`](https://pypi.org/project/nomadctl/); the installed command is `nd`.

## Install

Install the CLI as an isolated tool (recommended):

```bash
uv tool install nomadctl
```

Or install it into the current environment with pip:

```bash
pip install nomadctl
```

Either way the `nd` command is added to your `PATH`:

```bash
nd --help
```

### Run from source

To work on `nd` from a checkout, install the dependencies and run it through uv:

```bash
uv sync
uv run nd --help
```

The `nd plan`, `nd run`, `nd exec`, and `nd logs` commands also need the [`nomad` CLI binary](https://developer.hashicorp.com/nomad/install) on your `PATH`. `nd plan` and `nd run` use it because the HTTP API can't parse HCL2, so the local binary validates your job files and compiles them to JSON before deploying. `nd exec` and `nd logs` use it for the interactive shell session and log streaming, which the binary handles natively. The remaining commands (`status`, `stop`, `list`, `clean`, `volume`) talk to the API directly and don't need it.

## Configuration

`nd` runs with no setup at all. With nothing configured, it talks to a local Nomad agent at `http://127.0.0.1:4646`. To point it at a remote cluster, send an ACL token, or tell it where your job files live, add a config file at `$XDG_CONFIG_HOME/nd/config.toml` (default `~/.config/nd/config.toml`).

`nd` reads the standard Nomad environment variables (`NOMAD_ADDR`, `NOMAD_TOKEN`, and the others listed below) first, then applies the config file on top. A value set in `config.toml` overrides the matching environment variable.

Here is a config file that uses every option:

```toml
# ~/.config/nd/config.toml

[nomad]
address = "https://nomad.example.com:4646"
token = "your-acl-token"
namespace = "default"
region = "global"
timeout = 30.0
ui_url = "https://nomad.example.com"

[jobs]
directories = ["~/homelab/nomad-jobs", "/srv/nomad/services"]

[volumes]
directories = ["~/homelab/nomad-volumes", "/srv/nomad/volumes"]
```

Every key is optional. Set only the ones you need.

### `[nomad]` table

These keys control how `nd` connects to the Nomad HTTP API. They also apply to the bundled `nomad` binary that `plan`, `run`, `exec`, and `logs` call, so a config-file override points both the API client and the binary at the same cluster. Each key maps to a standard Nomad environment variable, except `timeout`, which has no variable.

| Key | What it sets | Default | Environment variable |
| --- | --- | --- | --- |
| `address` | Base URL of the Nomad HTTP API | `http://127.0.0.1:4646` | `NOMAD_ADDR` |
| `token` | ACL token sent with every request | none | `NOMAD_TOKEN` |
| `namespace` | Namespace that requests run against | Nomad's `default` | `NOMAD_NAMESPACE` |
| `region` | Region that requests run against | the server's region | `NOMAD_REGION` |
| `ca_cert` | Path to a PEM CA certificate used to verify the server's TLS certificate | system trust store | `NOMAD_CACERT` |
| `client_cert` | Path to a PEM client certificate for mutual TLS | none | `NOMAD_CLIENT_CERT` |
| `client_key` | Path to the PEM private key for mutual TLS | none | `NOMAD_CLIENT_KEY` |
| `tls_server_name` | Server name used when verifying the TLS certificate (SNI) | host from `address` | `NOMAD_TLS_SERVER_NAME` |
| `ui_url` | Base URL for the clickable web UI links shown by `nd status` and `nd list` | value of `address` | `NOMAD_UI_URL` |
| `timeout` | HTTP request timeout, in seconds | `60` | none |

> **Note:** Mutual TLS needs both `client_cert` and `client_key`. Setting only one has no effect.

### `[jobs]` table

This table tells `nd` where your Nomad job files live so that `nd list`, `nd plan`, and `nd run` can find them.

| Key | What it sets | Default |
| --- | --- | --- |
| `directories` | List of directories to scan for job files (`*.hcl` and `*.nomad`) | empty |

`nd` scans each listed directory for job files, expands a leading `~` to your home directory, and skips any directory that does not exist. Files are classified by content: a file with a `job "..." {}` block is treated as a job, so a host-volume spec sharing the same directory is not mistaken for one. Without a `[jobs]` table, the job-file commands have nothing to work with.

### `[volumes]` table

This table tells `nd` where your Nomad host-volume spec files live so that `nd volume register`, `nd volume delete`, and `nd volume list` can find them.

| Key | What it sets | Default |
| --- | --- | --- |
| `directories` | List of directories to scan for host-volume specs (`*.hcl` and `*.nomad`) | empty |

`nd` scans each listed directory with the same `*.hcl` and `*.nomad` globs it uses for job files. Files are classified by content: a file with `type = "host"` is treated as a volume spec; a file with a `job "..." {}` block is treated as a job. A single directory can therefore hold both kinds of file. `nd` expands a leading `~` and silently skips directories that do not exist. Without a `[volumes]` table, the volume commands have nothing to work with.

Add `-v` for debug output or `-vv` for request tracing on any command.

## Commands

### `nd status`

Show an at-a-glance overview of the cluster: servers and leader, client nodes (with their active allocation counts), jobs (with the nodes each runs on), allocation health, registered host volumes, and any in-progress deployments or stuck evaluations. The Volumes panel and count are empty when the cluster or token cannot read host volumes (for example on older Nomad versions), so the rest of the dashboard still renders.

```bash
uv run nd status
```

### `nd stop`

Stop (and optionally remove) running jobs.

```bash
uv run nd stop [JOB] [--purge/-p] [--force/-f] [--dry-run/-n]
```

- **`JOB`** — optional. Matches any running job whose name starts with the given text (case-insensitive). One match stops that job; several matches open a multi-select.
- **no `JOB`** — opens a multi-select of every running job.
- **`--purge` / `-p`** — garbage-collect the job after stopping it, instead of leaving it in the `dead` state.
- **`--force` / `-f`** — skip the confirmation prompt.
- **`--dry-run` / `-n`** — resolve and report the targets without actually stopping anything.

Each selected job is stopped concurrently, with a live panel that tracks it until its allocations have fully drained (including any `poststop` tasks). Press `Ctrl-C` at any time to abort cleanly.

The next three commands work with the local job files you point `nd` at with the [`[jobs]` table](#jobs-table).

### `nd list`

List every discovered job file alongside its status on the cluster: running, dead, or not deployed. Deployed job names link to the web UI.

```bash
uv run nd list
```

### `nd plan`

Preview the changes a job file would make by surfacing `nomad job plan` output verbatim, including Nomad's own colored diff. Already-running jobs are valid targets, so you can preview an in-place update.

```bash
uv run nd plan [JOB] [--dry-run/-n]
```

- **`JOB`** — optional. Matches any job file whose name starts with the given text. One match plans that job; several matches open a multi-select.
- **no `JOB`** — opens a multi-select of every job file.
- **`--dry-run` / `-n`** — report which files would be planned without running the binary.

### `nd run`

Deploy job files that are not already running, then watch the rollout in a live panel. Service jobs wait for the deployment to succeed; batch and system jobs track their allocations.

```bash
uv run nd run [JOB] [--dry-run/-n]
```

- **`JOB`** — optional. Matches any not-running job file whose name starts with the given text. One match runs that job; several matches open a multi-select.
- **no `JOB`** — opens a multi-select of every not-running job file.
- **`--dry-run` / `-n`** — resolve and validate the targets without registering anything.

### `nd clean`

Run cluster housekeeping: force garbage collection of dead jobs, terminal allocations and evaluations, and GC-eligible nodes, then reconcile any drifted job summary counts.

```bash
uv run nd clean
```

Both operations are safe and idempotent (they only remove or correct already-terminal state), so the command takes no arguments and no confirmation. Add `-v` to name each `PUT` request or `-vv` to also show its elapsed time.

The next three commands manage dynamic host volumes. They use the spec files you point `nd` at with the [`[volumes]` table](#volumes-table).

### `nd volume list`

List every discovered host-volume spec alongside its registration status on the cluster. There is one row per discovered spec, including specs not yet registered on any node (those show no nodes). Each row shows the volume name and which nodes it is currently registered on.

```bash
uv run nd volume list
```

### `nd volume register`

Register discovered host-volume specs on every eligible cluster node. `nd` reads each node's `nfsStorageRoot` metadata key and combines it with the spec's `relative_path` parameter to compute the host path, then calls the Nomad API to register the volume. Already-registered volumes are skipped.

```bash
uv run nd volume register [--dry-run/-n]
```

- **`--dry-run` / `-n`** — report what would be registered without changing the cluster.

### `nd volume delete`

Delete every registered host volume whose name matches a discovered spec.

```bash
uv run nd volume delete [--dry-run/-n]
```

- **`--dry-run` / `-n`** — report what would be deleted without changing the cluster.

The next two commands act on a single task inside a running allocation.

### `nd exec`

Open an interactive shell inside a running task.

```bash
uv run nd exec [JOB] [--task/-t TASK] [--shell/-s SHELL]
```

- **`JOB`** — optional. Matches any running job whose name starts with the given text. One match selects it; several open a prompt to pick one.
- **no `JOB`** — opens a prompt to pick from every running job.
- **`--task` / `-t`** — the task to enter, skipping the task prompt. Needed only when the allocation runs more than one task.
- **`--shell` / `-s`** — the shell to launch. By default `nd` runs `bash` when the container has it and falls back to `sh`, so it works on minimal images too.

`nd` walks you from the job to one of its running allocations to one of its running tasks, picking automatically whenever there's only one and prompting when there are several. The session inherits your terminal, so it's fully interactive. Type `exit` or press `Ctrl-D` to leave.

### `nd logs`

Stream, tail, or export a task's logs. Unlike `nd exec`, this also reaches dead, completed, and failed tasks, so you can read the logs of a job that already crashed.

```bash
uv run nd logs [JOB] [--task/-t TASK] [--stdout/-o] [--stderr/-e] [--tail/-n N] [--export PATH]
```

- **`JOB`** — optional. Matches any job whose name starts with the given text, running or not. One match selects it; several open a prompt to pick one.
- **no `JOB`** — opens a prompt to pick from every job.
- **`--task` / `-t`** — the task to read, skipping the task prompt.
- **`--stdout` / `-o`** — show only the stdout stream.
- **`--stderr` / `-e`** — show only the stderr stream.
- **`--tail` / `-n N`** — print the last `N` lines and exit, instead of following the live stream.
- **`--export PATH`** — write the current logs to `PATH`, then exit.

By default `nd logs` follows both stdout and stderr, interleaved, until you press `Ctrl-C`. Pass `--stdout` or `--stderr` to limit it to one stream.
