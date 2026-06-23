"""Centralized, tunable constants shared across ``nd``.

Values a developer may want to toggle, or that are reused between modules, live
here so they can be adjusted in one place rather than hunted down in situ.
"""

from __future__ import annotations

# --- Nomad connection defaults ---------------------------------------------------------
# Used when the corresponding env var / config value is not set.
DEFAULT_NOMAD_ADDRESS = "http://127.0.0.1:4646"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0

# --- Job stop / drain watching ---------------------------------------------------------
# Allocation client statuses that mean the alloc has fully stopped, including any
# poststop lifecycle tasks. An alloc only reaches "complete" after every task
# (poststop included) has finished, so this is the signal a job is truly stopped.
TERMINAL_ALLOC_STATUSES = frozenset({"complete", "failed", "lost"})
# How often to poll a stopped job's allocations, and how long to wait for them to
# drain before warning that the job is still stopping.
POLL_INTERVAL_SECONDS = 1.0
STOP_TIMEOUT_SECONDS = 120.0
