"""Rich output for nd doctor: one panel per check, worst first."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp
from rich.markup import escape

from nd.commands.doctor.findings import Finding, FindingSeverity
from nd.constants import DOCTOR_RESTART_WINDOW_SECONDS
from nd.ui.links import file_link
from nd.ui.panels import status_table, titled_panel
from nd.ui.styles import OUTCOME_GLYPH, muted

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from rich.panel import Panel

    from nd.ui.links import WebUi

_SEVERITY_GLYPH: dict[FindingSeverity, str] = {
    FindingSeverity.CRITICAL: OUTCOME_GLYPH["fail"],
    FindingSeverity.WARNING: OUTCOME_GLYPH["warn"],
    FindingSeverity.INFO: "[cyan]•[/]",
}
_SEVERITY_STYLE: dict[FindingSeverity, str] = {
    FindingSeverity.CRITICAL: "red",
    FindingSeverity.WARNING: "yellow",
    FindingSeverity.INFO: "cyan",
}

# Separates a job's name from the group or task a finding is about.
TASK_SEPARATOR = "›"  # noqa: RUF001
NO_FINDINGS_MESSAGE = "No problems found"


@dataclass(frozen=True)
class _CheckDisplay:
    """How one check's panel is titled and what its subject and detail columns are called."""

    title: str
    meaning: str
    subject_header: str = "JOB"
    detail_header: str = "DETAIL"


_CHECK_DISPLAY: dict[str, _CheckDisplay] = {
    "failed-alloc": _CheckDisplay("Failed allocations", "failed and not replaced", "JOB", "FAILED"),
    "lost-alloc": _CheckDisplay("Lost allocations", "node stopped reporting", "JOB", "LOST"),
    "node-down": _CheckDisplay("Unhealthy machines", "not ready or not alive", "MACHINE", "STATUS"),
    "high-restarts": _CheckDisplay(
        "Restart loops",
        f"restarting in the last {DOCTOR_RESTART_WINDOW_SECONDS // 3600}h",
        "JOB",
        "RESTARTS",
    ),
    "latest-tag": _CheckDisplay("Unpinned images", "tag is latest or missing", "JOB", "IMAGE"),
    "no-health-check": _CheckDisplay("No health check", "a service has no check", "JOB", "SERVICE"),
    "blocked-eval": _CheckDisplay(
        "Stuck evaluations", "scheduler cannot place work", "JOB", "STATUS"
    ),
    "default-resources": _CheckDisplay("Default resources", "CPU and memory never set"),
    "no-local-file": _CheckDisplay("No local job file", "running without a job file"),
    "drift-not-checked": _CheckDisplay(
        "Drift not checked", "jobs not compared with their files", "CHECK", "REASON"
    ),
    "job-drift": _CheckDisplay(
        "Out of sync", "deployed job differs from its file", "JOB", "CHANGED"
    ),
    "unused-volume": _CheckDisplay("Unused volumes", "no job requests them", "VOLUME"),
}


def _subject(finding: Finding, ui: WebUi) -> str:
    """Name what the finding is about: the linked job, plus its group or task when that differs."""
    if not finding.job_id or not finding.job_name:
        return escape(finding.target.split(":", maxsplit=1)[-1])
    name = ui.job(finding.job_id, escape(finding.job_name))
    # Job names can hold slashes (periodic and dispatched children), so strip the name
    # before splitting off the innermost group or task.
    below_job = finding.target.removeprefix(finding.job_name).removeprefix("/")
    if not below_job:
        return name
    tail = below_job.rsplit("/", maxsplit=1)[-1]
    return f"{name} {muted(TASK_SEPARATOR)} {escape(tail)}"


def _file(finding: Finding, file_paths: dict[str, Path]) -> str:
    """Show the job file's name, linked to the full path."""
    path = file_paths.get(finding.job_name or "")
    return muted(file_link(path, escape(path.name))) if path else ""


def _check_panel(findings: list[Finding], *, file_paths: dict[str, Path], ui: WebUi) -> Panel:
    """Build one check's panel: a row per finding, with only the columns its findings fill."""
    first = findings[0]
    display = _CHECK_DISPLAY.get(first.check, _CheckDisplay(first.check, ""))
    columns: list[tuple[str, Callable[[Finding], str]]] = [
        (display.subject_header, lambda f: _subject(f, ui))
    ]
    if any(f.job_name for f in findings):
        columns.append(("FILE", lambda f: _file(f, file_paths)))
    if any(f.problem for f in findings):
        columns.append((display.detail_header, lambda f: escape(f.problem)))
    if any(f.fix_hint for f in findings):
        columns.append(("FIX", lambda f: escape(f.fix_hint or "")))

    table = status_table(*(header for header, _ in columns))
    # Wrap a long value inside its cell rather than cutting it off with an ellipsis.
    for column in table.columns:
        column.overflow = "fold"
    for finding in findings:
        table.add_row(*(cell(finding) for _, cell in columns))

    style = _SEVERITY_STYLE[first.severity]
    title = f"{_SEVERITY_GLYPH[first.severity]} [{style}]{display.title}[/] {muted('· ' + display.meaning)}"
    return titled_panel(table, title, border_style=style, expand=True)


def _summary(findings: list[Finding]) -> str:
    """Count findings per severity, coloring only the counts that are not zero."""
    parts: list[str] = []
    for severity in FindingSeverity:
        count = sum(1 for f in findings if f.severity == severity)
        shown = f"[{_SEVERITY_STYLE[severity]}]{count}[/]" if count else str(count)
        parts.append(f"{shown} {severity.value}")
    return ", ".join(parts)


def render_findings(findings: list[Finding], *, file_paths: dict[str, Path], ui: WebUi) -> None:
    """Print one panel per check, worst first, then a count of each severity.

    Args:
        findings: The findings to show, worst first; each check's findings stay together.
        file_paths: Local job file for each job name.
        ui: Link builder for the Nomad web UI.
    """
    if not findings:
        pp.success(NO_FINDINGS_MESSAGE)
        return
    sections: dict[str, list[Finding]] = {}
    for finding in findings:
        sections.setdefault(finding.check, []).append(finding)
    console = pp.console()
    for section in sections.values():
        console.print(_check_panel(section, file_paths=file_paths, ui=ui))
    console.print(_summary(findings))
