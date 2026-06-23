"""Resolve which job, allocation, and task a command should act on.

`selection` is the generic name-prefix matching shared by every command that takes
an optional name argument; `alloc_target` builds on it to resolve an exec/logs target
through the API client. This module re-exports their public surface.
"""

from nd.targets.alloc_target import (
    ResolvedTarget,
    SelectionError,
    resolve_alloc_task,
    resolve_target,
)
from nd.targets.selection import (
    TargetResolution,
    pick_single,
    resolve_targets,
    select_candidates,
    select_one_candidate,
)

__all__ = [
    "ResolvedTarget",
    "SelectionError",
    "TargetResolution",
    "pick_single",
    "resolve_alloc_task",
    "resolve_target",
    "resolve_targets",
    "select_candidates",
    "select_one_candidate",
]
