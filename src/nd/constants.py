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
# Task states: a running task can write output; a dead one has exited for good, so its log
# cannot grow.
TASK_RUNNING_STATE = "running"
TASK_DEAD_STATE = "dead"
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
# When a deployment fails, nd explains it with the failed allocations' recent task events
# and the end of each failed task's stderr. These caps keep a job with many failed
# allocations from flooding the terminal.
DEPLOY_FAILURE_MAX_ALLOCS = 3
DEPLOY_FAILURE_EVENTS_PER_TASK = 5
DEPLOY_FAILURE_STDERR_LINES = 15

# --- Allocation exec / logs ------------------------------------------------------------
# The POSIX shell guaranteed to exist; used as the `-c` interpreter for the probe
# below and as the final fallback.
DEFAULT_EXEC_SHELL = "/bin/sh"
# With no --shell, `nd exec` prefers an interactive bash but falls back to sh in
# minimal images that lack it. The choice is probed inside the container (via
# `sh -c`) so it reflects what the container actually ships, not the local host.
EXEC_SHELL_PROBE = "command -v bash >/dev/null 2>&1 && exec bash || exec sh"
# Lines of earlier output each followed task prints before new output.
LOGS_BACKLOG_LINES = 20
# A read of a log's last lines starts at this many bytes per line, and at least the minimum,
# then doubles until it holds enough lines.
LOGS_TAIL_BYTES_PER_LINE = 120
LOGS_TAIL_MIN_BYTES = 8192
# Failed allocations found at start of the merged log view whose last lines print.
LOGS_MAX_FAILED_ALLOCS = 3
# How long one blocking query of the log views' allocation watcher waits.
LOGS_WATCH_WAIT_SECONDS = 30
# Added to a blocking query's wait for its request timeout; Nomad adds up to wait/16 jitter.
BLOCKING_QUERY_TIMEOUT_MARGIN_SECONDS = 10.0
# The most lines and lifecycle lines a log view holds before its readers wait for the printer.
LOGS_QUEUE_MAX_ITEMS = 1000
# How long a task's readers keep reading after the task ends, for its final output.
LOGS_FINAL_OUTPUT_GRACE_SECONDS = 2.0
# Waits between reconnects of a lost log stream; the last value repeats.
LOGS_RECONNECT_DELAYS_SECONDS = (1.0, 2.0, 5.0, 10.0)

# --- Doctor checks ---------------------------------------------------------------------
# A task restarting at least this many times, with its last restart inside the window,
# is in a restart loop. Nomad counts restarts over an allocation's whole life, so the
# window keeps a long-lived allocation that restarted months ago from staying flagged.
DOCTOR_RESTART_THRESHOLD = 5
DOCTOR_RESTART_WINDOW_SECONDS = 86_400
# `nomad` compiles nd doctor runs at once, so a large job directory does not flood the host.
DOCTOR_COMPILE_CONCURRENCY = 8
# Resources Nomad fills in at registration when a task sets none. The API cannot tell
# them from the same values set on purpose.
NOMAD_DEFAULT_CPU_MHZ = 100
NOMAD_DEFAULT_MEMORY_MB = 300
