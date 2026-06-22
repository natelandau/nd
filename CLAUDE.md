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

- `client.py` — `NomadClient`, the facade. It is an async context manager that owns a single transport and exposes resource namespaces: `client.agent`, `client.nodes`, `client.jobs`, `client.allocations`. Resource methods are coroutines, e.g. `await client.agent.self()`, `await client.nodes.list()`.
- `resources/` — one module per resource (`agent`, `nodes`, `jobs`, `allocations`) over `BaseResource`, which centralizes decoding via `_decode` / `_decode_list` (mapping `msgspec` failures to `NomadDecodeError`). `list()` methods auto-paginate.
- `transport.py` — `AsyncTransport` wraps `httpx2.AsyncClient`, sends the `X-Nomad-Token` header, merges namespace/region params, follows next-token pagination, and maps non-2xx responses to typed errors.
- `models/` — `msgspec.Struct` definitions (`agent`, `node`, `job`, `allocation`). Decoding uses **msgspec, not dataclasses or pydantic**: structs use `rename="pascal"`, `frozen=True`, `kw_only=True`, with explicit `msgspec.field(name=...)` for irregular Nomad keys (`ID`, `NodeID`, `JobID`, `HTTPAddr`, `TLSEnabled`, `TaskStates`); unknown fields are tolerated by default.
- `config.py` — `NomadConfig.resolve()` reads standard Nomad env vars (`NOMAD_ADDR`, `NOMAD_TOKEN`, `NOMAD_NAMESPACE`, `NOMAD_REGION`, `NOMAD_CACERT`, `NOMAD_CLIENT_CERT`, `NOMAD_CLIENT_KEY`, `NOMAD_TLS_SERVER_NAME`) as the base, then overrides them with a `[nomad]` table from `$XDG_CONFIG_HOME/nd/config.toml` (default `~/.config/nd/config.toml`).
- `errors.py` — exception hierarchy rooted at `NomadError` (`NomadConfigError`, `NomadConnectionError`, `NomadDecodeError`, `NomadHTTPError` with `NomadBadRequestError`/`NomadAuthError`/`NomadNotFoundError`/`NomadServerError`).

Public surface is re-exported from `nd.nomad`: `from nd.nomad import NomadClient, NomadConfig, NomadError`.

### CLI Wiring (planned, not yet implemented)

The CLI entry point is `nd:main` (per `pyproject.toml`), but no `main` or `cli.py` exists yet. The intended structure below is aspirational until the CLI layer lands:

- Root `typer.Typer()` in `cli.py` registers subcommands via `app.add_typer()`
- Each subcommand module exports its own `typer.Typer()` instance
- Subcommands use `@app.callback(invoke_without_command=True)` to allow future sub-subcommands

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

### Adding a New Subcommand (planned, once the CLI layer exists)

1. Create `src/nd/commands/<name>.py` with its own `typer.Typer()` and `@app.callback()`
2. In `cli.py`, import and register: `app.add_typer(<name>.app, name="<name>")`
3. Add tests in `tests/`

### Testing

- `tests/unit/` mirrors the source tree and tests package functionality. `tests/integration/` is reserved for CLI tests once the CLI lands (it does not exist yet).
- The Nomad API client is tested by mocking HTTP with **respx** through the **`pytest-httpx2`** plugin's `httpx2_mock: respx.Router` fixture. Routes use full urls; multi-response sequences (pagination) use `side_effect=[httpx.Response(...), ...]` with the respx-bundled `httpx`, not `httpx2.Response`. Async code is driven with `asyncio.run(...)` inside sync test functions (no async pytest plugin is configured).
- Tests follow the project test standards: imperative `Verify ...` docstrings, Given/When/Then comments, and `test_<unit>_<scenario>` names.

## Conventions

- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Docstrings: Google format
- Type hints on all function signatures
- Ruff for linting and formatting
