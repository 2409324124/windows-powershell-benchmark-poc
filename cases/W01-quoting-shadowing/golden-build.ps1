$ErrorActionPreference = 'Stop'

$runRoot = Split-Path -Parent $PSScriptRoot
$toolDirectory = Join-Path $runRoot 'installed\Shinonome Tools'
$helper = Join-Path $toolDirectory 'build helper.cmd'
$project = Join-Path $PSScriptRoot 'project.json'
$output = Join-Path $PSScriptRoot 'out\artifact.txt'
$originalPath = $env:PATH

try {
    $env:PATH = "$toolDirectory;$originalPath"
    & $helper --project $project --out $output
    exit $LASTEXITCODE
}
finally {
    $env:PATH = $originalPath
}
