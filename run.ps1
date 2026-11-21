# Runs a repository task in the toolbox container: ./run.ps1 TASK [ARGS]  (./run.ps1 -h lists tasks).
# Podman is the only host requirement; the task logic lives in infrastructure/scripts/tasks.py.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
podman compose run --rm --build -T toolbox python infrastructure/scripts/tasks.py @args
exit $LASTEXITCODE
