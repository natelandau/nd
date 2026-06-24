"""Tests for the stop command helpers."""

import asyncio
from io import StringIO

import httpx
import msgspec
import respx
from nclutils import pp
from rich.console import Console
from typer.testing import CliRunner

from nd.commands import stop as stop_module
from nd.commands.stop import (
    _OUTCOME_ROW,
    StopOutcome,
    StopStatus,
    _build_dry_run_panel,
    all_allocs_terminal,
    exit_code_for,
    final_title,
    phase_text,
    running_task_names,
    stop_and_wait,
    stopping_title,
)
from nd.nomad.client import NomadClient
from nd.nomad.config import NomadConfig
from nd.nomad.models.allocation import AllocListStub
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


def _alloc(client_status: str) -> AllocListStub:
    return msgspec.convert(
        {
            "ID": "a",
            "Name": "n",
            "NodeID": "x",
            "JobID": "web",
            "TaskGroup": "web",
            "ClientStatus": client_status,
            "DesiredStatus": "stop",
            "CreateIndex": 1,
            "ModifyIndex": 2,
        },
        type=AllocListStub,
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


def test_resolve_targets_single_prefix_match_auto():
    """Verify a prefix matching exactly one job needs no prompt."""
    # Given running jobs where only one starts with "we"
    running = [_job("web"), _job("api")]

    # When resolving with that prefix
    result = resolve_targets(running, "we", name_of=lambda j: j.name)

    # Then it is auto-selected without a prompt
    assert result.needs_prompt is False
    assert [j.name for j in result.candidates] == ["web"]


def test_resolve_targets_multi_prefix_match_prompts():
    """Verify a prefix matching several jobs offers them for a prompt."""
    # Given two jobs sharing a prefix
    running = [_job("web-api"), _job("web-ui"), _job("db")]

    # When resolving with the shared prefix (case-insensitive)
    result = resolve_targets(running, "WEB", name_of=lambda j: j.name)

    # Then both matches are candidates and a prompt is required
    assert result.needs_prompt is True
    assert [j.name for j in result.candidates] == ["web-api", "web-ui"]


def test_resolve_targets_no_match_returns_empty():
    """Verify a non-matching prefix yields no candidates and no prompt."""
    # Given running jobs
    running = [_job("web")]

    # When resolving with a prefix that matches nothing
    result = resolve_targets(running, "zzz", name_of=lambda j: j.name)

    # Then there are no candidates and no prompt
    assert result.needs_prompt is False
    assert result.candidates == []


def test_all_allocs_terminal_true_when_all_terminal():
    """Verify all_allocs_terminal is True only when every alloc is terminal."""
    # Given a mix of terminal allocations
    allocs = [_alloc("complete"), _alloc("failed"), _alloc("lost")]

    # When checking terminality
    # Then it is terminal
    assert all_allocs_terminal(allocs) is True


def test_all_allocs_terminal_false_when_any_running():
    """Verify all_allocs_terminal is False when any alloc is still running."""
    # Given one running allocation among terminal ones
    allocs = [_alloc("complete"), _alloc("running")]

    # When checking terminality
    # Then it is not terminal
    assert all_allocs_terminal(allocs) is False


def test_all_allocs_terminal_true_for_empty():
    """Verify a job with no allocations counts as terminal."""
    # Given no allocations
    # When checking terminality
    # Then it is terminal
    assert all_allocs_terminal([]) is True


def test_exit_code_for_zero_when_all_stopped():
    """Verify the exit code is 0 when every job stopped cleanly."""
    # Given all-stopped outcomes
    outcomes = [StopOutcome(_job("web"), StopStatus.STOPPED)]

    # When computing the exit code
    # Then it is zero
    assert exit_code_for(outcomes) == 0


def test_exit_code_for_one_when_any_not_stopped():
    """Verify the exit code is 1 when any job timed out or failed."""
    # Given a timeout outcome alongside a stopped one
    outcomes = [
        StopOutcome(_job("web"), StopStatus.STOPPED),
        StopOutcome(_job("api"), StopStatus.TIMEOUT, "still draining"),
    ]

    # When computing the exit code
    # Then it is one
    assert exit_code_for(outcomes) == 1


def _alloc_json(client_status: str) -> dict:
    return {
        "ID": "a",
        "Name": "n",
        "NodeID": "x",
        "JobID": "web",
        "TaskGroup": "web",
        "ClientStatus": client_status,
        "DesiredStatus": "stop",
        "CreateIndex": 1,
        "ModifyIndex": 2,
    }


def test_stop_and_wait_returns_stopped_when_allocs_drain(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports STOPPED once allocations reach a terminal state."""
    # Given a stop call and allocations that drain running -> complete
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[_alloc_json("running")]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    # And a no-op sleep so the poll loop runs instantly
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)

    # When stopping and waiting
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the job is reported stopped
    assert outcome.status is StopStatus.STOPPED


def test_stop_and_wait_skips_transient_alloc_decode_error(httpx2_mock: respx.Router, mocker):
    """Verify a one-off allocation decode error skips the poll instead of failing the stop."""
    # Given a stop call whose first drain poll is undecodable, then drains to complete
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[{"unexpected": "shape"}]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    # And a no-op sleep so the retry runs instantly
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)

    # When stopping and waiting through the transient decode error
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the transient error is skipped and the drain resolves to STOPPED, not FAILED
    assert outcome.status is StopStatus.STOPPED


def test_stop_and_wait_times_out_when_never_terminal(httpx2_mock: respx.Router, mocker):
    """Verify stop_and_wait reports TIMEOUT when allocations never drain."""
    # Given a stop call and allocations that stay running
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("running")])
    # And a tiny timeout budget plus a no-op sleep so the loop ends quickly
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)
    mocker.patch("nd.commands.stop.STOP_TIMEOUT_SECONDS", 0.03)
    mocker.patch("nd.commands.stop.POLL_INTERVAL_SECONDS", 0.01)

    # When stopping and waiting
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the job is reported as timed out
    assert outcome.status is StopStatus.TIMEOUT
    assert "draining" in outcome.detail


def test_stop_and_wait_reports_phase_and_drain_detail(httpx2_mock: respx.Router, mocker):
    """Verify the poll loop reports the running task in the phase and as a detail row."""
    # Given a stop call and an allocation with a running cleanup task, then terminal
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    alloc_running = {
        **_alloc_json("running"),
        "TaskStates": {"cleanup": {"State": "running", "Failed": False, "Restarts": 0}},
    }
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[alloc_running]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)
    phases: list[str] = []
    detail_labels: list[str] = []

    def _update(phase: str, children=()) -> None:
        phases.append(phase)
        detail_labels.extend(c.cells[0] for c in children)

    # When stopping and waiting, capturing the phase texts and detail rows
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=_update
            )

    outcome = asyncio.run(run())

    # Then it stops, the phase names the running task, and a detail row names it too
    assert outcome.status is StopStatus.STOPPED
    assert "running: cleanup" in phases
    assert any("cleanup" in label for label in detail_labels)


def test_stop_and_wait_purges_after_drain(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop watches the drain first, then garbage-collects the dead job."""
    # Given a job that drains running -> complete and a deregister endpoint
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").mock(
        side_effect=[
            httpx.Response(200, json=[_alloc_json("running")]),
            httpx.Response(200, json=[_alloc_json("complete")]),
        ]
    )
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the job stops, and the deregister was issued first plain then with purge=true
    assert outcome.status is StopStatus.STOPPED
    assert [c.request.url.params["purge"] for c in stop_route.calls] == ["false", "true"]


def test_stop_and_wait_does_not_purge_on_timeout(httpx2_mock: respx.Router, mocker):
    """Verify a purge stop that never drains times out without purging the job."""
    # Given a job whose allocations stay running past a tiny timeout budget
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("running")])
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)
    mocker.patch("nd.commands.stop.STOP_TIMEOUT_SECONDS", 0.03)
    mocker.patch("nd.commands.stop.POLL_INTERVAL_SECONDS", 0.01)

    # When stopping with purge=True
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then it times out and the job was never purged (only the plain stop was issued)
    assert outcome.status is StopStatus.TIMEOUT
    assert "true" not in [c.request.url.params["purge"] for c in stop_route.calls]


def test_stop_and_wait_reports_failed_when_purge_fails(httpx2_mock: respx.Router, mocker):
    """Verify a clean stop whose follow-up purge errors is reported as FAILED."""
    # Given a job that drains immediately, with the follow-up purge call erroring
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").mock(
        side_effect=[
            httpx.Response(200, json={"EvalID": "e1"}),
            httpx.Response(500, text="boom"),
        ]
    )
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[_alloc_json("complete")])
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)

    # When stopping with purge=True
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=True, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the outcome flags the purge failure distinctly from a hard stop failure
    assert outcome.status is StopStatus.PURGE_FAILED
    assert "purge failed" in outcome.detail


def test_stop_and_wait_reports_failed_on_nomad_error(httpx2_mock: respx.Router):
    """Verify stop_and_wait reports FAILED when the stop call errors."""
    # Given a stop endpoint that returns a server error
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(status_code=500, text="boom")

    # When stopping and waiting
    async def run() -> object:
        async with NomadClient.from_config(NomadConfig(address=_ADDR)) as client:
            return await stop_and_wait(
                client, _job("web"), purge=False, node_names={}, update=lambda *_a: None
            )

    outcome = asyncio.run(run())

    # Then the failure is captured, not raised
    assert outcome.status is StopStatus.FAILED
    assert "500" in outcome.detail


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


def test_stop_app_reports_no_running_jobs(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify the command exits cleanly when no jobs are running."""
    # Given an isolated config and a cluster with only a dead job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[{**_running_job_json(), "Status": "dead"}])

    # When invoking the stop command
    result = CliRunner().invoke(stop_module.app, [])

    # Then it exits zero with nothing to stop
    assert result.exit_code == 0


def test_stop_app_errors_on_no_prefix_match(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify a non-matching job argument exits non-zero."""
    # Given an isolated config and one running job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])

    # When invoking with a prefix that matches nothing
    result = CliRunner().invoke(stop_module.app, ["zzz"])

    # Then it exits non-zero
    assert result.exit_code == 1


def test_stop_app_force_stops_single_match(
    httpx2_mock: respx.Router, monkeypatch, tmp_path, mocker
):
    """Verify a single prefix match with --force stops without prompting."""
    # Given an isolated config and one running job that drains immediately
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    httpx2_mock.get(f"{_ADDR}/v1/nodes").respond(json=[])
    httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})
    httpx2_mock.get(f"{_ADDR}/v1/job/web/allocations").respond(json=[])
    mocker.patch("nd.commands.stop.asyncio.sleep", autospec=True)

    # When invoking with --force on the prefix
    result = CliRunner().invoke(stop_module.app, ["we", "--force"])

    # Then it stops the job and exits cleanly
    assert result.exit_code == 0


def test_stop_app_detach_issues_stop_without_watching(
    httpx2_mock: respx.Router, monkeypatch, tmp_path
):
    """Verify --detach issues the stop but never polls allocations to watch the drain."""
    # Given an isolated config and one running job
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --detach (and --force to skip the confirm prompt)
    result = CliRunner().invoke(stop_module.app, ["we", "--force", "--detach"])

    # Then the stop is issued once and no allocations are polled
    assert result.exit_code == 0
    assert stop_route.called
    assert not any(call.request.url.path.endswith("/allocations") for call in httpx2_mock.calls)


def test_stop_app_no_shutdown_delay_passthrough(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify --no-shutdown-delay forwards the bypass flag on the stop call."""
    # Given an isolated config and one running job, stopped with --detach for a short path
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])
    stop_route = httpx2_mock.delete(f"{_ADDR}/v1/job/web").respond(json={"EvalID": "e1"})

    # When invoking with --no-shutdown-delay
    result = CliRunner().invoke(
        stop_module.app, ["we", "--force", "--detach", "--no-shutdown-delay"]
    )

    # Then the deregister carries no_shutdown_delay=true
    assert result.exit_code == 0
    assert stop_route.calls.last.request.url.params["no_shutdown_delay"] == "true"


def test_stop_app_dry_run_skips_delete(httpx2_mock: respx.Router, monkeypatch, tmp_path):
    """Verify --dry-run resolves the target but never issues the stop call."""
    # Given an isolated config, one running job, and a stop endpoint
    monkeypatch.setenv("NOMAD_ADDR", _ADDR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    httpx2_mock.get(f"{_ADDR}/v1/jobs").respond(json=[_running_job_json()])

    # When invoking with --dry-run (and --force to skip the confirm prompt)
    result = CliRunner().invoke(stop_module.app, ["we", "--dry-run", "--force"])

    # Then it exits cleanly and never issues a DELETE (the stop call)
    assert result.exit_code == 0
    assert not any(call.request.method == "DELETE" for call in httpx2_mock.calls)


def _alloc_with_tasks(client_status: str, task_states: dict[str, str]) -> AllocListStub:
    return msgspec.convert(
        {
            "ID": "a",
            "Name": "n",
            "NodeID": "x",
            "JobID": "web",
            "TaskGroup": "web",
            "ClientStatus": client_status,
            "DesiredStatus": "stop",
            "CreateIndex": 1,
            "ModifyIndex": 2,
            "TaskStates": {
                name: {"State": state, "Failed": False, "Restarts": 0}
                for name, state in task_states.items()
            },
        },
        type=AllocListStub,
    )


def test_running_task_names_returns_sorted_unique_running():
    """Verify running_task_names lists only running tasks, sorted and de-duplicated."""
    # Given allocations with a mix of running and dead tasks
    allocs = [
        _alloc_with_tasks("running", {"web": "dead", "backup": "running"}),
        _alloc_with_tasks("running", {"cleanup": "running", "backup": "running"}),
    ]

    # When collecting running task names
    # Then only running tasks appear, sorted and unique
    assert running_task_names(allocs) == ["backup", "cleanup"]


def test_running_task_names_empty_when_none_running():
    """Verify running_task_names is empty when no task is running."""
    # Given allocations whose tasks are all dead
    allocs = [_alloc_with_tasks("complete", {"web": "dead"})]

    # When collecting running task names
    # Then the list is empty
    assert running_task_names(allocs) == []


def test_phase_text_names_running_tasks():
    """Verify phase_text surfaces the names of tasks still running."""
    # Given an allocation with a running cleanup task
    allocs = [_alloc_with_tasks("running", {"web": "dead", "cleanup": "running"})]

    # When building phase text
    # Then it names the running task
    assert phase_text(allocs) == "running: cleanup"


def test_phase_text_drains_when_no_task_running():
    """Verify phase_text falls back to a drain count when nothing is running."""
    # Given a non-terminal allocation with no running task
    allocs = [_alloc_with_tasks("pending", {})]

    # When building phase text
    # Then it reports the draining count
    assert phase_text(allocs) == "draining 1 allocs"


def test_phase_text_stopping_when_no_allocs():
    """Verify phase_text reports 'stopping' before any allocations are seen."""
    # Given no allocations
    # When building phase text
    # Then it reports stopping
    assert phase_text([]) == "stopping"


def test_stopping_title_includes_purge():
    """Verify stopping_title pluralizes and flags purge."""
    # Given a purge stop of two jobs
    # When building the title
    # Then it pluralizes and notes purge
    assert stopping_title(2, purge=True) == "Stopping 2 jobs (purge)"
    assert stopping_title(1, purge=False) == "Stopping 1 job"


def test_final_title_all_stopped_and_partial():
    """Verify final_title shows totals, elapsed, and the X-of-N partial form."""
    # Given outcomes where all stopped, then where one timed out
    all_ok = [
        StopOutcome(_job("web"), StopStatus.STOPPED),
        StopOutcome(_job("api"), StopStatus.STOPPED),
    ]
    mixed = [
        StopOutcome(_job("web"), StopStatus.STOPPED),
        StopOutcome(_job("api"), StopStatus.TIMEOUT, "still draining"),
    ]

    # When building final titles with a 12s elapsed
    # Then the all-stopped form and the partial form both render
    assert final_title(all_ok, elapsed_seconds=12.4) == "Stopped 2 jobs · 12s"
    assert final_title(mixed, elapsed_seconds=12.4) == "Stopped 1 of 2 jobs · 12s"


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
        LiveRow(label="ladder", phase="running: cleanup", started_at=0.0),
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

    # Then the title, both job names, the running phase, and a check glyph appear
    assert "Stopping 2 jobs" in text
    assert "ladder" in text
    assert "linkding" in text
    assert "running: cleanup" in text
    assert "✓" in text


def test_outcome_row_maps_status_to_glyph_and_label():
    """Verify _OUTCOME_ROW maps each terminal status to the correct glyph and label."""
    from nd.ui.styles import OUTCOME_GLYPH

    # Given the three terminal statuses
    # When looking up each status in _OUTCOME_ROW
    # Then each maps to the expected (glyph, label) pair
    assert _OUTCOME_ROW[StopStatus.STOPPED] == (OUTCOME_GLYPH["ok"], "stopped")
    assert _OUTCOME_ROW[StopStatus.TIMEOUT] == (OUTCOME_GLYPH["warn"], "still draining")
    assert _OUTCOME_ROW[StopStatus.FAILED] == (OUTCOME_GLYPH["fail"], "failed")
    assert _OUTCOME_ROW[StopStatus.PURGE_FAILED] == (OUTCOME_GLYPH["warn"], "stopped, purge failed")


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
