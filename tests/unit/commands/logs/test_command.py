"""Tests for the nd logs command in single-task mode."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx  # respx-bundled; used to build sequenced mock responses
import pytest

from nd.cli import app
from nd.commands import _common
from nd.commands.logs import stream as stream_mod
from nd.commands.logs import watch as watch_mod
from nd.commands.logs.stream import TaskStreamReader
from nd.commands.logs.watch import WATCH_FAILED_WARNING
from nd.nomad import NomadError
from nd.targets import ResolvedTarget, SelectionError
from tests.builders import alloc_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR, capture_output

if TYPE_CHECKING:
    from pathlib import Path

    import respx

    from nd.nomad.models.allocation import AllocListStub

TARGET = ResolvedTarget(
    job_name="web", alloc_id="alloc-1", task="server", job_id="web", namespace="default"
)
LOGS_URL = f"{NOMAD_TEST_ADDR}/v1/client/fs/logs/alloc-1"
ALLOCATIONS_URL = f"{NOMAD_TEST_ADDR}/v1/job/web/allocations"


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: ResolvedTarget | None,
    error: SelectionError | None = None,
) -> dict[str, object]:
    """Patch the target resolver so tests exercise the command, not the picker.

    A given ``error`` is raised instead of returning ``target``, as a failed resolution does.

    Returns:
        dict[str, object]: The arguments of the resolver call, filled in when the command runs.
    """
    calls: dict[str, object] = {}

    async def _fake_resolve(
        config, *, job_arg, task_arg, running_only=True
    ) -> ResolvedTarget | None:
        calls.update(job_arg=job_arg, task_arg=task_arg, running_only=running_only)
        if error is not None:
            raise error
        return target

    monkeypatch.setattr(_common, "resolve_target", _fake_resolve)
    return calls


def _mock_log(httpx2_mock: respx.Router, stream: str, body: bytes) -> respx.Route:
    """Answer every read of one stream's log with `body`."""
    return httpx2_mock.get(LOGS_URL, params__contains={"type": stream}).respond(content=body)


def _mock_allocations(httpx2_mock: respx.Router, allocs: list[AllocListStub]) -> None:
    httpx2_mock.get(ALLOCATIONS_URL).respond(
        json=[to_payload(a) for a in allocs], headers={"X-Nomad-Index": "5"}
    )


def _requested_streams(httpx2_mock: respx.Router) -> set[str]:
    return {call.request.url.params["type"] for call in httpx2_mock.calls}


@pytest.mark.parametrize(
    ("argv", "expected_streams"),
    [
        pytest.param([], {"stdout", "stderr"}, id="default-both-streams"),
        pytest.param(["--stderr"], {"stderr"}, id="stderr-only"),
        pytest.param(["--stdout"], {"stdout"}, id="stdout-only"),
    ],
)
def test_logs_reads_selected_streams(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router, argv, expected_streams
):
    """Verify only the selected streams are read, defaulting to both."""
    # Given a resolved target and logs for the selected streams
    _patch_resolver(monkeypatch, target=TARGET)
    for stream in expected_streams:
        _mock_log(httpx2_mock, stream, b"line\n")

    # When tailing with the parametrized stream selection
    result = typer_runner.invoke(app, ["logs", "web", "--tail", "5", *argv])

    # Then exactly the selected streams were requested
    assert result.exit_code == 0
    assert _requested_streams(httpx2_mock) == expected_streams


def test_logs_tail_prints_last_lines(monkeypatch, typer_runner, nomad_env, httpx2_mock):
    """Verify --tail prints only the last N lines of the stream."""
    # Given a stdout log of ten lines
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"".join(f"line {n}\n".encode() for n in range(1, 11)))
    console = capture_output()

    # When tailing three lines of stdout
    result = typer_runner.invoke(app, ["logs", "web", "--stdout", "--tail", "3"])

    # Then only lines 8 to 10 print, with no prefix
    assert result.exit_code == 0
    assert [line.strip() for line in console.export_text().splitlines()] == [
        "line 8",
        "line 9",
        "line 10",
    ]


def test_logs_tail_applies_filters(monkeypatch, typer_runner, nomad_env, httpx2_mock):
    """Verify --include and --exclude narrow the tailed lines."""
    # Given a log with three lines
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"keep one\nkeep two\ndrop\n")
    console = capture_output()

    # When tailing with an include and an exclude pattern
    result = typer_runner.invoke(
        app,
        ["logs", "web", "--stdout", "--tail", "5", "--include", "keep", "--exclude", "two"],
    )

    # Then only the line matching include and not exclude prints
    assert result.exit_code == 0
    assert [line.strip() for line in console.export_text().splitlines()] == ["keep one"]


def test_logs_export_writes_both_streams(
    monkeypatch, typer_runner, nomad_env, httpx2_mock, tmp_path: Path
):
    """Verify --export writes stdout then stderr as plain text."""
    # Given both logs
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"out\n")
    _mock_log(httpx2_mock, "stderr", b"err\n")
    destination = tmp_path / "web.log"

    # When exporting
    result = typer_runner.invoke(app, ["logs", "web", "--export", str(destination)])

    # Then the file holds stdout followed by stderr
    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8") == "out\nerr\n"


@pytest.mark.parametrize(
    "allocs",
    [
        pytest.param([alloc_stub("alloc-1", client_status="complete")], id="terminal-alloc"),
        pytest.param(
            [alloc_stub("alloc-1", task_states={"server": task_state("dead")})], id="dead-task"
        ),
        pytest.param([], id="alloc-gone"),
    ],
)
def test_logs_follow_ends_when_task_is_not_live(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router, allocs
):
    """Verify a follow ends, with exit 0, once its stream closes and the task is no longer live."""
    # Given follow streams that close and a task that is not live
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"out\n")
    _mock_log(httpx2_mock, "stderr", b"err\n")
    _mock_allocations(httpx2_mock, allocs)
    console = capture_output()

    # When following the logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the command exits 0 after printing both lines
    assert result.exit_code == 0
    # Stdout lines carry a blank gutter and stderr lines the stderr marker
    printed = {line.strip() for line in console.export_text().splitlines()}
    assert {"out", "! err"} <= printed


def test_logs_invalid_regex_is_usage_error(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a pattern that does not compile is a usage error and reads no log."""
    # Given a resolved target
    _patch_resolver(monkeypatch, target=TARGET)

    # When passing an invalid include pattern
    result = typer_runner.invoke(app, ["logs", "web", "--include", "("])

    # Then the command exits 2 and made no request
    assert result.exit_code == 2
    assert not httpx2_mock.calls


def test_logs_unresolvable_target_exits_one(monkeypatch, typer_runner):
    """Verify a selection failure ends the command with exit 1."""
    # Given a resolver that reports a selection failure
    _patch_resolver(
        monkeypatch, target=None, error=SelectionError("No running job matching 'nope'")
    )

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "nope"])

    # Then the command exits 1 with the selection error
    assert result.exit_code == 1
    assert isinstance(result.exception, SelectionError)


def test_logs_resolves_including_dead_targets(monkeypatch, typer_runner, nomad_env, httpx2_mock):
    """Verify logs resolves with running_only=False so dead tasks stay reachable."""
    # Given a resolver that records the running_only flag it is asked for
    calls = _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"")

    # When invoking logs
    result = typer_runner.invoke(app, ["logs", "web", "--stdout", "--tail", "1"])

    # Then the resolver is asked to include non-running (dead) targets
    assert result.exit_code == 0
    assert calls["running_only"] is False


def test_logs_export_with_tail_writes_last_lines(
    monkeypatch, typer_runner, nomad_env, httpx2_mock, tmp_path: Path
):
    """Verify --export with --tail writes the last N lines of each stream, endings intact."""
    # Given a stdout log with CRLF endings and a stderr log with no final newline
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"o1\r\no2\r\no3\r\n")
    _mock_log(httpx2_mock, "stderr", b"e1\ne2\ne3")
    destination = tmp_path / "web.log"

    # When exporting the last two lines
    result = typer_runner.invoke(app, ["logs", "web", "--tail", "2", "--export", str(destination)])

    # Then the file holds the last two lines of stdout, then of stderr, as the logs end them
    assert result.exit_code == 0
    assert destination.read_bytes() == b"o2\r\no3\r\ne2\ne3"


def test_logs_export_applies_include_and_exclude(
    monkeypatch, typer_runner, nomad_env, httpx2_mock, tmp_path: Path
):
    """Verify --export keeps the lines that pass --include and --exclude, unmarked."""
    # Given a stdout log of three lines
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_log(httpx2_mock, "stdout", b"keep one\nkeep two\ndrop\n")
    destination = tmp_path / "web.log"

    # When exporting with an include and an exclude pattern
    result = typer_runner.invoke(
        app,
        [
            *("logs", "web", "--stdout", "--export", str(destination)),
            *("--include", "keep", "--exclude", "two"),
        ],
    )

    # Then only the matching line is written
    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8") == "keep one\n"


@pytest.mark.parametrize("extra", [["--tail", "3"], ["--export", "OUT"]])
def test_logs_error_from_logs_endpoint_exits_one(
    monkeypatch, typer_runner, nomad_env, httpx2_mock, tmp_path: Path, extra
):
    """Verify a failed log read in tail or export ends with the Nomad error and exit 1."""
    # Given a logs endpoint that fails
    _patch_resolver(monkeypatch, target=TARGET)
    httpx2_mock.get(LOGS_URL).respond(status_code=500)
    argv = [str(tmp_path / "out.log") if arg == "OUT" else arg for arg in extra]

    # When reading one stream
    result = typer_runner.invoke(app, ["logs", "web", "--stdout", *argv])

    # Then the command exits 1 with a NomadError
    assert result.exit_code == 1
    assert isinstance(result.exception, NomadError)


def test_logs_follow_starts_from_the_beginning(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a follow prints the whole existing log, not only its last lines."""
    # Given a 30-line log and a task that has stopped
    _patch_resolver(monkeypatch, target=TARGET)
    body = "".join(f"line {n}\n" for n in range(1, 31)).encode()
    _mock_log(httpx2_mock, "stdout", body)
    _mock_log(httpx2_mock, "stderr", b"")
    _mock_allocations(httpx2_mock, [alloc_stub("alloc-1", client_status="complete")])
    console = capture_output()

    # When following the logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then line 1 prints, which a 20-line backlog would skip
    assert result.exit_code == 0
    assert "line 1" in {line.strip() for line in console.export_text().splitlines()}


async def _endless_run(reader: TaskStreamReader) -> None:
    """Stand in for a stream reader whose stream Nomad never closes."""
    reader.backlog_done.set()
    await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("target", "watched_url", "namespace"),
    [
        pytest.param(TARGET, ALLOCATIONS_URL, "default", id="job-named-by-its-id"),
        pytest.param(
            replace(TARGET, namespace="team-a"), ALLOCATIONS_URL, "team-a", id="job-namespace"
        ),
        pytest.param(
            replace(TARGET, job_id="web-prod"),
            f"{NOMAD_TEST_ADDR}/v1/job/web-prod/allocations",
            "default",
            id="job-id-differs-from-name",
        ),
    ],
)
def test_logs_follow_stops_open_streams_when_task_ends(
    monkeypatch,
    typer_runner,
    nomad_env,
    httpx2_mock: respx.Router,
    target: ResolvedTarget,
    watched_url: str,
    namespace: str,
):
    """Verify a follow watches the target's job and exits 0 once its task ends.

    Nomad keeps the streams open after the task ends, so only the watch can end the view.
    """
    # Given readers that never return and a target allocation that is complete
    _patch_resolver(monkeypatch, target=target)
    route = httpx2_mock.get(watched_url).respond(
        json=[to_payload(alloc_stub("alloc-1", client_status="complete"))],
        headers={"X-Nomad-Index": "5"},
    )
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(TaskStreamReader, "run", _endless_run)

    # When following the logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the job was watched by its ID in its own namespace, and the command ended on its own
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["namespace"] == namespace


def test_logs_follow_retries_a_failed_watch(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a failed allocations query is retried and does not end the follow."""
    # Given an allocations query that fails once, then shows the task ended
    _patch_resolver(monkeypatch, target=TARGET)
    route = httpx2_mock.get(ALLOCATIONS_URL).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(
                200,
                json=[to_payload(alloc_stub("alloc-1", client_status="complete"))],
                headers={"X-Nomad-Index": "5"},
            ),
        ]
    )
    monkeypatch.setattr(stream_mod, "LOGS_RECONNECT_DELAYS_SECONDS", (0.0,))
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(TaskStreamReader, "run", _endless_run)

    # When following the logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then the watch asked again and the follow ended normally once the task ended
    assert result.exit_code == 0
    assert route.call_count == 2


def test_logs_follow_prints_a_log_slower_than_the_grace(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a task that already ended still prints its whole log when its stream is slow."""
    # Given a complete task whose log stream opens later than the grace period
    _patch_resolver(monkeypatch, target=TARGET)
    _mock_allocations(httpx2_mock, [alloc_stub("alloc-1", client_status="complete")])
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.0)

    async def slow_log(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, content=b"first\nlast\n")

    httpx2_mock.get(LOGS_URL).mock(side_effect=slow_log)
    console = capture_output()

    # When following stdout
    result = typer_runner.invoke(app, ["logs", "web", "--stdout"])

    # Then every line of the log printed before the follow ended
    assert result.exit_code == 0
    assert [line.strip() for line in console.export_text().splitlines()] == ["first", "last"]


def test_logs_follow_warns_once_per_lasting_watch_failure(
    monkeypatch, typer_runner, nomad_env, httpx2_mock: respx.Router
):
    """Verify a watch that keeps failing warns once per failure streak, not on every retry."""
    # Given two failure streaks that each reach the longest backoff, split by a success
    _patch_resolver(monkeypatch, target=TARGET)
    failure = httpx.Response(403, text="denied")
    index = {"X-Nomad-Index": "5"}
    running = httpx.Response(200, json=[to_payload(alloc_stub("alloc-1"))], headers=index)
    complete = httpx.Response(
        200, json=[to_payload(alloc_stub("alloc-1", client_status="complete"))], headers=index
    )
    httpx2_mock.get(ALLOCATIONS_URL).mock(
        side_effect=[failure, failure, failure, running, failure, failure, failure, complete]
    )
    monkeypatch.setattr(stream_mod, "LOGS_RECONNECT_DELAYS_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(watch_mod, "LOGS_RECONNECT_DELAYS_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(watch_mod, "LOGS_FINAL_OUTPUT_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(TaskStreamReader, "run", _endless_run)
    console = capture_output(width=200)

    # When following the logs
    result = typer_runner.invoke(app, ["logs", "web"])

    # Then each streak warned once, and the follow still ended when the task did
    assert result.exit_code == 0
    assert console.export_text().count(WATCH_FAILED_WARNING.format(job="web")) == 2
