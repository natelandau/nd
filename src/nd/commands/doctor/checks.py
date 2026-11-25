"""The registry of nd doctor checks; each sets its own check ID on its findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nd.commands.doctor.cluster_checks import (
    check_blocked_eval,
    check_failed_alloc,
    check_lost_alloc,
    check_no_local_file,
    check_node_down,
    check_unused_volume,
)
from nd.commands.doctor.job_checks import (
    check_default_resources,
    check_high_restarts,
    check_latest_tag,
    check_no_health_check,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nd.commands.doctor.findings import DoctorSnapshot, Finding

CHECKS: tuple[Callable[[DoctorSnapshot], list[Finding]], ...] = (
    check_failed_alloc,
    check_lost_alloc,
    check_high_restarts,
    check_latest_tag,
    check_no_health_check,
    check_default_resources,
    check_no_local_file,
    check_unused_volume,
    check_blocked_eval,
    check_node_down,
)


def run_checks(snapshot: DoctorSnapshot) -> list[Finding]:
    """Run every check against one snapshot so the command can report all problems at once.

    Returns:
        list[Finding]: Every finding, worst severity first, then in registry order, then
            by target.
    """
    findings = [
        (position, finding) for position, check in enumerate(CHECKS) for finding in check(snapshot)
    ]
    ordered = sorted(findings, key=lambda pair: (pair[1].severity.rank, pair[0], pair[1].target))
    return [finding for _, finding in ordered]
