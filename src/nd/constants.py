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
# Allocation client statuses considered healthy: the alloc is placed and either
# running or finished cleanly. Used to judge cluster health and deploy success.
HEALTHY_ALLOC_STATUSES = frozenset({"running", "complete"})
# How often to poll a stopped job's allocations, and how long to wait for them to
# drain before warning that the job is still stopping.
POLL_INTERVAL_SECONDS = 1.0
STOP_TIMEOUT_SECONDS = 120.0

# --- Job file discovery ----------------------------------------------------------------
# Globs used to find Nomad job specs inside each configured directory.
JOB_FILE_GLOBS = ["*.hcl", "*.nomad"]

# --- Job run / deploy watching ---------------------------------------------------------
# How long to wait for a registered job's deployment (or allocations, for batch/system
# jobs that create no deployment) to reach a terminal state before warning.
DEPLOY_TIMEOUT_SECONDS = 300.0

# --- Allocation exec / logs ------------------------------------------------------------
# The POSIX shell guaranteed to exist; used as the `-c` interpreter for the probe
# below and as the final fallback.
DEFAULT_EXEC_SHELL = "/bin/sh"
# With no --shell, `nd exec` prefers an interactive bash but falls back to sh in
# minimal images that lack it. The choice is probed inside the container (via
# `sh -c`) so it reflects what the container actually ships, not the local host.
EXEC_SHELL_PROBE = "command -v bash >/dev/null 2>&1 && exec bash || exec sh"
