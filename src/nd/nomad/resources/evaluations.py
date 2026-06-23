"""Evaluations resource for the Nomad API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import builtins

from nd.nomad.models.evaluation import EvalListStub
from nd.nomad.resources.base import BaseResource


class EvaluationsResource(BaseResource):
    """Read access to Nomad evaluations."""

    async def list(self) -> builtins.list[EvalListStub]:
        """List all evaluations (``GET /v1/evaluations``), following pagination."""
        return await self._paginate_list("/evaluations", EvalListStub)
