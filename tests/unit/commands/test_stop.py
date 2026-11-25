"""Tests for the stop command helpers."""

from io import StringIO

import msgspec
import respx
from nclutils import pp
from rich.console import Console

from nd.commands import stop as stop_module
from nd.commands.stop import _build_dry_run_panel, stopping_title
from nd.nomad.models.job import JobListStub
from nd.targets import resolve_targets
from nd.ui.duration import fmt_elapsed as _fmt_elapsed
from nd.ui.live_panel import LiveRow, _build_panel
from nd.ui.prompts import clear_prompt_line as _clear_prompt_line

_ADDR = "http://nomad.test:4646"


def _job(name: str, status: str = "running") -> JobListStub:
    return msgspec.convert(
        {
            "ID": name,
            "Name": name,
            "Type": "service",
            "Status": status,
            "Priority": 50,
            "CreateIndex": 1,
            "ModifyIndex": 2,
        },
        type=JobListStub,
    )


def test_resolve_targets_no_arg_prompts_all():
    """Verify a missing job argument yields all running jobs for a prompt."""
    # Given two running jobs
    running = [_job("web"), _job("api")]

    # When resolving with no argument
    result = resolve_targets(running, None, name_of=lambda j: j.name)

    # Then every running job is a candidate and a prompt is required
    assert result.needs_prompt is True
    assert [j.name for j in result.candidates] == ["web", "api"]


def test_resolve_targets_single_substring_match_auto():
    """Verify a substring matching exactly one job needs no prompt."""
    # Given running jobs where only one contains "eb"
    running = [_job("web"), _job("api")]

    # When resolving with that substring
    result = resolve_targets(running, "eb", name_of=lambda j: j.name)

    # Then it is auto-selected without a prompt
    assert result.needs_prompt is False
    assert [j.name for j in result.candidates] == ["web"]


def test_resolve_targets_multi_substring_match_prompts():
    """Verify a substring matching several jobs offers them for a prompt."""
    # Given two jobs sharing an interior fragment
    running = [_job("web-api"), _job("db-api"), _job("ui")]

    # When resolving with the shared fragment (case-insensitive)
    result = resolve_targets(running, "API", name_of=lambda j: j.name)

    # Then both matches are candidates and a prompt is required
    assert result.needs_prompt is True
    assert [j.name for j in result.candidates] == ["web-api", "db-api"]


def test_resolve_targets_no_match_returns_empty():
    """Verify a non-matching substring yields no candidates and no prompt."""
    # Given running jobs
    running = [_job("web")]

    # When resolving with a substring that matches nothing
    result = resolve_targets(running, "zzz", name_of=lambda j: j.name)

    # Then there are no candidates and no prompt
    assert result.needs_prompt is False
    assert result.candidates == []


def _running_job_json(name: str = "web") -> dict:
    return {
        "ID": name,
        "Name": name,
        "Type": "service",
        "Status": "running",
        "Priority": 50,
        "CreateIndex": 1,
        "ModifyIndex": 2,
    }


def test_stop_app_reports_no_running_jobs(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify the command exits cleanly when no jobs are running."""
    # Given an isolated config and a cluster with only a dead job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[{**_running_job_json(), "Status": "dead"}])

    # When invoking the stop command
    result = typer_runner.invoke(stop_module.app, [])

    # Then it exits zero with nothing to stop
    assert result.exit_code == 0


def test_stop_app_errors_on_no_substring_match(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a non-matching job argument exits non-zero."""
    # Given an isolated config and one running job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])

    # When invoking with a substring that matches nothing
    result = typer_runner.invoke(stop_module.app, ["zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


def test_stop_app_no_argument_off_a_terminal_exits_non_zero(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a scripted stop with no job argument fails instead of silently doing nothing."""
    # Given an isolated config, two running jobs, and no terminal to pick between them
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(
        json=[_running_job_json(), {**_running_job_json(), "ID": "api", "Name": "api"}]
    )

    # When invoking with no job argument, which would otherwise open a multi-select
    result = typer_runner.invoke(stop_module.app, [])

    # Then it exits non-zero rather than reporting "nothing selected" as success
    assert result.exit_code == 1
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_stop_app_unconfirmable_off_a_terminal_exits_non_zero(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify a scripted stop without --force fails rather than reporting a clean abort."""
    # Given an isolated config, one running job, and no terminal to confirm on
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])

    # When invoking on an unambiguous job without --force
    result = typer_runner.invoke(stop_module.app, ["web"])

    # Then the unanswerable confirmation is an error, not a silent no-op that exits 0
    assert result.exit_code == 1
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_stop_app_force_stops_single_match(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, mocker, typer_runner
):
    """Verify a single substring match with --force stops without prompting."""
    # Given an isolated config and one running job that drains immediately
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    httpx2_mock.get(f"{_ADDR}/v1/nodes").respond(json=[])
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    mocker.patch("nd.commands._lifecycle.asyncio.sleep", autospec=True)

    # When invoking with --force on the substring
    result = typer_runner.invoke(stop_module.app, ["we", "--force"])

    # Then it stops the job and exits cleanly
    assert result.exit_code == 0


def test_stop_app_detach_issues_stop_without_watching(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify --detach issues the stop but never polls allocations to watch the drain."""
    # Given an isolated config and one running job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --detach (and --force to skip the confirm prompt)
    result = typer_runner.invoke(stop_module.app, ["we", "--force", "--detach"])

    # Then the stop is issued once and no allocations are polled
    assert result.exit_code == 0
    assert stop_route.called
    assert not any(call.request.url.path.endswith("/allocations") for call in httpx2_mock.calls)


def test_stop_app_no_shutdown_delay_passthrough(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify --no-shutdown-delay forwards the bypass flag on the stop call."""
    # Given an isolated config and one running job, stopped with --detach for a short path
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --no-shutdown-delay
    result = typer_runner.invoke(
        stop_module.app, ["we", "--force", "--detach", "--no-shutdown-delay"]
    )

    # Then the deregister carries no_shutdown_delay=true
    assert result.exit_code == 0
    assert stop_route.calls.last.request.url.params["no_shutdown_delay"] == "true"


def test_stop_app_dry_run_skips_delete(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, typer_runner
):
    """Verify --dry-run resolves the target but never issues the stop call."""
    # Given an isolated config, one running job, and a stop endpoint
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])

    # When invoking with --dry-run (and --force to skip the confirm prompt)
    result = typer_runner.invoke(stop_module.app, ["we", "--dry-run", "--force"])

    # Then it exits cleanly and never issues a DELETE (the stop call)
    assert result.exit_code == 0
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def test_stopping_title_includes_purge():
    """Verify stopping_title pluralizes and flags purge."""
    # Given a purge stop of two jobs
    # When building the title
    # Then it pluralizes and notes purge
    assert stopping_title(2, purge=True) == "Stopping 2 jobs (purge)"
    assert stopping_title(1, purge=False) == "Stopping 1 job"


def test_fmt_elapsed_formats_h_mm_ss():
    """Verify _fmt_elapsed renders H:MM:SS."""
    # Given 72 seconds
    # When formatting
    # Then it is 0:01:12
    assert _fmt_elapsed(72) == "0:01:12"


def _panel_text(panel) -> str:
    """Render a panel through a recording console and return its text."""
    console = Console(theme=pp.THEME, record=True, force_terminal=True, width=80)
    console.print(panel)
    return console.export_text()


def test_build_panel_shows_running_and_finished_rows():
    """Verify the panel shows the title, job names, phase, and a finished glyph."""
    from nd.ui.styles import OUTCOME_GLYPH

    # Given one in-flight row and one stopped row
    rows = [
        LiveRow(label="ladder", phase="waiting on: cleanup", started_at=0.0),
        LiveRow(
            label="linkding",
            phase="stopped",
            glyph=OUTCOME_GLYPH["ok"],
            started_at=0.0,
            ended_at=5.0,
        ),
    ]

    # When building the panel
    text = _panel_text(_build_panel(rows, title="Stopping 2 jobs", now=3.0))

    # Then the title, both job names, the in-flight phase, and a check glyph appear
    assert "Stopping 2 jobs" in text
    assert "ladder" in text
    assert "linkding" in text
    assert "waiting on: cleanup" in text
    assert "✓" in text


def test_build_dry_run_panel_names_targets():
    """Verify the dry-run panel titles the action and names each target job."""
    # Given two purge targets
    panel = _build_dry_run_panel([_job("ladder"), _job("linkding")], purge=True)

    # When rendering the panel
    text = _panel_text(panel)

    # Then it reads as a purge dry-run and names both jobs
    assert "Would stop 2 jobs (purge)" in text
    assert "ladder" in text
    assert "linkding" in text
    assert "dry-run" in text


def test_clear_prompt_line_noop_when_not_terminal(mocker):
    """Verify the prompt eraser writes nothing to a non-terminal console."""
    # Given a non-terminal recording console
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False)
    mocker.patch("nd.ui.prompts.pp.console", return_value=console)

    # When clearing the prompt line
    _clear_prompt_line()

    # Then nothing is written
    assert buffer.getvalue() == ""


def test_clear_prompt_line_writes_escape_when_terminal(mocker):
    """Verify the prompt eraser emits cursor-up + erase on a terminal."""
    # Given a terminal recording console
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True)
    mocker.patch("nd.ui.prompts.pp.console", return_value=console)

    # When clearing two prompt lines
    _clear_prompt_line(2)

    # Then it writes the cursor-up and erase-to-end sequence
    assert "\x1b[2A" in buffer.getvalue()
    assert "\x1b[J" in buffer.getvalue()
