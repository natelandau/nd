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
# Allocation client statuses that mean the alloc stopped because it broke (as opposed to
# finishing cleanly). Used both to color a failure red mid-drain and to flag a job as
# degraded when such an alloc is left unreplaced.
FAILED_ALLOC_STATUSES = frozenset({"failed", "lost"})
# How often to poll a stopped job's allocations, and how long to wait for them to
# drain before warning that the job is still stopping.
POLL_INTERVAL_SECONDS = 1.0
STOP_TIMEOUT_SECONDS = 120.0

# --- Job file discovery ----------------------------------------------------------------
# Globs used to find Nomad job specs inside each configured directory.
JOB_FILE_GLOBS = ["*.hcl", "*.nomad"]

# --- Status dashboard ------------------------------------------------------------------
# Minimum terminal width at which `nd status --hosts` lays its per-host panels into two
# columns; below this the panels stack in a single column so each stays readable.
HOSTS_TWO_COLUMN_MIN_WIDTH = 120

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

# --- Doctor checks ---------------------------------------------------------------------
# A task restarting at least this many times, with its last restart inside the window,
# is in a restart loop. Nomad counts restarts over an allocation's whole life, so the
# window keeps a long-lived allocation that restarted months ago from staying flagged.
DOCTOR_RESTART_THRESHOLD = 5
DOCTOR_RESTART_WINDOW_SECONDS = 86_400
# Resources Nomad fills in at registration when a task sets none. The API cannot tell
# them from the same values set on purpose.
NOMAD_DEFAULT_CPU_MHZ = 100
NOMAD_DEFAULT_MEMORY_MB = 300
