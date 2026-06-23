# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`nd` is a Python CLI tool that wraps common nomad commands for managing a homelab. Built with Typer and Rich, an async `httpx2` API client, and `msgspec` for decoding Nomad API responses.

## Running

```bash
uv run nd [COMMAND]
uv run nd --help
```

## Development

```bash
uv sync                  # Install dependencies
uv run duty lint         # Run all linters (ruff, ty, typos, prek)
uv run duty test         # Run tests with coverage
uv run ruff check src/   # Check code quality
uv run ruff format src/  # Format code
uv run ty check src/     # Type check code with ty
```

## Hashicorp Nomad

- This project is built on top of Hashicorp Nomad and the Nomad API and CLI.
- Web documentation is available at:
    - API: https://developer.hashicorp.com/nomad/api-docs
    - CLI: https://developer.hashicorp.com/nomad/commands
    - FULL Documentation: https://developer.hashicorp.com/nomad/docs

### Nomad API client (`src/nd/nomad/`)

The Nomad HTTP API is accessed through a typed, **async** client. Layers, top to bottom:

- `client.py` — `NomadClient`, the facade. It is an async context manager that owns a single transport and exposes resource namespaces: `client.agent`, `client.nodes`, `client.jobs`, `client.allocations`, `client.status`, `client.deployments`, `client.evaluations`, `client.system`. Resource methods are coroutines, e.g. `await client.agent.self()`, `await client.nodes.list()`.
- `resources/` — one module per resource (`agent`, `nodes`, `jobs`, `allocations`, `status`, `deployments`, `evaluations`, `system`) over `BaseResource`, which centralizes decoding via `_decode` / `_decode_list` (mapping `msgspec` failures to `NomadDecodeError`). `list()` methods auto-paginate. `jobs` also exposes lifecycle operations: `await client.jobs.stop(job_id, purge=...)` (`DELETE /v1/job/:id`), `await client.jobs.allocations(job_id)` (`GET /v1/job/:id/allocations`), `await client.jobs.register(body)` (`POST /v1/jobs`, body = compiled JSON from `jobspec.compile_to_json`), and `await client.jobs.deployments(job_id)` (`GET /v1/job/:id/deployments`). `deployments` now also exposes `await client.deployments.read(deployment_id)` (`GET /v1/deployment/:id`) to fetch full health counts during a rollout. `system` exposes cluster-housekeeping operations, both returning `None`: `await client.system.gc()` (`PUT /v1/system/gc`) and `await client.system.reconcile_summaries()` (`PUT /v1/system/reconcile/summaries`).
- `transport.py` — `AsyncTransport` wraps `httpx2.AsyncClient`, sends the `X-Nomad-Token` header, merges namespace/region params, follows next-token pagination, and maps non-2xx responses to typed errors.
- `models/` — `msgspec.Struct` definitions (`agent`, `node`, `job`, `allocation`, `deployment`). Decoding uses **msgspec, not dataclasses or pydantic**: structs use `rename="pascal"`, `frozen=True`, `kw_only=True`, with explicit `msgspec.field(name=...)` for irregular Nomad keys (`ID`, `NodeID`, `JobID`, `HTTPAddr`, `TLSEnabled`, `TaskStates`); unknown fields are tolerated by default. `job` also defines `JobDeregisterResponse` (the `jobs.stop()` result) and `JobRegisterResponse` (the `jobs.register()` result, carries `eval_id`, `job_modify_index`, `warnings`); `AllocListStub` decodes per-task `TaskStates` so callers can see which tasks are still running. `deployment` defines `DeploymentListStub` (list endpoint) and `Deployment` (full record with `task_groups: dict[str, TaskGroupDeploymentState]` for per-group health counts).
- `config.py` — `NomadConfig.resolve()` reads standard Nomad env vars (`NOMAD_ADDR`, `NOMAD_TOKEN`, `NOMAD_NAMESPACE`, `NOMAD_REGION`, `NOMAD_CACERT`, `NOMAD_CLIENT_CERT`, `NOMAD_CLIENT_KEY`, `NOMAD_TLS_SERVER_NAME`) as the base, then overrides them with a `[nomad]` table from `$XDG_CONFIG_HOME/nd/config.toml` (default `~/.config/nd/config.toml`). `NomadConfig` also carries `ui_url` and `timeout`; the address/timeout defaults come from `nd.constants`. The module also exports the public helper `default_config_path() -> Path`, which returns the XDG config file path and is reused by `jobfiles.py`.
- `errors.py` — exception hierarchy rooted at `NomadError` (`NomadConfigError`, `NomadConnectionError`, `NomadDecodeError`, `NomadHTTPError` with `NomadBadRequestError`/`NomadAuthError`/`NomadNotFoundError`/`NomadServerError`).

Public surface is re-exported from `nd.nomad`: `from nd.nomad import NomadClient, NomadConfig, NomadError`.

`src/nd/constants.py` holds centralized, tunable constants shared across the package: connection defaults (`DEFAULT_NOMAD_ADDRESS`, `DEFAULT_REQUEST_TIMEOUT_SECONDS`), the `nd stop` drain-watching tunables (`TERMINAL_ALLOC_STATUSES`, `POLL_INTERVAL_SECONDS`, `STOP_TIMEOUT_SECONDS`), job file globs (`JOB_FILE_GLOBS = ["*.hcl", "*.nomad"]`), and the `nd run` deploy-watching timeout (`DEPLOY_TIMEOUT_SECONDS`).

### CLI Wiring

The CLI entry point is `nd:main` (per `pyproject.toml`), implemented in `src/nd/cli.py`:

- A root `typer.Typer()` registers subcommands via `app.add_typer()` (`status`, `stop`, `clean`, `list`, `plan`, `run`, `logs`, `exec`).
- The root `@app.callback()` wires `-v`/`-vv` into `pp.configure()` and stores an `AppState` on `ctx.obj`; `--version` prints and exits.
- `main()` wraps `app()` to translate `KeyboardInterrupt` into a clean exit 130 and the `NomadError` subclasses into non-zero exits with a friendly message (no traceback).
- Each subcommand module exports its own `typer.Typer()` instance and uses `@app.callback(invoke_without_command=True)` to allow future sub-subcommands.

### Job files (`src/nd/jobfiles.py`, `src/nd/binary/jobspec.py`)

The `list`, `plan`, and `run` commands work with local Nomad job files discovered from configured directories.

**Config** - `~/.config/nd/config.toml` (same file as `[nomad]`) accepts a `[jobs]` table:

```toml
[jobs]
directories = ["/path/to/nomad-jobs", "~/homelab/jobs"]
```

`load_job_directories()` in `jobfiles.py` reads this list (expanding `~`) and returns an empty list if the section is absent. Job files are discovered by the globs `*.hcl` and `*.nomad` (from `JOB_FILE_GLOBS` in `constants.py`). Each file's job names are parsed by regex matching the top-level `job "<name>" {` block opener; interpolated names (containing `${`) are skipped. Results come back as `JobFile(path, job_names)` dataclass instances, sorted deterministically by path.

**Binary wrappers (`src/nd/binary/`)** - the local `nomad` binary is wrapped because the HTTP API cannot parse HCL2 and does not own the raw-TTY exec protocol. The package has three modules: `env.py` holds the shared layer (`NomadBinaryError`, `ensure_nomad()` which resolves the binary on PATH, and `binary_env(config)` which overlays the resolved `NomadConfig` as `NOMAD_*` env vars so the binary targets the same cluster as the API client); `jobspec.py` does HCL2 compile/validate; `allocio.py` does exec/logs (see below). `from nd.binary import jobspec, allocio, NomadBinaryError, ensure_nomad`. The caller resolves the binary once via `ensure_nomad()` and passes the path into each wrapper, so a multi-file run does not re-walk PATH per file.

- `validate(file, config, *, nomad_bin)` - runs `nomad job validate`; raises `NomadBinaryError` on failure.
- `plan(file, config, *, nomad_bin) -> int` - runs `nomad job plan` with `stream=True` so Nomad's own colored diff appears verbatim in the terminal; returns the binary's exit code (1 = changes present, 0 = no changes).
- `compile_to_json(file, config, *, nomad_bin) -> bytes` - runs `nomad job run -output` to produce the `{"Job": {...}}` JSON payload without submitting anything; this payload is passed directly to `client.jobs.register()`.

All three raise `NomadBinaryError` if the invocation fails.

**Commands:**

- `nd list` - renders a table of all discovered job files alongside their status on the cluster (running, dead, or not deployed). Candidates are all discovered files.
- `nd plan` - surfaces `nomad job plan` output verbatim for one or more job files. Candidates are all discovered files (including already-running jobs, so you can preview in-place updates). Accepts an optional name prefix to narrow targets; with `--dry-run / -n` it reports what would be planned without invoking the binary.
- `nd run` - deploys job files that are not already running. Compiles each file to JSON via the binary, registers it via `client.jobs.register()`, then watches the rollout: service jobs wait for the deployment to succeed (polling `client.deployments.read()`), while batch and system jobs watch allocations via `client.jobs.allocations()`. Progress is shown in a live Rich panel.

### Allocation exec & logs (`src/nd/binary/allocio.py`, `src/nd/targets/alloc_target.py`)

The `exec` and `logs` commands act on a single task. `targets/alloc_target.py` resolves the
target through the API client (`resolve_alloc_task` / `resolve_target`): a job (by
optional name prefix), then its allocation (auto when one, prompt when several),
then a task (auto when one, prompt when several, or a `--task/-t` override). The
`running_only` flag governs which candidates are offered: `nd exec` keeps the
default (`True`, live targets only, since you cannot shell into a dead task), while
`nd logs` passes `running_only=False` so a dead, completed, or failed task's logs
stay reachable. Allocation and task prompts show status so dead ones are
distinguishable. `SelectionError` marks a hard failure (exit 1); a cancelled prompt
or an empty cluster exits 0.

`allocio.py` then hands off to the local `nomad` binary, injecting the resolved
`NomadConfig` as `NOMAD_*` env vars (via `binary_env()` from `binary/env.py`, shared
across the binary wrappers) so the binary targets the same cluster as the client.
The `exec`/`logs` commands share the resolve-target-then-run-binary tail via
`run_alloc_action()` in `commands/_common.py`. `exec_shell()` runs
`nomad alloc exec` with inherited stdio for a full interactive TTY; it takes the
in-container command as a list, so with no `--shell` it runs the `EXEC_SHELL_PROBE`
(`sh -c 'command -v bash && exec bash || exec sh'`) to prefer bash and fall back to
sh, while an explicit `--shell` is run verbatim. It requests a pseudo-tty (`-t`)
only when stdin is a terminal, so piped/CI use does not hang. `stream_logs()` runs
`nomad alloc logs` and takes a `streams` tuple (default `("stdout", "stderr")`):
live `-f` follow of both streams by default (no stream flag, so Nomad interleaves
them natively), `--stdout/-o` or `--stderr/-e` to isolate one stream, `--tail/-n N`
for a static last-N read, and `--export PATH` to snapshot the current logs to a file
(no follow). Because Nomad cannot merge streams without `-f`, the one-shot tail and
export modes read each requested stream in turn (stdout then stderr) and concatenate.

## nclutils

- nclutils is a library for common utilities for the natelandau toolkit. Load the `/natelandau-toolkit:nclutils` skill to understand the library.
- nclutils is maintained by the nd team. If we need to add a new utility or make a change, ask a team member to update the library.

### Console Output

- Output is handled by the external `nclutils` package via its `pp` printer — never call `print()` or instantiate `rich.Console()` directly
- Import the printer: `from nclutils import pp`
    - `pp.step("message")` — context manager: spinner while running, `✓`/`✗` on completion
        - Use `s.sub("text")` inside `with pp.step(...) as s:` to queue sub-items
    - `pp.success(msg, details=[...])` — terminal success line with optional sub-items
    - `pp.info(msg)` — informational line
    - `pp.debug(msg)` — shown with `-v`
    - `pp.trace(msg)` — shown with `-vv`
    - `pp.dryrun(msg)` — always shown, prefixed `[dry-run]`
    - `pp.warning(msg, details=[...])` / `pp.error(msg, details=[...])` — stderr; pass a list for follow-up lines
- For tables/panels/direct Rich usage: `pp.console().print(...)`
- Verbosity set via `-v`/`-vv` flags on root command, wired through `pp.configure(verbosity=...)`

### Adding a New Subcommand

Follow the existing `status`, `stop`, and `clean` commands (`src/nd/commands/`) as references (`clean` shows the command-plus-new-resource flow):

1. Create `src/nd/commands/<name>.py` with its own `typer.Typer()` and `@app.callback(invoke_without_command=True)`
2. In `cli.py`, import and register: `app.add_typer(<name>.app, name="<name>")`
3. Add tests in `tests/unit/commands/test_<name>.py`

A larger command can be a package instead of a module (see `commands/status/`, split into `report.py` pure aggregation, `render.py` Rich rendering, and `command.py` Typer wiring, with the public surface re-exported from `__init__.py`).

**Shared command wiring (`src/nd/commands/_common.py`)** - the `-v/--verbose` option (`VerboseOption`), the verbosity-merge helper (`configure_verbosity`), the `StepLike` protocol and per-call progress recorder (`record_step`), and the exec/logs target-and-binary tail (`run_alloc_action`) are shared here rather than copied per command. Reuse them in new commands.

**Shared UI (`src/nd/ui/`)** - view styling, Rich panels, multi-select prompts, duration formatting, and the live progress panel all live in `src/nd/ui/` (`styles.py`, `panels.py`, `prompts.py`, `duration.py`, `links.py`, `alloc_rows.py`, `live_panel.py`). Reuse these rather than reimplementing them. `live_panel.py` exposes `run_live_panel` (the raw Rich live display) and `run_rows`, the higher-level concurrent orchestrator (build a row per item, run a worker, stamp the finished row, return ordered outcomes) used by both `stop` and `run`.

**Target resolution (`src/nd/targets/`)** - `resolve_targets(items, arg, *, name_of=...)` (in `targets/selection.py`, re-exported from `nd.targets`) handles the name-prefix matching pattern (no arg = offer all for multi-select; one match = auto-select; multiple matches = prompt). Commands that accept an optional name argument should call this rather than writing their own matching logic. `targets/alloc_target.py` builds the single-task exec/logs resolution on top of it.

### Testing

- `tests/unit/` mirrors the source tree and tests package functionality, including the CLI (`tests/unit/test_cli.py`, `tests/unit/commands/`). CLI commands are driven with Typer's `CliRunner`; assert on `exit_code` (verbosity reconfiguration means `pp` output is not reliably captured by the runner). Rendered Rich output is asserted via a recording `Console` + `pp.Emitter` (see `tests/unit/commands/test_status.py`).
- The Nomad API client is tested by mocking HTTP with **respx** through the **`pytest-httpx2`** plugin's `httpx2_mock: respx.Router` fixture. Routes use full urls; multi-response sequences (pagination) use `side_effect=[httpx.Response(...), ...]` with the respx-bundled `httpx`, not `httpx2.Response`. Async code is driven with `asyncio.run(...)` inside sync test functions (no async pytest plugin is configured).
- Tests follow the project test standards: imperative `Verify ...` docstrings, Given/When/Then comments, and `test_<unit>_<scenario>` names.

## Conventions

- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Docstrings: Google format
- Type hints on all function signatures
- Ruff for linting and formatting
