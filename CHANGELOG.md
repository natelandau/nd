## v0.4.0 (2026-06-30)

### Feat

- **select**: match job and volume names by substring, not prefix
- **volume**: confirm before deleting host volumes unless --force

### Fix

- **update**: describe job-name matching as substring in --help

### Refactor

- **commands**: share scaffolding across run, stop, and update

## v0.3.0 (2026-06-24)

### Feat

- **update**: add the nd update command to recreate running jobs
- **ui**: make run, stop, and volume result panels easier to read

### Fix

- **status**: show accurate cluster health with a clearer dashboard
- **run**: show the live rollout when re-running a stopped job
- no longer report healthy deploys and stops as failed

## v0.2.0 (2026-06-23)

### Feat

- **list**: add --hide-running flag to filter out running jobs
- **cli**: default bare nd to the status dashboard
- **cli**: detach stops and deploys, and target volumes by name
- **volume**: manage Nomad dynamic host volumes from the CLI
- **cli**: add the exec and logs commands
- **alloc**: resolve a job, allocation, and task to act on
- **nomad**: run exec sessions and log streams through the binary
- **nomad**: target the configured cluster for binary calls
- **cli**: add list, plan, and run commands
- **jobfiles**: discover job files and wrap the nomad binary
- **nomad**: add job register, deployments, and deployment model
- **ui**: add shared rendering, selection, and tunable primitives
- **status**: show where allocations run across the cluster
- **clean**: add command to run cluster garbage collection
- **stop**: add command to stop running Nomad jobs
- **cli**: add root application with version and verbosity
- **status**: add cluster status command
- **nomad**: add server, deployment, and evaluation endpoints
- **nomad**: add resource layer and client facade
- **nomad**: add async transport with pagination
- **nomad**: add msgspec response models
- **nomad**: add config and error hierarchy

### Fix

- **stop**: watch jobs drain fully before purging them

### Refactor

- **ui**: replace the link helpers with a WebUi builder
- **binary**: replace the binary wrappers with a NomadBinary class
- group the resolution layer into an nd.targets package
- group the nomad binary wrappers into an nd.binary package
- make exec/logs filtering and the no-spec view explicit
- **commands**: share the exec/logs target-and-binary tail
- **ui**: extract a shared concurrent live-panel orchestrator
- **commands**: share the verbosity and progress-step wiring
- **status**: split the command into report, render, and wiring
- **models**: share fields via struct inheritance
- apply behavior-preserving cleanups across the package
- **commands**: rebuild status and stop on the shared ui layer
- **nomad**: hoist paginated list into BaseResource helper

### Perf

- **jobspec**: resolve the nomad binary once per command, not per file
