# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Overview

`nd` is a Python CLI that wraps common Nomad commands for managing a homelab. Built with Typer + Rich, an async `httpx2` API client, and `msgspec` for decoding Nomad API responses.

## Commands

```bash
uv run nd [COMMAND]      # Run the CLI (bare `nd` shows the status dashboard)
uv sync                  # Install dependencies
uv run duty lint         # Run all linters (ruff, ty, typos, prek)
uv run duty test         # Run tests with coverage
uv run ty check src/     # Type check with ty (the project typechecker)
```

## Hashicorp Nomad

Built on top of the Nomad API and CLI. Research the docs before reasoning from general knowledge:

- API: https://developer.hashicorp.com/nomad/api-docs
- CLI: https://developer.hashicorp.com/nomad/commands
- Docs: https://developer.hashicorp.com/nomad/docs

### Nomad API client (`src/nd/nomad/`)

Typed, **async** client. Layers, top to bottom:

- `client.py` — `NomadClient`, an async-context-manager facade owning one transport, exposing resource namespaces (`client.jobs`, `client.nodes`, `client.volumes`, etc.). All resource methods are coroutines.
- `resources/` — one module per resource over `BaseResource`, which centralizes decoding (`_decode` / `_decode_list`, mapping `msgspec` failures to `NomadDecodeError`). `list()` methods auto-paginate.
- `transport.py` — `AsyncTransport` wraps `httpx2.AsyncClient`, sends `X-Nomad-Token`, merges namespace/region params, follows pagination, maps non-2xx to typed errors.
- `models/` — decoding uses **msgspec, not dataclasses or pydantic**. Structs use `rename="pascal"`, `frozen=True`, `kw_only=True`, with explicit `msgspec.field(name=...)` for irregular keys (`ID`, `NodeID`, etc.); unknown fields are tolerated.
- `config.py` — `NomadConfig.resolve()` reads standard `NOMAD_*` env vars, then overrides them with a `[nomad]` table from `~/.config/nd/config.toml`. Exports `default_config_path()`, reused by the jobfile/volumefile modules.
- `errors.py` — hierarchy rooted at `NomadError` (`NomadConfigError`, `NomadConnectionError`, `NomadDecodeError`, `NomadHTTPError` and its subclasses).

Public surface: `from nd.nomad import NomadClient, NomadConfig, NomadError`.

`src/nd/constants.py` holds tunable constants shared across the package (connection defaults, drain/deploy timeouts, poll intervals, `JOB_FILE_GLOBS`).

### CLI wiring (`src/nd/cli.py`)

Entry point is `nd:main`. A root `typer.Typer()` registers each subcommand via `app.add_typer()`. Each subcommand module exports its own `typer.Typer()` and uses `@app.callback(invoke_without_command=True)`. The root callback wires `-v`/`-vv` into `pp.configure()`, stores `AppState` on `ctx.obj`, and defaults to `status` when no subcommand is given. `main()` translates `KeyboardInterrupt` → exit 130 and `NomadError` subclasses → friendly non-zero exits (no traceback).

### Job & volume files (`src/nd/jobfiles.py`, `src/nd/volumefiles.py`, `src/nd/binary/`)

Local Nomad files are discovered from directories configured in `$XDG_CONFIG_HOME/nd/config.toml`

Both kinds share the `*.hcl`/`*.nomad` globs, so a directory may hold both. **Classification is content-based**: a file is a volume spec when its HCL contains `type = "host"`, a job when it contains a `job "..." {` block (`is_job_file()` / `parse_volume_spec()`). Volume specs are parsed with `python-hcl2`. Names that are unresolved interpolations (`${...}`) are skipped.

**Binary wrappers (`src/nd/binary/`)** — the local `nomad` binary is wrapped because the HTTP API cannot parse HCL2 and does not own the raw-TTY exec protocol. Build once per command with `NomadBinary.create(config)` (resolves the binary on PATH, raising `NomadBinaryError` if absent; builds the `NOMAD_*` env so it targets the same cluster as the API client). It exposes `validate`, `plan`, and `compile_to_json` (HCL → `{"Job": {...}}` JSON for `client.jobs.register()`) for job specs, and `exec_shell` / `stream_logs` for running tasks.

**Commands** (most accept an optional `NAME` prefix and `--dry-run / -n`):

- `nd list` — table of discovered job files with cluster status.
- `nd plan` — `nomad job plan` diff, verbatim.
- `nd run` — compile + register, then watch the rollout (`--detach / -d` skips the watch).
- `nd stop` — stop/purge running jobs and watch the drain (`--detach`, `--no-shutdown-delay / -S`).
- `nd volume register|delete|list` — manage dynamic host volumes from local specs.
- `nd status` — cluster dashboard (jobs, nodes, volumes, deployments, evals), all fetched concurrently.

## Console output (`nclutils`)

nclutils is the natelandau-toolkit utility library; load the `/natelandau-toolkit:nclutils` skill to understand it. It is maintained by the nd team — ask a team member to add or change utilities.

- **Never** call `print()` or instantiate `rich.Console()` directly. Output goes through the `pp` printer: `from nclutils import pp`.
- `pp.step(...)` (context manager with `s.sub(...)`), `pp.success/info/debug/trace/dryrun/warning/error`. `debug` shows with `-v`, `trace` with `-vv`. `warning`/`error` go to stderr and take `details=[...]`.
- Tables/panels/direct Rich: `pp.console().print(...)`.

## Adding a subcommand

1. Create `src/nd/commands/<name>.py` with its own `typer.Typer()` and `@app.callback(invoke_without_command=True)`. A larger command can be a package (see `commands/status/`: `report.py` aggregation, `render.py` Rich rendering, `command.py` Typer wiring).
2. Register in `cli.py`: `app.add_typer(<name>.app, name="<name>")`.
3. Add tests in `tests/unit/commands/test_<name>.py`.

Reuse the shared helpers rather than reimplementing:

- `commands/_common.py` — `VerboseOption`, `configure_verbosity`, `record_step`, `run_alloc_action` (exec/logs tail).
- `ui/` — styles, panels, prompts, duration formatting, `live_panel.run_rows` (concurrent row orchestrator used by `stop`/`run`).
- `targets/` — `resolve_targets(...)` for name-prefix matching/multi-select; `alloc_target.py` for single-task exec/logs resolution.

## Testing

- `tests/unit/` mirrors the source tree. CLI commands use Typer's `CliRunner` — assert on `exit_code` (verbosity reconfiguration means `pp` output is not reliably captured); assert rendered Rich output via a recording `Console` + `pp.Emitter` (see `tests/unit/commands/test_status.py`).
- Mock the Nomad API with **respx** via the **`pytest-httpx2`** plugin's `httpx2_mock` fixture. Routes use full URLs; pagination uses `side_effect=[httpx.Response(...), ...]` with respx-bundled `httpx`. Drive async code with `asyncio.run(...)` in sync tests (no async pytest plugin).
- Tests use imperative `Verify ...` docstrings, Given/When/Then comments, and `test_<unit>_<scenario>` names.

## Conventions

- `snake_case` functions, `UPPER_SNAKE_CASE` constants, Google-format docstrings, type hints on all signatures.
- Ruff for lint/format; `ty` is the sole typechecker.
