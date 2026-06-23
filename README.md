# nd

`nd` is a command-line tool for managing a [Hashicorp Nomad](https://developer.hashicorp.com/nomad) homelab. It wraps the Nomad HTTP API behind a small, friendly CLI built with Typer and Rich.

## Install and run

```bash
uv sync
uv run nd --help
```

## Configuration

`nd` connects to Nomad using the standard Nomad environment variables (`NOMAD_ADDR`, `NOMAD_TOKEN`, `NOMAD_NAMESPACE`, `NOMAD_REGION`, and the TLS variables). You can override them with a `[nomad]` table in `$XDG_CONFIG_HOME/nd/config.toml` (default `~/.config/nd/config.toml`). With nothing set, `nd` talks to `http://127.0.0.1:4646`.

Add `-v` for debug output or `-vv` for request tracing on any command.

## Commands

### `nd status`

Show an at-a-glance overview of the cluster: servers and leader, client nodes (with their active allocation counts), jobs (with the nodes each runs on), allocation health, and any in-progress deployments or stuck evaluations.

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

### `nd clean`

Run cluster housekeeping: force garbage collection of dead jobs, terminal allocations and evaluations, and GC-eligible nodes, then reconcile any drifted job summary counts.

```bash
uv run nd clean
```

Both operations are safe and idempotent (they only remove or correct already-terminal state), so the command takes no arguments and no confirmation. Add `-v` to name each `PUT` request or `-vv` to also show its elapsed time.
