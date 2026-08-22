$ErrorActionPreference = 'Stop'

$runRoot = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $runRoot 'installed\Shinonome Tools\build helper.cmd'
$project = Join-Path $PSScriptRoot 'project.json'
$output = Join-Path $PSScriptRoot 'out\artifact.txt'

# This machine used to accept this command construction. It now fails for this project path.
$command = "$helper --project $project --out $output"
cmd.exe /d /s /c $command
exit $LASTEXITCODE
