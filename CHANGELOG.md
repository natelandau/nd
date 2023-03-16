## v0.3.0 (2023-03-16)

### Feat

- major refactor of entire package

### Fix

- logfile has correct name
- logfile has correct name

### Refactor

- remove unnecessary `else` and `elif` statements

## v0.2.1 (2022-10-07)

### Fix

- rename 'rebuild' command to 'update'

## v0.2.0 (2022-09-12)

### Feat

- **run**: show output from nomad when running a job

### Fix

- **run**: update message when starting a job

### Refactor

- **utils**: move utils folder up a dir level

## v0.1.0 (2022-08-27)

### Feat

- **status**: add links to Nomad web URLs within status

### Fix

- logs and execute commands now interact directly with Nomad

### Refactor

- **alerts**: add warning, info, notice, and dim classes to alerts utility

## v0.0.2 (2022-08-25)

### Fix

- expand user directory if specified as '~'

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
