"""Tests for the nd signal command."""

import json
import re

import pytest
import respx
import typer

from nd.cli import app
from nd.commands import signal as signal_mod
from nd.commands.signal import _normalize_signal
from nd.targets import ResolvedTarget, SelectionError
from tests.builders import alloc_stub, job_stub, task_state, to_payload
from tests.helpers import NOMAD_TEST_ADDR, capture_output


def _patch_resolver(
    monkeypatch, *, target: ResolvedTarget | None, error: SelectionError | None = None
) -> dict[str, object]:
    """Patch resolve_alloc_task so tests exercise the command, not the picker.

    A given ``error`` is raised instead of returning ``target``, as a failed resolution
    does. Returns the dict the fake populates with each call's arguments so a test can
    assert on it without reading shared module state.
    """
    calls: dict[str, object] = {}

    async def _fake_resolve(
        client, *, job_arg, task_arg, alloc_arg=None, alloc_remedy="", running_only=True
    ) -> ResolvedTarget | None:
        calls.update(
            job_arg=job_arg, task_arg=task_arg, alloc_arg=alloc_arg, running_only=running_only
        )
        if error is not None:
            raise error
        return target

    monkeypatch.setattr(signal_mod, "resolve_alloc_task", _fake_resolve)
    return calls


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("SIGUSR1", "SIGUSR1"),
        ("sigusr1", "SIGUSR1"),
        ("USR1", "SIGUSR1"),
        ("usr1", "SIGUSR1"),
        (" sigterm ", "SIGTERM"),
        ("hup", "SIGHUP"),
        # Nomad accepts these; the local libc has no member for either
        ("signull", "SIGNULL"),
        ("iot", "SIGIOT"),
    ],
)
def test_normalize_signal_accepted_forms(given, expected):
    """Verify signal names normalize to their canonical SIG-prefixed uppercase form."""
    # Given a user-typed signal name in any case, with or without the SIG prefix
    # When normalizing it
    result = _normalize_signal(given)

    # Then it becomes the canonical name Nomad expects
    assert result == expected


@pytest.mark.parametrize("given", ["sigwat", "nope", "", "SIG", "SIGCHLD", "sigurg"])
def test_normalize_signal_rejects_unknown_names(given):
    """Verify a name Nomad will not deliver is a usage error rather than a request to it."""
    # Given a signal name Nomad's drivers do not accept
    # When normalizing it, Then it is rejected as a bad parameter
    with pytest.raises(typer.BadParameter):
        _normalize_signal(given)


@pytest.mark.usefixtures("nomad_env")
def test_signal_sends_the_signal_to_the_resolved_task(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify the resolved allocation and task receive the requested signal."""
    # Given a resolved target and a mocked signal endpoint
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/signal").respond(
        json={}
    )

    # When signaling the job by name
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])

    # Then it exits zero and posts the signal for that exact task
    assert result.exit_code == 0
    assert json.loads(route.calls.last.request.content) == {"Signal": "SIGUSR1", "Task": "ezbak"}


@pytest.mark.usefixtures("nomad_env")
def test_signal_normalizes_the_signal_before_sending(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify a lowercase unprefixed signal reaches Nomad in canonical form."""
    # Given a resolved target and a mocked signal endpoint
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    route = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/signal").respond(
        json={}
    )

    # When passing the signal as "usr1"
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "usr1"])

    # Then Nomad is sent SIGUSR1
    assert result.exit_code == 0
    assert json.loads(route.calls.last.request.content)["Signal"] == "SIGUSR1"


@pytest.mark.usefixtures("nomad_env")
def test_signal_resolves_only_running_targets(httpx2_mock: respx.Router, monkeypatch, typer_runner):
    """Verify the picker is restricted to running jobs, allocations, and tasks."""
    # Given a resolved target and a mocked signal endpoint
    calls = _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})

    # When signaling with an explicit task and allocation
    result = typer_runner.invoke(
        app, ["signal", "backup", "-s", "SIGUSR1", "-t", "ezbak", "--alloc", "alloc-1"]
    )

    # Then the resolver was asked for live targets only, and got every argument
    assert result.exit_code == 0
    assert calls == {
        "job_arg": "backup",
        "task_arg": "ezbak",
        "alloc_arg": "alloc-1",
        "running_only": True,
    }


@pytest.mark.usefixtures("nomad_env")
def test_signal_requires_the_signal_option(typer_runner):
    """Verify omitting -s is a usage error rather than a defaulted signal."""
    # Given a configured cluster address

    # When invoking with no signal
    result = typer_runner.invoke(app, ["signal", "backup"])

    # Then it is a usage error
    assert result.exit_code == 2


@pytest.mark.usefixtures("nomad_env")
def test_signal_rejects_an_unknown_signal_before_any_request(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify a misspelled signal fails locally without contacting Nomad."""
    # Given a resolved target
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))

    # When passing a signal that does not exist
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGWAT"])

    # Then it is a usage error and nothing was sent
    assert result.exit_code == 2
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
def test_signal_dry_run_resolves_but_sends_nothing(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify --dry-run resolves the target, then reports it without signaling it."""
    # Given a resolved target
    calls = _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))

    # When running with --dry-run
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1", "--dry-run"])

    # Then it exits zero, having resolved the target but sent nothing
    assert result.exit_code == 0
    assert calls == {"job_arg": "backup", "task_arg": None, "alloc_arg": None, "running_only": True}
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
def test_signal_unresolvable_target_exits_one(httpx2_mock: respx.Router, monkeypatch, typer_runner):
    """Verify a selection failure ends the command with exit 1 without signaling."""
    # Given a resolver reporting a selection failure
    _patch_resolver(monkeypatch, target=None, error=SelectionError("No running job matching 'x'"))

    # When signaling that name
    result = typer_runner.invoke(app, ["signal", "x", "-s", "SIGUSR1"])

    # Then it exits 1 and nothing was sent
    assert result.exit_code == 1
    assert isinstance(result.exception, SelectionError)
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
def test_signal_named_job_not_running_exits_one(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify naming a job that is not running fails loudly rather than exiting zero."""
    # Given a cluster whose only job, matching the name, is dead
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(
        json=[to_payload(job_stub("ezbak", status="dead", job_type="batch"))]
    )

    # When signaling it unattended
    result = typer_runner.invoke(app, ["signal", "ezbak", "-s", "SIGUSR1"])

    # Then it exits 1 and never posts a signal
    assert result.exit_code == 1
    assert isinstance(result.exception, SelectionError)
    assert not [c for c in httpx2_mock.calls if c.request.method == "POST"]


@pytest.mark.usefixtures("nomad_env")
def test_signal_cancelled_selection_exits_zero(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify cancelling the picker exits zero without signaling."""
    # Given a resolver reporting nothing selected
    _patch_resolver(monkeypatch, target=None)

    # When the user cancels
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])

    # Then it exits zero and nothing was sent
    assert result.exit_code == 0
    assert not httpx2_mock.calls


@pytest.mark.usefixtures("nomad_env")
def test_signal_success_message_claims_delivery_only(
    httpx2_mock: respx.Router, monkeypatch, typer_runner
):
    """Verify the success line reports delivery, never that the signal acted on the task."""
    # Given a resolved target and a mocked signal endpoint
    _patch_resolver(monkeypatch, target=ResolvedTarget("backup", "alloc-1", "ezbak"))
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/signal").respond(json={})
    capture = capture_output()

    # When signaling the resolved task
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1"])

    # Then the success line says the signal was sent, and never claims it acted on the task
    text = capture.export_text()
    assert result.exit_code == 0
    assert "Sent SIGUSR1 to task ezbak" in text
    lowered = text.lower()
    # Whole words only: these claims are substrings of ordinary words like "branch"
    for claim in ("triggered", "ran", "started"):
        assert not re.search(rf"\b{claim}\b", lowered)


def _mock_backup_job(httpx2_mock: respx.Router, *, alloc_ids: list[str]) -> None:
    """Mock a running `backup` job whose allocations each run one `ezbak` task."""
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/jobs").respond(json=[to_payload(job_stub("backup"))])
    httpx2_mock.get(f"{NOMAD_TEST_ADDR}/v1/job/backup/allocations").respond(
        json=[
            to_payload(alloc_stub(alloc_id, job_id="backup", task_states={"ezbak": task_state()}))
            for alloc_id in alloc_ids
        ]
    )


@pytest.mark.usefixtures("nomad_env")
def test_signal_all_allocs_signals_every_running_alloc(httpx2_mock: respx.Router, typer_runner):
    """Verify --all-allocs delivers the signal to the task in each running allocation."""
    # Given a job with two running allocations
    _mock_backup_job(httpx2_mock, alloc_ids=["alloc-1", "alloc-2"])
    routes = [
        httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/{alloc_id}/signal").respond(
            json={}
        )
        for alloc_id in ("alloc-1", "alloc-2")
    ]

    # When signaling every allocation unattended
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1", "--all-allocs"])

    # Then each allocation's task received the signal
    assert result.exit_code == 0
    for route in routes:
        assert json.loads(route.calls.last.request.content) == {
            "Signal": "SIGUSR1",
            "Task": "ezbak",
        }


@pytest.mark.usefixtures("nomad_env")
def test_signal_all_allocs_failure_still_signals_the_rest(httpx2_mock: respx.Router, typer_runner):
    """Verify one failed delivery exits 1 without stopping delivery to other allocations."""
    # Given two running allocations, one of which rejects the signal
    _mock_backup_job(httpx2_mock, alloc_ids=["alloc-1", "alloc-2"])
    httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-1/signal").respond(
        status_code=500, text="driver error"
    )
    healthy = httpx2_mock.post(f"{NOMAD_TEST_ADDR}/v1/client/allocation/alloc-2/signal").respond(
        json={}
    )

    # When signaling every allocation
    result = typer_runner.invoke(app, ["signal", "backup", "-s", "SIGUSR1", "--all-allocs"])

    # Then the command fails, and the healthy allocation was still signaled
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert healthy.called


@pytest.mark.usefixtures("nomad_env")
def test_signal_all_allocs_dry_run_sends_nothing(httpx2_mock: respx.Router, typer_runner):
    """Verify --all-allocs with --dry-run resolves every target and signals none."""
    # Given a job with two running allocations
    _mock_backup_job(httpx2_mock, alloc_ids=["alloc-1", "alloc-2"])

    # When previewing a signal to every allocation
    result = typer_runner.invoke(
        app, ["signal", "backup", "-s", "SIGUSR1", "--all-allocs", "--dry-run"]
    )

    # Then it exits zero having sent nothing
    assert result.exit_code == 0
    assert not [c for c in httpx2_mock.calls if c.request.method == "POST"]


@pytest.mark.usefixtures("nomad_env")
def test_signal_rejects_alloc_with_all_allocs(httpx2_mock: respx.Router, typer_runner):
    """Verify --alloc and --all-allocs together are a usage error before any request."""
    # Given a configured cluster address

    # When asking for one allocation and every allocation at once
    result = typer_runner.invoke(
        app, ["signal", "backup", "-s", "SIGUSR1", "--alloc", "a1", "--all-allocs"]
    )

    # Then it is a usage error and nothing was requested
    assert result.exit_code == 2
    assert not httpx2_mock.calls
