# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`nd` is a Python CLI tool that wraps common nomad commands for managing a homelab. Built with Typer and Rich.

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

### CLI Wiring

- Root `typer.Typer()` in `cli.py` registers subcommands via `app.add_typer()`
- Each subcommand module exports its own `typer.Typer()` instance
- Subcommands use `@app.callback(invoke_without_command=True)` to allow future sub-subcommands
- Entry point: `nd.cli:main` (configured in `pyproject.toml`)

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

1. Create `src/nd/commands/<name>.py` with its own `typer.Typer()` and `@app.callback()`
2. In `cli.py`, import and register: `app.add_typer(<name>.app, name="<name>")`
3. Add tests in `tests/`

### Testing

- `tests/integration/` used for testing the CLI
- `tests/unit/` used for testing the underlying functionality of the package

## Conventions

- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Docstrings: Google format
- Type hints on all function signatures
- Ruff for linting and formatting
