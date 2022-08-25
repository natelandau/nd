## v0.0.1 (2022-08-25)

### Feat

- add rebuild command
- add run command
- Add stop command
- add logs command
- add exec command
- add 'clean' command to run Nomad garbage collection
- add 'Status' command
- add 'plan' command
- filter Nomad job files by optional pattern
- add error handling for configuration missing keys
- add List command
- add alertis, logging, toml config file parsing

### Fix

- Fallback for systems where copying to clipboard is impossible
- **list**: option to filter valid job files by running jobs
- fix docstring
- recursively search for Nomad job files

### Refactor

- move filter for running jobs to job_files.py
- refactor commands and associated tests