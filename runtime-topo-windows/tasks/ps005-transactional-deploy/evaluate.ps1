$ErrorActionPreference = 'Stop'
$root = 'C:\WCB\tasks\PS005 Transactional Deploy'
$package = Join-Path $root 'package'
$deploy = Join-Path $root 'deployment'
$current = Join-Path $deploy 'current'
$manifest = Join-Path $root 'manifest.json'
$script = Join-Path $root 'deploy.ps1'

function Invoke-Deploy {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -ManifestPath $manifest -PackageRoot $package -DeployRoot $deploy 1>$null 2>$null
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    return $code
}
function Test-VersionTwo {
    if (-not (Test-Path -LiteralPath (Join-Path $current 'bin\app.txt'))) { return $false }
    if ((Get-Content -LiteralPath (Join-Path $current 'bin\app.txt') -Raw) -ne "version=2`r`n") { return $false }
    if ((Get-Content -LiteralPath (Join-Path $current 'config\settings.json') -Raw) -ne '{"enabled":true}') { return $false }
    if ((Get-Content -LiteralPath (Join-Path $current 'docs\read me.txt') -Raw) -ne "release-notes`r`n") { return $false }
    $relative = @(Get-ChildItem -LiteralPath $current -File -Recurse | ForEach-Object { $_.FullName.Substring($current.Length + 1).Replace('\','/') } | Sort-Object)
    return (($relative -join '|') -eq 'bin/app.txt|config/settings.json|docs/read me.txt')
}
function Test-NoTemporaryDirectories {
    return @(Get-ChildItem -LiteralPath $deploy -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'current' }).Count -eq 0
}

if (Test-Path -LiteralPath $deploy) { Remove-Item -LiteralPath $deploy -Recurse -Force }
New-Item -ItemType Directory -Path $current -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $current 'version.txt'), "version=1`r`n")
$validExit = Invoke-Deploy
$validState = Test-VersionTwo
$validClean = Test-NoTemporaryDirectories

[IO.File]::WriteAllText((Join-Path $package 'bin\app.txt'), "version=3`r`n")
$invalidExit = Invoke-Deploy
$rollbackState = Test-VersionTwo
$invalidClean = Test-NoTemporaryDirectories
[IO.File]::WriteAllText((Join-Path $package 'bin\app.txt'), "version=2`r`n")

[IO.File]::WriteAllText($manifest, '{"files":["bin/app.txt","../outside-source.txt"]}')
Remove-Item -LiteralPath (Join-Path $deploy 'outside-source.txt') -Force -ErrorAction SilentlyContinue
$traversalExit = Invoke-Deploy
$traversalState = Test-VersionTwo
$escapeAbsent = -not (Test-Path -LiteralPath (Join-Path $deploy 'outside-source.txt'))
$traversalClean = Test-NoTemporaryDirectories
[IO.File]::WriteAllText($manifest, '{"files":["bin/app.txt","config/settings.json","docs/read me.txt"]}')

$result = [ordered]@{
    valid_exit = $validExit
    valid_deployment_exact = $validState
    invalid_candidate_rejected = $invalidExit -ne 0
    previous_version_preserved = $rollbackState
    traversal_rejected = $traversalExit -ne 0
    escape_absent = $escapeAbsent
    current_unchanged_after_traversal = $traversalState
    temporary_directories_cleaned = $validClean -and $invalidClean -and $traversalClean
    passed = $false
}
$result.passed = $validExit -eq 0 -and $result.valid_deployment_exact -and $result.invalid_candidate_rejected -and $result.previous_version_preserved -and $result.traversal_rejected -and $result.escape_absent -and $result.current_unchanged_after_traversal -and $result.temporary_directories_cleaned
$result | ConvertTo-Json -Compress
if (-not $result.passed) { exit 1 }
