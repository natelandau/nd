# CLAUDE.md

`nd`: Python CLI wrapping common Nomad operations for a homelab. Typer + Rich, async `httpx2` API client, `msgspec` decoding. `uv run nd --help` lists the commands.

## Commands

```bash
uv sync               # Install dependencies
uv run nd [COMMAND]   # Run the CLI; bare `nd` shows the status dashboard
uv run duty lint      # ruff, ty, typos, prek
uv run duty test      # pytest with coverage
uv run ty check       # Type check src/, tests/, and duties.py
```

`duty test` and `duty prek` run through gate-cache, which skips a check that already passed on the same files.

- Run tests and prek only through `duty`, not bare `pytest` or `prek`. An `already passed on` line is a pass.
- `duty test` with extra pytest arguments bypasses the cache.
- Tests start reading a new tracked file: add it to `TEST_GATE_PATHS` in `duties.py`.
- Before adding or changing a gate: `uv run gate-cache --skill`.

## Nomad

Docs: [API](https://developer.hashicorp.com/nomad/api-docs), [CLI](https://developer.hashicorp.com/nomad/commands), [concepts](https://developer.hashicorp.com/nomad/docs). Check them before relying on memory of Nomad behavior.

### API client (`src/nd/nomad/`)

Async `NomadClient` facade -> per-resource namespaces (`client.jobs`, `client.nodes`, ...) in `resources/` -> `AsyncTransport` (`transport.py`). Import from `nd.nomad`.

- Decode through `BaseResource._decode` / `_decode_list`, which map `msgspec` failures to `NomadDecodeError`. Resource `list()` methods paginate; never paginate by hand.
- Models subclass `NomadModel` (`models/__init__.py`, PascalCase renaming) and repeat `frozen=True, kw_only=True`, which msgspec and type checkers do not inherit. Use `msgspec.field(name=...)` only for irregular keys (`ID`, `NodeID`). Not dataclasses or pydantic.
- New errors subclass `NomadError` (`errors.py`). `main()` turns any `NomadError` into a clean non-zero exit, so let them propagate instead of catching to print and exit.
- `NomadConfig.resolve()` precedence: `cli_overrides` > `NOMAD_*` env vars > `[nomad]` in `$XDG_CONFIG_HOME/nd/config.toml` > defaults. A future connection flag passes its value through `cli_overrides` (`NomadConfigOverrides`; None means unset). An autouse fixture in `tests/conftest.py` clears `NOMAD_*` and points `XDG_CONFIG_HOME` at a temp dir for every test.
- Tunable shared values (timeouts, poll intervals, `JOB_FILE_GLOBS`) go in `src/nd/constants.py`.

### Job and volume files

Discovered from directories in `$XDG_CONFIG_HOME/nd/config.toml`. Both kinds share `*.hcl`/`*.nomad`, so classify by content: `type = "host"` -> volume spec (`parse_volume_spec()`, `python-hcl2`), `job "..." {` block -> job (`is_job_file()`). Skip names that are unresolved `${...}` interpolations.

`src/nd/binary/` wraps the local `nomad` binary because the HTTP API cannot parse HCL2 or run the raw-TTY exec protocol. Build with `NomadBinary.create(config)`, once per command. It provides `validate`, `validate_all` (concurrent), `plan`, `compile_to_json` (HCL -> JSON for `client.jobs.register()`; `compile_job` is its async form), `exec_command`, `stream_logs`. Everything else uses the API client.

## Console output

- All output through `from nclutils import pp`. No `print()` and no `rich.Console()` in `src/`. Exception: a `--json` document goes to stdout through `nd.ui.json_output.print_json`; pass `json_output=` to `configure_verbosity` so `pp` writes to stderr.
- `pp.step(...)` (context manager, `s.sub(...)`), `pp.success/info/debug/trace/dryrun/warning/error`. `debug` shows at `-v`, `trace` at `-vv`. `warning`/`error` go to stderr and take `details=[...]`.
- Tables and panels: `pp.console().print(...)`.
- Layout, so every command reads as one product (see `commands/status/render.py`, `commands/doctor/render.py`):
    - One `titled_panel` per kind of item, holding a `status_table`. Uppercase column headers named for the data (`IMAGE`, `SERVICE`, `FIX`), not generic (`DETAIL`).
    - One line per item at 80 columns, with no wrapping and no `…` truncation. Shorten values (drop a registry host, a repeated job name) before adding a column. Pass `status_table(..., overflow="fold")` so a rare long value wraps instead of truncating.
    - Link the visible text: jobs and nodes with `WebUi.job`/`WebUi.node`, local files with `links.file_link`. No separate "UI" label.
    - Glyphs and status colors from `ui/styles.py`.
- `nclutils` API reference: the `natelandau-nclutils:nclutils` skill. Never patch `nclutils`; ask the user for a change to it.

## Adding a subcommand

1. Create `src/nd/commands/<name>.py` exporting its own `typer.Typer()` with `@app.callback(invoke_without_command=True)`. For a large command, use a package like `commands/status/` (`report.py` data, `render.py` Rich output, `command.py` Typer wiring).
2. Register in `src/nd/cli.py`: `app.add_typer(<name>.app, name="<name>")`.
3. Add tests in `tests/unit/commands/test_<name>.py`.

Match the existing commands: optional `NAME` substring argument and `--dry-run / -n` where they apply. Reuse:

- `commands/_common.py`: `command_app`, `VerboseOption`, `ForceOption`, `dry_run_option`, `configure_verbosity`, `record_step`, `run_alloc_action`, `list_volumes_or_empty` (host volumes; empty when the endpoint fails).
- `commands/_orchestration.py`: `Outcome`/`Severity` for multi-target results, `run_outcome_rows` (live rows, report, exit code), `request_all` (`--detach` fan-out), `confirm_jobs`.
- `commands/_lifecycle.py`: `watch_deploy`, `stop_and_wait`, `poll_until` (deadline poll loop), `task_lifecycle`.
- `ui/`: styles, panels, prompts (`confirm`, `select_one`, `select_many`), durations, `text.plural`, `text.short_id`, `text.untrusted_markup` and `text.strip_terminal_controls` (required for task logs, events, and other workload text), `live_panel.run_rows` (concurrent per-target rows), `links.WebUi` and `links.file_link` (clickable job, node, and file names).
- `targets/`: `select_targets` (substring match, multi-select, exits on no match), `job_file_label`; `alloc_target.py`: `resolve_alloc_task` (one job/alloc/task), `resolve_allocation` (job/alloc only, no task prompt), `resolve_task_in_every_alloc` (one task in every running alloc). Each returns None when there is nothing to act on or the user cancels (exit 0), and raises `SelectionError` or `PromptUnavailableError`, which `main()` turns into exit 1.
- `nodes.py`: `node_names_by_id`, `node_label` (name, or short ID when unknown).

## Testing

- `tests/unit/` mirrors `src/nd/`.
- Invoke CLI commands with the `typer_runner` fixture, not `typer.testing.CliRunner`. Typer colors output when `GITHUB_ACTIONS`/`FORCE_COLOR` is set, and only `typer_runner` strips the ANSI, so raw substring asserts pass locally and fail in CI.
- Assert on `exit_code`; `pp` output is not reliably captured. For an expected exit 1, also assert the exception type (`isinstance(result.exception, SystemExit)` for `typer.Exit`, or `SelectionError`/`PromptUnavailableError`): the runner turns any exception into exit 1, including respx's error for an unmocked request, which `httpx2_mock.calls` does not record. To assert rendered output, call `capture_output()` from `tests/helpers.py` and read the returned console's `export_text()`.
- Autouse fixtures in `tests/conftest.py` give each test a fresh `pp` emitter, fail any real DNS lookup or socket connection, and hide the `nomad` binary, so an unmocked request or `NomadBinary.create` fails instead of reaching a real cluster.
- Fixtures in `tests/conftest.py` (prefer them over patching module internals):
    - `nomad_env`: sets `NOMAD_ADDR` to `NOMAD_TEST_ADDR` for code that calls `NomadConfig.resolve()`.
    - `job_files` / `volume_files`: write real spec files into a directory listed in the test's nd config, so discovery runs for real.
    - `fake_nomad_binary`: makes `NomadBinary.create` return a `MagicMock(spec=NomadBinary)`.
    - `interactive_session`: acts as a terminal; set the returned `PromptAnswers` (`choice=False` declines a confirmation).
- `tests/helpers.py`: `NOMAD_TEST_ADDR`, `run_with_client` (drive client-backed async code), `async_return`, `discard_panel_update`, `capture_output`.
- `tests/builders.py`: model builders with valid defaults (`job_stub`, `alloc_stub`, `node_stub`, ...). Mock a response body with `to_payload(job_stub("web"))`. Add a builder here instead of a file-local one. Keep literal JSON only in tests of decoding.
- Mock Nomad with respx through the `httpx2_mock` fixture (`pytest-httpx2`). Full-URL routes; pagination via `side_effect=[httpx.Response(...), ...]`, using the `httpx` that respx bundles, not `httpx2`.
- No async pytest plugin: drive async code with `asyncio.run(...)` from sync tests.
- pytest-randomly shuffles test order and reseeds `random` each run. A failure that depends on order: rerun with the seed from the header, `uv run duty test -p randomly --randomly-seed=<seed>`.
- Names `test_<unit>_<scenario>`, imperative `Verify ...` docstrings, Given/When/Then comments.
