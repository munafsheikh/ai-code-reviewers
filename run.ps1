# Runs a repository task in the toolbox container: ./run.ps1 TASK [ARGS]  (./run.ps1 -h lists tasks).
# Podman is the only host requirement; the task logic lives in infrastructure/scripts/tasks.py.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# Build output goes to the host, so a task's output stays clean for callers that capture it.
podman compose build toolbox | Out-Host
if ($LASTEXITCODE) { exit $LASTEXITCODE }
podman compose run --rm -T toolbox python infrastructure/scripts/tasks.py @args
exit $LASTEXITCODE
