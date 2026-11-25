"""Models for the Nomad evaluations endpoints."""

from __future__ import annotations

import msgspec

from nd.nomad.models import NomadModel

# Evaluation statuses that mean the scheduler is stuck.
_PROBLEM_EVAL_STATUSES = frozenset({"blocked", "pending"})
# Terminal evaluation statuses whose queued-allocation counts are historical, not live.
_TERMINAL_EVAL_STATUSES = frozenset({"complete", "canceled", "cancelled", "failed"})


class EvalListStub(NomadModel, frozen=True, kw_only=True):
    """An evaluation as returned by ``GET /v1/evaluations``."""

    id: str = msgspec.field(name="ID")
    job_id: str = msgspec.field(name="JobID")
    namespace: str = "default"
    status: str
    type: str
    triggered_by: str = ""
    queued_allocations: dict[str, int] = msgspec.field(default_factory=dict)
    create_index: int
    modify_index: int

    @property
    def is_problem(self) -> bool:
        """Whether the evaluation is stuck: blocked, pending, or live with queued allocations.

        Use this so every view of cluster health flags the same evaluations. Queued
        allocations on a terminal evaluation are historical, not a live problem.
        """
        if self.status in _PROBLEM_EVAL_STATUSES:
            return True
        if self.status in _TERMINAL_EVAL_STATUSES:
            return False
        return any(count > 0 for count in self.queued_allocations.values())
