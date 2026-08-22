$ErrorActionPreference = 'Stop'

$project = Join-Path $PSScriptRoot 'project.json'
$output = Join-Path $PSScriptRoot 'out\runtime.txt'
$projectHash = (Get-FileHash -LiteralPath $project -Algorithm SHA256).Hash.ToLowerInvariant()
$content = @(
    'RUNTIME_RECOVERY_OK'
    "project_sha256=$projectHash"
    "edition=$($PSVersionTable.PSEdition)"
    "major=$($PSVersionTable.PSVersion.Major)"
    'provenance=build.ps1'
) -join "`n"

New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
[IO.File]::WriteAllText($output, $content + "`n", [Text.UTF8Encoding]::new($false))
