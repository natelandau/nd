[![Automated Tests](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml/badge.svg)](https://github.com/natelandau/nd/actions/workflows/automated-tests.yml) [![codecov](https://codecov.io/gh/natelandau/nd/graph/badge.svg?token=HpyhUwExqh)](https://codecov.io/gh/natelandau/nd)

# nd

A friendly command-line tool for managing a Nomad cluster.

`nd` wraps the Nomad HTTP API and the local `nomad` binary in a small set of
task-focused commands. The commands connect the job and volume files on your disk to
the live cluster. You refer to jobs and volumes by name, and `nd` finds the
allocation ID and task name for you.

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
- Standard `NOMAD_*` environment variables work by default, with an optional
  config file for settings you do not want to retype.

## Requirements

- Python 3.13, 3.14, or 3.15.
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

`nd` reads each setting from three places. When a setting appears in more than one
place, the source higher in this list wins:

1. Environment variables (`NOMAD_*`)
2. The `[nomad]` table of the config file
3. Built-in defaults

If you already run `nomad` from your shell, `nd` targets the same cluster with no
extra setup. An empty environment variable counts as not set.

### Settings

| Environment variable    | Config key        | Purpose                      | Default                    |
| ----------------------- | ----------------- | ---------------------------- | -------------------------- |
| `NOMAD_ADDR`            | `address`         | Cluster API address          | `http://127.0.0.1:4646`    |
| `NOMAD_TOKEN`           | `token`           | ACL token                    | none                       |
| `NOMAD_NAMESPACE`       | `namespace`       | Default namespace            | none                       |
| `NOMAD_REGION`          | `region`          | Default region               | none                       |
| `NOMAD_CACERT`          | `ca_cert`         | Path to a CA certificate     | none                       |
| `NOMAD_CLIENT_CERT`     | `client_cert`     | Path to a client certificate | none                       |
| `NOMAD_CLIENT_KEY`      | `client_key`      | Path to a client key         | none                       |
| `NOMAD_TLS_SERVER_NAME` | `tls_server_name` | TLS server name override     | none                       |
| `NOMAD_UI_URL`          | `ui_url`          | Base URL for web UI links    | falls back to `NOMAD_ADDR` |
| none                    | `timeout`         | API request timeout, seconds | `60`                       |

### Config file

For settings you do not want to export every session, create
`~/.config/nd/config.toml` (or `$XDG_CONFIG_HOME/nd/config.toml`). An environment
variable overrides the same setting in this file.

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
them, `list`, `plan`, `run`, `update`, and the `volume` commands have nothing to
discover.

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

Follow its logs, then open a shell inside it:

```bash
nd logs web
nd exec web                    # open a shell inside it
nd exec web -- ps -ef          # or run a single command
nd exec web -T -- env          # -T skips the pseudo-terminal, so lines end in LF, not CRLF
```

## Commands

Run `nd --help`, or `nd <command> --help`, for the full option list at any time.

| Command                     | What it does                                                                      |
| --------------------------- | --------------------------------------------------------------------------------- |
| `nd status`                 | Show an at-a-glance overview of the cluster. Also runs when you type `nd` alone.  |
| `nd status --hosts`         | Pivot the same overview to one panel per host, listing the jobs each is running.  |
| `nd doctor [NAME]`          | List job and cluster problems, worst first. Exits 1 on any warning.               |
| `nd list`                   | List discovered job files and whether each is running, dead, or not deployed.     |
| `nd plan [JOB]`             | Preview the changes one or more job files would apply, including to running jobs. |
| `nd run [JOB]`              | Deploy not-yet-running job files and watch the rollout.                           |
| `nd update [JOB]`           | Recreate a running job from its local file and watch the rollout.                 |
| `nd stop [JOB]`             | Stop, and optionally purge, running jobs and watch them drain.                    |
| `nd logs [JOB]`             | Stream, tail, or export a task's logs.                                            |
| `nd exec [JOB] [-- CMD]`    | Open a shell inside a running task, or run one command in it.                     |
| `nd signal [JOB] -s SIG`    | Send a signal to a running task, such as to trigger an on-demand action.          |
| `nd restart [JOB]`          | Restart a running allocation's tasks, or one task, in place.                      |
| `nd clean`                  | Force garbage collection and reconcile job summaries.                             |
| `nd volume register [NAME]` | Register host volumes on every eligible node.                                     |
| `nd volume delete [NAME]`   | Delete registered host volumes matching the selected specs.                       |
| `nd volume list [NAME]`     | List host volume specs and where each is registered.                              |

### Targeting jobs by name

Commands that take a `JOB` or `NAME` argument match by case-insensitive substring:
any name that contains the text matches, so `web` finds both `web` and `reverse-web`.
A single match runs immediately. Several matches open a prompt. Omit the argument
to pick from a list of every candidate.

```bash
nd run web          # runs the job whose name contains "web" (prompts if several match)
nd stop             # prompts you to choose from all running jobs
```

### Previewing before you act

Lifecycle commands accept `--dry-run` (`-n`) to report their targets without
touching the cluster:

```bash
nd run --dry-run
nd update web --dry-run
nd stop web --dry-run
nd signal web -s SIGHUP --dry-run
nd restart web --dry-run
nd volume register --dry-run
```

For `nd run` and `nd update`, a dry run still validates each job file locally, so it
catches a broken spec without registering anything.

### Deploying jobs

`nd run` only offers jobs that are not already running. Each selected file is
validated and registered, then watched live until its deployment or allocations
settle. Use `--detach` to register and return without watching the rollout.

If a deployment fails, `nd run` shows why. For each failed allocation, it prints the
recent task events, such as a driver failure or a failed health check, and the last
lines that each failed task wrote to stderr.

If a selected job is still present in the cluster as a dead job (stopped without
`--purge`), `nd run` offers to garbage-collect it first so the new version deploys
onto a clean slate rather than on top of stale deployment history. Pass `--clean`
(`-c`) to purge it without prompting. A non-interactive run leaves the dead job in
place and deploys on top.

```bash
nd run                # choose from every deployable job
nd run web            # deploy the job whose name contains "web"
nd run web --detach   # register and return immediately
nd run web --clean    # purge a leftover dead "web" first, then deploy
```

### Updating jobs

`nd update` recreates a job that is already running. Reach for it to roll out an
edited job file, or to pull a fresh version when the file is unchanged, such as a
container that tracks a moving tag. It only offers jobs that are both running and
have a local file.

Each selected job is stopped, drained, purged, then re-registered from its local
file and watched until the new rollout settles. If the new rollout fails, `nd update`
shows why, the same as `nd run`. The job is fully recreated, so
expect brief downtime. `nd update` confirms before it acts unless you pass `--force`
(`-f`). It purges the job by default, while `nd stop` purges only with `--purge`.
Pass `--no-purge` to keep the job's version history.

```bash
nd update                 # choose from every running job that has a local file
nd update web             # recreate the job whose name contains "web"
nd update web --no-purge  # recreate but keep the version history
nd update web --force     # skip the confirmation prompt
```

Whether a new container image is actually pulled depends on the job's Docker driver
config, such as `force_pull` or a pinned digest, not on `nd`. The recreate
guarantees fresh allocations. The image policy stays with your job spec.

### Working with logs

`nd logs` streams both stdout and stderr live until you press Ctrl-C. Narrow or
redirect the output with flags:

```bash
nd logs web                 # follow stdout and stderr
nd logs web --stderr        # follow stderr only
nd logs web --tail 100      # print the last 100 lines, no follow
nd logs web --export run.log  # write the current logs to a file
```

### Signaling a task

Some services expose an out-of-band trigger over a POSIX signal. `nd signal` finds the
running task and delivers one, picking the job, allocation, and task the same way
`nd exec` does:

```bash
nd signal ezbak -s SIGUSR1      # ask a scheduled backup to run now
nd signal ezbak -s usr1         # same thing; the name is case-insensitive
nd signal -s SIGHUP             # pick the job from a list
nd signal web -s SIGHUP -t api  # signal the "api" task, skipping the task prompt
nd signal web -s SIGHUP -n      # show the target without sending anything
```

A success line means Nomad delivered the signal to the task. Whether the process acted
on it is up to the process: it can be busy, or it can ignore that signal. Check
with `nd logs ezbak`.

The name is checked against the fixed set Nomad's task drivers accept, which is not the
same as your machine's signal list: `SIGCHLD` and `SIGURG` are refused even though your
libc has them, and `SIGNULL` and `SIGIOT` are accepted even when your libc lacks them. A name
outside that set is rejected before anything is sent, and the error lists the ones you
can use.

Signaling needs the `alloc-lifecycle` capability on the namespace. A token that works
for every other `nd` command can still be refused here, so a "not authorized" error is
worth checking against your ACL policy before you suspect the token itself.

### Restarting a task

`nd restart` restarts tasks in place, on the same node and in the same allocation.
Use it when a process hangs or must read its config again. It is faster than
`nd update` because Nomad does not schedule a new allocation. The job, allocation,
and task are selected the same way as for `nd signal`.

```bash
nd restart web               # restart every running task in the allocation
nd restart web -t api        # restart only the "api" task
nd restart web --all-tasks   # also run prestart and poststart tasks again
nd restart web -n            # show the target without restarting anything
```

By default, Nomad restarts only the tasks that are running. A prestart or poststart
task that finished does not run again unless you add `--all-tasks` (`-a`). You cannot
use `--all-tasks` together with `--task`.

A success line means that Nomad accepted the restart. To see the task start again,
use `nd status` or `nd logs web`. Like signaling, restarting needs the
`alloc-lifecycle` capability on the namespace.

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

### Managing host volumes

`nd volume register` and `nd volume delete` create and remove dynamic host volumes
from your local spec files, and `nd volume list` shows where each spec is registered.
Deleting a host volume is irreversible and orphans data for any job that mounts it,
so `nd volume delete` confirms before it acts unless you pass `--force` (`-f`). A
`--dry-run` (`-n`) lists the registrations to delete, with no prompt.

```bash
nd volume register data            # register the "data" volume on eligible nodes
nd volume delete data              # confirm, then delete the "data" registrations
nd volume delete data --force      # delete without a prompt
nd volume delete data --dry-run    # preview what would be deleted
```

### Running from scripts and cron

Every prompt needs a real terminal on both stdin and stdout. Off one, `nd` fails with
a non-zero exit and names the flag or argument that makes the choice for it,
rather than assuming an answer. So a scripted run must resolve its own choices: name
the job or volume instead of relying on the picker, and pass `--force` (or `--clean`
for `nd run`'s dead-job cleanup) to skip a confirmation.

```bash
nd stop web --force        # works unattended
nd stop                    # fails: nothing named a job to stop
nd stop web                # fails: nothing answered the confirmation
```

`nd signal` takes no confirmation, so naming the job (and the task, when the job has
more than one) is all it needs to run from cron, provided the job has a single running
allocation. Nothing names an allocation, so a job running several always needs a
terminal:

```bash
nd signal ezbak -s SIGUSR1        # works unattended
nd signal ezbak -s SIGUSR1 -t db  # name the task too when the job runs several
nd signal web -s SIGHUP           # fails when "web" has more than one allocation
```

A named job that is not running is an error, not a no-op, so a scheduled trigger fails
loudly instead of silently doing nothing.

`nd restart` follows the same rules. Without `--task`, it never asks for a task, so
naming a job with one running allocation is enough.

### JSON output for scripts and agents

Add `--json` to `nd list`, `nd status`, or `nd status --hosts` to get the result as
one JSON document. Stdout holds only the JSON. Errors and `-v` output go to stderr,
so you can pipe stdout to `jq`.

| Command                    | Output                                                                                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nd list --json`           | An array of `{job, status, file}`. The status is the Nomad job status, or `not deployed`. `job` is `null` when the job name in the file is not resolved. |
| `nd status --json`         | An object with `health`, `cluster`, `servers`, `nodes`, `jobs`, `allocations`, `volumes`, `deployments`, and `problem_evaluations`.                      |
| `nd status --hosts --json` | The same object, with a `hosts` array. Each host lists its jobs with a `started_at` time, or `null` when Nomad has none.                                 |

Each job in `nd status --json` has two statuses. `status` is the status that `nd`
shows, and it can be `degraded`. `nomad_status` is the status that Nomad reports.
Times use ISO 8601 in UTC.

```bash
# Names of jobs that are not running cleanly
nd status --json | jq -r '.jobs[] | select(.status != "running") | .name'
```

### Verbosity

Add `-v` for debug output or `-vv` to trace each API request with timings. The flag
works before or after the subcommand.

```bash
nd status -v
nd -vv run web
```

## Contributing

To set up a development environment, run the checks, and submit a change, read
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
